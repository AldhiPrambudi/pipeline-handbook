"""Core boundary and extensibility tests through validated configuration/public CLI."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_handbook.config import load_config
from pipeline_handbook.security import bounded_read
from tests.test_acceptance import ROOT, run_cli


class CoreBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pipeline-handbook-core-")
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "source"
        self.source.mkdir()
        self.output = self.directory / "output"
        self.config_path = self.directory / "config.json"
        self.config = {
            "project": "core_boundary_tests",
            "sources": [{"id": "scope", "kind": "directory", "environment": "test", "service": "orders", "path": "source"}],
            "output": {"directory": "output", "formats": ["json", "markdown", "html"]},
            "budgets": {"scan_timeout_seconds": 20, "adapter_timeout_seconds": 2},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        return self.config_path

    def scan(self):
        run_cli("analyze", "--config", str(self.write_config()))
        return json.loads((self.output / "latest.json").read_text())

    def sql(self, source="raw.orders", target="final.orders", dialect=True):
        prefix = "-- dialect: postgres\n" if dialect else ""
        (self.source / "orders.sql").write_text(prefix + f"CREATE TABLE {target} AS SELECT order_id FROM {source};\n")

    def acme_rule(self):
        pack = json.loads((ROOT / "pipeline_handbook/data/builtin.json").read_text())
        entry = deepcopy(next(item for item in pack["entries"] if item["technology"] == "docker"))
        entry.update({
            "id": "example.acme", "technology": "acme", "family": "integration",
            "positive": [{"kind": "json_fields", "fields": {"technology": "acme", "tasks": "$object"}, "category": "recognized", "reason": "Fictional Acme export schema fields"}],
            "negative": [], "mention_terms": ["acme"], "adapters": [],
            "applicability": "Fictional Acme schema 1 exports only.", "input_formats": ["json"],
            "limitations": ["Fictional teaching format; no runtime or vendor behavior is established."],
            "official_references": [], "fixtures": ["examples/trusted_plugins/acme-export.json"],
            "maturity": "experimental", "mapping": {"concept": "pipeline", "explanation": "{name} is a declared {kind} in the fictional Acme export; no run is observed."},
        })
        entry["features"] = {key: ("subset" if key in {"detection", "metadata_extraction", "table_lineage", "documentation"} else "unsupported") for key in entry["features"]}
        directory = self.directory / "reviewed_rules"
        directory.mkdir(exist_ok=True)
        path = directory / "acme.rules.json"
        path.write_text(json.dumps({"schema_version": "1", "entries": [entry]}))
        self.config["rules"] = {"directories": ["reviewed_rules"]}
        shutil.copyfile(ROOT / "examples/trusted_plugins/acme-export.json", self.source / "acme.json")
        return path

    def plugin(self, name="acme", code=None, technology="acme"):
        directory = self.directory / "trusted"
        directory.mkdir(exist_ok=True)
        path = directory / (name + ".py")
        if code is None:
            shutil.copyfile(ROOT / "examples/trusted_plugins/acme.py", path)
        else:
            path.write_text(code)
        adapter_id = "example:" + name
        adapters = self.config.setdefault("adapters", {"trusted": ["builtin:*"], "plugins": []})
        adapters["trusted"].append(adapter_id)
        adapters["plugins"].append({"id": adapter_id, "path": str(path), "version": "1.0.0", "technologies": [technology], "priority": 150})
        return path

    def test_configuration_rejects_unknown_network_disabled_redaction_and_overlap(self):
        baseline = deepcopy(self.config)
        variants = [
            {**baseline, "unknown_policy": True},
            {**baseline, "security": {"network_enabled": True}},
            {**baseline, "security": {"allowed_endpoints": ["https://example.invalid"]}},
            {**baseline, "security": {"redact": False}},
            {**baseline, "output": {"directory": "source/generated"}},
            {**baseline, "output": {"directory": "."}},
        ]
        for variant in variants:
            with self.subTest(config=variant):
                self.config = variant
                with self.assertRaises(ValueError):
                    load_config(self.write_config())

    def test_no_implicit_or_in_scope_plugin_trust(self):
        self.acme_rule()
        plugin = self.plugin()
        self.config["adapters"]["trusted"] = ["builtin:*", "example:*"]
        with self.assertRaisesRegex(ValueError, "exact-ID"):
            load_config(self.write_config())
        self.config["adapters"]["trusted"] = ["builtin:*", "example:acme"]
        candidate = self.source / "suggested_plugin.py"
        candidate.write_text("raise RuntimeError('scanned plugins must never be imported')\n")
        self.config["adapters"]["plugins"][0]["path"] = str(candidate)
        with self.assertRaisesRegex(ValueError, "outside scanned"):
            load_config(self.write_config())

    def test_reviewed_detector_pack_adds_technology_without_core_change(self):
        self.acme_rule()
        snapshot = self.scan()
        self.assertTrue(any(item["technology"] == "acme" and item["category"] == "recognized" for item in snapshot["detections"]))
        self.assertFalse(any(node.get("technology") == "acme" for node in snapshot["nodes"]))

    def test_explicit_trusted_adapter_produces_shared_canonical_model(self):
        self.acme_rule()
        self.plugin()
        self.sql()
        snapshot = self.scan()
        nodes = {node["id"]: node for node in snapshot["nodes"]}
        technologies = {node.get("technology") for node in nodes.values() if node["kind"] == "pipeline"}
        self.assertTrue({"acme", "postgresql"} <= technologies)
        pairs = {(nodes[edge["source"]]["name"], nodes[edge["target"]]["name"]) for edge in snapshot["edges"] if edge["kind"] == "data_flow"}
        self.assertIn(("raw.acme_orders", "final.acme_orders"), pairs)
        self.assertIn(("raw.orders", "final.orders"), pairs)
        evidence = {item["id"] for item in snapshot["evidence"]}
        for node in nodes.values():
            self.assertTrue(node["evidence"])
            self.assertTrue(set(node["evidence"]) <= evidence)

    def test_failure_and_timeout_do_not_erase_other_adapter_results(self):
        self.acme_rule()
        self.plugin("failure", "def analyze(artifact, ctx):\n    raise ValueError('password=FAKE_EXCEPTION_SECRET_CANARY')\n")
        self.plugin("slow", "import time\ndef analyze(artifact, ctx):\n    time.sleep(30)\n")
        self.config["budgets"]["adapter_timeout_seconds"] = 1
        self.sql()
        snapshot = self.scan()
        self.assertTrue(any(node["kind"] == "dataset" and node["name"] == "final.orders" for node in snapshot["nodes"]))
        failures = [item for item in snapshot["issues"] if item["code"] == "adapter_failed"]
        self.assertGreaterEqual(len(failures), 2)
        self.assertNotIn("FAKE_EXCEPTION_SECRET_CANARY", json.dumps(snapshot))

    def test_symlinks_unreadable_inputs_and_traversal_are_coverage_gaps(self):
        outside = self.directory / "outside.sql"
        outside.write_text("-- dialect: postgres\nCREATE TABLE leaked.target AS SELECT id FROM leaked.source;\n")
        (self.source / "escape.sql").symlink_to(outside)
        unreadable = self.source / "unreadable.sql"
        unreadable.write_text(outside.read_text())
        unreadable.chmod(0)
        (self.source / "run.sh").write_text("#!/bin/sh\n# handbook: working-directory=.\npsql -f ../outside.sql\n")
        try:
            snapshot = self.scan()
        finally:
            unreadable.chmod(0o600)
        codes = {issue["code"] for issue in snapshot["issues"]}
        self.assertIn("symlink_skipped", codes)
        self.assertIn("access_denied", codes)
        self.assertIn("unresolved_reference", codes)
        self.assertFalse(any(node["name"] == "leaked.target" for node in snapshot["nodes"]))
        with self.assertRaises((ValueError, OSError)):
            bounded_read(self.source / ".." / "outside.sql", self.source, 10000)

    def test_byte_budget_and_data_files_do_not_acquire_parsed_contents(self):
        self.config["budgets"]["max_file_bytes"] = 100
        (self.source / "oversize.py").write_text("x" * 1000)
        (self.source / "raw.csv").write_text("password\nFAKE_BUSINESS_ROW_CANARY\n")
        snapshot = self.scan()
        self.assertTrue({"budget_exceeded", "data_content_skipped"} <= {issue["code"] for issue in snapshot["issues"]})
        self.assertNotIn("FAKE_BUSINESS_ROW_CANARY", json.dumps(snapshot))

    def test_manual_dialect_override_is_auditable_without_becoming_observed(self):
        self.sql(dialect=False)
        self.config["discovery"] = {"mode": "manual"}
        self.config["technologies"] = {"include": ["postgresql"], "overrides": {"postgresql": {"dialect": "postgres", "version": "99.0"}}}
        snapshot = self.scan()
        self.assertTrue(any(node["kind"] == "dataset" and node["name"] == "final.orders" for node in snapshot["nodes"]))
        self.assertEqual(snapshot["effective_config"]["technologies"]["overrides"]["postgresql"]["dialect"], "postgres")
        self.assertTrue(all(node["status"] != "observed" for node in snapshot["nodes"]))
        self.assertFalse(any(item["category"] == "observed" for item in snapshot["detections"]))

    def test_input_change_produces_meaningful_diff_and_fresh_hash(self):
        self.sql()
        first = self.scan()
        before = self.directory / "before.json"
        before.write_text(json.dumps(first))
        self.sql(target="final.changed_orders")
        second = self.scan()
        after = self.directory / "after.json"
        after.write_text(json.dumps(second))
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(first["artifacts"][0]["hash"], second["artifacts"][0]["hash"])
        result = run_cli("diff", str(before), str(after))
        self.assertTrue(result.stdout.strip())
        self.assertNotEqual(result.stdout.strip(), "{}")
        self.assertTrue(any(node["name"] == "final.changed_orders" for node in second["nodes"]))
        self.assertFalse(any(node["name"] == "final.orders" for node in second["nodes"]))

    def test_rule_versions_and_adapter_code_invalidate_snapshot(self):
        rule = self.acme_rule()
        adapter = self.plugin()
        first = self.scan()
        pack = json.loads(rule.read_text())
        pack["entries"][0]["version"] = "1.0.1"
        rule.write_text(json.dumps(pack))
        second = self.scan()
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(first["registry_fingerprint"], second["registry_fingerprint"])
        adapter.write_text(adapter.read_text() + "\n# reviewed component revision\n")
        third = self.scan()
        self.assertNotEqual(second["registry_fingerprint"], third["registry_fingerprint"])
        self.assertNotEqual(second["snapshot_id"], third["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
