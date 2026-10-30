"""Adapter metadata-only permissions and reviewed configuration path boundaries."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from pipeline_handbook.config import load_config
from tests import test_core as core_helpers
from tests.test_acceptance import run_cli


class WorkerInspectionGuards(unittest.TestCase):
    def setUp(self):
        self.workspace = core_helpers.CoreBoundaries()
        self.workspace.setUp()

    def tearDown(self):
        self.workspace.tearDown()

    def test_adapter_process_network_file_and_dynamic_execution_permissions(self):
        workspace = self.workspace
        workspace.acme_rule()
        workspace.sql()
        workspace.output.mkdir()
        (workspace.output / "read-probe.txt").write_text("synthetic existing output metadata")
        canary = "FAKE_WORKER_OUTPUT_CANARY_902104"
        export = json.loads((workspace.source / "acme.json").read_text())
        export["secret"] = canary
        (workspace.source / "acme.json").write_text(json.dumps(export))
        operations = {
            "subprocess": "import subprocess, sys\n    subprocess.run([sys.executable, '-c', 'pass'], check=True)",
            "system": "import os\n    os.system('true')",
            "socket": "import socket\n    connection = socket.socket()\n    connection.close()",
            "target_read": "path = ctx.config['sources'][0]['_root'] + '/orders.sql'\n    open(path).read()",
            "output_read": "path = ctx.config['output']['_root'] + '/read-probe.txt'\n    open(path).read()",
            "write": "path = ctx.config['output']['_root'] + '/write-canary.txt'\n    open(path, 'w').write('guard failed')",
            "dynamic_exec": "exec(artifact['text'])",
        }
        for name, operation in operations.items():
            workspace.plugin(name, "def analyze(artifact, ctx):\n    " + operation + "\n")
        workspace.plugin("printed_failure", (
            "import os, sys\n"
            f"print({canary!r})\n"
            f"os.write(1, {canary.encode()!r})\n"
            f"os.write(2, {canary.encode()!r})\n"
            "def analyze(artifact, ctx):\n"
            f"    print({canary!r}, file=sys.stderr)\n"
            f"    raise ValueError({canary!r})\n"
        ))
        # A permitted plugin proves successful component import/SDK access, so
        # denied operations cannot all be mistaken for a broken loader.
        workspace.plugin("control", "def analyze(artifact, ctx):\n    ctx.node('pipeline', 'guard_control', {'definition_only': True})\n")
        result = run_cli("analyze", "--config", str(workspace.write_config()))
        snapshot = json.loads((workspace.output / "latest.json").read_text())
        failures = [issue for issue in snapshot["issues"] if issue["code"] == "adapter_failed"]
        for name in operations:
            with self.subTest(operation=name):
                self.assertTrue(any("example:" + name + " " in issue["message"] and "PermissionError" in issue["message"] for issue in failures))
        self.assertTrue(any("example:printed_failure " in issue["message"] and "ValueError" in issue["message"] for issue in failures))
        self.assertTrue(any(node["kind"] == "pipeline" and node["name"] == "guard_control" for node in snapshot["nodes"]))
        self.assertTrue(any(node["kind"] == "dataset" and node["name"] == "final.orders" for node in snapshot["nodes"]))
        self.assertFalse((workspace.output / "write-canary.txt").exists())
        self.assertNotIn(canary, result.stdout + result.stderr)
        for path in workspace.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(canary.encode(), path.read_bytes(), str(path))

    def test_config_rejects_ancestor_symlinks_for_source_plugin_and_annotations(self):
        workspace = self.workspace
        real = workspace.directory / "real"
        real.mkdir()
        (real / "source").mkdir()
        (real / "acme.py").write_text("def analyze(artifact, ctx):\n    pass\n")
        (real / "annotations.json").write_text("[]")
        (workspace.directory / "alias").symlink_to(real, target_is_directory=True)
        baseline = deepcopy(workspace.config)
        variants = []
        for path in ("alias/source", "alias/../source"):
            variant = deepcopy(baseline)
            variant["sources"][0]["path"] = path
            variants.append(variant)
        variant = deepcopy(baseline)
        variant["adapters"] = {"trusted": ["example:acme"], "plugins": [{"id": "example:acme", "path": "alias/acme.py", "version": "1.0.0", "technologies": ["acme"], "priority": 100}]}
        variants.append(variant)
        variant = deepcopy(baseline)
        variant["annotations"] = "alias/annotations.json"
        variants.append(variant)
        for variant in variants:
            with self.subTest(config=variant):
                workspace.config = variant
                with self.assertRaisesRegex(ValueError, "symlink"):
                    load_config(workspace.write_config())

    def test_reviewed_annotations_cannot_live_inside_sources_or_generated_output(self):
        workspace = self.workspace
        for path in ("source/reviewed.json", "output/reviewed.json"):
            with self.subTest(annotations=path):
                workspace.config["annotations"] = path
                with self.assertRaisesRegex(ValueError, "reviewed annotations must be outside"):
                    load_config(workspace.write_config())


if __name__ == "__main__":
    unittest.main()
