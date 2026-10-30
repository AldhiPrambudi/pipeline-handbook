#!/usr/bin/env python3
"""Measure architecture recovery only against independent synthetic labels."""

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


def rate(correct, total):
    return round(correct / total, 4) if total else None


def compare(actual, expected):
    return {
        "expected": len(expected), "actual": len(actual), "correct": len(actual & expected),
        "precision": rate(len(actual & expected), len(actual)),
        "recall": rate(len(actual & expected), len(expected)),
        "unexpected": sorted(actual - expected), "missing": sorted(expected - actual),
    }


def evaluate(snapshot, labels):
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    evidence = {item["id"]: item for item in snapshot["evidence"]}
    explicit = {(node["environment"], node["namespace"], node["kind"], node["name"])
                for node in nodes.values() if node["namespace"] in {"arch_dev", "arch_prod"}
                and node["kind"] in {"component", "deployment_resource", "report"}}
    expected_assets = {(item["environment"], item["namespace"], item["kind"], item["name"]) for item in labels["explicit_assets"]}
    connection, placement, startup, invocation = set(), set(), set(), set()
    for edge in snapshot["edges"]:
        source, target = nodes[edge["source"]], nodes[edge["target"]]
        triple = source["environment"], source["name"], target["name"]
        if edge["kind"] == "connection":
            connection.add(triple)
        if edge["kind"] == "deployment" and target["name"] in {"host.dev.local", "host.prod.local"}:
            placement.add(triple)
        if edge["kind"] == "deployment" and edge["attributes"].get("relation") == "startup_dependency":
            startup.add((*triple, edge["attributes"].get("condition")))
        if edge["kind"] == "invocation" and source["name"].startswith("dag.py::warehouse_orders::"):
            invocation.add((source["environment"], source["namespace"], source["name"], target["name"]))
    graph = {
        "explicit_components_resources_consumers": compare(explicit, expected_assets),
        "explicit_connections": compare(connection, {(item["environment"], item["source"], item["target"]) for item in labels["explicit_connections"]}),
        "declared_host_placements": compare(placement, {(item["environment"], item["source"], item["target"]) for item in labels["host_placements"]}),
        "startup_declarations": compare(startup, {(item["environment"], item["source"], item["target"], item["condition"]) for item in labels["startup_dependencies"]}),
        "exact_task_model_bindings": compare(invocation, {(item["environment"], item["namespace"], item["source"], item["target"]) for item in labels["exact_invocations"]}),
    }
    answers = []
    for label in labels["report_walkthroughs"]:
        outputs = [node for node in nodes.values() if node["kind"] == "report" and node["environment"] == label["environment"] and node["namespace"] == label["namespace"] and node["name"] == label["report"]]
        matches = [walk for walk in snapshot["architecture"]["walkthroughs"] if outputs and walk["output_id"] == outputs[0]["id"]]
        checks = {"unique_output_walkthrough": len(outputs) == len(matches) == 1}
        if matches:
            walk = matches[0]
            upstream = [nodes[nid] for nid in walk["upstream_dataset_ids"]]
            checks.update({
                "dataset_ancestry": {node["name"] for node in upstream} == set(label["upstream_datasets"]),
                "environment_service_identity": all(node["environment"] == label["environment"] and node["namespace"] == label["dataset_namespace"] for node in upstream),
                "producing_definitions": set(label["producer_names"]) <= {nodes[nid]["name"] for nid in walk["producer_ids"]},
                "dependency_order_is_not_execution_sequence": walk.get("data_ancestry_order") == "dependency presentation; not execution sequence",
                "evidence_locations": set(label["evidence_paths"]) <= {evidence[eid]["location"].split(":L")[0] for eid in walk["evidence"]},
            })
            if label.get("schedule_expression"):
                checks["schedule_definition"] = label["schedule_expression"] in json.dumps(walk["schedules"])
            if label.get("control_condition"):
                checks["control_condition"] = label["control_condition"] in json.dumps(walk["control_steps"])
        answers.append({"report": label["report"], "environment": label["environment"], "checks": checks, "passed": all(checks.values())})
    codes = {issue["code"] for issue in snapshot["issues"]}
    negative_checks = {
        "required_conflict_and_unresolved_findings": set(labels["required_gap_codes"]) <= codes,
        "missing_unsupported_and_malformed_assets_not_manufactured": not any(node["name"] in labels["rejected_asset_names"] for node in nodes.values()),
        "no_cross_environment_edges": not any(nodes[edge["source"]]["environment"] != nodes[edge["target"]]["environment"] for edge in snapshot["edges"]),
        "no_static_definition_promoted_to_observed_run": not any(node["kind"] == "run" or node["status"] == "observed" for node in nodes.values()),
        "no_unsupported_target_architecture_recommendations": not snapshot["architecture"]["recommendations"],
    }
    passed = all(not result["unexpected"] and not result["missing"] for result in graph.values()) and all(item["passed"] for item in answers) and all(negative_checks.values())
    return {
        "scope": labels["description"], "passed": passed, "graph_metrics": graph,
        "new_joiner_walkthroughs": {"tested": len(answers), "passed": sum(item["passed"] for item in answers), "results": answers},
        "negative_evidence_checks": negative_checks,
        "limitations": [
            "Synthetic offline declarations only; placement and connection edges do not prove deployment or successful communication.",
            "Metrics cover only the manually labeled architecture subset and report/form questions in tests/architecture_expectations.json.",
            "Runtime-generated graphs, proprietary application/report parsers and live metadata APIs were not measured.",
            "A declared inspection point is a location to review, not authorization to access or execute it.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/architecture.json")
    parser.add_argument("--snapshot", type=Path, help="Evaluate an existing snapshot without regenerating output")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/architecture-observed-metrics.json")
    args = parser.parse_args()
    measurement = {}
    if args.snapshot:
        snapshot_path = args.snapshot
        measurement["mode"] = "existing snapshot; no scan timing measured"
    else:
        config = json.loads(args.config.read_text())
        output = (args.config.resolve().parent / config["output"]["directory"]).resolve()
        start = time.perf_counter()
        process = subprocess.run([sys.executable, "-m", "pipeline_handbook", "document", "--config", str(args.config.resolve())], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if process.returncode:
            print(process.stderr or process.stdout, file=sys.stderr)
            return process.returncode
        elapsed = time.perf_counter() - start
        rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        measurement.update({"mode": "one CLI document scan including startup and rendering", "elapsed_seconds": round(elapsed, 6), "peak_child_rss_bytes": int(rss if platform.system() == "Darwin" else rss * 1024), "python": platform.python_version(), "platform": platform.system()})
        snapshot_path = output / "latest.json"
    snapshot = json.loads(snapshot_path.read_text())
    labels = json.loads((ROOT / "tests/architecture_expectations.json").read_text())
    report = evaluate(snapshot, labels)
    report.update({"measured_at": datetime.now(timezone.utc).isoformat(), "snapshot_id": snapshot["snapshot_id"], "measurement": {**measurement, "artifact_count": len(snapshot["artifacts"]), "inventoried_bytes": sum(item.get("size", 0) for item in snapshot["artifacts"]), "core_metrics": snapshot.get("metrics", {})}})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.report), "passed": report["passed"], "graph_metrics": report["graph_metrics"], "new_joiner_walkthroughs": report["new_joiner_walkthroughs"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
