"""Architecture recovery checks against independent synthetic declarations."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_acceptance import ROOT, run_cli


LABELS = json.loads((ROOT / "tests/architecture_expectations.json").read_text())
ARCHITECTURE_KINDS = {"component", "deployment_resource", "report"}


def make_architecture_config(directory):
    config = json.loads((ROOT / "configs/architecture.json").read_text())
    for source in config["sources"]:
        source["path"] = str((ROOT / "configs" / source["path"]).resolve())
    config["rules"]["directories"] = [str(ROOT / "rules")]
    config["output"]["directory"] = str(directory / "output")
    path = directory / "config.json"
    path.write_text(json.dumps(config))
    return path


def identity(node):
    return node["environment"], node["namespace"], node["kind"], node["name"]


class ArchitectureAcceptance(unittest.TestCase):
    longMessage = False

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pipeline-handbook-architecture-")
        cls.directory = Path(cls.temporary.name)
        cls.config_path = make_architecture_config(cls.directory)
        run_cli("document", "--config", str(cls.config_path))
        cls.output = cls.directory / "output"
        cls.snapshot = json.loads((cls.output / "latest.json").read_text())
        cls.nodes = {node["id"]: node for node in cls.snapshot["nodes"]}
        cls.evidence = {item["id"]: item for item in cls.snapshot["evidence"]}
        cls.architecture = cls.snapshot["architecture"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def node(self, environment, namespace, kind, name):
        matches = [node for node in self.nodes.values() if identity(node) == (environment, namespace, kind, name)]
        self.assertEqual(len(matches), 1, (environment, namespace, kind, name))
        return matches[0]

    def test_declared_components_boundaries_locations_and_consumers_match_manual_inventory(self):
        actual = {identity(node) for node in self.nodes.values() if node["kind"] in ARCHITECTURE_KINDS and node["namespace"] in {"arch_dev", "arch_prod"}}
        expected = {(label["environment"], label["namespace"], label["kind"], label["name"]) for label in LABELS["explicit_assets"]}
        self.assertEqual(actual, expected)
        architecture_ids = {item["node_id"] for item in self.architecture["components"] if item.get("node_id")}
        for label in LABELS["explicit_assets"]:
            with self.subTest(asset=label):
                node = self.node(label["environment"], label["namespace"], label["kind"], label["name"])
                self.assertIn(node["id"], architecture_ids)
                self.assertEqual(node["status"], "declared")
                self.assertTrue(node["evidence"])
                for attribute in ("boundary", "location", "report_type"):
                    if attribute in label:
                        self.assertEqual(node["attributes"].get(attribute), label[attribute])
                if label.get("location_unknown"):
                    self.assertFalse(node["attributes"].get("location"))

    def test_explicit_connections_are_not_inferred_from_shared_network_or_startup(self):
        actual = set()
        for edge in self.snapshot["edges"]:
            if edge["kind"] == "connection":
                source, target = self.nodes[edge["source"]], self.nodes[edge["target"]]
                actual.add((source["environment"], source["name"], target["name"]))
                self.assertEqual(source["environment"], target["environment"])
                self.assertEqual(edge["status"], "declared")
        expected = {(label["environment"], label["source"], label["target"]) for label in LABELS["explicit_connections"]}
        self.assertEqual(actual, expected)
        startup = set()
        placements = set()
        for edge in self.snapshot["edges"]:
            source, target = self.nodes[edge["source"]], self.nodes[edge["target"]]
            if edge["kind"] == "deployment" and edge["attributes"].get("relation") == "startup_dependency":
                startup.add((source["environment"], source["name"], target["name"], edge["attributes"].get("condition")))
            if edge["kind"] == "deployment" and target["name"] in {"host.dev.local", "host.prod.local"}:
                placements.add((source["environment"], source["name"], target["name"]))
        self.assertEqual(startup, {(label["environment"], label["source"], label["target"], label["condition"]) for label in LABELS["startup_dependencies"]})
        self.assertEqual(placements, {(label["environment"], label["source"], label["target"]) for label in LABELS["host_placements"]})
        self.assertFalse(any(edge["kind"] in {"control_flow", "data_flow"} and self.nodes[edge["source"]]["kind"] == self.nodes[edge["target"]]["kind"] == "component" for edge in self.snapshot["edges"]))

    def test_cross_tool_bindings_match_six_field_selectors_and_keep_all_endpoint_evidence(self):
        actual = []
        for edge in self.snapshot["edges"]:
            source, target = self.nodes[edge["source"]], self.nodes[edge["target"]]
            if edge["kind"] == "invocation" and source["name"].startswith("dag.py::warehouse_orders::"):
                actual.append((source["environment"], source["namespace"], source["name"], target["name"]))
                paths = {self.evidence[eid]["location"].split(":L")[0] for eid in edge["evidence"]}
                self.assertTrue({"modern_dev/dag.py", "modern_dev/manifest.json", "arch_dev/environment-map.json"} <= paths)
                binding_evidence = [self.evidence[eid] for eid in edge["evidence"] if self.evidence[eid]["location"].startswith("arch_dev/environment-map.json")]
                self.assertTrue(any(item.get("object_path", "").startswith("/links/") for item in binding_evidence))
        self.assertEqual(set(actual), {(label["environment"], label["namespace"], label["source"], label["target"]) for label in LABELS["exact_invocations"]})

    def test_report_walkthroughs_trace_graph_back_to_raw_definitions_and_controls(self):
        for label in LABELS["report_walkthroughs"]:
            with self.subTest(report=label):
                output = self.node(label["environment"], label["namespace"], "report", label["report"])
                walkthroughs = [item for item in self.architecture["walkthroughs"] if item["output_id"] == output["id"]]
                self.assertEqual(len(walkthroughs), 1)
                walk = walkthroughs[0]
                datasets = [self.nodes[nid] for nid in walk["upstream_dataset_ids"]]
                self.assertEqual({node["name"] for node in datasets}, set(label["upstream_datasets"]))
                self.assertTrue(all(node["environment"] == label["environment"] and node["namespace"] == label["dataset_namespace"] for node in datasets))
                producers = {self.nodes[nid]["name"] for nid in walk["producer_ids"]}
                self.assertTrue(set(label["producer_names"]) <= producers)
                self.assertEqual(walk["data_ancestry_order"], "dependency presentation; not execution sequence")
                locations = {self.evidence[eid]["location"].split(":L")[0] for eid in walk["evidence"]}
                self.assertTrue(set(label["evidence_paths"]) <= locations, locations)
                if label.get("schedule_expression"):
                    self.assertIn(label["schedule_expression"], json.dumps(walk["schedules"]), "Expected schedule missing from report walkthrough")
                if label.get("control_condition"):
                    self.assertIn(label["control_condition"], json.dumps(walk["control_steps"]), "Expected condition missing from report walkthrough")

    def test_newcomer_can_trace_report_via_public_impact_command(self):
        result = run_cli("impact", "--config", str(self.config_path), "--asset", "orders.summary", "--environment", "dev", "--service", "arch_dev", "--direction", "upstream")
        trace = json.loads(result.stdout)
        datasets = {node["name"] for node in trace["affected"] if node["kind"] == "dataset"}
        self.assertEqual(datasets, {"DEMO.RAW.ORDERS", "DEMO.STAGING.ORDERS", "DEMO.FINAL.ORDERS"})
        self.assertTrue(all(node["environment"] == "dev" for node in trace["affected"]))
        ambiguous = run_cli("impact", "--config", str(self.config_path), "--asset", "orders.summary", "--direction", "upstream", check=False)
        self.assertEqual(ambiguous.returncode, 2)
        self.assertEqual({item["environment"] for item in json.loads(ambiguous.stdout)["candidates"]}, {"dev", "prod"})

    def test_conflicts_missing_metadata_and_cross_environment_links_are_explicit(self):
        codes = {item["code"] for item in self.snapshot["issues"]}
        self.assertTrue(set(LABELS["required_gap_codes"]) <= codes)
        warehouse = self.node("dev", "arch_dev", "component", "warehouse.orders")
        declarations = json.dumps(warehouse)
        for location in next(label["conflicting_locations"] for label in LABELS["explicit_assets"] if label.get("conflicting_locations")):
            self.assertIn(location, declarations)
        questions = json.dumps(self.architecture["questions"])
        for code in LABELS["required_gap_codes"]:
            self.assertIn(code, questions, "Architecture questions omit coverage code " + code)
        self.assertIn("unplaced.worker", questions, "Unplaced component needs a location question")
        self.assertFalse(any(self.nodes[edge["source"]]["environment"] != self.nodes[edge["target"]]["environment"] for edge in self.snapshot["edges"]))
        for name in LABELS["rejected_asset_names"]:
            self.assertFalse(any(node["name"] == name for node in self.nodes.values()))

    def test_misleading_unsupported_malformed_and_dynamic_artifacts_remain_coverage_gaps(self):
        artifacts = {item["id"]: item for item in self.snapshot["artifacts"]}
        misleading = next(item for item in artifacts.values() if item["source_id"] == "arch_dev" and item["path"] == "compose-misleading.json")
        self.assertFalse(any(item["artifact_id"] == misleading["id"] for item in self.snapshot["detections"]))
        issue_paths = {artifacts[item["artifact_id"]]["path"] for item in self.snapshot["issues"] if item.get("artifact_id") in artifacts}
        self.assertTrue({"future-map.json", "malformed-map.json", "dynamic-map.json"} <= issue_paths)
        future = next(item for item in artifacts.values() if item["source_id"] == "arch_dev" and item["path"] == "future-map.json")
        self.assertTrue(any(item["artifact_id"] == future["id"] for item in self.snapshot["detections"]))

    def test_architecture_records_are_evidenced_declared_or_inferred_without_runtime_claims(self):
        self.assertFalse(self.architecture["recommendations"])
        for collection in ("findings", "components", "technology_roles", "relationships", "walkthroughs", "inspection_points", "questions"):
            for record in self.architecture[collection]:
                self.assertTrue(record["id"])
                self.assertIn(record["status"], {"declared", "inferred", "unknown"})
                self.assertTrue(record["text"])
                self.assertTrue(set(record["evidence"]) <= self.evidence.keys())
        self.assertFalse(any(node["kind"] == "run" or node["status"] == "observed" for node in self.nodes.values()))
        for location in LABELS["known_inspection_locations"]:
            self.assertIn(location, json.dumps(self.architecture["inspection_points"]), "Inspection point missing: " + location)
        questions = json.dumps(self.architecture["questions"]).lower()
        self.assertIn("runtime", questions, "Runtime visibility question missing")
        self.assertIn("log", questions, "Log visibility question missing")
        self.assertIn("owner", questions, "Ownership question missing")
        canary = b"FAKE_ARCH_SECRET_CANARY_7231"
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(canary, path.read_bytes(), str(path))

    def test_generated_offline_handbook_contains_architecture_and_walkthrough_evidence(self):
        markdown = (self.output / "handbook.md").read_text()
        html = (self.output / "index.html").read_text()
        for phrase in ("orders.summary", "orders.review_form", "Analytics boundary", "Consumer boundary", "host.dev.local", "DEMO.RAW.ORDERS", "environment-map.json", "compose.json"):
            self.assertIn(phrase, markdown, "Markdown handbook missing " + phrase)
            self.assertIn(phrase, html, "HTML handbook missing " + phrase)
        self.assertIn("architecture", html.lower())
        self.assertNotIn('<script src="http', html.lower())


class UnavailableArchitectureTargets(unittest.TestCase):
    def test_missing_and_excluded_metadata_targets_cannot_be_resolved_by_selectors(self):
        with tempfile.TemporaryDirectory(prefix="pipeline-handbook-unavailable-map-") as temporary:
            directory = Path(temporary)
            source = directory / "map"
            excluded = directory / "excluded"
            source.mkdir()
            excluded.mkdir()
            shutil.copyfile(ROOT / "fixtures/modern/dev/manifest.json", excluded / "manifest.json")
            origin = {"kind": "component", "name": "inspection.probe", "environment": "dev", "namespace": "map", "source_id": "map", "artifact_path": "access-map.json"}
            links = []
            for target_source in ("missing", "excluded"):
                target = {"kind": "pipeline", "name": "manifest.json::model.synthetic_orders.final_orders", "environment": "dev", "namespace": target_source, "source_id": target_source, "artifact_path": "manifest.json"}
                links.append({"source": origin, "target": target, "kind": "invocation", "attributes": {"relation": "supplied reference cannot grant access"}})
            (source / "access-map.json").write_text(json.dumps({"format": "pipeline-handbook.environment/v1", "components": [{"name": "inspection.probe"}], "links": links}))
            config = {
                "project": "unavailable_architecture_targets",
                "sources": [
                    {"id": "map", "kind": "directory", "environment": "dev", "path": "map"},
                    {"id": "missing", "kind": "directory", "environment": "dev", "path": "metadata-not-supplied"},
                    {"id": "excluded", "kind": "directory", "environment": "dev", "path": "excluded", "exclude": ["manifest.json"]}
                ],
                "output": {"directory": "output", "formats": ["json"]}
            }
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config))
            run_cli("analyze", "--config", str(config_path))
            snapshot = json.loads((directory / "output/latest.json").read_text())
            self.assertIn("access_denied", {item["code"] for item in snapshot["issues"]})
            unresolved = [item for item in snapshot["issues"] if item["code"] == "unresolved_architecture_link"]
            self.assertEqual(len(unresolved), 2)
            self.assertTrue(all(item["evidence"] for item in unresolved))
            self.assertFalse(any(edge["kind"] == "invocation" for edge in snapshot["edges"]))
            self.assertFalse(any(node["kind"] == "pipeline" for node in snapshot["nodes"]))


if __name__ == "__main__":
    unittest.main()
