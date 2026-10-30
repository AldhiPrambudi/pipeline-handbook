"""Presentation acceptance for recovered facts, without inventing architecture."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from pipeline_handbook.render import document


class ArchitectureRenderingTests(unittest.TestCase):
    def snapshot(self):
        def node(nid, kind, name, attrs=None):
            return {"id": nid, "kind": kind, "name": name, "environment": "dev", "namespace": "demo",
                    "status": "declared", "attributes": attrs or {}, "evidence": ["ev1"]}
        def record(rid, text, **kwargs):
            return {"id": rid, "status": "declared", "evidence": ["ev1"], "text": text, **kwargs}
        snapshot = {
            "project": "architecture_demo", "snapshot_id": "static", "collected_at": "2026-10-30T01:00:00Z",
            "registry_fingerprint": "registry", "effective_config": {}, "metrics": {}, "detections": [],
            "artifacts": [{"id": "a1", "path": "environment.json", "source_id": "demo", "environment": "dev", "size": 100, "hash": "hash"}],
            "nodes": [node("component", "component", "workflow engine", {"boundary": "application zone", "role": "declared scheduler"}),
                      node("host", "deployment_resource", "local container", {"boundary": "runner host"}),
                      node("database", "component", "warehouse service"),
                      node("raw", "dataset", "source.orders"), node("output", "dataset", "staging.orders"),
                      node("pipeline", "pipeline", "transform.sql", {"entrypoint": True}),
                      node("report", "report", 'order form <script>alert(1)</script>', {"report_type": "form"})],
            "edges": [{"id": "deploy", "source": "component", "target": "host", "kind": "deployment", "status": "declared", "attributes": {}, "evidence": ["ev1"]},
                      {"id": "connect", "source": "component", "target": "database", "kind": "connection", "status": "declared", "attributes": {}, "evidence": ["ev1"]},
                      {"id": "lineage", "source": "raw", "target": "output", "kind": "data_flow", "status": "declared", "attributes": {"via": "pipeline"}, "evidence": ["ev1"]}],
            "evidence": [{"id": "ev1", "artifact_id": "a1", "location": "demo/environment.json:L1", "object_path": "/components/0", "source_hash": "hash", "adapter": "builtin:environment_map", "adapter_version": "1.0.0", "rule_id": "map", "rule_version": "1.0.0", "status": "declared"}],
            "issues": [], "capabilities": [], "annotations": [],
        }
        inspection = record("inspect", "Inspect the declared form definition", node_id="report", kind="definition", location="reports/orders.json", object_path="/reports/0", environment="dev")
        snapshot["architecture"] = {
            "schema_version": "1", "findings": [record("finding", "A supplied form consumes a declared dataset", node_ids=["report", "output"])],
            "components": [record("comp-view", "Configured scheduler component", node_id="component", name="workflow engine", kind="component", environment="dev", boundary="application zone", location="configured container", technology="airflow")],
            "technology_roles": [record("role", "Airflow defines declared task dependencies", technology="airflow", environment="dev", source_id="demo", category="recognized", analysis_status="subset", node_ids=["component"])],
            "relationships": [],
            "walkthroughs": [record("walk", "Trace the form's declared data ancestry; execution unverified.", status="inferred", title="Order form walkthrough", output_id="report", environment="dev", namespace="demo",
                                     data_steps=[record("data-step", "source.orders feeds staging.orders through transform.sql", node_ids=["raw", "output", "pipeline"], edge_ids=["lineage"])],
                                     control_steps=[record("control-step", "The declared task condition is success", node_ids=["component"])],
                                     schedules=[record("schedule", "Declared schedule: 0 3 * * *")], inspection_points=[inspection], limitations=["Actual deployment, runtime success and ownership are unknown."])],
            "inspection_points": [inspection], "questions": [record("question", "Where are time-bound run logs?", status="unknown")], "recommendations": [],
        }
        return snapshot

    def render(self, snapshot):
        with tempfile.TemporaryDirectory() as directory:
            paths = document(snapshot, directory)
            return {key: Path(path).read_text() for key, path in paths.items()}

    def test_architecture_keeps_deployment_data_and_control_views_separate(self):
        html = self.render(self.snapshot())["html"]
        self.assertIn('id="architecture-overview"', html)
        topology = html.split('<section id="architecture-topology">')[1].split('</section>')[0]
        self.assertIn("application zone", topology)
        self.assertIn("runner host", topology)
        self.assertIn("Boundary not supplied", topology)
        self.assertIn("deployment", topology)
        self.assertIn("connection", topology)
        self.assertNotIn("source.orders", topology)
        self.assertIn('id="data-flow"', html)
        self.assertIn('id="control-flow"', html)
        self.assertIn("configured deployment or connection references", topology)

    def test_walkthrough_labels_inspection_sequence_not_execution_order(self):
        outputs = self.render(self.snapshot())
        for rendered in (outputs["html"], outputs["markdown"]):
            self.assertIn("not execution order" if rendered == outputs["markdown"] else "not an asserted execution order", rendered)
            self.assertIn("Data ancestry", rendered)
            self.assertIn("Actual declared control dependencies", rendered)
            self.assertIn("The declared task condition is success", rendered)
            self.assertIn("0 3 * * *", rendered)
            self.assertIn("Actual deployment, runtime success and ownership are unknown", rendered)
            self.assertIn("reports/orders.json", rendered)

    def test_all_architecture_evidence_and_asset_links_resolve_once(self):
        html = self.render(self.snapshot())["html"]
        ids = re.findall(r'\bid="([^"]+)"', html)
        targets = set(re.findall(r'href="#([^"]+)"', html))
        self.assertEqual(targets - set(ids), set())
        self.assertEqual(len(ids), len(set(ids)))
        self.assertRegex(html, r'<summary>demo/environment\.json:L1 <code>/components/0</code>')

    def test_empty_rfc6901_pointer_is_visible_as_document_root(self):
        snapshot = self.snapshot()
        snapshot["evidence"][0]["object_path"] = ""
        snapshot["architecture"]["inspection_points"][0]["object_path"] = ""
        outputs = self.render(snapshot)
        self.assertIn("document root (empty JSON pointer)", outputs["html"])
        self.assertIn("document root \\(empty JSON pointer\\)", outputs["markdown"])
        self.assertEqual(json.loads(outputs["json"])["evidence"][0]["object_path"], "")

    def test_recommendations_empty_and_findings_stay_factual(self):
        outputs = self.render(self.snapshot())
        html = outputs["html"]
        section = html.split('<section id="architecture-recommendations">')[1].split('</section>')[0]
        self.assertIn("No recommendations generated", section)
        self.assertNotIn("A supplied form consumes", section)
        self.assertIn("A supplied form consumes", html)
        self.assertIn("No recommendations generated", outputs["markdown"])

    def test_invocations_are_separate_from_actual_task_controls(self):
        snapshot = self.snapshot()
        snapshot["architecture"]["walkthroughs"][0]["control_steps"].append({
            "id": "invocation", "kind": "invocation", "status": "declared", "evidence": ["ev1"],
            "text": "Explicit workflow reference, not a task dependency", "node_ids": ["component", "pipeline"],
        })
        snapshot["architecture"]["walkthroughs"][0]["deployment_steps"] = [{
            "id": "placement", "kind": "deployment", "status": "declared", "evidence": ["ev1"],
            "text": "Configured placement only; actual runtime host is unknown", "node_ids": ["component", "host"],
        }]
        html = self.render(snapshot)["html"]
        controls = html.split("<h4>Actual declared control dependencies</h4>")[1].split("<h4>")[0]
        self.assertIn("The declared task condition is success", controls)
        self.assertNotIn("Explicit workflow reference", controls)
        invocations = html.split("<h4>Definition invocation references</h4>")[1].split("<h4>")[0]
        self.assertIn("Explicit workflow reference", invocations)
        self.assertIn("Configured placement only; actual runtime host is unknown", html)

    def test_untrusted_labels_escape_and_json_retains_exact_contract(self):
        snapshot = self.snapshot()
        outputs = self.render(snapshot)
        self.assertNotIn("<script>", outputs["html"])
        self.assertIn("&lt;script&gt;", outputs["html"])
        self.assertEqual(json.loads(outputs["json"]), snapshot)

    def test_markdown_labels_cannot_embed_remote_images_or_links(self):
        snapshot = self.snapshot()
        snapshot["nodes"][0]["name"] = "foreign ![image](https://example.invalid/track) [link](javascript:alert)"
        outputs = self.render(snapshot)
        self.assertNotIn("![image](https://example.invalid/track)", outputs["markdown"])
        self.assertNotIn("[link](javascript:alert)", outputs["markdown"])
        self.assertIn("!\\[image\\]\\(https://example.invalid/track\\)", outputs["markdown"])

    def test_optional_architecture_capability_declarations_are_readable(self):
        snapshot = self.snapshot()
        snapshot["capabilities"] = [{"technology": "environment-map", "architecture_features": {
            "technology_role_evidence": "subset", "component_inventory": "subset", "deployment_configuration": "subset",
            "configured_connections": "subset", "report_consumers": "subset", "exact_bindings": "subset",
            "architecture_views": "subset", "workflow_walkthroughs": "subset",
        }}]
        outputs = self.render(snapshot)
        for rendered in (outputs["html"], outputs["markdown"]):
            self.assertIn("Architecture recovery capabilities", rendered)
            self.assertIn("Configured connections", rendered)
            self.assertIn("environment-map", rendered)

    def test_old_snapshots_remain_compatible_and_get_no_invented_view(self):
        snapshot = self.snapshot()
        del snapshot["architecture"]
        outputs = self.render(snapshot)
        self.assertNotIn('id="architecture-overview"', outputs["html"])
        self.assertNotIn("## Recovered architecture overview", outputs["markdown"])
        self.assertEqual(json.loads(outputs["json"]), snapshot)

    def test_source_grouping_without_components_does_not_invent_topology(self):
        snapshot = self.snapshot()
        snapshot["nodes"] = [n for n in snapshot["nodes"] if n["kind"] not in {"component", "deployment_resource", "report"}]
        snapshot["edges"] = [e for e in snapshot["edges"] if e["kind"] == "data_flow"]
        snapshot["architecture"]["walkthroughs"] = []
        snapshot["architecture"]["components"] = [{"id": "group", "status": "inferred", "text": "Definitions share an authorized source", "name": "source group", "node_ids": ["pipeline"], "evidence": ["ev1"]}]
        html = self.render(snapshot)["html"]
        topology = html.split('<section id="architecture-topology">')[1].split('</section>')[0]
        self.assertIn("No explicit component deployment or connection topology", topology)
        self.assertNotIn("<svg", topology)
        self.assertNotIn("bronze", topology)


if __name__ == "__main__":
    unittest.main()
