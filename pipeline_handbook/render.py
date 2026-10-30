"""Self-contained, evidence-linked handbook output. No network or target code.

The renderer consumes the canonical sanitized snapshot; it does not read source
files. All source-controlled strings are escaped before HTML/SVG/Markdown output.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import os
from pathlib import Path
import tempfile
import textwrap


def _string(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value if value is not None else "unknown")


def _h(value):
    return escape(_string(value), quote=True)


def _md(value):
    return _string(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("(", "\\(").replace(")", "\\)").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("`", "&#96;")


def _mermaid_label(value):
    return _string(value).replace("&", "&amp;").replace('"', "&quot;").replace("[", "&#91;").replace("]", "&#93;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")


def _anchor(value):
    return "item-" + hashlib.sha256(str(value).encode()).hexdigest()[:18]


def _evidence_ids(obj):
    values = obj.get("evidence", [])
    return [values] if isinstance(values, str) else values or []


def _object_pointer(obj):
    value = obj.get("object_path")
    return "document root (empty JSON pointer)" if value == "" else value


def _refs(obj, html=True):
    refs = _evidence_ids(obj)
    if html:
        return " ".join(f'<a class="evidence-link" href="#{_anchor(e)}">E{_h(str(e)[-6:])}</a>' for e in refs) or "No evidence recorded"
    return ", ".join(f"[E{str(e)[-6:]}](#{_anchor(e)})" for e in refs) or "No evidence recorded"


def _table(headers, rows):
    header = "".join(f"<th>{_h(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>' if rows else '<p class="muted">No entries within the documented scan coverage.</p>'


def _markdown_table(headers, rows):
    if not rows:
        return "No entries within the documented scan coverage.\n"
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join("| " + " | ".join(_md(v) for v in row) + " |" for row in rows) + "\n"


def _graph_groups(snapshot, kind):
    allowed = {"data_flow"} if kind == "data" else {"control_flow", "invocation", "schedule"}
    nodes = {n["id"]: n for n in snapshot.get("nodes", [])}
    groups = defaultdict(list)
    for e in snapshot.get("edges", []):
        if e.get("kind") in allowed and e.get("source") in nodes and e.get("target") in nodes:
            source = nodes[e["source"]]
            groups[source.get("environment", "unknown")].append(e)
    return nodes, sorted(groups.items())


def _svg(nodes, edges, label, include_nodes=None, boundaries=False):
    """Layered directed graph with cycle fallback; explicit semantics on edges."""
    used = sorted({e[k] for e in edges for k in ("source", "target")} | set(include_nodes or []))
    incoming = {n: 0 for n in used}
    downstream = defaultdict(list)
    for e in edges:
        incoming[e["target"]] += 1
        downstream[e["source"]].append(e["target"])
    level = {n: 0 for n in used}
    q = deque(sorted(n for n in used if incoming[n] == 0))
    visited = set()
    while q:
        n = q.popleft()
        visited.add(n)
        for target in sorted(downstream[n]):
            level[target] = max(level[target], level[n] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                q.append(target)
    # Cycles are shown without pretending there is a topological order.
    fallback = max(level.values(), default=0) + 1
    for n in used:
        if n not in visited:
            level[n] = fallback
    pos = {}
    bands = []
    if boundaries:
        found = defaultdict(list)
        for n in used:
            boundary = nodes[n].get("attributes", {}).get("boundary")
            found[str(boundary) if boundary else "Boundary not supplied"].append(n)
        offset = 38
        for boundary, ids in sorted(found.items()):
            columns = defaultdict(list)
            for n in ids:
                columns[level[n]].append(n)
            rows = max(map(len, columns.values()), default=1)
            for col, children in sorted(columns.items()):
                for row, n in enumerate(sorted(children, key=lambda x: (nodes[x].get("name", ""), x))):
                    pos[n] = (40 + col * 335, offset + 32 + row * 115)
            band_height = rows * 115 + 25
            bands.append((boundary, offset, band_height))
            offset += band_height + 18
    else:
        columns = defaultdict(list)
        for n in used:
            columns[level[n]].append(n)
        for col, ids in sorted(columns.items()):
            for row, n in enumerate(sorted(ids, key=lambda x: (nodes[x].get("name", ""), x))):
                pos[n] = (30 + col * 335, 30 + row * 125)
    width = max((x + 285 for x, _ in pos.values()), default=360)
    height = max((y + 120 for _, y in pos.values()), default=160)
    marker = "arrow-" + hashlib.sha256(label.encode()).hexdigest()[:12]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{_h(label)}">',
           f'<title>{_h(label)}</title><defs><marker id="{marker}" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#4b716b"/></marker></defs>']
    for boundary, y, band_height in bands:
        out.append(f'<rect x="15" y="{y-6}" width="{width-30}" height="{band_height}" rx="8" fill="#edf2e9" stroke="#c8d6ca" stroke-dasharray="5 3"/><text x="30" y="{y+13}" font-family="system-ui,sans-serif" font-size="11" fill="#46644e">{_h(boundary)}</text>')
    for e in edges:
        x1, y1 = pos[e["source"]]
        x2, y2 = pos[e["target"]]
        x1 += 255
        y1 += 39
        y2 += 39
        bend = (x1 + x2) / 2
        out.append(f'<path d="M{x1},{y1} C{bend},{y1} {bend},{y2} {x2},{y2}" fill="none" stroke="#4b716b" stroke-width="2" marker-end="url(#{marker})"><title>{_h(e.get("kind"))}: {_h(e.get("attributes", {}))}</title></path>')
    for n in used:
        x, y = pos[n]
        obj = nodes[n]
        name = obj.get("name", n)
        lines = textwrap.wrap(name, 32, break_long_words=True)[:2] or [name]
        out.append(f'<a href="#{_anchor(n)}"><rect x="{x}" y="{y}" width="255" height="82" rx="8" fill="#fff" stroke="#a9bcb5"/><text x="{x+12}" y="{y+18}" font-family="system-ui,sans-serif" font-size="10" fill="#52766a">{_h(obj.get("kind", "asset").upper())}</text>')
        out.extend(f'<text x="{x+12}" y="{y+38+i*17}" font-family="system-ui,sans-serif" font-size="12" fill="#183d38">{_h(line)}</text>' for i, line in enumerate(lines))
        out.append(f'<title>{_h(name)} · {_h(obj.get("environment"))} · {_h(obj.get("status"))}</title></a>')
    out.append("</svg>")
    return "".join(out)


def _flow_html(snapshot, kind):
    nodes, groups = _graph_groups(snapshot, kind)
    if not groups:
        return '<p class="muted">No supported relationships extracted. Missing edges do not prove absence.</p>'
    sections = []
    for env, edges in groups:
        label = ("Data flow" if kind == "data" else "Control flow, invocation and schedule") + " · " + env
        sections.append(f'<h3>{_h(env)}</h3><div class="diagram">{_svg(nodes, edges, label)}</div>')
        sections.append(_table(["Upstream", "Downstream", "Relationship / conditions", "Evidence"], [
            (f'<a href="#{_anchor(e["source"])}">{_h(nodes[e["source"]]["name"])}</a>',
             f'<a href="#{_anchor(e["target"])}">{_h(nodes[e["target"]]["name"])}</a>',
             _h(e["kind"]) + "<br>" + _h(e.get("attributes", {})), _refs(e))
            for e in edges]))
    return "".join(sections)


def _flow_markdown(snapshot, kind):
    nodes, groups = _graph_groups(snapshot, kind)
    if not groups:
        return "No supported relationships extracted. Missing edges do not prove absence.\n"
    out = []
    for env, edges in groups:
        out.append(f"### {_md(env)}\n\n```mermaid\ngraph LR")
        used = sorted({e[k] for e in edges for k in ("source", "target")})
        for n in used:
            # Encoded labels cannot close a Mermaid string or inject directives.
            label = _mermaid_label(nodes[n].get("name", n))
            out.append(f'  {_anchor(n).replace("-", "_")}["{label}"]')
        for e in edges:
            out.append(f'  {_anchor(e["source"]).replace("-", "_")} -->|{e["kind"]}| {_anchor(e["target"]).replace("-", "_")}')
        out.append("```\n")
        out.append(_markdown_table(["Upstream", "Downstream", "Kind", "Conditions", "Evidence IDs"], [
            (nodes[e["source"]]["name"], nodes[e["target"]]["name"], e["kind"], e.get("attributes", {}), ", ".join(_evidence_ids(e))) for e in edges]))
    return "\n".join(out)


def _node_card(node, snapshot):
    related = [e for e in snapshot.get("edges", []) if node["id"] in (e.get("source"), e.get("target"))]
    names = {n["id"]: n.get("name", n["id"]) for n in snapshot.get("nodes", [])}
    rows = [("Status", _h(node.get("status", "unknown"))), ("Environment / namespace", _h(node.get("environment")) + " / " + _h(node.get("namespace"))),
            ("Definition", _h(node.get("explanation", "Declared metadata; purpose requires a reviewed annotation."))),
            ("Attributes", '<code class="wrap">' + _h(node.get("attributes", {})) + '</code>'), ("Evidence", _refs(node))]
    if node.get("kind") in {"pipeline", "task"}:
        flows = [e for e in snapshot.get("edges", []) if e.get("kind") == "data_flow" and (e.get("attributes", {}).get("via") == node["id"] or node["id"] in (e.get("source"), e.get("target")))]
        inputs = sorted({names.get(e["source"], "unknown") for e in flows if e["source"] != node["id"]})
        outputs = sorted({names.get(e["target"], "unknown") for e in flows if e["target"] != node["id"]})
        rows.extend([("Supported inputs", _h(inputs or "Not extracted / unknown")), ("Supported outputs", _h(outputs or "Not extracted / unknown"))])
    relation_rows = [("→ " if e["source"] == node["id"] else "← ") + e["kind"] + " · " + names.get(e["target"] if e["source"] == node["id"] else e["source"], "unknown") for e in related]
    return f'<article class="asset" id="{_anchor(node["id"])}"><p class="eyebrow">{_h(node.get("kind"))} · {_h(node.get("environment"))}</p><h3>{_h(node.get("name"))}</h3>' + _table(["Property", "Recorded value"], rows) + ("<details><summary>Declared relationships</summary><ul>" + "".join(f"<li>{_h(r)}</li>" for r in relation_rows) + "</ul></details>" if relation_rows else "") + "</article>"


_FEATURES = ["detection", "version_identification", "metadata_extraction", "table_lineage", "column_lineage", "control_flow", "schedules", "runtime_evidence", "documentation"]
_ARCHITECTURE_FEATURES = ["technology_role_evidence", "component_inventory", "deployment_configuration", "configured_connections", "report_consumers", "exact_bindings", "architecture_views", "workflow_walkthroughs"]
_ARCHITECTURE_HEADERS = ["Technology", "Role evidence", "Components", "Deployment", "Configured connections", "Reports/forms", "Exact bindings", "Architecture view", "Walkthroughs"]


def _architecture_capability_rows(snapshot):
    rows = []
    for item in snapshot.get("capabilities", []):
        if not isinstance(item, dict):
            continue
        features = item.get("architecture_features") or {}
        if any(value in {"subset", "supported"} for value in features.values()):
            rows.append([item.get("technology", "unknown")] + [features.get(key, "unsupported") for key in _ARCHITECTURE_FEATURES])
    return rows


def _capability_html(snapshot):
    capabilities = snapshot.get("capabilities", [])
    if not isinstance(capabilities, list):
        return '<pre class="wrap">' + _h(capabilities) + '</pre>'
    headers = ["Technology / tested applicability", "Detection", "Version", "Metadata", "Tables", "Columns", "Control", "Schedule", "Runtime", "Docs"]
    rows = []
    details = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        rows.append([_h(item.get("technology")) + "<br><small>" + _h(item.get("applicable_versions", [])) + "</small>"] + [_h(item.get("features", {}).get(f, "unsupported")) for f in _FEATURES])
        details.append('<details><summary>' + _h(item.get("technology")) + ' · limitations and test evidence</summary><pre>' + _h(json.dumps(item, indent=2, ensure_ascii=False)) + '</pre></details>')
    architecture_rows = _architecture_capability_rows(snapshot)
    architecture_table = ('<details><summary>Architecture recovery capabilities</summary><p>Only entries declaring an architecture subset appear here. Unlisted/detection-only entries and exact limitations remain available in each rule declaration below.</p>' + _table(_ARCHITECTURE_HEADERS, [[_h(cell) for cell in row] for row in architecture_rows]) + '</details>') if architecture_rows else ""
    return _table(headers, rows) + architecture_table + "".join(details)


def _impact_rows(snapshot):
    nodes = {n["id"]: n for n in snapshot.get("nodes", [])}
    adjacency = defaultdict(set)
    for edge in snapshot.get("edges", []):
        if edge.get("kind") == "data_flow":
            adjacency[edge["source"]].add(edge["target"])
    rows = []
    for start in sorted(n for n, v in nodes.items() if v.get("kind") == "dataset"):
        seen = {start}
        queue = deque([start])
        while queue:
            for target in sorted(adjacency[queue.popleft()]):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        affected = [nodes[n]["name"] for n in sorted(seen - {start}) if n in nodes and nodes[n].get("kind") == "dataset"]
        if affected:
            rows.append((nodes[start].get("environment"), nodes[start].get("namespace"), nodes[start]["name"], affected))
    return rows


def _node_links(record, snapshot, html=True):
    """Only link actual canonical nodes; projected group IDs are not assets."""
    nodes = {n["id"]: n for n in snapshot.get("nodes", [])}
    candidates = [record.get("node_id"), record.get("output_id")]
    candidates += list(record.get("node_ids") or [])
    result = []
    for nid in dict.fromkeys(n for n in candidates if isinstance(n, str)):
        if nid in nodes:
            name = nodes[nid].get("name", nid)
            result.append(f'<a href="#{_anchor(nid)}">{_h(name)}</a>' if html else f'[{_md(name)}](#{_anchor(nid)})')
    return " · ".join(result)


def _record_rows(records, snapshot):
    return [(_h(r.get("text", "No explanation supplied")), _h(r.get("status", "unknown")), _node_links(r, snapshot), _refs(r)) for r in records]


def _architecture_deployment_html(snapshot):
    nodes = {n["id"]: n for n in snapshot.get("nodes", [])}
    groups = defaultdict(list)
    isolated = defaultdict(list)
    for node in nodes.values():
        if node.get("kind") in {"component", "deployment_resource", "report"}:
            isolated[node.get("environment", "unknown")].append(node["id"])
    for edge in snapshot.get("edges", []):
        if edge.get("kind") in {"deployment", "connection"} and edge.get("source") in nodes and edge.get("target") in nodes:
            groups[nodes[edge["source"]].get("environment", "unknown")].append(edge)
    out = []
    for env in sorted(set(groups) | set(isolated)):
        edges = groups[env]
        out += [f'<h3>{_h(env)}</h3><div class="diagram">',
                _svg(nodes, edges, "Declared deployment and connections · " + env, isolated[env], boundaries=True), '</div>',
                _table(["From", "To", "Declared relationship", "Status", "Evidence"], [
                    (f'<a href="#{_anchor(e["source"])}">{_h(nodes[e["source"]]["name"])}</a>',
                     f'<a href="#{_anchor(e["target"])}">{_h(nodes[e["target"]]["name"])}</a>',
                     _h(e.get("kind")) + "<br>" + _h(e.get("attributes", {})), _h(e.get("status", "unknown")), _refs(e)) for e in edges])]
    return "".join(out) or '<p class="muted">No explicit component deployment or connection topology was extracted. Definition-backed source groupings do not establish deployment boundaries.</p>'


def _inspection_html(records, snapshot):
    return _table(["Inspection point", "Declared location / object", "Environment / status", "Asset", "Evidence"], [
        (_h(r.get("text", r.get("kind", "unknown"))), _h(r.get("location", "unknown")) + ("<br><code>" + _h(_object_pointer(r)) + "</code>" if _object_pointer(r) is not None else ""),
         _h(r.get("environment", "unknown")) + " / " + _h(r.get("status", "unknown")), _node_links(r, snapshot), _refs(r))
        for r in records])


def _walkthrough_records_html(records, snapshot, ordered=False):
    if not records:
        return ""
    tag = "ol" if ordered else "ul"
    return f'<{tag} class="walkthrough-steps">' + "".join(
        '<li><p>' + _h(r.get("text", "No explanation supplied")) + '</p><p><span class="badge">' + _h(r.get("kind", "graph fact")) + " / " + _h(r.get("status", "unknown")) + '</span> ' + _node_links(r, snapshot) + " " + _refs(r) + '</p></li>' for r in records) + f'</{tag}>'


def _architecture_html(snapshot):
    architecture = snapshot.get("architecture")
    if not isinstance(architecture, dict):
        return ""
    view_limits = ('<details><summary>Architecture view limits</summary><p>These bounds limit presentation, not the facts authorized for collection. Truncated or unresolved coverage is reported in the questions above.</p><pre>' + _h(json.dumps(architecture["limits"], indent=2, ensure_ascii=False)) + '</pre></details>') if architecture.get("limits") else ""
    out = ['<section id="architecture-overview"><p class="eyebrow">Recovered view / Existing evidence</p><h2>Architecture overview</h2>',
           '<p>This view reconstructs the environment described by the supplied evidence. It does not prescribe a target architecture. Components, technology roles and boundaries are stated only where definitions or explicit metadata support them. Declared connections do not prove successful communication or running services.</p>',
           '<h3>Recovered findings</h3>', _table(["Finding", "Status", "Related assets", "Evidence"], _record_rows(architecture.get("findings", []), snapshot)),
           '<h3>Components & found boundaries</h3>',
           _table(["Component / group", "Environment", "Boundary / location", "Recovered role", "Conflicts", "Status", "Evidence"], [
               (_h(r.get("name", "definition-backed group")) + "<br>" + _node_links(r, snapshot), _h(r.get("environment", "unknown")), _h(r.get("boundary") or "Boundary not supplied") + "<br>" + _h(r.get("location") or "Location not supplied"),
                _h(r.get("text", "unknown")), _h(r.get("conflicts") or "None reported"), _h(r.get("status", "unknown")), _refs(r)) for r in architecture.get("components", [])]),
           '<h3>Technology roles</h3>', _table(["Technology / environment", "Evidence category / analysis", "Recovered role", "Related definitions", "Evidence"], [
               (_h(r.get("technology", "unknown")) + " / " + _h(r.get("environment", "unknown")), _h(r.get("category", "unknown")) + " / " + _h(r.get("analysis_status", "unknown")), _h(r.get("text", "unknown")), _node_links(r, snapshot), _refs(r))
               for r in architecture.get("technology_roles", [])]), '</section>',
           '<section id="architecture-topology"><p class="eyebrow">Recovered view / Deployment and connection</p><h2>Deployment & connection map</h2><p>These arrows show configured deployment or connection references, separately from the data-flow and task-control diagrams. Groups use only found environments and boundary/project labels from supplied metadata. A Compose project label does not prove physical or security isolation. “Boundary not supplied” records missing evidence; it is not an invented application layer.</p>',
           _architecture_deployment_html(snapshot), '</section>',
           '<section id="architecture-walkthroughs"><p class="eyebrow">Recovered view / Follow an output</p><h2>Workflow walkthroughs</h2><p>Follow an output through its data ancestry, then inspect separately evidenced controls, schedules and source locations. Numbered data steps are a reading order through the graph, not an asserted execution order. Missing control evidence cannot be reconstructed from data arrows.</p>']
    out.append(_table(["Output walkthrough", "Environment / namespace", "Recovered view", "Status"], [
        (f'<a href="#{_anchor("walkthrough:" + str(w.get("id", w.get("output_id", "unknown"))))}">{_h(w.get("title", "Output walkthrough"))}</a>',
         _h(w.get("environment", "unknown")) + " / " + _h(w.get("namespace", "unknown")),
         _h(f'{len(w.get("data_steps", []))} data facts · {len(w.get("control_steps", []))} control/reference facts · {len(w.get("schedules", []))} schedules'), _h(w.get("status", "unknown")))
        for w in architecture.get("walkthroughs", [])]))
    for walk in architecture.get("walkthroughs", []):
        controls = [r for r in walk.get("control_steps", []) if r.get("kind") in {None, "control_flow"}]
        invocations = [r for r in walk.get("control_steps", []) if r.get("kind") == "invocation"]
        out += [f'<article class="asset" id="{_anchor("walkthrough:" + str(walk.get("id", walk.get("output_id", "unknown"))))}"><p class="eyebrow">{_h(walk.get("environment", "unknown"))} / {_h(walk.get("namespace", "unknown"))}</p><h3>{_h(walk.get("title", "Output walkthrough"))}</h3>',
                '<p>' + _h(walk.get("text", "Static graph walkthrough; execution is unverified.")) + '</p><p>' + _node_links(walk, snapshot) + " " + _refs(walk) + '</p>',
                '<h4>Data ancestry — inspection sequence</h4>',
                _walkthrough_records_html(walk.get("data_steps", []), snapshot, ordered=True) or '<p class="muted">No supported upstream data ancestry was recovered for this output.</p>',
                '<h4>Actual declared control dependencies</h4>',
                _walkthrough_records_html(controls, snapshot) or '<p class="muted">No control dependency evidence was linked to this output. Data ancestry does not supply an execution order.</p>',
                '<h4>Definition invocation references</h4>',
                _walkthrough_records_html(invocations, snapshot) or '<p class="muted">No exact invocation reference was linked to this output.</p>',
                '<h4>Schedules & conditions</h4>',
                _walkthrough_records_html(walk.get("schedules", []), snapshot) or '<p class="muted">No schedule evidence was linked to this output.</p>',
                '<h4>Configured deployment & connection context</h4>',
                _walkthrough_records_html(walk.get("deployment_steps", []), snapshot) or '<p class="muted">No configured deployment or connection evidence was linked to this output; actual placement and communication remain unverified.</p>',
                '<h4>Where to inspect</h4>', _inspection_html(walk.get("inspection_points", []), snapshot),
                '<h4>Limits of this explanation</h4><ul>' + "".join('<li>' + _h(limit) + '</li>' for limit in walk.get("limitations", [])) + '</ul></article>']
    if not architecture.get("walkthroughs"):
        out.append('<p class="muted">No supported dataset/report output is available for a walkthrough.</p>')
    out += ['</section>', '<section id="architecture-inspection"><p class="eyebrow">Recovered view / Inspection points</p><h2>Environment inspection guide</h2><p>Locations below are supplied pointers or definition evidence. A log/report path declaration does not prove the target exists or contains successful runs. The scanner does not execute an inspection command.</p>',
            _inspection_html(architecture.get("inspection_points", []), snapshot),
            '<h3>Unknowns & questions</h3>', _table(["Question / missing evidence", "Status", "Related assets", "Evidence"], _record_rows(architecture.get("questions", []), snapshot)), view_limits, '</section>',
            '<section id="architecture-recommendations"><p class="eyebrow">Separate from recovered findings</p><h2>Recommendations</h2>']
    recommendations = architecture.get("recommendations", [])
    out.append(_table(["Recommendation", "Status", "Related assets", "Supporting evidence"], _record_rows(recommendations, snapshot)) if recommendations else '<p class="muted">No recommendations generated. Recovered findings and unknowns describe the supplied environment; no preferred design or optimization is inferred.</p>')
    out.append('</section>')
    return "\n".join(out)


def _architecture_markdown(snapshot):
    architecture = snapshot.get("architecture")
    if not isinstance(architecture, dict):
        return ""
    out = ["## Recovered architecture overview", "", "This reconstructs the supplied evidence; it is not a prescribed target architecture. Declared deployment/connection references do not prove running services or successful communication.", "", "### Recovered findings", "",
           _markdown_table(["Finding", "Status", "Evidence IDs"], [(r.get("text"), r.get("status"), _evidence_ids(r)) for r in architecture.get("findings", [])]), "",
           "### Components and found boundaries", "", _markdown_table(["Component / group", "Environment", "Boundary", "Location", "Recovered role", "Status", "Evidence IDs"], [(r.get("name"), r.get("environment"), r.get("boundary") or "Boundary not supplied", r.get("location") or "Location not supplied", r.get("text"), r.get("status"), _evidence_ids(r)) for r in architecture.get("components", [])]), "",
           "### Technology roles", "", _markdown_table(["Technology", "Environment", "Category / analysis", "Recovered role", "Evidence IDs"], [(r.get("technology"), r.get("environment"), {"category": r.get("category"), "analysis": r.get("analysis_status")}, r.get("text"), _evidence_ids(r)) for r in architecture.get("technology_roles", [])]), "",
           "## Deployment and connection map", "", "Only found environments and supplied boundary/project labels are grouped. Project labels do not prove physical or security isolation. These relationships are distinct from data flow and control flow. A missing boundary is recorded as unknown, not filled with a preferred architecture.", ""]
    nodes = {n["id"]: n for n in snapshot.get("nodes", [])}
    edges = [e for e in snapshot.get("edges", []) if e.get("kind") in {"deployment", "connection"} and e.get("source") in nodes and e.get("target") in nodes]
    groups = defaultdict(list)
    for e in edges:
        groups[nodes[e["source"]].get("environment", "unknown")].append(e)
    for env, relationships in sorted(groups.items()):
        out += ["### " + _md(env), "", "```mermaid", "graph LR"]
        used = sorted({e[k] for e in relationships for k in ("source", "target")})
        boundaries = defaultdict(list)
        for nid in used:
            boundaries[str(nodes[nid].get("attributes", {}).get("boundary") or "Boundary not supplied")].append(nid)
        for boundary, members in sorted(boundaries.items()):
            label = _mermaid_label(boundary)
            out.append('  subgraph ' + _anchor(env + boundary).replace("-", "_") + '["' + label + '"]')
            for nid in members:
                name = _mermaid_label(nodes[nid].get("name", nid))
                out.append(f'    {_anchor(nid).replace("-", "_")}["{name}"]')
            out.append("  end")
        for e in relationships:
            out.append(f'  {_anchor(e["source"]).replace("-", "_")} -->|{e["kind"]}| {_anchor(e["target"]).replace("-", "_")}')
        out += ["```", "", _markdown_table(["From", "To", "Kind", "Status", "Evidence IDs"], [(nodes[e["source"]]["name"], nodes[e["target"]]["name"], e["kind"], e.get("status"), _evidence_ids(e)) for e in relationships]), ""]
    if not groups:
        out += ["No explicit component deployment or connection topology was extracted.", ""]
    out += ["## Workflow walkthroughs", "", "Numbered data steps are an inspection sequence through data ancestry, not execution order. Actual declared controls and schedules are separate.", ""]
    for walk in architecture.get("walkthroughs", []):
        controls = [r for r in walk.get("control_steps", []) if r.get("kind") in {None, "control_flow"}]
        invocations = [r for r in walk.get("control_steps", []) if r.get("kind") == "invocation"]
        out += [f'<a id="{_anchor("walkthrough:" + str(walk.get("id", walk.get("output_id", "unknown"))))}"></a>', "### " + _md(walk.get("title", "Output walkthrough")), "", _md(walk.get("text")), "", "Output: " + _node_links(walk, snapshot, html=False), "", "Evidence: " + _refs(walk, html=False), "", "#### Data ancestry — inspection sequence", ""]
        for i, step in enumerate(walk.get("data_steps", []), 1):
            out += [f'{i}. {_md(step.get("text"))} [{_md(step.get("status"))}]. ' + _node_links(step, snapshot, html=False) + " " + _refs(step, html=False), ""]
        if not walk.get("data_steps"):
            out += ["No supported upstream data ancestry recovered.", ""]
        out += ["#### Actual declared control dependencies", ""]
        out += ["- " + _md(step.get("text")) + " " + _refs(step, html=False) for step in controls] or ["No control dependency evidence linked to this output."]
        out += ["", "#### Definition invocation references", ""]
        out += ["- " + _md(step.get("text")) + " " + _refs(step, html=False) for step in invocations] or ["No exact invocation reference linked to this output."]
        out += ["", "#### Schedules and conditions", ""]
        out += ["- " + _md(step.get("text")) + " " + _refs(step, html=False) for step in walk.get("schedules", [])] or ["No schedule evidence linked to this output."]
        out += ["", "#### Configured deployment and connection context", ""]
        out += ["- " + _md(step.get("text")) + " " + _refs(step, html=False) for step in walk.get("deployment_steps", [])] or ["No configured deployment or connection evidence linked to this output; placement and communication remain unverified."]
        out += ["", "#### Where to inspect", "", _markdown_table(["Inspection point", "Location", "Object pointer", "Status", "Evidence IDs"], [(r.get("text"), r.get("location"), _object_pointer(r) or "not supplied", r.get("status"), _evidence_ids(r)) for r in walk.get("inspection_points", [])]), "", "#### Limits", ""]
        out += ["- " + _md(limit) for limit in walk.get("limitations", [])] + [""]
    out += ["## Environment inspection guide", "", "Locations are declarations or source evidence, not proof that logs/reports exist or contain successful runs.", "", _markdown_table(["Inspection point", "Location", "Object pointer", "Environment", "Status", "Evidence IDs"], [(r.get("text"), r.get("location"), _object_pointer(r) or "not supplied", r.get("environment"), r.get("status"), _evidence_ids(r)) for r in architecture.get("inspection_points", [])]), "", "### Unknowns and questions", "", _markdown_table(["Question", "Status", "Evidence IDs"], [(r.get("text"), r.get("status"), _evidence_ids(r)) for r in architecture.get("questions", [])]), "", "## Recommendations", ""]
    recommendations = architecture.get("recommendations", [])
    out += [_markdown_table(["Recommendation", "Status", "Evidence IDs"], [(r.get("text"), r.get("status"), _evidence_ids(r)) for r in recommendations]) if recommendations else "No recommendations generated. Recovered findings and unknowns describe the supplied environment; no preferred design or optimization is inferred.", ""]
    architecture_rows = _architecture_capability_rows(snapshot)
    if architecture_rows:
        out += ["## Architecture recovery capabilities", "", "Only entries declaring an architecture subset appear here; exact limitations and detection-only entries remain in the complete capability declarations.", "", _markdown_table(_ARCHITECTURE_HEADERS, architecture_rows), ""]
    return "\n".join(out)


def _freshness(snapshot):
    timestamp = snapshot.get("collected_at", "unknown")
    stale = "Age cannot be calculated from the recorded collection timestamp."
    try:
        collected = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - collected).total_seconds() / 86400)
        stale = f"Snapshot age at generation: {age_days:.1f} days. " + ("Age reminder: older than 7 days (display heuristic, no SLA inferred)." if age_days > 7 else "Age alone does not establish source freshness.")
    except (ValueError, TypeError, AttributeError):
        pass
    return f"Inspected: {timestamp}. {stale} Regenerate after source changes. File hashes describe this scan; the saved page does not recheck the inputs. Source exports may predate this inspection: their generated/collected timestamps describe the supplied export, not an observed live system. Static definitions do not prove deployment or successful execution."


_CSS = """
:root{--ink:#153c35;--muted:#62746c;--line:#d7e2da;--paper:#f7f8f2;--accent:#237358}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,sans-serif}a{color:#166951;text-underline-offset:3px}code{font:12px/1.5 ui-monospace,SFMono-Regular,monospace}.wrap{white-space:normal;overflow-wrap:anywhere}aside{position:fixed;left:0;top:0;bottom:0;width:238px;padding:28px 25px;background:#123b33;color:#e8f0e7;overflow:auto}aside h2{font-size:21px;line-height:1.3;margin:15px 0 8px}aside p{color:#a9c4b3;font-size:12px}nav a{display:block;color:#d6e4d9;text-decoration:none;padding:7px 0;font-size:13px}nav a:hover{color:#fff;text-decoration:underline}.brandmark{width:35px;height:35px;border:1px solid #90b09e;display:grid;place-items:center;border-radius:9px;font-weight:600}main{max-width:1500px;margin-left:238px;padding:52px 54px 70px}.eyebrow{letter-spacing:1.5px;text-transform:uppercase;font-size:10px;font-weight:700;color:var(--accent);margin:0 0 10px}.hero h1{font-size:clamp(32px,4vw,56px);line-height:1.05;letter-spacing:-2px;max-width:850px;margin:8px 0 20px}.hero .intro{font-size:17px;max-width:730px;color:#475e51}.badge{display:inline-block;border:1px solid var(--line);border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;background:#fff}.stats{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));gap:14px;margin:32px 0}.stat{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px}.stat strong{font-size:29px;display:block;line-height:1.2}.stat span{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}.notice{background:#e8f1e6;border-left:3px solid #417b56;border-radius:0 6px 6px 0;padding:15px 19px;color:#3c5945;font-size:13px}section{padding-top:38px;margin-top:20px;border-top:1px solid var(--line)}h2{font-size:27px;letter-spacing:-.6px;line-height:1.25}h3{font-size:18px;line-height:1.35;overflow-wrap:anywhere}.muted{color:var(--muted)}.table-scroll,.diagram{overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff;margin:15px 0 25px}table{border-collapse:collapse;width:100%;font-size:12px;line-height:1.55}th{text-align:left;letter-spacing:.4px;font-size:10px;text-transform:uppercase;background:#edf2e9;color:#426348}th,td{padding:11px 13px;border-bottom:1px solid #e7ece5;vertical-align:top;overflow-wrap:anywhere}tr:last-child td{border-bottom:0}td{max-width:430px}.asset{padding:19px 22px;background:#fff;border:1px solid var(--line);border-radius:10px;margin:18px 0}.asset h3{margin:0 0 15px}.asset table th:first-child{width:150px}.asset .table-scroll{border:0;margin:0}.evidence-link{display:inline-block;font:10px ui-monospace,monospace;white-space:nowrap;margin:2px 2px 2px 0;border:1px solid #bdd3c1;border-radius:3px;padding:2px 4px;text-decoration:none}.evidence:target,.asset:target{outline:3px solid #a6c585;scroll-margin-top:20px}summary{cursor:pointer;font-size:12px;color:#41704c;margin-top:12px}.empty{font-style:italic;color:var(--muted)}.diagram{padding:8px}.diagram svg{display:block;max-width:none}footer{margin-top:50px;color:var(--muted);font-size:11px}details pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}ol{padding-left:22px}li{margin:5px 0}@media(max-width:900px){aside{position:static;width:auto}nav{display:flex;gap:10px;flex-wrap:wrap}nav a{padding:0;font-size:12px}aside p{margin-bottom:0}main{margin:0;padding:28px 20px}.stats{grid-template-columns:repeat(2,1fr)}.two-col{grid-template-columns:1fr}}@media print{aside{display:none}main{margin:0;padding:0}section{break-inside:auto}.asset{break-inside:avoid}.diagram{overflow:visible}.diagram svg{max-width:100%;height:auto}body{background:#fff}.table-scroll{overflow:visible}a{color:inherit}}
"""


def _html(snapshot):
    nodes = snapshot.get("nodes", [])
    detections = snapshot.get("detections", [])
    artifacts = snapshot.get("artifacts", [])
    issues = snapshot.get("issues", [])
    technologies = sorted({d.get("technology", "unknown") for d in detections})
    environments = sorted({a.get("environment", "unknown") for a in artifacts})
    pipelines = [n for n in nodes if n.get("kind") in ("pipeline", "task", "schedule")]
    assets = [n for n in nodes if n.get("kind") not in ("pipeline", "task", "schedule")]
    sections = [("start", "Start Here"), ("inventory", "Technology inventory"), ("pipelines", "Pipeline catalogue"), ("data-flow", "Data flow"), ("control-flow", "Control flow"), ("assets", "Asset dictionary"), ("check", "Where to check"), ("changes", "Impact & changes"), ("coverage", "Coverage & questions"), ("capabilities", "Support matrix"), ("annotations", "Reviewed context"), ("glossary", "Glossary"), ("evidence", "Evidence index")]
    if isinstance(snapshot.get("architecture"), dict):
        sections[1:1] = [("architecture-overview", "Architecture overview"), ("architecture-topology", "Deployment & connections"), ("architecture-walkthroughs", "Workflow walkthroughs"), ("architecture-inspection", "Environment inspection"), ("architecture-recommendations", "Recommendations")]
    out = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
           f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">',
           f'<title>{_h(snapshot.get("project", "Pipeline Handbook"))} · Pipeline Handbook</title><style>{_CSS}</style></head><body><aside><div class="brandmark">PH</div><h2>Pipeline<br>Handbook</h2><p>Evidence before explanation</p><nav>',
           "".join(f'<a href="#{key}">{label}</a>' for key, label in sections),
           '</nav><p>Local snapshot · offline edition<br>No workflow execution</p></aside><main><header class="hero"><p class="eyebrow">Engineering onboarding / field guide</p>',
           f'<h1>Understand the stack.<br>Follow the evidence.</h1><p class="intro">A handbook for {_h(snapshot.get("project", "this project"))}. Trace supported outputs, find the definitions behind each relationship, and see what still needs a human answer.</p><span class="badge">Definition-led analysis</span> <span class="badge">{_h(", ".join(environments) or "No environments")}</span>',
           '<div class="stats">' + "".join(f'<div class="stat"><strong>{value}</strong><span>{label}</span></div>' for value, label in [(len(technologies), "Technology candidates"), (len(artifacts), "Artifacts inventoried"), (sum(n.get("kind") == "pipeline" for n in nodes), "Pipeline definitions"), (len(issues), "Coverage findings")]) + '</div></header>',
           '<div class="notice">' + _h(_freshness(snapshot)) + '</div>',
           '<section id="start"><p class="eyebrow">01 / Orientation</p><h2>Start Here</h2><ol><li>Check the technology inventory and environment before choosing an output.</li><li>Find the output in the asset dictionary. Follow upstream arrows in the data-flow view.</li><li>Use the pipeline catalogue and evidence links to locate responsible definitions.</li><li>Read control-flow conditions separately. A dependency does not establish data movement.</li><li>Review coverage findings before making an operational decision.</li></ol><p>Business purpose, ownership, SLAs, actual run success and recovery procedures require reviewed documentation or time-bound runtime evidence. This handbook does not infer them from names.</p></section>',
           _architecture_html(snapshot),
           '<section id="inventory"><p class="eyebrow">02 / Discovery</p><h2>Technology & environment inventory</h2><p class="muted">A documentation mention is weaker evidence than a pipeline definition. Client or dbt adapter versions are not warehouse server versions. A version in a saved metadata export is a declaration from that export, possibly older than this scan; it is not a current live observation. Selected indicates eligibility for analysis, not deployment.</p>',
           _table(["Technology / family", "Environment", "Category / confidence", "Declared version / kind", "Support / selection", "Reasons / conflicts", "Evidence"], [
               (_h(d.get("technology")) + "<br><small>" + _h(d.get("family")) + "</small>", _h(d.get("environment")), _h(d.get("category")) + " / " + _h(d.get("confidence")), _h(d.get("versions", []) or "unknown") + "<br><small>" + _h(d.get("version_kinds", []) or "not identified") + "<br>Client: " + _h(d.get("client_versions", []) or "unknown") + "<br>Export: " + _h(d.get("source_exported_at", "unknown")) + "</small>", _h(d.get("support", "detection-only")) + "<br>Selected: " + _h(d.get("selected", False)) + "<br>Analysis: " + _h(d.get("analysis_status", "unknown")), _h(d.get("reasons", [])) + "<br>" + _h(d.get("conflicts", [])), _refs(d)) for d in detections]), '</section>',
           '<section id="pipelines"><p class="eyebrow">03 / Definitions</p><h2>Pipeline catalogue</h2><p>Parameters, schedules and controls below are declared metadata. Unresolved expressions remain coverage findings; definitions alone do not prove execution.</p>',
           "".join(_node_card(n, snapshot) for n in pipelines) or '<p class="muted">No supported pipeline definitions extracted.</p>', '</section>',
           '<section id="data-flow"><p class="eyebrow">04 / Lineage</p><h2>Data flow</h2><p>Arrows point from an input toward its downstream consumer or output. Only supported, evidence-backed data relationships appear. Column mappings are listed in the dictionary relationships.</p>', _flow_html(snapshot, "data"), '</section>',
           '<section id="control-flow"><p class="eyebrow">05 / Orchestration</p><h2>Control flow</h2><p>Control-flow arrows describe declared task dependencies. Invocation identifies a referenced definition; schedule identifies a declared trigger. Job result conditions and Airflow trigger rules appear in the relationship table. These edges do not prove execution or data movement.</p>', _flow_html(snapshot, "control"), '</section>',
           '<section id="assets"><p class="eyebrow">06 / Dictionary</p><h2>Assets, columns & mappings</h2>', "".join(_node_card(n, snapshot) for n in assets) or '<p class="muted">No supported assets extracted.</p>', '</section>',
           '<section id="check"><p class="eyebrow">07 / Inspection</p><h2>Where to check</h2><p>Evidence locations are relative to an authorized source. Open the indicated file and line in an editor. Artifact hashes let you compare the definition you are reading with this snapshot. No inspection commands generated here execute a pipeline or query business rows.</p>',
           _table(["Environment / source", "Artifact", "State / size", "SHA-256"], [(_h(a.get("environment")) + " / " + _h(a.get("source_id")), _h(a.get("path")), _h(a.get("status", "inventoried")) + " · " + _h(a.get("size", "unknown")) + " bytes", '<code class="wrap">' + _h(a.get("hash", "unknown")) + '</code>') for a in artifacts]),
           '<div class="two-col"><div><h3>Initial read-only checks</h3><ol><li>Confirm environment, source service and collection time.</li><li>Open the evidence location and compare its source hash.</li><li>Check unresolved parameters and unsupported syntax findings.</li><li>Request an authorized metadata or run export when runtime facts are needed.</li></ol></div><div><h3>Logs, validation & datasets</h3><p>Dataset names identify declared resources; they are not a row sample. Logs and validation outputs are unknown unless explicitly provided as authorized evidence. Ask the owner where those records are retained. Do not infer a retry or recovery action from a diagram.</p></div></div></section>',
           '<section id="changes"><p class="eyebrow">08 / Change awareness</p><h2>Impact, snapshots & freshness</h2><p>Use the CLI <code>impact</code> command to traverse supported downstream data or control relationships. Inspect each edge\'s evidence before interpreting the result. Use <code>diff</code> between stored snapshots to see added, removed and changed facts. Run <code>status --config &lt;reviewed-config.json&gt;</code> to recheck source hashes, registry and configuration against the latest snapshot. A saved page does not poll sources. Missing visibility can make impact or freshness checks incomplete.</p>',
           f'<p>Semantic snapshot: <code class="wrap">{_h(snapshot.get("snapshot_id", "unknown"))}</code><br>Registry fingerprint: <code class="wrap">{_h(snapshot.get("registry_fingerprint", "unknown"))}</code></p>',
           '<h3>Supported downstream data impact</h3><p class="muted">Reachability through extracted data-flow edges only. Inspect the flow tables for evidence; a blank result does not prove no impact.</p>',
           _table(["Environment", "Service", "Changed dataset", "Reachable downstream datasets"], [tuple(_h(v) for v in row) for row in _impact_rows(snapshot)]),
           '<details><summary>Effective scan configuration and recorded metrics</summary><pre>' + _h({"effective_config": snapshot.get("effective_config", {}), "metrics": snapshot.get("metrics", {})}) + '</pre></details></section>',
           '<section id="coverage"><p class="eyebrow">09 / Limits</p><h2>Coverage gaps, conflicts & human questions</h2><p>Permission errors, ambiguous technology, unsupported constructs and unresolved references limit this view. Missing visibility does not establish absence.</p>',
           _table(["Finding", "Severity", "Explanation / next input", "Evidence"], [(_h(i.get("code")), _h(i.get("severity", "warning")), _h(i.get("message")), _refs(i)) for i in issues]),
           '<h3>Questions for the responsible owner</h3><ul><li>Which environment and service does each unresolved connection target?</li><li>Can reviewed purpose, ownership, SLAs and terminology be provided?</li><li>Which authorized export would resolve each unsupported or dynamic reference?</li><li>Where are the time-bound run records, logs and validation reports?</li></ul></section>',
           '<section id="capabilities"><p class="eyebrow">10 / Tested scope</p><h2>Technology support matrix</h2><p>A detector is not an analyzer. Each capability is bounded by its rule/adapter declaration and tested fixtures. Expand a technology for exact limitations and test references. See the repository capability guide for the manually tested subset.</p>' + _capability_html(snapshot) + '</section>',
           '<section id="annotations"><p class="eyebrow">11 / Reviewed interpretation</p><h2>Human context</h2><p>Annotations come from the separate reviewed annotation file and survive regeneration. They are business interpretation, separate from parser observations.</p>',
           _table(["Asset", "Purpose / owner / SLA", "Review"], [(_h(a.get("node_id")), _h({k: a.get(k) for k in ("purpose", "owner", "sla") if k in a}), _h(a.get("reviewed_by", "unknown")) + " · " + _h(a.get("reviewed_at", "unknown"))) for a in snapshot.get("annotations", [])]), '</section>',
           '<section id="glossary"><p class="eyebrow">12 / Vocabulary</p><h2>Glossary</h2>', _table(["Term", "Meaning"], [("Artifact", "A file inventoried inside an authorized source scope."), ("Declared", "Present in a static definition or configuration; not proof of execution."), ("Observed", "Captured through explicit time-bound runtime or metadata evidence."), ("Inferred", "Derived from a supported rule; not directly observed."), ("Unknown", "Insufficient evidence or unsupported analysis."), ("Data flow", "A supported upstream-to-downstream data dependency."), ("Control flow", "A technology-specific dependency or condition between tasks."), ("Evidence", "Sanitized source location, source hash and parser/rule provenance."), ("Namespace", "Environment-aware service/source context used to prevent identity collisions.")]), '</section>',
           '<section id="evidence"><p class="eyebrow">13 / Provenance</p><h2>Evidence index</h2><p>Source text is intentionally absent. Locate the authorized original through the relative location, then verify its hash and parser/rule version.</p>']
    for e in snapshot.get("evidence", []):
        pointer = ' <code>' + _h(_object_pointer(e)) + '</code>' if _object_pointer(e) is not None else ""
        out.append(f'<details class="asset evidence" id="{_anchor(e["id"])}"><summary>{_h(e.get("location", "unknown"))}{pointer} · E{_h(str(e["id"])[-6:])}</summary><pre>' + _h(json.dumps(e, indent=2, ensure_ascii=False)) + '</pre></details>')
    out.append('</section><footer>Pipeline Handbook · local MVP · registered static analysis · no vendor runtime or paid API required.</footer></main></body></html>')
    return "\n".join(out)


def _markdown(snapshot):
    nodes = snapshot.get("nodes", [])
    out = [f'# Pipeline Handbook · {_md(snapshot.get("project", "project"))}', "", "## Start Here", "", _freshness(snapshot), "", "1. Check technology and environment inventory.\n2. Choose an output in the asset dictionary and trace upstream data flow.\n3. Open the evidence locations to find the responsible code or job.\n4. Read control-flow conditions and coverage findings before drawing operational conclusions.", "", "Static definitions do not prove successful execution. Business meaning, ownership and safe recovery procedures require reviewed evidence.", "", "## Technology and environment inventory", "", _markdown_table(["Technology", "Family", "Environment", "Category", "Confidence", "Versions", "Client versions", "Export declared at", "Support", "Analysis", "Selected", "Reasons / conflicts", "Evidence IDs"], [(d.get("technology"), d.get("family"), d.get("environment"), d.get("category"), d.get("confidence"), d.get("versions", []) or "unknown", d.get("client_versions", []) or "unknown", d.get("source_exported_at", "unknown"), d.get("support"), d.get("analysis_status", "unknown"), d.get("selected"), {"reasons": d.get("reasons"), "conflicts": d.get("conflicts")}, _evidence_ids(d)) for d in snapshot.get("detections", [])]), "", "## Pipeline catalogue", ""]
    for n in nodes:
        if n.get("kind") not in ("pipeline", "task", "schedule"):
            continue
        out += [f'<a id="{_anchor(n["id"])}"></a>', f'### {_md(n.get("name"))}', "", f'Kind: {_md(n.get("kind"))}; environment: {_md(n.get("environment"))}; namespace: {_md(n.get("namespace"))}; status: {_md(n.get("status"))}.', "", _md(n.get("explanation", "Declared definition; purpose requires review.")), "", _md(n.get("attributes", {})), "", "Evidence: " + _refs(n, False), ""]
    out += ["## Data-flow diagram", "", "Arrows point upstream to downstream. Supported data dependencies do not establish execution order.", "", _flow_markdown(snapshot, "data"), "", "## Control-flow diagram", "", "Task dependencies, invocation and schedule are separate from data movement. Conditions appear in the relationship tables.", "", _flow_markdown(snapshot, "control"), "", "## Asset dictionary and column mappings", ""]
    for n in nodes:
        if n.get("kind") in ("pipeline", "task", "schedule"):
            continue
        out += [f'<a id="{_anchor(n["id"])}"></a>', f'### {_md(n.get("name"))}', "", f'Kind: {_md(n.get("kind"))}; environment: {_md(n.get("environment"))}; namespace: {_md(n.get("namespace"))}; status: {_md(n.get("status"))}.', "", _md(n.get("attributes", {})), "", "Evidence: " + _refs(n, False), ""]
    names = {n["id"]: n.get("name", n["id"]) for n in nodes}
    out += [_markdown_table(["Source column", "Target column", "Mapping", "Evidence IDs"], [(names.get(e.get("source"), "unknown"), names.get(e.get("target"), "unknown"), e.get("attributes", {}), _evidence_ids(e)) for e in snapshot.get("edges", []) if e.get("kind") == "column_lineage"]), "", "## Where to check", "", "Open each relative source location in an editor and compare its SHA-256 hash with this snapshot. Dataset names identify declared resources; no business rows were sampled. Logs, validation outputs and actual run success are unknown unless explicitly provided as authorized evidence.", "", _markdown_table(["Source", "Environment", "Path", "Size", "SHA-256"], [(a.get("source_id"), a.get("environment"), a.get("path"), a.get("size"), a.get("hash")) for a in snapshot.get("artifacts", [])]), "", "### Initial read-only troubleshooting", "", "1. Confirm the environment, service and collection time.\n2. Locate and inspect the definition at its evidence location.\n3. Review unresolved parameters, dynamic references and permission gaps.\n4. Request an authorized metadata/run export to answer runtime questions.\n5. Obtain owner-reviewed recovery instructions before changing a workflow.", "", "## Impact, snapshot changes and freshness", "", f'Semantic snapshot: `{_md(snapshot.get("snapshot_id"))}`. Registry fingerprint: `{_md(snapshot.get("registry_fingerprint"))}`.', "", "Use `impact` to traverse supported relationships and `diff` to compare stored snapshots. A saved handbook cannot poll source files. Run `status --config <config.json>` to check for stale definitions; `document` rescans before generation. Missing graph visibility limits impact results.", "", "## Coverage gaps, conflicts and human questions", "", _markdown_table(["Code", "Severity", "Explanation / next input", "Evidence IDs"], [(i.get("code"), i.get("severity"), i.get("message"), _evidence_ids(i)) for i in snapshot.get("issues", [])]), "", "Questions: Who owns each pipeline? Which reviewed business purpose and SLA apply? Which environment/service does each unresolved connection target? Where are time-bound logs, validation reports and run exports?", "", "## Capability declarations", "", "These declarations are limited to the stated adapters and tested fixtures. Detection alone does not imply parsing, lineage, deployment or execution.", "", "```json", json.dumps(snapshot.get("capabilities", []), indent=2, ensure_ascii=False), "```", "", "## Reviewed annotations", "", _markdown_table(["Asset", "Purpose", "Owner", "SLA", "Reviewed by", "Reviewed at"], [(a.get("node_id"), a.get("purpose"), a.get("owner"), a.get("sla"), a.get("reviewed_by"), a.get("reviewed_at")) for a in snapshot.get("annotations", [])]), "", "## Glossary", "", "- **Declared:** present in a static definition; execution is unproven.\n- **Observed:** captured through authorized time-bound evidence.\n- **Inferred:** derived through a supported rule.\n- **Unknown:** missing evidence or unsupported analysis.\n- **Data flow:** supported upstream-to-downstream data dependency.\n- **Control flow:** technology-specific task order/conditions.\n- **Evidence:** sanitized source location, hash and parser/rule provenance.", "", "## Evidence index", ""]
    for e in snapshot.get("evidence", []):
        pointer = " · " + _md(_object_pointer(e)) if _object_pointer(e) is not None else ""
        out += [f'<a id="{_anchor(e["id"])}"></a>', f'### E{str(e["id"])[-6:]} · {_md(e.get("location"))}{pointer}', "", "```json", json.dumps(e, indent=2, ensure_ascii=False), "```", ""]
    out += ["## Effective configuration and metrics", "", "```json", json.dumps({"effective_config": snapshot.get("effective_config", {}), "metrics": snapshot.get("metrics", {})}, indent=2, ensure_ascii=False), "```", ""]
    if isinstance(snapshot.get("architecture"), dict):
        insertion = out.index("## Technology and environment inventory")
        out[insertion:insertion] = [_architecture_markdown(snapshot), ""]
    return "\n".join(out)


def document(snapshot, output_dir, formats=None):
    """Render a sanitized canonical snapshot; return paths to requested artifacts."""
    formats = list(formats if formats is not None else ["markdown", "html", "json"])
    if any(f not in {"markdown", "html", "json"} for f in formats):
        raise ValueError("Output formats must be markdown, html or json")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    writers = {"html": ("index.html", _html), "markdown": ("handbook.md", _markdown), "json": ("handbook.json", lambda x: json.dumps(x, indent=2, ensure_ascii=False, sort_keys=True) + "\n")}
    result = {}
    for fmt in formats:
        filename, render = writers[fmt]
        target = output_dir / filename
        if target.is_symlink():
            raise ValueError("Output artifact must not be a symlink")
        # Replace atomically: a previously saved page is never left truncated.
        fd, temporary = tempfile.mkstemp(prefix=".handbook-render-", dir=output_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(render(snapshot))
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        result[fmt] = str(target)
    return result


generate = document
