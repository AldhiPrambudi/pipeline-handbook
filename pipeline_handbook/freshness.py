"""Recheck definition hashes without reusing extraction results or running code."""
import time

from .config import public_config
from .inventory import inventory
from .registry import Registry


def check(config, snapshot):
    registry = Registry(config)
    artifacts, issues, _ = inventory(config, time.monotonic() + config["budgets"]["scan_timeout_seconds"])
    old = {item["id"]: item for item in snapshot["artifacts"]}
    new = {item["id"]: item for item in artifacts}
    added = [new[key]["source_id"] + "/" + new[key]["path"] for key in sorted(new.keys() - old.keys())]
    removed = [old[key]["source_id"] + "/" + old[key]["path"] for key in sorted(old.keys() - new.keys())]
    changed = [new[key]["source_id"] + "/" + new[key]["path"] for key in sorted(new.keys() & old.keys()) if new[key]["hash"] != old[key]["hash"]]
    registry_changed = registry.fingerprint != snapshot["registry_fingerprint"]
    configuration_changed = public_config(config) != snapshot["effective_config"]
    annotation_changed = False
    if config.get("annotations"):
        from pathlib import Path
        from .security import redact, safe_json
        annotation_changed = redact(safe_json(Path(config["_base"]) / config["annotations"])) != snapshot["annotations"]
    incomplete = any(item["code"] in {"access_denied", "budget_exceeded", "symlink_skipped"} for item in issues)
    stale = bool(added or removed or changed or registry_changed or configuration_changed or annotation_changed)
    return {"snapshot_id": snapshot["snapshot_id"], "state": "stale" if stale else "unknown" if incomplete else "current",
            "stale": stale if stale or not incomplete else None, "added": added, "removed": removed,
            "changed": changed, "registry_changed": registry_changed, "configuration_changed": configuration_changed,
            "annotations_changed": annotation_changed, "coverage_complete": not incomplete,
            "findings": issues, "note": "Freshness compares only local definition hashes/configuration/rules/components/annotations. It does not observe runs or revalidate runtime state."}
