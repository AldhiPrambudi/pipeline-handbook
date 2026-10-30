"""Regression cases found by independent review of the canonical graph boundary."""

import json
import unittest

from pipeline_handbook.model import validate_result
from tests.test_adapters import context
from tests import test_core as _core


class CanonicalAudit(unittest.TestCase):
    def test_redacted_display_names_and_namespaces_do_not_merge_identities(self):
        artifact, ctx = context("", "fixture.json", "acme")
        first = ctx.node("task", "notify::alice@example.com")
        second = ctx.node("task", "notify::bob@example.com")
        self.assertNotEqual(first, second)
        self.assertEqual(ctx.nodes[first]["name"], ctx.nodes[second]["name"])
        first_dataset = ctx.node("dataset", "raw.orders", namespace="alice@example.com")
        second_dataset = ctx.node("dataset", "raw.orders", namespace="bob@example.com")
        self.assertNotEqual(first_dataset, second_dataset)
        persisted = json.dumps(ctx.result())
        self.assertNotIn("alice@example.com", persisted)
        self.assertNotIn("bob@example.com", persisted)
        validate_result(ctx.result(), ctx.config, artifact)

    def test_sdk_rejects_malformed_attributes_and_columns(self):
        _, ctx = context("", "fixture.json", "acme")
        for attrs in (["bad"], "bad", {"columns": "bad"}, {"columns": [None]}, {"entrypoint": "yes"}):
            with self.subTest(attrs=attrs), self.assertRaises(ValueError):
                ctx.node("dataset", "raw.orders", attrs)
        with self.assertRaises(ValueError):
            ctx.dataset("raw.orders", columns="order_id")
        with self.assertRaises(ValueError):
            ctx.node("dataset", 123)
        with self.assertRaises(ValueError):
            ctx.edge(None, "dataset:known", "data_flow")

    def test_validator_accepts_known_cross_artifact_endpoint(self):
        artifact, ctx = context("", "fixture.json", "acme")
        node = ctx.dataset("final.orders")
        external = "dataset:known-from-another-artifact"
        ctx.edge(external, node, "data_flow")
        validate_result(ctx.result(), ctx.config, artifact, known_nodes={external: {"id": external}})
        with self.assertRaises(ValueError):
            validate_result(ctx.result(), ctx.config, artifact)

    def test_validator_rejects_dangling_evidence_before_merge(self):
        artifact, ctx = context("", "fixture.json", "acme")
        ctx.dataset("raw.orders")
        ctx.evidences.clear()
        with self.assertRaises(ValueError):
            validate_result(ctx.result(), ctx.config, artifact)

    def test_validator_rejects_edge_identity_reused_for_different_facts(self):
        artifact, ctx = context("", "fixture.json", "acme")
        source, target = ctx.dataset("raw.orders"), ctx.dataset("final.orders")
        eid = ctx.edge(source, target, "data_flow")
        ctx.edges[eid]["source"], ctx.edges[eid]["target"] = target, source
        with self.assertRaises(ValueError):
            validate_result(ctx.result(), ctx.config, artifact)

    def test_updating_existing_node_at_budget_does_not_create_false_failure(self):
        _, ctx = context("", "fixture.json", "acme")
        ctx.config["budgets"]["max_nodes_per_adapter"] = 1
        identity = ctx.node("dataset", "raw.orders")
        self.assertEqual(identity, ctx.node("dataset", "raw.orders", {"columns": ["order_id"]}))
        with self.assertRaises(ValueError):
            ctx.node("dataset", "raw.second")


class SourceAndPluginAudit(unittest.TestCase):
    # Reuse fixture helpers without inheriting and rerunning the existing suite.
    setUp = _core.CoreBoundaries.setUp
    tearDown = _core.CoreBoundaries.tearDown
    write_config = _core.CoreBoundaries.write_config
    scan = _core.CoreBoundaries.scan
    sql = _core.CoreBoundaries.sql
    acme_rule = _core.CoreBoundaries.acme_rule
    plugin = _core.CoreBoundaries.plugin

    def second_source(self):
        other = self.directory / "other"
        other.mkdir()
        self.config["sources"].append({"id": "other", "kind": "directory", "environment": "test", "service": "orders", "path": "other"})
        return other

    def test_permissive_second_source_cannot_defeat_first_source_filter(self):
        self.config["sources"][0]["schema_filters"] = ["raw"]
        self.sql(target="final.blocked")
        other = self.second_source()
        (other / "orders.sql").write_text("-- dialect: postgres\nCREATE TABLE final.allowed AS SELECT order_id FROM raw.other;\n")
        snapshot = self.scan()
        datasets = {node["name"] for node in snapshot["nodes"] if node["kind"] == "dataset"}
        self.assertNotIn("final.blocked", datasets)
        self.assertIn("raw.orders", datasets)
        self.assertIn("final.allowed", datasets)
        self.assertIn("resource_filtered", {issue["code"] for issue in snapshot["issues"]})

    def test_shared_allowed_identity_retains_only_allowed_source_evidence(self):
        self.config["sources"][0]["resource_filters"] = ["raw.*"]
        self.sql(target="final.shared")
        other = self.second_source()
        (other / "orders.sql").write_text("-- dialect: postgres\nCREATE TABLE final.shared AS SELECT order_id FROM raw.other;\n")
        snapshot = self.scan()
        node = next(node for node in snapshot["nodes"] if node["kind"] == "dataset" and node["name"] == "final.shared")
        evidence = {item["id"]: item for item in snapshot["evidence"]}
        self.assertTrue(node["evidence"])
        self.assertTrue(all(evidence[eid]["location"].startswith("other/") for eid in node["evidence"]))

    def test_malformed_trusted_plugins_are_discarded_atomically(self):
        self.acme_rule()
        self.sql()
        self.plugin("badattrs", '''def analyze(artifact, ctx):
    first = ctx.dataset("raw.partial_badattrs")
    second = ctx.dataset("final.partial_badattrs")
    ctx.edge(first, second, "data_flow")
    ctx.nodes[first]["attributes"] = ["not a canonical object"]
''')
        self.plugin("badedge", '''def analyze(artifact, ctx):
    first = ctx.dataset("raw.partial_badedge")
    ctx.edge(first, "dataset:does-not-exist", "data_flow")
''')
        self.plugin("badevidence", '''def analyze(artifact, ctx):
    ctx.dataset("raw.partial_badevidence")
    ctx.evidences.clear()
''')
        self.plugin("unexpected", '''def analyze(artifact, ctx):
    first = ctx.dataset("raw.partial_unexpected")
    ctx.nodes[first]["raw_text"] = "FAKE_PLUGIN_RAW_CANARY"
''')
        snapshot = self.scan()
        datasets = {node["name"] for node in snapshot["nodes"] if node["kind"] == "dataset"}
        self.assertIn("final.orders", datasets)
        self.assertFalse(any("partial_" in name for name in datasets))
        failed = [issue for issue in snapshot["issues"] if issue["code"] == "adapter_failed"]
        self.assertEqual(4, len(failed))
        self.assertTrue(all("InvalidAdapterResult" in issue["message"] for issue in failed))
        self.assertNotIn("FAKE_PLUGIN_RAW_CANARY", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
