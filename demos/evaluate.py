#!/usr/bin/env python3
"""Measure only the manually labeled synthetic fixture scope."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(snapshot: dict, labels: dict) -> dict:
    artifacts = {artifact["id"]: artifact for artifact in snapshot["artifacts"]}
    results = []
    by_technology = {}
    for label in labels["detection_labels"]:
        matches = [item for item in snapshot["detections"]
                   if item["technology"] == label["technology"]
                   and artifacts[item["artifact_id"]]["source_id"] == label["source"]
                   and artifacts[item["artifact_id"]]["path"] == label["path"]]
        predicted = bool(matches)
        correct = predicted == label["present"]
        category_correct = not label.get("category") or label["category"] in {item["category"] for item in matches}
        results.append({**label, "detected": predicted, "presence_correct": correct, "category_correct": category_correct})
        counts = by_technology.setdefault(label["technology"], {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "labeled_pairs": 0})
        counts["labeled_pairs"] += 1
        counts[("t" if correct else "f") + ("p" if predicted else "n")] += 1
    for counts in by_technology.values():
        counts["precision"] = rate(counts["tp"], counts["tp"] + counts["fp"])
        counts["recall"] = rate(counts["tp"], counts["tp"] + counts["fn"])
        counts["accuracy"] = rate(counts["tp"] + counts["tn"], counts["labeled_pairs"])

    nodes = {node["id"]: node for node in snapshot["nodes"]}
    actual = set()
    for edge in snapshot["edges"]:
        source, target = nodes[edge["source"]], nodes[edge["target"]]
        if edge["kind"] == "data_flow" and source["kind"] == target["kind"] == "dataset":
            actual.add((source["environment"], source["namespace"], source["name"], target["name"]))
    expected = {(item["environment"], item["namespace"], item["source"], item["target"]) for item in labels["dataset_edges"]}
    return {
        "scope": labels["description"],
        "detection": {
            "labeled_pairs": len(results),
            "presence_accuracy": rate(sum(item["presence_correct"] for item in results), len(results)),
            "category_accuracy": rate(sum(item["category_correct"] for item in results), len(results)),
            "by_technology": by_technology,
            "results": results,
        },
        "dataset_graph": {
            "expected_edges": len(expected), "actual_edges": len(actual),
            "correct_edges": len(actual & expected),
            "precision": rate(len(actual & expected), len(actual)),
            "recall": rate(len(actual & expected), len(expected)),
            "unexpected": sorted(actual - expected), "missing": sorted(expected - actual),
        },
        "limitations": [
            "Synthetic offline definitions only; no vendor execution or live connector was measured.",
            "Detection accuracy covers only explicitly labeled technology/artifact pairs, including three negatives.",
            "Graph metrics cover direct dataset edges in the documented subset, not dynamic or proprietary workflows.",
            "One measured scan is descriptive; it is not a scalability or production performance guarantee.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/demo.json")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/observed-metrics.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    config_base = args.config.resolve().parent
    output = (config_base / config["output"]["directory"]).resolve()
    started = time.perf_counter()
    command = [sys.executable, "-m", "pipeline_handbook", "analyze", "--config", str(args.config.resolve())]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    elapsed = time.perf_counter() - started
    if process.returncode:
        print(process.stderr or process.stdout, file=sys.stderr)
        return process.returncode
    snapshot = json.loads((output / "latest.json").read_text())
    labels = json.loads((ROOT / "tests/expectations.json").read_text())
    report = evaluate(snapshot, labels)
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    report.update({
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot["snapshot_id"],
        "measurement": {
            "command": "python3 -m pipeline_handbook analyze --config configs/demo.json",
            "python": platform.python_version(), "platform": platform.system(),
            "elapsed_seconds_including_cli_startup": round(elapsed, 6),
            "peak_child_rss_bytes": int(rss if platform.system() == "Darwin" else rss * 1024),
            "artifact_count": len(snapshot["artifacts"]),
            "inventoried_bytes": sum(item.get("size", 0) for item in snapshot["artifacts"]),
            "core_metrics": snapshot.get("metrics", {}),
        },
    })
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "detection_presence_accuracy": report["detection"]["presence_accuracy"], "graph_precision": report["dataset_graph"]["precision"], "graph_recall": report["dataset_graph"]["recall"]}, indent=2))
    return 0 if report["detection"]["presence_accuracy"] == 1 and report["detection"]["category_accuracy"] == 1 and not report["dataset_graph"]["missing"] and not report["dataset_graph"]["unexpected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
