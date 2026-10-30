"""Public-CLI acceptance checks against hand-labeled, synthetic fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "tests/expectations.json").read_text())


def run_cli(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [sys.executable, "-m", "pipeline_handbook", *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    if check and result.returncode:
        raise AssertionError(f"CLI {arguments!r} failed: {result.stdout}\n{result.stderr}")
    return result


def make_config(directory: Path, mode="auto", include=None, exclude=None, overrides=None) -> Path:
    template = json.loads((ROOT / "configs/demo.json").read_text())
    for source in template["sources"]:
        source["path"] = str((ROOT / "configs" / source["path"]).resolve())
    template["rules"]["directories"] = [str(ROOT / "rules")]
    template["discovery"]["mode"] = mode
    template["technologies"] = {"include": include or ["*"], "exclude": exclude or [], "overrides": overrides or {}}
    template["output"]["directory"] = str(directory / "output")
    path = directory / "config.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    return path


class PortfolioAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pipeline-handbook-acceptance-")
        cls.directory = Path(cls.temporary.name)
        cls.config = make_config(cls.directory)
        run_cli("analyze", "--config", str(cls.config))
        cls.output = cls.directory / "output"
        cls.snapshot = json.loads((cls.output / "latest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_labeled_technology_inventory(self):
        artifacts = {artifact["id"]: artifact for artifact in self.snapshot["artifacts"]}
        detections = self.snapshot["detections"]
        for label in LABELS["detection_labels"]:
            with self.subTest(label=label):
                matches = [
                    item for item in detections
                    if item["technology"] == label["technology"]
                    and artifacts[item["artifact_id"]]["source_id"] == label["source"]
                    and artifacts[item["artifact_id"]]["path"] == label["path"]
                ]
                self.assertEqual(bool(matches), label["present"])
                if matches and "category" in label:
                    self.assertIn(label["category"], {item["category"] for item in matches})

    def test_manual_expected_lineage_and_direction(self):
        nodes = {node["id"]: node for node in self.snapshot["nodes"]}
        actual = set()
        for edge in self.snapshot["edges"]:
            source, target = nodes[edge["source"]], nodes[edge["target"]]
            if edge["kind"] == "data_flow" and source["kind"] == target["kind"] == "dataset":
                self.assertEqual(source["environment"], target["environment"])
                actual.add((source["environment"], source["namespace"], source["name"], target["name"]))
        expected = {(item["environment"], item["namespace"], item["source"], item["target"]) for item in LABELS["dataset_edges"]}
        self.assertEqual(actual, expected)
        for environment, namespace, source, target in expected:
            self.assertNotIn((environment, namespace, target, source), actual)

    def test_separate_environment_identity(self):
        nodes = [node for node in self.snapshot["nodes"] if node["kind"] == "dataset" and node["name"] == "final.orders"]
        self.assertEqual({node["environment"] for node in nodes}, {"dev", "prod"})
        self.assertEqual(len({node["id"] for node in nodes}), 2)

    def test_no_target_execution_or_secret_persistence(self):
        self.assertFalse((ROOT / "SCANNER_EXECUTION_CANARY").exists())
        self.assertFalse((ROOT / "fixtures/adversarial/SCANNER_EXECUTION_CANARY").exists())
        forbidden = [
            b"FAKE_PASSWORD_CANARY_938172", b"FAKE_API_KEY_CANARY_827361",
            b"FAKE_TOKEN_CANARY_716253", b"FAKE_URI_CANARY_625134",
            b"FAKE_PRIVATE_KEY_CANARY_514023",
        ]
        for path in self.output.rglob("*"):
            if path.is_file():
                persisted = path.read_bytes()
                for canary in forbidden:
                    self.assertNotIn(canary, persisted, str(path))
        self.assertTrue(all("text" not in artifact for artifact in self.snapshot["artifacts"]))

    def test_static_definitions_never_become_runtime_observations(self):
        self.assertFalse(any(node["kind"] == "run" for node in self.snapshot["nodes"]))
        self.assertFalse(any(node["status"] == "observed" for node in self.snapshot["nodes"]))
        snowflake = [item for item in self.snapshot["detections"] if item["technology"] == "snowflake"]
        self.assertTrue(snowflake)
        # Connector and dbt package versions cannot establish a warehouse server version.
        for detection in snowflake:
            self.assertFalse(any(version in ("3.12.3", "1.8.4", "1.8.8") for version in detection.get("versions", [])))

    def test_version_conflicts_export_age_and_client_identity_are_preserved(self):
        self.assertTrue(any(issue["code"] == "version_conflict" for issue in self.snapshot["issues"]))
        postgres = [item for item in self.snapshot["detections"] if item["technology"] == "postgresql"]
        self.assertTrue(any(item.get("source_exported_at") == "2026-01-15T00:00:00Z" for item in postgres))
        self.assertTrue(any("16.4" in item["versions"] for item in postgres))
        self.assertTrue(any("15.8" in item["versions"] for item in postgres))
        client = [item for item in self.snapshot["detections"] if item["technology"] == "snowflake" and item.get("client_versions")]
        self.assertEqual(len(client), 1)
        self.assertEqual(client[0]["client_versions"], ["3.12.3"])
        self.assertEqual(client[0]["versions"], [])
        self.assertEqual(client[0]["category"], "declared")

    def test_unknowns_and_adversarial_gaps_remain_visible(self):
        artifacts = {artifact["id"]: artifact for artifact in self.snapshot["artifacts"]}
        self.assertTrue(any(artifact["path"] == "unknown.workflow" for artifact in artifacts.values()))
        issue_paths = {artifacts[item["artifact_id"]]["path"] for item in self.snapshot["issues"] if item.get("artifact_id") in artifacts}
        self.assertIn("unsafe.ktr", issue_paths)
        self.assertIn("dynamic_dag.py", issue_paths)
        self.assertIn("dynamic.sql", issue_paths)

    def test_repeated_scan_has_same_semantic_snapshot(self):
        run_cli("analyze", "--config", str(self.config))
        repeated = json.loads((self.output / "latest.json").read_text())
        self.assertEqual(self.snapshot["snapshot_id"], repeated["snapshot_id"])

    def test_new_joiner_traces_final_dataset_to_raw_with_scoped_evidence(self):
        result = run_cli("impact", "--config", str(self.config), "--asset", "final.orders",
                         "--direction", "upstream", "--environment", "dev", "--service", "legacy_orders")
        trace = json.loads(result.stdout)
        upstream_datasets = {node["name"] for node in trace["affected"] if node["kind"] == "dataset"}
        self.assertEqual(upstream_datasets, {"raw.orders", "staging.orders"})
        self.assertTrue(all(node["environment"] == "dev" for node in trace["affected"]))
        self.assertTrue(trace["relationships"])
        self.assertTrue(all(edge["kind"] == "data_flow" and edge["evidence"] for edge in trace["relationships"]))
        evidence = {item["id"]: item for item in self.snapshot["evidence"]}
        locations = {evidence[eid]["location"] for edge in trace["relationships"] for eid in edge["evidence"]}
        self.assertTrue(any("transform.ktr" in location for location in locations))
        self.assertTrue(any("publish.sql" in location for location in locations))

    def test_impact_keeps_ambiguous_and_unknown_identities_explicit(self):
        result = run_cli("impact", "--config", str(self.config), "--asset", "final.orders", check=False)
        self.assertEqual(result.returncode, 2)
        ambiguity = json.loads(result.stdout)
        self.assertEqual({node["environment"] for node in ambiguity["candidates"]}, {"dev", "prod"})
        self.assertIn("error", ambiguity)
        result = run_cli("impact", "--config", str(self.config), "--asset", "not_a_known_asset", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["candidates"], [])

    def test_unsupported_dbt_schema_remains_visible_without_extracted_graph(self):
        artifact = next(item for item in self.snapshot["artifacts"] if item["source_id"] == "adversarial" and item["path"] == "dbt-v11.json")
        findings = [item for item in self.snapshot["detections"] if item["artifact_id"] == artifact["id"] and item["technology"] == "dbt"]
        self.assertTrue(findings)
        self.assertTrue(any(item["artifact_id"] == artifact["id"] and "unsupported" in item["code"] for item in self.snapshot["issues"]))
        source_evidence = {item["id"] for item in self.snapshot["evidence"] if item["artifact_id"] == artifact["id"]}
        self.assertFalse(any(source_evidence.intersection(node["evidence"]) for node in self.snapshot["nodes"]))

    def test_browsable_handbook_answers_labeled_tasks(self):
        run_cli("document", "--config", str(self.config))
        for filename in ("index.html", "handbook.md", "handbook.json"):
            self.assertTrue((self.output / filename).is_file())
        handbook = (self.output / "handbook.md").read_text()
        for label in LABELS["new_joiner_answers"]:
            if label["evidence_path"]:
                self.assertIn(label["answer"], handbook)
                self.assertIn(label["evidence_path"], handbook)
        html = (self.output / "index.html").read_text().lower()
        self.assertNotIn("<script src=\"http", html)
        self.assertNotIn("<link rel=\"stylesheet\" href=\"http", html)
        self.assertIn("evidence", html)

    def test_manual_and_hybrid_effective_selection(self):
        with tempfile.TemporaryDirectory(prefix="pipeline-handbook-modes-") as name:
            directory = Path(name)
            config = make_config(directory, mode="manual", include=["postgresql"], overrides={"postgresql": {"dialect": "postgres", "version": "16.4"}})
            run_cli("analyze", "--config", str(config))
            manual = json.loads((directory / "output/latest.json").read_text())
            self.assertTrue(any(item["technology"] == "airflow" and not item["selected"] for item in manual["detections"]))
            self.assertEqual(manual["effective_config"]["technologies"]["overrides"]["postgresql"]["version"], "16.4")
            config = make_config(directory, mode="hybrid", exclude=["docker"])
            run_cli("analyze", "--config", str(config))
            hybrid = json.loads((directory / "output/latest.json").read_text())
            self.assertTrue(any(item["technology"] == "docker" and not item["selected"] for item in hybrid["detections"]))
            self.assertTrue(any(item["technology"] == "airflow" and item["selected"] for item in hybrid["detections"]))


class ExplicitDataDemo(unittest.TestCase):
    def test_raw_transformed_final_example_requires_separate_explicit_commands(self):
        with tempfile.TemporaryDirectory(prefix="pipeline-handbook-data-demo-") as name:
            database = Path(name) / "orders.sqlite"
            def demo(command):
                result = subprocess.run([sys.executable, str(ROOT / "demos/data_demo.py"), command, "--database", str(database)], capture_output=True, text=True, check=True, timeout=20)
                return json.loads(result.stdout)
            self.assertEqual(demo("setup")["raw_rows"], 3)
            before = demo("inspect")
            self.assertEqual(before["tables"]["final_orders"]["status"], "not created")
            result = demo("run")
            self.assertEqual(result["final_order_count"], 2)
            self.assertEqual(result["final_total_amount"], 30.0)
            self.assertEqual(len(demo("inspect")["tables"]["transformed_orders"]["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
