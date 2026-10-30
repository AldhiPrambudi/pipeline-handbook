"""Sanitized immutable JSON snapshots with a small SQLite metadata index."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .security import redact


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".handbook-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(redact(value), handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(snapshot, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if snapshot["phase"] == "discovery":
        atomic_json(output / "discovery.json", snapshot)
        return output / "discovery.json"
    directory = output / "snapshots"
    if directory.is_symlink():
        raise ValueError("snapshot output directory must not be a symlink")
    immutable = directory / (snapshot["snapshot_id"] + ".json")
    if immutable.is_symlink():
        raise ValueError("snapshot file must not be a symlink")
    if not immutable.exists():
        atomic_json(immutable, snapshot)
    atomic_json(output / "latest.json", snapshot)
    database = output / "metadata.sqlite"
    if database.is_symlink():
        raise ValueError("metadata database must not be a symlink")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, collected_at TEXT NOT NULL, project TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?)", (snapshot["snapshot_id"], snapshot["collected_at"], snapshot["project"], json.dumps(redact(snapshot), sort_keys=True)))
    return output / "latest.json"


def diff(before, after):
    result = {"before": before["snapshot_id"], "after": after["snapshot_id"], "changed": before["snapshot_id"] != after["snapshot_id"],
              "registry_changed": before["registry_fingerprint"] != after["registry_fingerprint"],
              "configuration_changed": before["effective_config"] != after["effective_config"], "collections": {}}
    for key in ("artifacts", "nodes", "edges", "evidence"):
        left = {item["id"]: {k: v for k, v in item.items() if k != "collected_at"} for item in before[key]}
        right = {item["id"]: {k: v for k, v in item.items() if k != "collected_at"} for item in after[key]}
        result["collections"][key] = {"added": [right[k] for k in sorted(right.keys() - left.keys())],
                                       "removed": [left[k] for k in sorted(left.keys() - right.keys())],
                                       "modified": [{"id": k, "before": left[k], "after": right[k]} for k in sorted(left.keys() & right.keys()) if left[k] != right[k]]}
    result["findings_changed"] = before["issues"] != after["issues"]
    result["annotations_changed"] = before["annotations"] != after["annotations"]
    return redact(result)
