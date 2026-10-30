"""Public staging is a reviewed synthetic rebuild, not a raw scan upload."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from demos.build_public_site import (PUBLIC_ARTIFACTS, PUBLIC_FILES, PUBLIC_PROFILE, PUBLIC_SOURCES,
                                     ROOT, _checked_config, _check_fixture_bytes, _manifest,
                                     build_public_site, stage_artifacts)
from pipeline_handbook.publication import anonymize_snapshot, create_publication_manifest
from tests.test_publication import private_snapshot, CANARY


class PublicSiteTests(unittest.TestCase):
    def provenance(self):
        return {"snapshot_id": "a" * 24, "fixture_manifest_sha256": "b" * 64,
                "generated_at": "2026-10-30T00:00:00+00:00", "private_path": "never publish this"}

    def prepared(self, base):
        generated = base / "generated"
        generated.mkdir()
        for name in PUBLIC_ARTIFACTS:
            (generated / name).write_text("public synthetic content", encoding="utf-8")
        return generated

    def copied_public_root(self, base):
        root = base / "checkout"
        for item in ("configs/architecture.json", "demos/public-fixtures.json"):
            target = root / item
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / item, target)
        manifest = json.loads((ROOT / "demos/public-fixtures.json").read_text())
        for source, files in manifest["sources"].items():
            folder = PUBLIC_SOURCES[source][0]
            for relative in files:
                target = root / folder / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / folder / relative, target)
        (root / "rules").mkdir()
        return root

    def test_fixed_allowlist_ignores_database_history_and_private_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            generated = self.prepared(base)
            for relative in ("metadata.sqlite", "snapshots/private.json", ".local/private.json", "ncbs/raw.json", ".hidden"):
                path = generated / relative
                path.parent.mkdir(exist_ok=True)
                path.write_text("PRIVATE_FAKE_CASE_CANARY")
            output = base / "public"
            record = stage_artifacts(generated, output, self.provenance())
            self.assertEqual({p.name for p in output.iterdir()}, PUBLIC_FILES)
            self.assertEqual(set(record["files"]), set(PUBLIC_ARTIFACTS))
            self.assertNotIn("private_path", record)
            self.assertNotIn("PRIVATE_FAKE_CASE_CANARY", "".join(p.read_text() for p in output.iterdir()))

    def test_nonempty_output_is_refused_without_overwriting_private_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            generated = self.prepared(base)
            output = base / "public"
            output.mkdir()
            private = output / "private.sqlite"
            private.write_text("unchanged")
            with self.assertRaises(ValueError):
                stage_artifacts(generated, output, self.provenance())
            self.assertEqual(private.read_text(), "unchanged")
            self.assertEqual([p.name for p in output.iterdir()], ["private.sqlite"])

    def test_symlink_and_hardlink_artifacts_are_refused(self):
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(link_kind=link_kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                generated = self.prepared(base)
                private = base / "not-approved.html"
                private.write_text("PRIVATE_FAKE_CASE_CANARY")
                (generated / "index.html").unlink()
                if link_kind == "symlink":
                    (generated / "index.html").symlink_to(private)
                else:
                    os.link(private, generated / "index.html")
                with self.assertRaises((OSError, ValueError)):
                    stage_artifacts(generated, base / "public", self.provenance())
                self.assertFalse((base / "public").exists())

    def test_config_cannot_redirect_public_build_to_private_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_public_root(Path(temporary).resolve())
            path = root / "configs/architecture.json"
            config = json.loads(path.read_text())
            config["sources"][0]["path"] = "../.local/private"
            raw = json.dumps(config).encode()
            path.write_bytes(raw)
            manifest, _ = _manifest(root)
            # Even changing the reviewed config digest does not change the
            # hard-coded public source-root/identity allowlist.
            manifest["config_sha256"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                _checked_config(root, manifest)

    def test_fixture_byte_changes_require_explicit_public_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_public_root(Path(temporary).resolve())
            manifest, _ = _manifest(root)
            path = root / "fixtures/legacy/dev/publish.sql"
            path.write_text(path.read_text() + "\n-- unreviewed content\n")
            with self.assertRaises(ValueError):
                _check_fixture_bytes(root, manifest)

    def test_manifest_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copied_public_root(Path(temporary).resolve())
            manifest_path = root / "demos/public-fixtures.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["sources"]["legacy_dev"] = {"../private.sql": "a" * 64}
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                _manifest(root)

    def test_fresh_build_ignores_unreviewed_files_and_stages_no_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = self.copied_public_root(base)
            unreviewed = root / "fixtures/legacy/dev/unreviewed-private.json"
            unreviewed.write_text('{"private":"PRIVATE_FAKE_CASE_CANARY"}')
            output = base / "public"
            record = build_public_site(output, root=root, include_ncbs=False)
            self.assertEqual({p.name for p in output.iterdir()}, PUBLIC_FILES)
            snapshot = json.loads((output / "handbook.json").read_text())
            self.assertEqual(snapshot["project"], PUBLIC_PROFILE)
            self.assertEqual(len(snapshot["artifacts"]), 34)
            self.assertFalse(snapshot["annotations"])
            self.assertNotIn("unreviewed-private.json", (output / "handbook.json").read_text())
            self.assertNotIn("PRIVATE_FAKE_CASE_CANARY", "".join(p.read_text() for p in output.iterdir()))
            self.assertEqual(record["snapshot_id"], snapshot["snapshot_id"])

    def test_ncbs_case_uses_only_validated_alias_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();root=self.copied_public_root(base)
            public,_=anonymize_snapshot(private_snapshot())
            bundle=root/'publication/ncbs';bundle.mkdir(parents=True)
            path=bundle/'snapshot.json';path.write_text(json.dumps(public,indent=2)+'\n')
            (bundle/'manifest.json').write_text(json.dumps(create_publication_manifest(path)))
            (bundle/'raw-private.sqlite').write_text(CANARY)
            output=base/'site'
            record=build_public_site(output,root=root)
            self.assertEqual({p.name for p in output.iterdir()},PUBLIC_FILES|{'ncbs'})
            self.assertEqual({p.name for p in (output/'ncbs').iterdir()},PUBLIC_FILES)
            self.assertIn('ncbs',record['case_studies'])
            self.assertIn('ncbs/index.html',(output/'index.html').read_text())
            self.assertIn('Anonymized NCBS',(output/'ncbs/index.html').read_text())
            for p in output.rglob('*'):
                if p.is_file():self.assertNotIn(CANARY,p.read_text())

    def test_missing_or_raw_ncbs_bundle_prevents_any_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();root=self.copied_public_root(base)
            output=base/'site'
            with self.assertRaises((ValueError,OSError)):
                build_public_site(output,root=root)
            self.assertFalse(output.exists())
            bundle=root/'publication/ncbs';bundle.mkdir(parents=True)
            (bundle/'snapshot.json').write_text(json.dumps(private_snapshot()))
            (bundle/'manifest.json').write_text('{}')
            with self.assertRaises(ValueError):build_public_site(output,root=root)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
