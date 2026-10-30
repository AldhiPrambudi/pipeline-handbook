import json
from pathlib import Path
import re
import tempfile
import unittest

from pipeline_handbook.render import document


class RenderTests(unittest.TestCase):
    def snapshot(self):
        return {
            "project": "Synthetic <script>alert(1)</script>",
            "collected_at": "2026-10-29T10:00:00+00:00",
            "snapshot_id": "abc", "registry_fingerprint": "def",
            "artifacts": [{"id": "a", "source_id": "demo", "path": "test.sql", "hash": "123", "size": 4, "environment": "dev"}],
            "detections": [{"technology": "postgresql", "family": "database", "environment": "dev", "category": "recognized", "confidence": "high", "versions": [], "support": "subset", "selected": True, "reasons": ["dialect marker"], "evidence": ["ev1"]}],
            "nodes": [{"id": "n1", "kind": "dataset", "name": "raw.orders", "environment": "dev", "namespace": "warehouse", "status": "declared", "attributes": {}, "evidence": ["ev1"]}, {"id": "n2", "kind": "dataset", "name": "mart.orders <x>", "environment": "dev", "namespace": "warehouse", "status": "declared", "attributes": {}, "evidence": ["ev1"]}],
            "edges": [{"id": "e1", "kind": "data_flow", "source": "n1", "target": "n2", "evidence": ["ev1"]}],
            "evidence": [{"id": "ev1", "artifact_id": "a", "location": "demo/test.sql:L1", "source_hash": "123", "adapter": "builtin:sql", "adapter_version": "1.0", "rule_id": "sql", "rule_version": "1", "reason": "definition", "status": "declared"}],
            "issues": [], "capabilities": [], "annotations": [], "effective_config": {}, "metrics": {},
        }

    def test_offline_html_is_escaped_and_all_internal_links_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            files = document(self.snapshot(), directory)
            html = Path(files["html"]).read_text()
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)
            self.assertIn("Content-Security-Policy", html)
            self.assertNotIn("<script src", html)
            self.assertNotIn("https://", html)
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            links = set(re.findall(r'href="#([^"]+)"', html))
            self.assertEqual(links - ids, set())
            self.assertIn("<svg", html)
            self.assertIn("Data flow", html)
            self.assertIn("Control flow", html)
            self.assertEqual(json.loads(Path(files["json"]).read_text()), self.snapshot())

    def test_requested_formats_only_and_invalid_format(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(set(document(self.snapshot(), directory, ["markdown"])), {"markdown"})
            self.assertFalse((Path(directory) / "index.html").exists())
            with self.assertRaises(ValueError):
                document(self.snapshot(), directory, ["exe"])

    def test_empty_snapshot_renders_without_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            files = document({}, directory)
            self.assertIn("Missing edges do not prove absence", Path(files["html"]).read_text())


if __name__ == "__main__":
    unittest.main()
