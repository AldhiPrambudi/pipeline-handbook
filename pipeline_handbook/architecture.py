"""Recover architecture and onboarding journeys from the existing evidence graph.

This module has no filesystem, execution or network access. Its findings are
projections of collected facts, never a proposed architecture or runtime claim.
"""
from __future__ import annotations

from collections import defaultdict, deque

from .security import redact, stable_id

MAX_WALKTHROUGHS = 64
MAX_ANCESTORS = 512
MAX_STEPS = 128
MAX_RECORDS = 500


def _proof(*records):
    return sorted({eid for record in records if record for eid in record.get("evidence", [])})


def _record(prefix, identity, text, evidence, status="inferred", **fields):
    return {"id": stable_id(prefix, identity), "status": status, "evidence": sorted(set(evidence)), "text": text, **fields}


def _bounded(values, limit, collection, omissions):
    if len(values) > limit:
        omissions[collection] = {"count": len(values), "shown": limit, "limit": limit}
    return values[:limit]


def _relationship(edge, nodes):
    source, target = nodes[edge["source"]], nodes[edge["target"]]
    kind, attrs = edge["kind"], edge.get("attributes", {})
    meaning = {
        "data_flow": "supported data dependency; actual data movement is unverified",
        "control_flow": "declared task dependency; this does not establish data movement or successful execution",
        "invocation": "declared reference to a workflow definition; execution is unverified",
        "schedule": "declared trigger; no run is established",
        "deployment": "deployment configuration relationship; actual deployment and readiness are unverified",
        "connection": "explicit configured connection reference; successful communication is unverified",
    }.get(kind, "declared relationship")
    condition = attrs.get("condition")
    suffix = f" Condition: {condition}." if condition is not None else ""
    relation = attrs.get("relation")
    if relation:
        suffix += f" Configuration relation: {relation}."
    return {**edge, "text": f'{source["name"]} → {target["name"]}: {meaning}.{suffix}',
            "node_ids": [source["id"], target["id"]], "edge_ids": [edge["id"]]}


def recover(snapshot):
    """Return a bounded, deterministic architecture view of a canonical snapshot."""
    nodes = {node["id"]: node for node in snapshot.get("nodes", [])}
    evidence = {item["id"]: item for item in snapshot.get("evidence", [])}
    artifacts = {item["id"]: item for item in snapshot.get("artifacts", [])}
    edges = [edge for edge in snapshot.get("edges", []) if edge["source"] in nodes and edge["target"] in nodes]
    sources = {source["id"]: source for source in snapshot.get("sources", [])}
    result = {"schema_version": "1", "findings": [], "components": [], "technology_roles": [],
              "relationships": [], "walkthroughs": [], "inspection_points": [], "questions": [],
              "recommendations": [], "limits": {"walkthroughs": MAX_WALKTHROUGHS,
                  "ancestor_nodes_per_output": MAX_ANCESTORS, "steps_per_kind": MAX_STEPS,
                  "overview_records_per_kind": MAX_RECORDS},
              "truncation": {"truncated": False, "collections": {}, "walkthrough_ids": []}}
    if not nodes and not artifacts and not snapshot.get("detections"):
        return result

    points, questions = {}, {}

    def question(code, text, proof, identity=None, **fields):
        if not proof:
            return  # no unsupported factual claims about an empty/uncollected scope
        record = _record("architecture-question", identity or (code, text), text, proof, "unknown", code=code, **fields)
        previous = questions.get(record["id"])
        if previous:
            record["evidence"] = _proof(previous, record)
        questions[record["id"]] = record

    # Definition locations and explicitly exported inspection points are distinct.
    for node in nodes.values():
        for eid in node.get("evidence", []):
            item = evidence.get(eid, {})
            if item.get("artifact_id") not in artifacts:
                continue
            location = item["location"]
            pointer = item.get("object_path")
            identity = (node["id"], location, pointer)
            record = _record("inspection", identity,
                f'Inspect the authorized definition at {location}' + (f" (object {pointer})" if pointer else "") + ". Verify the recorded source hash and analyzer version.",
                [eid], "declared", node_id=node["id"], kind="definition", location=location,
                environment=node["environment"], object_path=pointer)
            prior = points.get(record["id"])
            if prior:
                record["evidence"] = _proof(prior, record)
            points[record["id"]] = record
        for index, point in enumerate(node.get("attributes", {}).get("inspection_points", [])):
            if not isinstance(point, dict) or not isinstance(point.get("location"), str):
                continue
            kind = point.get("kind", "declared_location")
            record = _record("inspection", (node["id"], kind, point["location"], index),
                f'{kind}: {point["location"]}. This location is declared in supplied metadata; its contents and accessibility were not inspected.',
                node["evidence"], "declared", node_id=node["id"], kind=kind, location=point["location"],
                environment=node["environment"])
            points[record["id"]] = record

    for node in nodes.values():
        if node["kind"] not in {"component", "deployment_resource", "report"}:
            continue
        attrs = node.get("attributes", {})
        boundary, location = attrs.get("boundary", "unknown"), attrs.get("location", "unknown")
        conflicts = node.get("conflicts", [])
        if conflicts:
            conflicted = {conflict["field"] for conflict in conflicts}
            if "location" in conflicted:
                location = "conflicting declarations; inspect all source evidence"
            if "boundary" in conflicted:
                boundary = "conflicting declarations; inspect all source evidence"
        tech = attrs.get("technology", attrs.get("declared_technology", "unknown"))
        record = _record("architecture-component", node["id"],
            f'{node["name"]} is a declared {node["kind"]} in {node["environment"]}. '
            f'Boundary: {boundary}. Location: {location}. Deployment and runtime state are unverified.',
            node["evidence"], "unknown" if conflicts else node["status"], node_id=node["id"],
            name=node["name"], kind=node["kind"], environment=node["environment"], namespace=node["namespace"],
            boundary=boundary, location=location, technology=tech, role=attrs.get("role", "unknown"), conflicts=conflicts)
        result["components"].append(record)
        if location == "unknown":
            question("deployment_location_unknown", f'What authorized deployment metadata identifies the actual host or service placement for {node["name"]}? The configuration does not establish it.', node["evidence"], node["id"])

    # Recover grouping from source/definition identity; this is not a deployed layer.
    grouped = defaultdict(dict)
    for node in nodes.values():
        if node["kind"] != "pipeline":
            continue
        for eid in node["evidence"]:
            artifact = artifacts.get(evidence.get(eid, {}).get("artifact_id"))
            if artifact:
                grouped[(node["environment"], artifact["source_id"])][node["id"]] = node
    for (environment, source_id), definitions in sorted(grouped.items()):
        proof = _proof(*definitions.values())
        service = sources.get(source_id, {}).get("service", source_id)
        result["components"].append(_record("definition-group", (environment, source_id),
            f'{source_id} groups {len(definitions)} supported pipeline definitions under configured service {service}. This source boundary does not establish a deployment or architectural layer.',
            proof, "inferred", name=service, kind="definition_group", environment=environment,
            namespace=source_id, boundary=f"authorized source {source_id}", location="actual deployment unknown",
            technology="mixed definitions", node_ids=sorted(definitions)))

    role_groups = defaultdict(list)
    for detection in snapshot.get("detections", []):
        role_groups[(detection["environment"], detection.get("source_id", "unknown"), detection["technology"], detection["category"])].append(detection)
    for (environment, source_id, technology, category), detections in sorted(role_groups.items()):
        aids = {item["artifact_id"] for item in detections}
        attached = [node for node in nodes.values() if technology in node.get("technologies", [node.get("technology")])
                    and any(evidence.get(eid, {}).get("artifact_id") in aids for eid in node["evidence"])]
        counts = defaultdict(int)
        for node in attached:
            counts[node["kind"]] += 1
        if category == "mentioned":
            text = f"{technology} is mentioned in documentation in {source_id}; its environment role and deployment are unverified."
        elif attached:
            description = ", ".join(f"{count} {kind} definitions" for kind, count in sorted(counts.items()))
            names = sorted(node["name"] for node in attached if node["kind"] in {"pipeline", "component", "report"})
            examples = ", ".join(names[:4])
            text = f"{technology} evidence in {source_id} contributes {description}."
            if examples:
                text += f" Definition examples: {examples}."
            text += " These describe the supported declared role; execution and deployment remain unverified."
        else:
            text = f"{technology} has {category} evidence in {source_id}, with no supported graph extraction from those artifacts. Its operational role is unknown; dependency or detection alone is insufficient."
        result["technology_roles"].append(_record("technology-role", (environment, source_id, technology, category), text,
            _proof(*detections, *attached), "unknown" if category == "ambiguous" else "inferred" if attached else "declared",
            technology=technology, environment=environment, source_id=source_id, category=category,
            analysis_status=sorted({item.get("analysis_status", "unknown") for item in detections}),
            node_ids=sorted(node["id"] for node in attached)))

    meaningful = {"data_flow", "control_flow", "invocation", "schedule", "deployment", "connection"}
    result["relationships"] = [_relationship(edge, nodes) for edge in edges if edge["kind"] in meaningful]
    relationship_by_id = {edge["id"]: edge for edge in result["relationships"]}
    incoming = defaultdict(list)
    control_neighbours = defaultdict(list)
    parents = defaultdict(set)
    trigger_edges = defaultdict(list)
    deployment_edges = defaultdict(list)
    for edge in edges:
        if edge["kind"] == "data_flow":
            incoming[edge["target"]].append(edge)
        elif edge["kind"] == "contains":
            parents[edge["target"]].add(edge["source"])
        elif edge["kind"] in {"control_flow", "invocation"}:
            control_neighbours[edge["source"]].append(edge)
            control_neighbours[edge["target"]].append(edge)
        elif edge["kind"] == "schedule":
            trigger_edges[edge["target"]].append(edge)
        elif edge["kind"] == "deployment":
            deployment_edges[edge["source"]].append(edge)
            deployment_edges[edge["target"]].append(edge)

    outputs = sorted((node for node in nodes.values() if node["kind"] in {"dataset", "report"}),
                     key=lambda node: (node["environment"], node["namespace"], node["name"], node["id"]))
    shown_outputs = _bounded(outputs, MAX_WALKTHROUGHS, "walkthroughs", result["truncation"]["collections"])
    for output in shown_outputs:
        omissions = {}
        edge_budget = MAX_ANCESTORS * 8
        visited, queue, ancestry = {output["id"]}, deque([output["id"]]), {}
        rejected, examined, edge_limit_hit = 0, 0, False
        while queue and not edge_limit_hit:
            for edge in sorted(incoming[queue.popleft()], key=lambda edge: edge["id"]):
                if examined >= edge_budget:
                    edge_limit_hit = True
                    break
                examined += 1
                source = edge["source"]
                if source not in visited:
                    if len(visited) >= MAX_ANCESTORS:
                        rejected += 1
                        continue
                    visited.add(source)
                    queue.append(source)
                # Keep machine ancestry and displayed edges within the same
                # admitted identity set; rejected endpoints are not displayed.
                ancestry[edge["id"]] = edge
        if rejected:
            omissions["ancestor_nodes"] = {"count_at_least": len(visited) + 1, "shown": len(visited),
                "limit": MAX_ANCESTORS, "omitted_candidate_edges": rejected,
                "note": "Further reachability beyond admitted nodes is unknown."}
        if edge_limit_hit:
            omissions["ancestor_edges"] = {"count_at_least": examined + 1, "shown": len(ancestry), "limit": edge_budget}
        producer_candidates = {nid for nid in visited if nodes[nid]["kind"] in {"pipeline", "task"}}
        producer_candidates.update(edge["attributes"]["via"] for edge in ancestry.values()
            if edge.get("attributes", {}).get("via") in nodes
            and nodes[edge["attributes"]["via"]]["kind"] in {"pipeline", "task"})
        producers = set(_bounded(sorted(producer_candidates), min(MAX_STEPS, MAX_ANCESTORS), "producers", omissions))
        # This ordering is a dependency reading order, never asserted run order.
        ordered, cyclic = _dependency_order(visited, list(ancestry.values()))
        rank = {nid: number for number, nid in enumerate(ordered)}
        ordered_edges = sorted(ancestry.values(), key=lambda edge: (rank.get(edge["target"], 0), rank.get(edge["source"], 0), edge["id"]))
        data_steps = [relationship_by_id[edge["id"]] for edge in ordered_edges]
        for nid in sorted(producers):
            node = nodes[nid]
            proof = _proof(node, *[edge for edge in ancestry.values() if edge.get("attributes", {}).get("via") == nid])
            data_steps.append(_record("producer-step", (output["id"], nid),
                f'Definition on the supported data path: {node["name"]} ({node["kind"]}). Inspect its source evidence; no execution is established.',
                proof, "inferred", node_ids=[nid], edge_ids=[]))
        data_steps = _bounded(data_steps, MAX_STEPS, "data_steps", omissions)
        relevant, queue, controls, schedules = set(producers), deque(sorted(producers)), {}, {}
        rejected_context, examined_context, context_limit_hit = 0, 0, False
        while queue and not context_limit_hit:
            nid = queue.popleft()
            for next_id in sorted(parents[nid] - relevant):
                if len(relevant) >= MAX_ANCESTORS:
                    rejected_context += 1
                else:
                    relevant.add(next_id)
                    queue.append(next_id)
            for edge in sorted(control_neighbours[nid], key=lambda edge: edge["id"]):
                if examined_context >= edge_budget:
                    context_limit_hit = True
                    break
                examined_context += 1
                other = edge["target"] if edge["source"] == nid else edge["source"]
                if other not in relevant:
                    if len(relevant) >= MAX_ANCESTORS:
                        rejected_context += 1
                        continue
                    relevant.add(other)
                    queue.append(other)
                controls[edge["id"]] = edge
            for edge in trigger_edges[nid]:
                schedules[edge["id"]] = edge
        if rejected_context:
            omissions["control_context_nodes"] = {"count_at_least": len(relevant) + 1, "shown": len(relevant),
                "limit": MAX_ANCESTORS, "omitted_context_references": rejected_context}
        if context_limit_hit:
            omissions["control_context_edges"] = {"count_at_least": examined_context + 1, "shown": len(controls), "limit": edge_budget}
        deployments = {}
        # Outputs and ancestor assets may have explicit placement declarations
        # even when no producer/control definition is available.
        for nid in visited | relevant:
            for edge in deployment_edges[nid]:
                deployments[edge["id"]] = edge
        deployment_steps = _bounded([relationship_by_id[edge["id"]] for edge in sorted(deployments.values(), key=lambda edge: edge["id"])], MAX_STEPS, "deployment_steps", omissions)
        context = {nid for step in deployment_steps for nid in step["node_ids"]}
        control_steps = _bounded([relationship_by_id[edge["id"]] for edge in sorted(controls.values(), key=lambda edge: edge["id"])], MAX_STEPS, "control_steps", omissions)
        schedule_edges = _bounded(sorted(schedules.values(), key=lambda edge: edge["id"]), MAX_STEPS, "schedules", omissions)
        schedule_steps = []
        for edge in schedule_edges:
            step = dict(relationship_by_id[edge["id"]])
            expression = nodes[edge["source"]].get("attributes", {}).get("expression", "unknown")
            step["text"] += f" Declared schedule expression: {expression}. Timezone and actual runs require their own evidence."
            schedule_steps.append(step)
            context.update((edge["source"], edge["target"]))
        visible = visited | relevant | context
        available_checks = sorted((point for point in points.values() if point.get("node_id") in visible), key=lambda point: point["id"])
        has_log_location = any(point["kind"] in {"logs", "log", "validation"} for point in available_checks)
        checks = _bounded(available_checks, MAX_STEPS, "inspection_points", omissions)
        limitations = ["Data ancestry is presented for inspection, not as an execution sequence.",
                       "Static definitions and exported declarations do not prove deployment, communication or successful execution.",
                       "Business purpose, original design rationale, ownership, SLAs and recovery steps require reviewed human evidence."]
        if not ancestry:
            limitations.append("No supported incoming data dependency was extracted; source origin is unknown rather than proven external or absent.")
        if not schedules:
            limitations.append("No supported trigger was resolved for this output; schedules may exist outside available evidence.")
        if not has_log_location:
            limitations.append("Log and validation inspection locations are unknown for this trace.")
        if cyclic:
            limitations.append("A cycle is present in the declared data graph; no execution order is inferred.")
        if omissions:
            limitations.append("The bounded architecture view was truncated; inspect the canonical graph for remaining relationships.")
            question("architecture_view_truncated", limitations[-1], output["evidence"], output["id"])
            result["truncation"]["walkthrough_ids"].append(output["id"])
        proof = _proof(output, *ancestry.values(), *[nodes[nid] for nid in producers], *controls.values(), *schedules.values(), *deployment_steps)
        if not has_log_location:
            question("log_visibility_unknown", f'Where are the authorized logs and validation records for {output["name"]} in {output["environment"]}/{output["namespace"]}? No location was resolved for this trace; request metadata or owner-reviewed inspection guidance.',
                     proof, output["id"])
        result["walkthroughs"].append(_record("walkthrough", output["id"],
            f'Trace {output["name"]} in {output["environment"]}/{output["namespace"]} through supported data ancestry, then inspect separately declared controls and triggers.',
            proof, title=output["name"], output_id=output["id"], environment=output["environment"], namespace=output["namespace"],
            data_ancestry_order="dependency presentation; not execution sequence",
            upstream_dataset_ids=sorted(nid for nid in visited - {output["id"]} if nodes[nid]["kind"] == "dataset"),
            producer_ids=sorted(producers), data_steps=data_steps, control_steps=control_steps,
            deployment_steps=deployment_steps, schedules=schedule_steps, inspection_points=checks,
            truncation={"truncated": bool(omissions), "collections": omissions}, limitations=limitations))

    scope_proof = sorted({eid for node in nodes.values() for eid in node.get("evidence", [])}
                         | {eid for detection in snapshot.get("detections", []) for eid in detection.get("evidence", [])})
    if scope_proof:
        result["findings"].append(_record("architecture-finding", "scope",
            f'The supplied snapshot contains {len(artifacts)} inventoried artifacts in {len(sources)} authorized scopes, '
            f'{sum(node["kind"] == "pipeline" for node in nodes.values())} supported pipeline definitions and '
            f'{sum(node["kind"] == "report" for node in nodes.values())} declared report/form consumers. Boundaries are recovered from source identity and explicit metadata; no predefined layers are imposed.', scope_proof))
        observed = [node for node in nodes.values() if node["kind"] == "run" and node["status"] == "observed"]
        if not observed:
            question("runtime_visibility_unknown", "No supported observed run records are included. Request authorized time-bound run/metadata exports to assess successful execution or communication; missing visibility does not establish absence.", scope_proof)
        question("business_context_requires_review", "Which reviewed business purposes, owners, original design rationale, SLAs and recovery instructions apply? Preserve supplied annotations; do not infer these from names or diagrams.", scope_proof)
    for item in snapshot.get("issues", []):
        message = item["message"]
        if item["code"] == "adapter_conflict":
            message += " Provide an export aligned to the same revision or reviewed clarification of the conflicting declarations."
        question(item["code"], message, item.get("evidence", []) or scope_proof,
                 (item["code"], item.get("artifact_id"), item["message"]))
    omissions = result["truncation"]["collections"]
    result["inspection_points"] = _bounded(sorted(points.values(), key=lambda item: item["id"]), MAX_RECORDS, "inspection_points", omissions)
    for key in ("components", "findings", "technology_roles"):
        result[key] = _bounded(sorted(result[key], key=lambda item: item["id"]), MAX_RECORDS, key, omissions)
    result["relationships"] = _bounded(sorted(result["relationships"], key=lambda item: item["id"]), MAX_RECORDS, "relationships", omissions)
    if len(questions) > MAX_RECORDS:
        omissions["questions"] = {"count": len(questions) + 1, "shown": MAX_RECORDS, "limit": MAX_RECORDS,
            "note": "Shown questions reserve one slot for the truncation summary."}
    result["truncation"]["truncated"] = bool(omissions or result["truncation"]["walkthrough_ids"])
    if result["truncation"]["truncated"]:
        question("architecture_view_truncated", "Architecture view limits omitted collected records. Consult the count/limit metadata and canonical graph; omitted items are not established absent.", scope_proof, "architecture-truncation-summary")
        summary_id = stable_id("architecture-question", "architecture-truncation-summary")
        summary = questions.get(summary_id)
        # Reserve a visible warning even when the question collection itself is
        # clipped; sorting alone could otherwise hide the only omission notice.
        other_questions = sorted((item for key, item in questions.items() if key != summary_id), key=lambda item: item["id"])
        if len(questions) > MAX_RECORDS and "questions" not in omissions:
            omissions["questions"] = {"count": len(questions), "shown": MAX_RECORDS, "limit": MAX_RECORDS,
                "note": "Shown questions reserve one slot for the truncation summary."}
        result["questions"] = sorted(other_questions[:max(0, MAX_RECORDS - (1 if summary else 0))] + ([summary] if summary else []), key=lambda item: item["id"])
    else:
        result["questions"] = sorted(questions.values(), key=lambda item: item["id"])
    return redact(result)


def _dependency_order(node_ids, edges):
    incoming = {nid: 0 for nid in node_ids}
    following = defaultdict(list)
    for edge in edges:
        if edge["source"] in incoming and edge["target"] in incoming:
            incoming[edge["target"]] += 1
            following[edge["source"]].append(edge["target"])
    queue = deque(sorted(nid for nid, count in incoming.items() if count == 0))
    ordered = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for target in sorted(following[current]):
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    remainder = sorted(set(node_ids) - set(ordered))
    return ordered + remainder, bool(remainder)
