"""Freshness, reviewed annotations and portable extension evidence."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_acceptance import ROOT, run_cli


class FreshnessAndPortableExtensions(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pipeline-handbook-freshness-")
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "source"
        self.source.mkdir()
        self.output = self.directory / "output"
        self.config_path = self.directory / "config.json"
        self.config = {
            "project": "freshness_tests",
            "sources": [{"id": "scope", "kind": "directory", "environment": "test", "service": "orders", "path": "source"}],
            "output": {"directory": "output", "formats": ["markdown", "html", "json"]},
        }
        self.sql = self.source / "orders.sql"
        self.sql.write_text("-- dialect: postgres\nCREATE TABLE final.orders AS SELECT order_id FROM raw.orders;\n")

    def tearDown(self):
        self.temporary.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def scan(self, command="analyze"):
        self.write_config()
        run_cli(command, "--config", str(self.config_path))
        return json.loads((self.output / "latest.json").read_text())

    def status(self):
        self.write_config()
        return json.loads(run_cli("status", "--config", str(self.config_path)).stdout)

    def extension_workspace(self, directory):
        source = directory / "source"
        rules = directory / "reviewed_rules"
        plugins = directory / "trusted"
        for path in (source, rules, plugins):
            path.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "examples/trusted_plugins/acme-export.json", source / "acme.json")
        shutil.copyfile(ROOT / "examples/trusted_plugins/acme.rules.json", rules / "acme.rules.json")
        shutil.copyfile(ROOT / "examples/trusted_plugins/acme.py", plugins / "acme.py")
        config = {
            "project": "portable_extension",
            "sources": [{"id": "acme", "kind": "directory", "environment": "demo", "service": "acme_orders", "path": "source"}],
            "rules": {"directories": ["reviewed_rules"]},
            "adapters": {"trusted": ["builtin:*", "example:acme"], "plugins": [{"id": "example:acme", "path": "trusted/acme.py", "version": "1.0.0", "technologies": ["acme"], "priority": 150}]},
            "output": {"directory": "output", "formats": ["json"]},
        }
        config_path = directory / "config.json"
        config_path.write_text(json.dumps(config))
        return config_path

    def test_status_is_current_then_reports_changed_definition_without_rewriting_snapshot(self):
        self.scan()
        original = (self.output / "latest.json").read_bytes()
        current = self.status()
        self.assertEqual(current["state"], "current")
        self.assertFalse(current["stale"])
        self.assertEqual((self.output / "latest.json").read_bytes(), original)
        self.sql.write_text(self.sql.read_text().replace("raw.orders", "raw.changed_orders"))
        stale = self.status()
        self.assertEqual(stale["state"], "stale")
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["changed"], ["scope/orders.sql"])
        self.assertEqual((self.output / "latest.json").read_bytes(), original)

    def test_status_reports_added_and_removed_artifacts(self):
        self.scan()
        extra = self.source / "extra.json"
        extra.write_text('{"unsupported_format": "synthetic"}\n')
        added = self.status()
        self.assertEqual(added["state"], "stale")
        self.assertEqual(added["added"], ["scope/extra.json"])
        self.scan()
        extra.unlink()
        removed = self.status()
        self.assertEqual(removed["state"], "stale")
        self.assertEqual(removed["removed"], ["scope/extra.json"])

    def test_annotations_change_freshness_and_survive_document_regeneration(self):
        initial = self.scan()
        node_id = next(node["id"] for node in initial["nodes"] if node["kind"] == "dataset" and node["name"] == "final.orders")
        annotations = self.directory / "annotations.json"
        reviewed = [{"node_id": node_id, "purpose": "Synthetic reviewed publication for onboarding", "owner": "Demo data team", "reviewed_by": "Portfolio reviewer", "reviewed_at": "2026-01-15"}]
        annotations.write_text(json.dumps(reviewed))
        self.config["annotations"] = "annotations.json"
        self.scan("document")
        self.assertEqual(self.status()["state"], "current")
        reviewed[0]["purpose"] = "Updated reviewed purpose retained across regeneration"
        annotations.write_text(json.dumps(reviewed))
        original = annotations.read_bytes()
        stale = self.status()
        self.assertTrue(stale["annotations_changed"])
        self.assertEqual(stale["state"], "stale")
        regenerated = self.scan("document")
        self.assertEqual(annotations.read_bytes(), original)
        self.assertEqual(regenerated["annotations"], reviewed)
        self.assertIn(reviewed[0]["purpose"], (self.output / "handbook.md").read_text())
        self.assertEqual(self.status()["state"], "current")

    def test_missing_visibility_has_unknown_freshness_when_no_definition_change_is_proven(self):
        self.sql.chmod(0)
        try:
            self.scan()
            result = self.status()
            self.assertEqual(result["state"], "unknown")
            self.assertIsNone(result["stale"])
            self.assertFalse(result["coverage_complete"])
        finally:
            self.sql.chmod(0o600)

    def test_identical_extension_snapshots_are_reproducible_across_workspace_paths(self):
        snapshots = []
        for name in ("location_one", "a_different_location"):
            directory = self.directory / name
            config_path = self.extension_workspace(directory)
            run_cli("analyze", "--config", str(config_path))
            snapshots.append(json.loads((directory / "output/latest.json").read_text()))
        self.assertEqual(snapshots[0]["registry_fingerprint"], snapshots[1]["registry_fingerprint"])
        self.assertEqual(snapshots[0]["effective_config"], snapshots[1]["effective_config"])
        self.assertEqual(snapshots[0]["snapshot_id"], snapshots[1]["snapshot_id"])
        self.assertNotIn(str(self.directory), json.dumps(snapshots))

    def test_duplicate_json_export_keys_are_reported_without_extraction(self):
        directory = self.directory / "duplicate_json"
        config_path = self.extension_workspace(directory)
        export = directory / "source/acme.json"
        export.write_text('{"technology":"acme","export_schema":"1","tasks":{},"tasks":{"bad":{"input":"raw.duplicate","output":"final.duplicate"}}}')
        run_cli("analyze", "--config", str(config_path))
        snapshot = json.loads((directory / "output/latest.json").read_text())
        self.assertIn("invalid_json", {issue["code"] for issue in snapshot["issues"]})
        self.assertFalse(any(node["kind"] in {"pipeline", "task", "dataset"} for node in snapshot["nodes"]))

    def test_rule_attribute_aliases_map_existing_metadata_and_record_concept(self):
        directory = self.directory / "declarative_mapping"
        config_path = self.extension_workspace(directory)
        pack_path = directory / "reviewed_rules/acme.rules.json"
        pack = json.loads(pack_path.read_text())
        pack["entries"][0]["mapping"].update({"attribute_aliases": {"label": "display_name"}, "concept": "onboarding_workflow"})
        pack_path.write_text(json.dumps(pack))
        (directory / "trusted/acme.py").write_text('def analyze(artifact, ctx):\n    ctx.node("pipeline", artifact["path"], {"label": "ACME"})\n')
        run_cli("analyze", "--config", str(config_path))
        snapshot = json.loads((directory / "output/latest.json").read_text())
        pipeline = next(node for node in snapshot["nodes"] if node["kind"] == "pipeline")
        self.assertEqual(pipeline["attributes"]["label"], "ACME")
        self.assertEqual(pipeline["attributes"]["display_name"], "ACME")
        self.assertIn("onboarding_workflow", pipeline["rule_concepts"])


if __name__ == "__main__":
    unittest.main()
