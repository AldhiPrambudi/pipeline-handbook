"""Inventory → detect → select trusted adapters → canonical evidence graph."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import posixpath
import time

from .config import public_config
from .detection import detect
from .inventory import inventory
from .model import Context, validate_result
from .registry import Registry, matches
from .security import digest, redact, safe_json, stable_id
from .workers import run_adapter


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items()
                if key not in {"collected_at", "metrics", "snapshot_id"}}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def scan(config, analyze=True):
    start = time.monotonic()
    deadline = start + config["budgets"]["scan_timeout_seconds"]
    collected = datetime.now(timezone.utc).isoformat(timespec="seconds")
    registry = Registry(config)
    entries = {item["id"]: item for item in registry.entries}
    artifacts, issues, total_bytes = inventory(config, deadline)
    nodes, edges, evidences, detections, references, links = {}, {}, {}, [], [], []
    adapter_runs, adapter_failures = 0, 0

    def issue(code, message, artifact=None, evidence=None, severity="warning"):
        issues.append(redact({"code": code, "message": message, "severity": severity,
                              "artifact_id": artifact["id"] if artifact else None, "evidence": evidence or []}))

    def merge(result):
        for ev in result["evidence"]:
            evidences[ev["id"]] = ev
        for kind, target in (("nodes", nodes), ("edges", edges)):
            for item in result[kind]:
                if item["id"] not in target:
                    target[item["id"]] = item
                    continue
                prior = target[item["id"]]
                prior["evidence"] = sorted(set(prior["evidence"] + item["evidence"]))
                if kind == "nodes":
                    prior["rule_concepts"] = sorted(set(prior.get("rule_concepts", []) + item.get("rule_concepts", [])))
                for key, value in item.get("attributes", {}).items():
                    if key == "columns":
                        prior["attributes"][key] = sorted(set(prior["attributes"].get(key, []) + value))
                    elif key in prior["attributes"] and prior["attributes"][key] != value:
                        # Preserve both declarations, never let adapter order pick a fact.
                        prior.setdefault("conflicts", []).append({"field": key, "values": [prior["attributes"][key], value], "evidence": item["evidence"]})
                        issue("adapter_conflict", f'Adapters disagree on {key} for {prior.get("name", item["id"])}; both evidence sets are retained.', evidence=prior["evidence"])
                    else:
                        prior["attributes"][key] = value
                if "technology" in item and item["technology"] != prior.get("technology"):
                    prior["technologies"] = sorted(set(prior.get("technologies", [prior["technology"]]) + [item["technology"]]))
        issues.extend(result["issues"])
        references.extend(result["references"])
        links.extend(result.get("links", []))

    for artifact in artifacts:
        if time.monotonic() >= deadline:
            issue("budget_exceeded", "Scan deadline reached; subsequent definitions were not analyzed.", artifact)
            break
        try:
            findings = detect(artifact, registry.entries, deadline) if artifact["text"] else []
        except TimeoutError:
            issue("budget_exceeded", "Detection deadline reached; remaining candidates are unknown.", artifact)
            break
        # Explicit dialect/technology selection can analyze an otherwise ambiguous
        # SQL input. This is configured applicability, never a detected fact.
        if config["discovery"]["mode"] in {"manual", "hybrid"}:
            for tech, override in config["technologies"]["overrides"].items():
                if tech == "postgresql" and override.get("dialect") and artifact["format"] == "sql" and not any(f["technology"] == tech for f in findings):
                    rule = next((e for e in registry.entries if e["technology"] == tech), None)
                    if rule:
                        findings.append({"technology": tech, "family": rule["family"], "artifact_id": artifact["id"], "source_id": artifact["source_id"], "environment": artifact["environment"], "service": artifact["service"], "category": "ambiguous", "confidence": "low", "versions": [], "version_kinds": [], "reasons": ["Explicit configured dialect assumption; source dialect unverified"], "line": 1, "rule_id": rule["id"], "rule_version": rule["version"], "conflicts": [], "support": rule["maturity"], "selected": False})
        if not findings:
            issue("unknown_artifact", "No supported structural signature. Provide format/schema metadata, an export, a reviewed detector/adapter, or human clarification.", artifact)
        seen_adapters = set()
        for finding in findings:
            rule = entries[finding["rule_id"]]
            ctx = Context(artifact, finding["technology"], config, {"id": "builtin:detector", "version": "1.0.0"}, rule, collected)
            status = "unknown" if finding["category"] == "ambiguous" else "declared"
            finding["evidence"] = [ctx.evidence(finding.pop("line"), "; ".join(finding["reasons"]), status)]
            evidences.update(ctx.evidences)
            selected = matches(finding["technology"], config["technologies"]["include"]) and not matches(finding["technology"], config["technologies"]["exclude"])
            finding["selected"] = selected and finding["category"] != "mentioned"
            override = config["technologies"]["overrides"].get(finding["technology"], {})
            if override:
                finding["overrides"] = {"values": override, "status": "inferred", "origin": "effective_config"}
            if config["discovery"]["mode"] == "manual" and not selected and finding["category"] != "mentioned":
                issue("manual_conflict", f'{finding["technology"]} was detected outside manual technology selection; evidence remains visible.', artifact, finding["evidence"])
            eligible = registry.select(finding["technology"], rule) if finding["selected"] else []
            finding["eligible_adapters"] = [a["id"] for a in eligible]
            finding["analysis_status"] = "not_requested" if not analyze else "detection_only"
            detections.append(finding)
            if not analyze or not finding["selected"]:
                continue
            for adapter in eligible:
                # Applicability narrows formats only after structural detection.
                formats = {"builtin:sql": {"sql"}, "builtin:airflow": {"py"}, "builtin:dbt": {"json"}, "builtin:pentaho": {"xml", "ktr", "kjb"}, "builtin:compose": {"json"}, "builtin:environment_map": {"json"}}
                if adapter["id"] in formats and artifact["format"] not in formats[adapter["id"]]:
                    continue
                if adapter["id"] in seen_adapters:
                    continue
                seen_adapters.add(adapter["id"])
                adapter_runs += 1
                result = run_adapter(artifact, finding["technology"], config, adapter, rule, collected, deadline)
                if result["ok"]:
                    try:
                        # Validate the whole graph before mutating shared state.
                        # Trusted code can still have bugs or bypass SDK helpers.
                        validate_result(result["result"], config, artifact, nodes, evidences)
                        source = next(source for source in config["sources"] if source["id"] == artifact["source_id"])
                        _filter_adapter_resources(result["result"], source, nodes, artifact, issue)
                    except (ValueError, TypeError, KeyError, RecursionError):
                        result = {"ok": False, "error": "InvalidAdapterResult"}
                    else:
                        merge(result["result"])
                        finding["analysis_status"] = "analyzed_subset"
                if not result["ok"]:
                    adapter_failures += 1
                    issue("adapter_failed", f'{adapter["id"]} failed or exceeded its resource budget ({result["error"]}); other analysis is retained.', artifact, finding["evidence"])
                    finding["analysis_status"] = "failed"

    # Every inventoried artifact and inventory failure receives hash-aware provenance.
    by_artifact = {a["id"]: a for a in artifacts}
    for item in issues:
        if item.get("artifact_id") in by_artifact and not item.get("evidence"):
            artifact = by_artifact[item["artifact_id"]]
            ctx = Context(artifact, "unknown", config, {"id": "builtin:inventory", "version": "1.0.0"}, {"id": "inventory", "version": "1.0.0"}, collected)
            item["evidence"] = [ctx.evidence(reason=item["code"], status="unknown")]
            evidences.update(ctx.evidences)
    for source in config["sources"]:
        # Source systems are configured inventory scopes, not observed services.
        artifact = {"id": stable_id("source", source["id"]), "source_id": source["id"], "path": "[configured-scope]", "hash": digest(public_config(config)["sources"]), "environment": source["environment"], "service": source["service"]}
        ctx = Context(artifact, "unknown", config, {"id": "builtin:inventory", "version": "1.0.0"}, {"id": "inventory", "version": "1.0.0"}, collected)
        ctx.node("source_system", source["service"], {"scope_id": source["id"], "kind": "authorized_local_directory", "runtime_observation": False})
        merge(ctx.result())

    groups = defaultdict(list)
    if config["discovery"]["mode"] in {"manual", "hybrid"}:
        known = {entry["technology"] for entry in registry.entries}
        detected = {finding["technology"] for finding in detections if finding["category"] != "mentioned"}
        for selected in config["technologies"]["include"]:
            if "*" not in selected and "?" not in selected and selected not in detected:
                message = "Configured technology has no matching structural evidence in this scan; deployment and absence remain unverified."
                if selected not in known:
                    message = "Configured technology has no registered detector/adapter. Add a reviewed extension; support is unknown."
                issue("configured_technology_unseen", selected + ": " + message)
    for finding in detections:
        if finding["category"] != "mentioned" and "server" in finding["version_kinds"]:
            groups[(finding["environment"], finding["service"], finding["technology"])].append(finding)
        version = config["technologies"]["overrides"].get(finding["technology"], {}).get("version")
        if version and finding["versions"] and version not in finding["versions"]:
            finding["conflicts"].append("Configured version differs from source declarations; neither establishes observed runtime version.")
            issue("override_conflict", finding["conflicts"][-1], by_artifact[finding["artifact_id"]], finding["evidence"])
    for group in groups.values():
        versions = sorted({version for f in group for version in f["versions"]})
        if len(versions) > 1:
            message = "Conflicting server/deployment versions in this environment/service: " + ", ".join(versions) + ". Resolve deployment vs export age; runtime version is unknown."
            for finding in group:
                finding["conflicts"].append(message)
            issue("version_conflict", message, by_artifact[group[0]["artifact_id"]], sorted({eid for f in group for eid in f["evidence"]}))

    _resolve_references(references, nodes, edges, evidences, by_artifact, issue)
    _resolve_links(links, nodes, edges, evidences, by_artifact, issue)
    # Invalid plugin edges do not corrupt the remaining graph.
    for eid, edge in list(edges.items()):
        if edge["source"] not in nodes or edge["target"] not in nodes:
            issue("invalid_relationship", "An adapter relationship referenced a missing or filtered node; relationship omitted.", evidence=edge["evidence"])
            del edges[eid]

    annotations = []
    if config.get("annotations"):
        annotations = safe_json(Path(config["_base"]) / config["annotations"])
        if not isinstance(annotations, list) or any(not isinstance(a, dict) or "node_id" not in a for a in annotations):
            raise ValueError("annotations must be a JSON list with node_id on every entry")
        for annotation in annotations:
            if annotation["node_id"] not in nodes:
                issue("annotation_unmatched", "A reviewed annotation targets an absent/filtered asset; annotation preserved for reconciliation.")
    snapshot = redact({"schema_version": "1", "project": config["project"], "phase": "analyzed" if analyze else "discovery",
        "collected_at": collected, "effective_config": public_config(config), "registry_fingerprint": registry.fingerprint,
        "sources": public_config(config)["sources"], "artifacts": [{k: v for k, v in a.items() if k != "text"} for a in artifacts],
        "detections": detections, "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges.values(), key=lambda e: e["id"]), "evidence": sorted(evidences.values(), key=lambda e: e["id"]),
        "issues": sorted(issues, key=lambda i: (i.get("artifact_id") or "", i["code"], i["message"])),
        "references": references, "links": sorted(links, key=lambda link: link["id"]),
        "annotations": annotations, "capabilities": registry.capabilities(),
        "freshness": {"state": "current_at_collection", "collected_at": collected,
                      "note": "Run status to compare current file hashes; offline documents cannot observe later changes. Runtime state is unknown."},
        "metrics": {"files": len(artifacts), "input_bytes": total_bytes, "adapter_runs": adapter_runs,
                    "adapter_failures": adapter_failures, "elapsed_seconds": round(time.monotonic() - start, 6),
                    "extraction_cache": "disabled; every input is rehashed and reparsed", "resource_isolation": "spawned workers; wall time + platform-supported CPU/address-space limits"}})
    if analyze:
        from .architecture import recover
        snapshot["architecture"] = recover(snapshot)
    snapshot["snapshot_id"] = digest(_semantic(snapshot))[:24]
    return snapshot


def _resolve_references(references, nodes, edges, evidences, artifacts, issue):
    entrypoints = defaultdict(set)
    for node in nodes.values():
        if node.get("attributes", {}).get("entrypoint"):
            for eid in node["evidence"]:
                entrypoints[evidences[eid]["artifact_id"]].add(node["id"])
    paths = {(a["source_id"], a["path"]): a["id"] for a in artifacts.values()}
    for reference in references:
        target = reference["target_path"]
        attrs = reference["attributes"]
        if not isinstance(target, str) or attrs.get("runtime_cwd") == "unknown" or target.startswith("/") or any(part in target for part in ("$", "{{", "..", "\\")):
            issue("unresolved_reference", "Absolute, dynamic, traversal, or unknown-working-directory reference remains unresolved.", artifacts[reference["artifact_id"]], reference["evidence"])
            reference["resolution"] = "unknown"
            continue
        normalized = posixpath.normpath(posixpath.join(posixpath.dirname(reference["base_path"]), target))
        aid = paths.get((reference["source_id"], normalized))
        candidates = entrypoints.get(aid, set())
        if len(candidates) != 1:
            issue("unresolved_reference", "Referenced exact same-scope artifact has no unique supported entrypoint. Supply connection/context metadata or a trusted adapter.", artifacts[reference["artifact_id"]], reference["evidence"])
            reference["resolution"] = "unknown"
            continue
        to_id = next(iter(candidates))
        eid = stable_id("edge", reference["from_id"], to_id, reference["kind"], attrs)
        edges[eid] = {"id": eid, "source": reference["from_id"], "target": to_id, "kind": reference["kind"], "attributes": {**attrs, "resolution": "exact same-source relative artifact path"}, "status": "declared", "evidence": reference["evidence"]}
        reference.update(resolution="resolved", target_id=to_id)


def _filter_adapter_resources(result, source, known_nodes, artifact, issue):
    """Apply the producing source's filters before canonical identities merge.

    Sources can intentionally share a service. A permissive source must never
    authorize another source's otherwise excluded declarations or evidence.
    """
    candidates = {**known_nodes, **{node["id"]: node for node in result["nodes"]}}
    excluded = set()
    produced_ids = {node["id"] for node in result["nodes"]}
    for node in candidates.values():
        if node["kind"] == "dataset":
            schema = node["name"].split(".")[-2] if "." in node["name"] else ""
            if not (matches(node["name"], source["resource_filters"]) and matches(schema, source["schema_filters"])):
                excluded.add(node["id"])
                if node["id"] in produced_ids:
                    issue("resource_filtered", "Producing source's schema/resource filter omitted a dataset declaration; another source cannot override this scope.", artifact=artifact, evidence=node["evidence"], severity="info")
    for node in candidates.values():
        if node["kind"] == "column" and node.get("attributes", {}).get("dataset") in excluded:
            excluded.add(node["id"])
    result["nodes"] = [node for node in result["nodes"] if node["id"] not in excluded]
    result["edges"] = [edge for edge in result["edges"] if edge["source"] not in excluded and edge["target"] not in excluded]
    result["references"] = [reference for reference in result["references"] if reference["from_id"] not in excluded]


def _resolve_links(links, nodes, edges, evidences, artifacts, issue):
    """Resolve exported declarations by full identity and exact source evidence.

    This performs no I/O. A binding cannot create an excluded/missing endpoint,
    substitute an identically named PROD asset, or prove a successful operation.
    """
    allowed_sources = {(artifact["source_id"], artifact["path"], artifact["environment"]): artifact["id"]
                       for artifact in artifacts.values()}
    for link in links:
        origin = artifacts[link["artifact_id"]]
        selectors = (link["source_selector"], link["target_selector"])
        if any(selector["environment"] != origin["environment"] for selector in selectors):
            link.update(resolution="unknown", reason="Cross-environment bindings are unsupported; explicit environment identities differ.")
            issue("cross_environment_link", link["reason"], origin, link["evidence"])
            continue
        endpoints = []
        for selector in selectors:
            artifact_id = allowed_sources.get((selector["source_id"], selector["artifact_path"], selector["environment"]))
            node = nodes.get(selector["node_id"])
            exact = node and all(node[key] == selector[key] for key in ("kind", "name", "environment", "namespace"))
            source_evidence = exact and any(evidences[eid]["artifact_id"] == artifact_id for eid in node["evidence"])
            if artifact_id and source_evidence:
                endpoints.append(node)
        if len(endpoints) != 2:
            link.update(resolution="unknown", reason="Exact binding endpoint is absent, excluded, inaccessible or unsupported. Supply the matching authorized artifact and analyzer; short names are insufficient.")
            issue("unresolved_architecture_link", link["reason"], origin, link["evidence"])
            continue
        attrs = {**link["attributes"], "binding_id": link["id"], "runtime_verified": False,
                 "resolution": "exact environment/namespace/name/source-artifact declaration"}
        eid = stable_id("edge", endpoints[0]["id"], endpoints[1]["id"], link["kind"], attrs)
        proof = sorted(set(link["evidence"] + endpoints[0]["evidence"] + endpoints[1]["evidence"]))
        if eid in edges:
            edges[eid]["evidence"] = sorted(set(edges[eid]["evidence"] + proof))
        else:
            edges[eid] = {"id": eid, "source": endpoints[0]["id"], "target": endpoints[1]["id"],
                          "kind": link["kind"], "attributes": attrs, "status": "declared", "evidence": proof}
        link.update(resolution="resolved", edge_id=eid, source_id=endpoints[0]["id"], target_id=endpoints[1]["id"])
