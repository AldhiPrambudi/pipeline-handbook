"""Inventory explicitly configured roots; never follow symlinks or execute files."""
from __future__ import annotations

from fnmatch import fnmatchcase
import os
from pathlib import Path
import stat
import time

from .security import bounded_read, digest, redact, stable_id, parse_json_text

SKIP_DIRS = {".git", ".aws", ".ssh", "node_modules", ".venv", "__pycache__"}
DATA_FORMATS = {"csv", "tsv", "parquet", "avro", "xlsx", "xls", "sqlite", "db", "zip", "gz", "png", "jpg", "pdf"}


def inventory(config, deadline):
    artifacts, issues = [], []
    budgets = config["budgets"]
    total_bytes, inspected = 0, 0

    def issue(code, message, artifact_id=None):
        issues.append(redact({"code": code, "message": message, "severity": "warning", "artifact_id": artifact_id, "evidence": []}))

    for source in config["sources"]:
        root = Path(source["_root"])
        if not root.exists() or not root.is_dir():
            issue("access_denied", f'{source["id"]}: directory missing or inaccessible; supply an authorized metadata export or correct the scope.')
            continue
        if not root.stat().st_mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH):
            issue("access_denied", f'{source["id"]}: directory has no read permission bits; coverage unknown.')
            continue

        def onerror(error):
            issue("access_denied", f'{source["id"]}: an input directory could not be listed; coverage unknown.')

        for directory, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
            if time.monotonic() >= deadline or inspected >= budgets["max_files"]:
                issue("budget_exceeded", "Inventory time/entry budget reached; remaining inputs are unknown.")
                return artifacts, issues, total_bytes
            kept = []
            for name in sorted(dirs):
                inspected += 1
                child = Path(directory) / name
                if child.is_symlink():
                    issue("symlink_skipped", f'{source["id"]}/{child.relative_to(root).as_posix()}: symlink directory excluded.')
                elif name not in SKIP_DIRS:
                    kept.append(name)
            dirs[:] = kept
            for filename in sorted(files):
                inspected += 1
                path = Path(directory) / filename
                relative = path.relative_to(root).as_posix()
                if not any(fnmatchcase(relative, pattern) for pattern in source["include"]) or any(fnmatchcase(relative, pattern) for pattern in source["exclude"]):
                    continue
                aid = stable_id("artifact", source["id"], source["environment"], relative)
                if inspected > budgets["max_files"] or time.monotonic() >= deadline:
                    issue("budget_exceeded", "Inventory time/entry budget reached; remaining inputs are unknown.")
                    return artifacts, issues, total_bytes
                base = {"id": aid, "source_id": source["id"], "environment": source["environment"],
                        "service": source["service"], "path": relative,
                        "format": path.suffix.lower().lstrip(".") or path.name.lower()}
                try:
                    if path.is_symlink():
                        raise ValueError("symlink inputs are not permitted")
                    info = path.stat()
                    base["size"] = info.st_size
                    if not info.st_mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH):
                        raise PermissionError("no read permission bits")
                    if total_bytes + info.st_size > budgets["max_total_bytes"]:
                        raise ValueError("total byte budget exceeded")
                    raw = bounded_read(path, root, budgets["max_file_bytes"])
                    total_bytes += len(raw)
                    base["hash"] = digest(raw)
                    if base["format"] in DATA_FORMATS:
                        base.update(text="", inspection="metadata-only")
                        issue("data_content_skipped", "Data/binary content was not parsed; provide a metadata/schema export for lineage.", aid)
                    else:
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            text = ""
                            issue("unsupported_file", "Non-UTF8 content inventoried; provide a supported text metadata export.", aid)
                        base.update(text=text, inspection="static-definition")
                        if base["format"] == "json" and text:
                            try:
                                parse_json_text(text)
                            except (ValueError, RecursionError):
                                base["text"] = ""
                                issue("invalid_json", "JSON with malformed, duplicated, deeply nested or nonfinite values rejected; provide an unambiguous metadata export.", aid)
                    if "<!DOCTYPE" in base["text"].upper() or "<!ENTITY" in base["text"].upper():
                        base["text"] = ""
                        issue("unsafe_xml", "DOCTYPE/entity XML rejected; supply a sanitized export without external entities.", aid)
                except (OSError, ValueError) as error:
                    base.update(hash=None, text="", inspection="unreadable")
                    code = "access_denied" if isinstance(error, OSError) else "symlink_skipped" if "symlink" in str(error) else "budget_exceeded"
                    issue(code, f'Input could not be inspected ({type(error).__name__}); missing visibility does not establish absence.', aid)
                artifacts.append(base)
    return artifacts, issues, total_bytes
