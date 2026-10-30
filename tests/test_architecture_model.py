"""Additive SDK and derived architecture regressions, without runtime services."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from pipeline_handbook import architecture
from pipeline_handbook.engine import _resolve_links
from pipeline_handbook.model import validate_result
from tests.test_architecture_adapters import context, selector


def snapshot(ctx, detections=None):
    return {"nodes": list(ctx.nodes.values()), "edges": list(ctx.edges.values()),
        "evidence": list(ctx.evidences.values()), "artifacts": [{key: value for key, value in ctx.artifact.items() if key != "text"}],
        "sources": [{"id": ctx.artifact["source_id"], "environment": ctx.artifact["environment"], "service": ctx.artifact["service"]}],
        "detections": detections or [], "issues": list(ctx.issues)}


class ArchitectureSDKTests(unittest.TestCase):
    def test_json_pointers_distinguish_root_empty_keys_and_escaped_segments(self):
        artifact, ctx = context({}, "map.json", "environment-map")
        root = ctx.evidence(object_path="")
        empty_key = ctx.evidence(object_path="/")
        escaped = ctx.evidence(object_path="/a~1b/~0key")
        self.assertEqual(3, len({root, empty_key, escaped}))
        self.assertEqual("", ctx.evidences[root]["object_path"])
        self.assertEqual("/", ctx.evidences[empty_key]["object_path"])
        self.assertEqual(artifact["hash"], ctx.evidences[escaped]["source_hash"])
        for invalid in ("services/image", "/bad~", "/bad~2escape", "/a\nb", "/a\x00b"):
            with self.subTest(pointer=invalid), self.assertRaises(ValueError):
                ctx.evidence(object_path=invalid)
        validate_result(ctx.result(), ctx.config, artifact)

    def test_old_results_without_links_or_object_pointers_remain_valid(self):
        artifact, ctx = context({}, "legacy.json", "acme")
        ctx.node("pipeline", "legacy.definition")
        legacy = deepcopy(ctx.result())
        legacy.pop("links")
        self.assertTrue(all("object_path" not in item for item in legacy["evidence"]))
        validate_result(legacy, ctx.config, artifact)

    def test_link_is_deferred_and_cannot_manufacture_endpoint_nodes(self):
        artifact, ctx = context({}, "map.json", "environment-map")
        source = selector("pipeline", "build", source="external_scope", path="manifest.json")
        target = selector("component", "warehouse", path="map.json")
        ctx.link(source, target, "invocation", object_path="/links/0")
        self.assertFalse(ctx.nodes)
        self.assertFalse(ctx.edges)
        self.assertEqual(1, len(ctx.links))
        self.assertEqual("/links/0", ctx.evidences[ctx.links[0]["evidence"][0]]["object_path"])
        self.assertEqual("declared", ctx.evidences[ctx.links[0]["evidence"][0]]["status"])
        validate_result(ctx.result(), ctx.config, artifact)
        incomplete = dict(source)
        incomplete.pop("namespace")
        with self.assertRaises(ValueError):
            ctx.link(incomplete, target, "connection")

    def test_raw_identity_is_hashed_before_selector_display_redaction(self):
        _, ctx = context({}, "map.json", "environment-map")
        identity = ctx.node("component", "notify::alice@example.com", object_path="/components/0")
        source = selector("component", "notify::alice@example.com", path="map.json")
        target = selector("component", "notify::bob@example.com", path="map.json")
        ctx.link(source, target, "connection", object_path="/links/0")
        self.assertEqual(identity, ctx.links[0]["source_selector"]["node_id"])
        self.assertNotEqual(identity, ctx.links[0]["target_selector"]["node_id"])
        self.assertNotIn("alice@example.com", json.dumps(ctx.result()))
        self.assertNotIn("bob@example.com", json.dumps(ctx.result()))


class ExactBindingTests(unittest.TestCase):
    def fixtures(self):
        _, source_ctx = context({}, "dag.py", "airflow", source="orchestrator")
        source_ctx.node("task", "dag.py::orders::build", object_path="/tasks/build")
        _, target_ctx = context({}, "manifest.json", "dbt", source="models")
        target_ctx.node("pipeline", "manifest.json::model.orders.final", object_path="/nodes/model.orders.final")
        _, binding = context({}, "bindings.json", "environment-map", source="bindings")
        source = selector("task", "dag.py::orders::build", source="orchestrator", path="dag.py")
        target = selector("pipeline", "manifest.json::model.orders.final", source="models", path="manifest.json")
        binding.link(source, target, "invocation", object_path="/links/0")
        return source_ctx, target_ctx, binding

    def resolve(self, contexts, links):
        nodes, evidence, artifacts, problems = {}, {}, {}, []
        for ctx in contexts:
            nodes.update(deepcopy(ctx.nodes))
            evidence.update(deepcopy(ctx.evidences))
            artifacts[ctx.artifact["id"]] = deepcopy(ctx.artifact)
        edges = {}
        def issue(code, message, artifact=None, proof=None, **kwargs):
            problems.append({"code": code, "message": message})
        _resolve_links(links, nodes, edges, evidence, artifacts, issue)
        return edges, problems, nodes, evidence, artifacts

    def test_resolution_is_source_order_independent_and_keeps_endpoint_provenance(self):
        source, target, binding = self.fixtures()
        first = deepcopy(binding.links)
        second = deepcopy(binding.links)
        edges, problems, _, _, _ = self.resolve([source, target, binding], first)
        reversed_edges, reversed_problems, _, _, _ = self.resolve([binding, target, source], second)
        self.assertFalse(problems)
        self.assertFalse(reversed_problems)
        self.assertEqual(edges, reversed_edges)
        self.assertEqual(first, second)
        edge = next(iter(edges.values()))
        self.assertEqual("invocation", edge["kind"])
        self.assertEqual("declared", edge["status"])
        self.assertIs(edge["attributes"]["runtime_verified"], False)
        expected = set(binding.links[0]["evidence"]) | set(next(iter(source.nodes.values()))["evidence"]) | set(next(iter(target.nodes.values()))["evidence"])
        self.assertEqual(expected, set(edge["evidence"]))

    def test_identical_short_name_in_wrong_artifact_cannot_supply_proof(self):
        source, target, binding = self.fixtures()
        _, decoy = context({}, "wrong.py", "airflow", source="orchestrator")
        links = deepcopy(binding.links)
        links[0]["source_selector"]["artifact_path"] = "wrong.py"
        edges, problems, _, _, _ = self.resolve([source, target, binding, decoy], links)
        self.assertFalse(edges)
        self.assertEqual("unknown", links[0]["resolution"])
        self.assertIn("unresolved_architecture_link", {item["code"] for item in problems})

    def test_missing_endpoint_and_cross_environment_stay_unresolved(self):
        source, target, binding = self.fixtures()
        absent = deepcopy(target)
        absent.nodes = {}
        edges, problems, _, _, _ = self.resolve([source, absent, binding], deepcopy(binding.links))
        self.assertFalse(edges)
        self.assertIn("unresolved_architecture_link", {item["code"] for item in problems})
        links = deepcopy(binding.links)
        links[0]["target_selector"]["environment"] = "prod"
        edges, problems, _, _, _ = self.resolve([source, target, binding], links)
        self.assertFalse(edges)
        self.assertIn("cross_environment_link", {item["code"] for item in problems})


class ArchitectureProjectionTests(unittest.TestCase):
    def test_only_pipeline_or_task_via_nodes_become_producer_definitions(self):
        _, ctx = context({}, "map.json", "environment-map")
        raw, final = ctx.dataset("raw.orders"), ctx.dataset("final.orders")
        component = ctx.node("component", "query.service")
        job = ctx.node("pipeline", "supported.producer")
        ctx.edge(raw, final, "data_flow", {"via": component})
        ctx.edge(raw, final, "data_flow", {"via": raw})
        ctx.edge(raw, final, "data_flow", {"via": job})
        trace = next(item for item in architecture.recover(snapshot(ctx))["walkthroughs"] if item["output_id"] == final)
        self.assertEqual([job], trace["producer_ids"])

    def test_declared_data_cycles_are_not_presented_as_execution_order(self):
        _, ctx = context({}, "map.json", "environment-map")
        first, second = ctx.dataset("raw.orders"), ctx.dataset("final.orders")
        ctx.edge(first, second, "data_flow")
        ctx.edge(second, first, "data_flow")
        recovered = architecture.recover(snapshot(ctx))
        self.assertEqual(2, len(recovered["walkthroughs"]))
        for trace in recovered["walkthroughs"]:
            self.assertTrue(any("cycle" in text.lower() for text in trace["limitations"]))
            self.assertIn("not execution sequence", trace["data_ancestry_order"])
        self.assertFalse(recovered["recommendations"])

    def test_detection_only_inventory_cannot_become_deployed_components(self):
        _, ctx = context({}, "requirements.txt", "kafka")
        proof = ctx.evidence(reason="dependency declaration")
        detection = {"technology": "kafka", "environment": "dev", "source_id": ctx.artifact["source_id"],
            "artifact_id": ctx.artifact["id"], "category": "declared", "evidence": [proof], "analysis_status": "detection_only"}
        recovered = architecture.recover(snapshot(ctx, [detection]))
        self.assertFalse(recovered["components"])
        self.assertFalse(recovered["walkthroughs"])
        self.assertFalse(recovered["recommendations"])
        self.assertEqual([], recovered["technology_roles"][0]["node_ids"])
        self.assertIn("operational role is unknown", recovered["technology_roles"][0]["text"])

    def test_report_placement_and_host_inspection_are_kept_separate_from_data(self):
        _, ctx = context({}, "map.json", "environment-map")
        report = ctx.node("report", "orders.dashboard")
        host = ctx.node("deployment_resource", "report.host", {"inspection_points": [{"kind": "logs", "location": "declared/logs/report.log"}]})
        edge = ctx.edge(report, host, "deployment", {"relation": "declared_placement"})
        recovered = architecture.recover(snapshot(ctx))
        trace = next(item for item in recovered["walkthroughs"] if item["output_id"] == report)
        self.assertEqual([edge], [item["id"] for item in trace["deployment_steps"]])
        self.assertFalse(trace["data_steps"])
        self.assertFalse(trace["control_steps"])
        self.assertTrue(any(item["kind"] == "logs" for item in trace["inspection_points"]))
        self.assertFalse(any(item["code"] == "log_visibility_unknown" for item in recovered["questions"]))

    def test_overview_omissions_have_counts_and_a_reserved_question(self):
        _, ctx = context({}, "map.json", "environment-map")
        for index in range(5):
            ctx.node("component", f"declared.component.{index}")
        with patch.object(architecture, "MAX_RECORDS", 2):
            recovered = architecture.recover(snapshot(ctx))
        self.assertEqual(2, len(recovered["components"]))
        self.assertEqual({"count": 5, "shown": 2, "limit": 2}, recovered["truncation"]["collections"]["components"])
        self.assertTrue(recovered["truncation"]["truncated"])
        self.assertLessEqual(len(recovered["questions"]), 2)
        self.assertTrue(any(item["code"] == "architecture_view_truncated" for item in recovered["questions"]))
        self.assertIn("questions", recovered["truncation"]["collections"])

    def test_every_walkthrough_step_collection_reports_clipping(self):
        _, ctx = context({}, "map.json", "environment-map")
        raw, final = ctx.dataset("raw.orders"), ctx.dataset("final.orders")
        producer = ctx.node("pipeline", "producer")
        ctx.edge(raw, final, "data_flow", {"via": producer})
        prior = producer
        for index in range(2):
            task = ctx.node("task", f"task.{index}")
            ctx.edge(prior, task, "control_flow")
            prior = task
            schedule = ctx.node("schedule", f"schedule.{index}", {"expression": "0 3 * * *"})
            ctx.edge(schedule, producer, "schedule")
            host = ctx.node("deployment_resource", f"host.{index}")
            ctx.edge(final, host, "deployment", {"relation": "declared_placement"})
        with patch.object(architecture, "MAX_STEPS", 1):
            recovered = architecture.recover(snapshot(ctx))
        trace = next(item for item in recovered["walkthroughs"] if item["output_id"] == final)
        omitted = trace["truncation"]["collections"]
        self.assertTrue({"data_steps", "control_steps", "deployment_steps", "schedules", "inspection_points"} <= set(omitted))
        for collection in ("data_steps", "control_steps", "deployment_steps", "schedules", "inspection_points"):
            self.assertEqual(1, omitted[collection]["limit"])
            self.assertGreater(omitted[collection]["count"], 1)
            self.assertLessEqual(len(trace[collection]), 1)

    def test_ancestor_budget_does_not_display_unadmitted_source_edges(self):
        _, ctx = context({}, "map.json", "environment-map")
        final = ctx.dataset("final.orders")
        for index in range(5):
            source = ctx.dataset(f"raw.orders_{index}")
            ctx.edge(source, final, "data_flow")
        with patch.object(architecture, "MAX_ANCESTORS", 2):
            recovered = architecture.recover(snapshot(ctx))
        trace = next(item for item in recovered["walkthroughs"] if item["output_id"] == final)
        self.assertEqual(1, len(trace["upstream_dataset_ids"]))
        admitted = {final, *trace["upstream_dataset_ids"], *trace["producer_ids"]}
        self.assertTrue(all(set(step["node_ids"]) <= admitted for step in trace["data_steps"]))
        self.assertEqual(2, trace["truncation"]["collections"]["ancestor_nodes"]["limit"])

    def test_conflict_question_requests_resolving_input_without_mutating_issue(self):
        _, ctx = context({}, "map.json", "environment-map")
        ctx.node("component", "warehouse")
        ctx.issue("adapter_conflict", "Two exports disagree about location.")
        original = snapshot(ctx)
        before = deepcopy(original)
        recovered = architecture.recover(original)
        question = next(item for item in recovered["questions"] if item["code"] == "adapter_conflict")
        self.assertIn("reviewed clarification", question["text"])
        self.assertIn("same revision", question["text"])
        self.assertEqual(before, original)


if __name__ == "__main__":
    unittest.main()
