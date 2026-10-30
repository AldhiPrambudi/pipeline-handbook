#!/usr/bin/env python3
"""Rebuild and stage only the reviewed synthetic handbook for public hosting.

This is deliberately not a generic 'publish any scan' command. It has no input
configuration/source option, accepts only the bundled architecture profile, and
checks reviewed fixture byte hashes before and after analysis. Private scans,
SQLite stores and snapshot history never enter the staged directory.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_handbook import __version__
from pipeline_handbook.config import load_config
from pipeline_handbook.engine import scan
from pipeline_handbook.render import document
from pipeline_handbook.publication import verify_publication_bundle


PUBLIC_ARTIFACTS = ("index.html", "handbook.md", "handbook.json")
PUBLIC_FILES = frozenset((*PUBLIC_ARTIFACTS, "publication.json"))
PUBLIC_PROFILE = "pipeline_handbook_architecture_recovery"
PUBLIC_SOURCES = {
    "legacy_dev": ("fixtures/legacy/dev", "dev", "legacy_orders"),
    "legacy_prod": ("fixtures/legacy/prod", "prod", "legacy_orders"),
    "modern_dev": ("fixtures/modern/dev", "dev", "analytics_warehouse"),
    "adversarial": ("fixtures/adversarial", "test", "untrusted_fixture"),
    "arch_dev": ("fixtures/architecture/dev", "dev", "architecture_dev"),
    "arch_prod": ("fixtures/architecture/prod", "prod", "architecture_prod"),
}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _regular_bytes(path, limit=20_000_000):
    """Read one regular, unlinked file; never dereference a publication link."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise ValueError("Publication inputs must not be symlinks")
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("Publication inputs must be bounded regular files without hard links")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(limit + 1)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("Publication input changed during its bounded read")
        return data
    finally:
        os.close(fd)


def _no_symlink_ancestors(path):
    for part in (Path(path), *Path(path).parents):
        if part.is_symlink():
            raise ValueError("Publication paths must not contain symlink components")


def _manifest(root):
    data = _regular_bytes(root / "demos/public-fixtures.json", 1_000_000)
    value = json.loads(data)
    if not isinstance(value, dict) or set(value) != {"schema_version", "profile", "config_sha256", "sources"} or value.get("schema_version") != "1" or value.get("profile") != PUBLIC_PROFILE:
        raise ValueError("A reviewed synthetic fixture manifest is required")
    if not isinstance(value["sources"], dict) or set(value["sources"]) != set(PUBLIC_SOURCES):
        raise ValueError("The public manifest must contain exactly the bundled synthetic source scopes")
    for source, files in value["sources"].items():
        if not isinstance(files, dict) or not files:
            raise ValueError("Every public fixture scope must list reviewed files")
        for name, digest in files.items():
            path = Path(name)
            if not isinstance(name, str) or path.is_absolute() or any(p in {"", ".", ".."} or p.startswith(".") for p in path.parts) or not path.parts or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Public fixture records require a safe relative path and SHA-256")
    return value, _hash(data)


def _checked_config(root, manifest):
    config_file = root / "configs/architecture.json"
    _no_symlink_ancestors(config_file)
    if _hash(_regular_bytes(config_file, 100_000)) != manifest["config_sha256"]:
        raise ValueError("Public architecture configuration differs from the reviewed profile")
    config = load_config(config_file)
    if config["project"] != PUBLIC_PROFILE or set(s["id"] for s in config["sources"]) != set(PUBLIC_SOURCES):
        raise ValueError("Only the fixed synthetic architecture profile can be published")
    if config.get("annotations") or config["adapters"]["plugins"] or config["adapters"]["trusted"] != ["builtin:*"]:
        raise ValueError("Public builds cannot use annotation files or external executable components")
    for source in config["sources"]:
        relative, environment, service = PUBLIC_SOURCES[source["id"]]
        expected = root / relative
        _no_symlink_ancestors(expected)
        if Path(source["_root"]).resolve() != expected.resolve() or source["environment"] != environment or source["service"] != service:
            raise ValueError("Public source identity/path differs from the fixed synthetic scope")
        # Do not let newly added/unreviewed files enter a public scan.
        source["include"] = sorted(manifest["sources"][source["id"]])
    allowed_rules = (root / "rules").resolve()
    if any((Path(config["_base"]) / directory).resolve() != allowed_rules for directory in config["rules"]["directories"]):
        raise ValueError("Public builds may use only bundled reviewed rules")
    return config


def _check_fixture_bytes(root, manifest):
    expected = {}
    for source, files in manifest["sources"].items():
        folder = root / PUBLIC_SOURCES[source][0]
        for relative, digest in files.items():
            target = folder / relative
            _no_symlink_ancestors(target)
            if _hash(_regular_bytes(target, 1_000_000)) != digest:
                raise ValueError("Synthetic fixture bytes differ from the reviewed public manifest")
            expected[(source, relative)] = digest
    return expected


def _check_snapshot(snapshot, expected):
    if snapshot.get("project") != PUBLIC_PROFILE:
        raise ValueError("The generated snapshot is not the public synthetic profile")
    actual = {(a["source_id"], a["path"]): a.get("hash") for a in snapshot.get("artifacts", [])}
    if actual != expected:
        raise ValueError("Scanned artifacts do not match the reviewed synthetic fixture manifest")
    if snapshot.get("annotations"):
        raise ValueError("Reviewed private annotations cannot enter the public site")


def stage_artifacts(generated, destination, provenance):
    """Copy a fixed allowlist from an internal fresh build, with no recursion."""
    generated, destination = Path(generated), Path(destination)
    if not isinstance(provenance, dict) or not re.fullmatch(r"[0-9a-f]{24}", str(provenance.get("snapshot_id", ""))) or not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("fixture_manifest_sha256", ""))):
        raise ValueError("Publication provenance requires opaque snapshot/manifest digests")
    try:
        datetime.fromisoformat(provenance["generated_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError("Publication provenance requires an ISO collection timestamp") from None
    _no_symlink_ancestors(generated)
    _no_symlink_ancestors(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Public staging requires a new or empty directory")
    payloads = {name: _regular_bytes(generated / name) for name in PUBLIC_ARTIFACTS}
    hashes = {name: _hash(data) for name, data in sorted(payloads.items())}
    # Select provenance fields explicitly; caller dictionaries cannot smuggle
    # private paths or arbitrary scan metadata into the publication record.
    record = {"schema_version": "1", "project_version": __version__, "profile": PUBLIC_PROFILE,
              "input_classification": "reviewed bundled synthetic definitions only",
              "snapshot_id": provenance["snapshot_id"], "fixture_manifest_sha256": provenance["fixture_manifest_sha256"],
              "generated_at": provenance["generated_at"], "files": hashes,
              "excluded": ["private scans/configuration", "SQLite databases", "snapshot history", "raw source files"]}
    payloads["publication.json"] = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        # Exclusive create plus no reuse prevents stale extra/private files from
        # surviving a prior staging attempt.
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    if {p.name for p in destination.iterdir()} != PUBLIC_FILES:
        raise ValueError("Unexpected files appeared in the public staging directory")
    return record


def _ncbs_bundle(root):
    folder = root / "publication/ncbs"
    for name in ("snapshot.json", "manifest.json"):
        _no_symlink_ancestors(folder / name)
        _regular_bytes(folder / name)
    return verify_publication_bundle(folder / "snapshot.json", folder / "manifest.json")


def _stage_ncbs(snapshot, destination):
    """Render a validated alias-only graph, never an arbitrary local scan."""
    with tempfile.TemporaryDirectory(prefix="handbook-ncbs-public-", dir=Path(tempfile.gettempdir()).resolve()) as name:
        generated = Path(name)
        document(snapshot, generated, ["html", "markdown", "json"])
        notice = '<p class="notice"><strong>Anonymized NCBS compatibility test.</strong> Private identifiers and source locations are replaced by aliases. No NCBS code, environment files, business rows or private annotations are published. Original hashes attest the local evidence; the reverse mapping remains private. This is static analysis, not runtime verification. <a href="../index.html">Back to the synthetic demo</a>.</p>'
        index = generated / "index.html"
        index.write_text(index.read_text().replace("<main>", "<main>" + notice, 1))
        payloads = {file: _regular_bytes(generated / file) for file in PUBLIC_ARTIFACTS}
        record = {"schema_version": "1", "profile": "ncbs-anonymized/v1", "policy": "strict-alias-projection/v1",
                  "snapshot_id": snapshot["snapshot_id"], "source_code_included": False, "business_rows_included": False,
                  "files": {file: _hash(data) for file, data in payloads.items()}}
        payloads["publication.json"] = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
        destination.mkdir(exist_ok=False)
        for file, data in payloads.items():
            with (destination / file).open("xb") as handle:
                handle.write(data)
        return record


def build_public_site(destination, root=ROOT, include_ncbs=True):
    """Build fixed reviewed synthetic and deidentified case-study inputs only."""
    root = Path(root)
    _no_symlink_ancestors(root)
    manifest, manifest_hash = _manifest(root)
    config = _checked_config(root, manifest)
    expected = _check_fixture_bytes(root, manifest)
    ncbs = _ncbs_bundle(root) if include_ncbs else None
    destination = Path(destination).absolute()
    for relative, _, _ in PUBLIC_SOURCES.values():
        source_root = (root / relative).resolve()
        if destination.resolve() == source_root or source_root in destination.resolve().parents or destination.resolve() in source_root.parents:
            raise ValueError("Public output must not overlap the synthetic input scopes")
    with tempfile.TemporaryDirectory(prefix="pipeline-handbook-public-", dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        generated = Path(temporary) / "generated"
        config["output"]["_root"] = str(generated)
        snapshot = scan(config, analyze=True)
        _check_fixture_bytes(root, manifest)
        _check_snapshot(snapshot, expected)
        document(snapshot, generated, ["html", "markdown", "json"])
        record = stage_artifacts(generated, destination, {"snapshot_id": snapshot["snapshot_id"],
            "fixture_manifest_sha256": manifest_hash, "generated_at": datetime.now(timezone.utc).isoformat()})
        if ncbs is not None:
            destination = Path(destination)
            case = _stage_ncbs(ncbs, destination / "ncbs")
            index = destination / "index.html"
            link = '<p class="notice"><a href="ncbs/index.html">Open the anonymized NCBS compatibility report</a> — a source-only test on a separate private project. Private names and locations are replaced by aliases; no target code or data is published.</p>'
            index.write_text(index.read_text().replace("<main>", "<main>" + link, 1))
            record["files"]["index.html"] = _hash(index.read_bytes())
            record["case_studies"] = {"ncbs": case}
            (destination / "publication.json").write_text(json.dumps(record,indent=2,sort_keys=True)+"\n")
            if {p.name for p in destination.iterdir()} != PUBLIC_FILES | {"ncbs"}:
                raise ValueError("Unexpected public site inputs")
        return record


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build reviewed synthetic and strictly anonymized NCBS handbooks into a public allowlist")
    parser.add_argument("--output", default="public_site", help="New or empty public staging directory (default: public_site)")
    args = parser.parse_args(argv)
    try:
        record = build_public_site(args.output)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, "Public build refused. Check the reviewed synthetic fixture manifest and choose a new/empty output directory.\n")
    print(json.dumps({"profile": record["profile"], "snapshot_id": record["snapshot_id"], "staged_files": sorted(PUBLIC_FILES), "case_studies": sorted(record.get("case_studies", {}))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
