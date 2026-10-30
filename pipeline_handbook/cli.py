"""Exact CLI syntax is discoverable with `python -m pipeline_handbook --help`."""
from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sys

from . import __version__

from .config import DEFAULTS, _merge, load_config
from .engine import scan
from .registry import Registry
from .security import clean_text, safe_json
from .store import diff, save


def impact(snapshot, asset, direction="downstream", kind="data_flow", environment=None, service=None):
    candidates = [n for n in snapshot["nodes"] if (n["id"] == asset or n["name"] == asset)
                  and (environment is None or n["environment"] == environment)
                  and (service is None or n["namespace"] == service)]
    if len(candidates) != 1:
        options = [{key: n[key] for key in ("id", "name", "kind", "environment", "namespace")} for n in candidates]
        return {"error": "Asset must match exactly one identity; provide --environment and --service or use a node ID.", "candidates": options}
    root = candidates[0]["id"]
    graph = {}
    for edge in snapshot["edges"]:
        if kind != "all" and edge["kind"] != kind:
            continue
        a, b = (edge["source"], edge["target"]) if direction == "downstream" else (edge["target"], edge["source"])
        graph.setdefault(a, []).append((b, edge))
    seen, queue, relationships = {root}, deque([root]), {}
    while queue:
        current = queue.popleft()
        for following, edge in graph.get(current, []):
            relationships[edge["id"]] = edge
            if following not in seen:
                seen.add(following)
                queue.append(following)
    return {"snapshot_id": snapshot["snapshot_id"], "asset": candidates[0], "direction": direction, "kind": kind,
            "affected": [node for node in snapshot["nodes"] if node["id"] in seen and node["id"] != root],
            "relationships": sorted(relationships.values(), key=lambda e: e["id"]),
            "limitation": "Only supported, visible relationships are traversed. Absence of a path does not establish absence of impact; definitions do not prove execution."}


def parser():
    root = argparse.ArgumentParser(prog="pipeline-handbook", description="Offline technology discovery and evidence-backed onboarding")
    root.add_argument("--version", action="version", version=f"pipeline-handbook {__version__}")
    subs = root.add_subparsers(dest="command", required=True)
    for name in ("discover", "analyze", "document", "status"):
        command = subs.add_parser(name)
        command.add_argument("--config", required=True, help="Reviewed JSON configuration path")
    capability = subs.add_parser("capabilities")
    capability.add_argument("--config", help="Include reviewed custom rules and components")
    capability.add_argument("--json", action="store_true")
    change = subs.add_parser("diff")
    change.add_argument("before")
    change.add_argument("after")
    traversal = subs.add_parser("impact")
    traversal.add_argument("--config", required=True)
    traversal.add_argument("--asset", required=True)
    traversal.add_argument("--direction", choices=["upstream", "downstream"], default="downstream")
    traversal.add_argument("--kind", choices=["data_flow", "control_flow", "all"], default="data_flow")
    traversal.add_argument("--environment")
    traversal.add_argument("--service")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "diff":
            print(json.dumps(diff(safe_json(Path(args.before), 100_000_000), safe_json(Path(args.after), 100_000_000)), indent=2))
            return 0
        if args.command == "capabilities":
            config = load_config(args.config) if args.config else _merge(DEFAULTS, {"_base": str(Path.cwd()), "sources": []})
            rows = Registry(config).capabilities()
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(f'{row["technology"]:18} {row["maturity"]:15} ' + ", ".join(key for key, value in row["features"].items() if value != "unsupported"))
            return 0
        config = load_config(args.config)
        output = Path(config["output"]["_root"])
        if args.command == "status":
            from .freshness import check
            from .security import redact
            result = check(config, safe_json(output / "latest.json", 100_000_000))
            print(json.dumps(redact(result), indent=2))
            return 0
        if args.command == "impact":
            snapshot = safe_json(output / "latest.json", 100_000_000)
            result = impact(snapshot, args.asset, args.direction, args.kind, args.environment, args.service)
            print(json.dumps(result, indent=2))
            return 2 if "error" in result else 0
        snapshot = scan(config, analyze=args.command != "discover")
        location = save(snapshot, output)
        generated = {}
        if args.command == "document":
            from .render import document
            generated = document(snapshot, output, config["output"]["formats"])
        print(json.dumps({"snapshot_id": snapshot["snapshot_id"], "snapshot": str(location),
                          "files": len(snapshot["artifacts"]), "detections": len(snapshot["detections"]),
                          "nodes": len(snapshot["nodes"]), "edges": len(snapshot["edges"]),
                          "coverage_findings": len(snapshot["issues"]), "metrics": snapshot["metrics"],
                          "generated": {k: str(v) for k, v in generated.items()}}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        # Do not include raw parser exception messages or host paths/SQL literals.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            print("Configuration/analysis error: " + clean_text(str(error)), file=sys.stderr)
        else:
            print(f"Pipeline Handbook could not complete this command ({type(error).__name__}). Check reviewed configuration and local access.", file=sys.stderr)
        return 2
