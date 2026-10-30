"""SDK v1 canonical model. Evidence is attached at creation, never retrofitted."""
from __future__ import annotations

import math
from pathlib import PurePosixPath
import re

from .security import redact, stable_id

NODE_KINDS = {"pipeline", "task", "dataset", "column", "schedule", "run", "source_system", "component", "deployment_resource", "report"}
EDGE_KINDS = {"data_flow", "control_flow", "contains", "invocation", "schedule", "column_lineage", "deployment", "connection"}
STATUSES = {"declared", "observed", "inferred", "unknown"}


def _string(value, label, maximum=4096):
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError("invalid SDK " + label)


def _json_value(value, remaining, depth=0):
    """Validate a bounded JSON tree, including mutations outside SDK methods."""
    if depth > 24:
        raise ValueError("adapter result nesting budget exceeded")
    remaining[0] -= 8
    if isinstance(value, str):
        remaining[0] -= len(value.encode("utf-8"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("adapter JSON object keys must be strings")
            remaining[0] -= len(key.encode("utf-8"))
            _json_value(item, remaining, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_value(item, remaining, depth + 1)
    elif value is None or isinstance(value, bool):
        pass
    elif isinstance(value, int):
        if value.bit_length() > 1024:
            raise ValueError("adapter integer exceeds bounds")
    elif not isinstance(value, float) or not math.isfinite(value):
        raise ValueError("adapter values must be finite JSON data")
    if remaining[0] < 0:
        raise ValueError("adapter result size budget exceeded")


def _attributes(value):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("SDK attributes must be a JSON object")
    if "columns" in value and (not isinstance(value["columns"], list) or any(not isinstance(col, str) or not col for col in value["columns"])):
        raise ValueError("SDK columns must be a list of nonempty strings")
    if "entrypoint" in value and not isinstance(value["entrypoint"], bool):
        raise ValueError("SDK entrypoint must be boolean")
    return value


def _object_pointer(value):
    if value is not None and (not isinstance(value, str) or value and not value.startswith("/") or len(value) > 4096
            or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value)
            or re.search(r"~(?![01])", value)):
        raise ValueError("SDK object_path must be a bounded JSON pointer")


def _selector(value, resolved=False):
    required = {"kind", "name", "environment", "namespace", "source_id", "artifact_path"}
    if resolved:
        required.add("node_id")
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("semantic selector requires exact environment, namespace and artifact identity")
    for key, item in value.items():
        _string(item, "selector " + key, 10000)
    if value["kind"] not in NODE_KINDS:
        raise ValueError("unsupported semantic selector kind")
    path = PurePosixPath(value["artifact_path"])
    if path.is_absolute() or ".." in path.parts or "\\" in value["artifact_path"] or "$" in value["artifact_path"] or "{{" in value["artifact_path"]:
        raise ValueError("selector artifact path must be static and scope-relative")
    return value


def validate_result(result, config, artifact, known_nodes=None, known_evidence=None):
    """Validate a complete worker graph before the engine mutates shared state.

    Explicit trust authorizes adapter code; it does not make malformed output
    infallible. Cross-artifact edges may reference already-known identities.
    """
    expected = {"nodes", "edges", "evidence", "issues", "references"}
    if not isinstance(result, dict) or not expected <= set(result) or not set(result) <= expected | {"links"}:
        raise ValueError("adapter result has invalid collections")
    limit = config["budgets"]["max_nodes_per_adapter"]
    limits = {"nodes": limit, "edges": limit * 8, "evidence": limit * 12 + 100,
              "issues": limit, "references": limit, "links": limit}
    for key in result:
        if not isinstance(result[key], list) or len(result[key]) > limits[key]:
            raise ValueError("adapter result collection budget/type violation")
    _json_value(result, [max(1_000_000, config["budgets"].get("max_file_bytes", 1_000_000) * 32)])
    known_nodes = known_nodes or {}
    known_evidence = known_evidence or {}
    evidence_ids = set(known_evidence)
    result_evidence = set()

    def fields(item, required, optional=()):
        if not isinstance(item, dict) or not set(required) <= set(item) or not set(item) <= set(required) | set(optional):
            raise ValueError("adapter record has invalid fields")

    def references(ids):
        if not isinstance(ids, list) or not ids or any(not isinstance(eid, str) or eid not in evidence_ids for eid in ids):
            raise ValueError("adapter record has unresolved provenance")

    evidence_fields = {"id", "artifact_id", "location", "source_hash", "adapter", "adapter_version", "rule_id", "rule_version", "collected_at", "reason", "status"}
    for item in result["evidence"]:
        fields(item, evidence_fields, {"object_path"})
        _object_pointer(item.get("object_path"))
        for key in evidence_fields - {"source_hash"}:
            _string(item[key], "evidence " + key, 10000)
        if item["id"] in result_evidence or item["artifact_id"] != artifact["id"] or item["status"] not in STATUSES:
            raise ValueError("adapter evidence identity/status violation")
        if item["source_hash"] != artifact["hash"]:
            raise ValueError("adapter evidence has incorrect source hash")
        if item["id"] in known_evidence and item != known_evidence[item["id"]]:
            raise ValueError("adapter evidence conflicts with existing provenance")
        result_evidence.add(item["id"])
    evidence_ids.update(result_evidence)
    node_ids = set(known_nodes)
    result_nodes = set()
    node_fields = {"id", "kind", "name", "environment", "namespace", "technology", "status", "attributes", "rule_concepts", "evidence", "explanation"}
    for item in result["nodes"]:
        fields(item, node_fields)
        for key in ("id", "kind", "name", "environment", "namespace", "technology", "status", "explanation"):
            _string(item[key], "node " + key, 10000)
        if item["id"] in result_nodes or item["kind"] not in NODE_KINDS or item["status"] not in STATUSES or item["environment"] != artifact["environment"]:
            raise ValueError("adapter node identity/status violation")
        if not isinstance(item["rule_concepts"], list) or any(not isinstance(value, str) for value in item["rule_concepts"]):
            raise ValueError("adapter rule concepts must be strings")
        _attributes(item["attributes"])
        references(item["evidence"])
        if item["id"] in known_nodes and any(item[key] != known_nodes[item["id"]][key] for key in ("kind", "name", "environment", "namespace")):
            raise ValueError("adapter attempted to replace an existing identity")
        result_nodes.add(item["id"])
    node_ids.update(result_nodes)
    for item in result["nodes"]:
        if item["kind"] == "column" and item["attributes"].get("dataset") not in node_ids:
            raise ValueError("adapter column has no known dataset")
    result_edges = set()
    for item in result["edges"]:
        fields(item, {"id", "source", "target", "kind", "status", "attributes", "evidence"})
        for key in ("id", "source", "target", "kind", "status"):
            _string(item[key], "edge " + key)
        if item["id"] in result_edges or item["kind"] not in EDGE_KINDS or item["status"] not in STATUSES or item["source"] not in node_ids or item["target"] not in node_ids:
            raise ValueError("adapter relationship has invalid identity/endpoints/status")
        _attributes(item["attributes"])
        if item["id"] != stable_id("edge", item["source"], item["target"], item["kind"], item["attributes"]):
            raise ValueError("adapter relationship ID does not match its facts")
        if "via" in item["attributes"] and (not isinstance(item["attributes"]["via"], str) or item["attributes"]["via"] not in node_ids):
            raise ValueError("adapter relationship has no known transformation")
        references(item["evidence"])
        result_edges.add(item["id"])
    for item in result["issues"]:
        fields(item, {"code", "message", "severity", "artifact_id", "evidence"})
        for key in ("code", "message", "severity", "artifact_id"):
            _string(item[key], "issue " + key, 10000)
        if item["artifact_id"] != artifact["id"] or item["severity"] not in {"info", "warning", "error"}:
            raise ValueError("adapter issue has invalid source/severity")
        references(item["evidence"])
    for item in result["references"]:
        fields(item, {"from_id", "target_path", "kind", "attributes", "artifact_id", "source_id", "base_path", "evidence"})
        for key in ("from_id", "target_path", "kind", "artifact_id", "source_id", "base_path"):
            _string(item[key], "reference " + key, 10000)
        if item["from_id"] not in node_ids or item["kind"] not in EDGE_KINDS or item["artifact_id"] != artifact["id"] or item["source_id"] != redact(artifact["source_id"]) or item["base_path"] != redact(artifact["path"]):
            raise ValueError("adapter artifact reference has invalid scope/identity")
        _attributes(item["attributes"])
        references(item["evidence"])

    for item in result.get("links", []):
        fields(item, {"id", "source_selector", "target_selector", "kind", "attributes", "artifact_id", "evidence"})
        _string(item["id"], "semantic link ID")
        _selector(item["source_selector"], resolved=True)
        _selector(item["target_selector"], resolved=True)
        _attributes(item["attributes"])
        if item["kind"] not in EDGE_KINDS or item["artifact_id"] != artifact["id"]:
            raise ValueError("invalid semantic link source/kind")
        references(item["evidence"])


class Context:
    def __init__(self, artifact, technology, config, adapter, rule, collected_at):
        self.artifact = artifact
        self.technology = technology
        self.config = config
        self.overrides = config["technologies"]["overrides"].get(technology, {})
        self.adapter = adapter
        self.rule = rule
        self.collected_at = collected_at
        self.nodes = {}
        self.edges = {}
        self.evidences = {}
        self.issues = []
        self.references = []
        self.links = []

    def evidence(self, line=1, reason="definition", status="declared", object_path=None):
        if status not in STATUSES:
            raise ValueError("invalid evidence status")
        line = max(1, int(line))
        _object_pointer(object_path)
        record = redact({
            "artifact_id": self.artifact["id"],
            "location": f'{self.artifact["source_id"]}/{self.artifact["path"]}:L{line}',
            "source_hash": self.artifact["hash"], "adapter": self.adapter["id"],
            "adapter_version": self.adapter["version"], "rule_id": self.rule["id"],
            "rule_version": self.rule["version"], "reason": reason, "status": status,
        })
        if object_path is not None:
            record["object_path"] = redact(object_path)
        eid = stable_id("evidence", record)
        if eid not in self.evidences and len(self.evidences) >= self.config["budgets"]["max_nodes_per_adapter"] * 12 + 100:
            raise ValueError("adapter evidence budget exceeded")
        self.evidences[eid] = {"id": eid, **record, "collected_at": self.collected_at}
        return eid

    def node(self, kind, name, attributes=None, status="declared", line=1, namespace=None, object_path=None):
        if kind not in NODE_KINDS or status not in STATUSES:
            raise ValueError("invalid node kind/status")
        namespace = namespace or (self.artifact["service"] if kind in {"dataset", "column"} else self.artifact["source_id"])
        _string(name, "node name", 10000)
        _string(namespace, "namespace", 10000)
        # Hash the full identity; redact only its published display. Redacting
        # first would merge different credential/email-bearing names.
        nid = stable_id(kind, self.artifact["environment"], namespace, name)
        name, namespace = redact(name), redact(namespace)
        if nid not in self.nodes and len(self.nodes) >= self.config["budgets"]["max_nodes_per_adapter"]:
            raise ValueError("adapter node budget exceeded")
        eid = self.evidence(line, f"{kind} definition: {name}", status, object_path=object_path)
        attrs = redact(_attributes({} if attributes is None else attributes))
        for original, normalized in self.rule.get("mapping", {}).get("attribute_aliases", {}).items():
            if normalized in {"entrypoint", "dataset", "via", "id", "source", "target"}:
                raise ValueError("rule cannot alias a reserved identity/relationship attribute")
            if original in attrs and normalized not in attrs:
                attrs[normalized] = attrs[original]
        _attributes(attrs)
        prior = self.nodes.get(nid)
        if prior:
            if "columns" in attrs:
                attrs["columns"] = sorted(set(prior["attributes"].get("columns", []) + attrs["columns"]))
            prior["attributes"].update(attrs)
            prior["evidence"] = sorted(set(prior["evidence"] + [eid]))
            return nid
        template = self.rule.get("mapping", {}).get("explanation", "{name} is a declared {kind}; execution is unverified.")
        explanation = template.replace("{name}", name).replace("{kind}", kind).replace("{technology}", self.technology)
        self.nodes[nid] = {"id": nid, "kind": kind, "name": name,
                           "environment": self.artifact["environment"], "namespace": namespace,
                           "technology": self.technology, "status": status, "attributes": attrs,
                           "rule_concepts": [self.rule.get("mapping", {}).get("concept", self.technology)],
                           "evidence": [eid], "explanation": redact(explanation)}
        return nid

    def dataset(self, name, columns=None, line=1):
        _attributes({"columns": [] if columns is None else columns})
        nid = self.node("dataset", name, {"columns": columns or []}, line=line)
        for column in columns or []:
            cid = self.node("column", f"{name}.{column}", {"dataset": nid}, line=line)
            self.edge(nid, cid, "contains", line=line)
        return nid

    def edge(self, source, target, kind, attributes=None, status="declared", line=1, object_path=None):
        if kind not in EDGE_KINDS or status not in STATUSES:
            raise ValueError("invalid edge kind/status")
        if len(self.edges) >= self.config["budgets"]["max_nodes_per_adapter"] * 8:
            raise ValueError("adapter relationship budget exceeded")
        _string(source, "edge source")
        _string(target, "edge target")
        attributes = redact(_attributes({} if attributes is None else attributes))
        eid = self.evidence(line, f"{kind} relationship", status, object_path=object_path)
        edge_id = stable_id("edge", source, target, kind, attributes)
        existing = self.edges.get(edge_id)
        if existing:
            existing["evidence"] = sorted(set(existing["evidence"] + [eid]))
        else:
            self.edges[edge_id] = {"id": edge_id, "source": source, "target": target,
                                   "kind": kind, "status": status, "attributes": attributes, "evidence": [eid]}
        return edge_id

    def issue(self, code, message, line=1, severity="warning", object_path=None):
        _string(code, "issue code")
        _string(message, "issue message", 10000)
        if severity not in {"info", "warning", "error"} or len(self.issues) >= self.config["budgets"]["max_nodes_per_adapter"]:
            raise ValueError("invalid SDK issue severity/budget")
        self.issues.append(redact({"code": code, "message": message, "severity": severity,
                                   "artifact_id": self.artifact["id"],
                                   "evidence": [self.evidence(line, "coverage limit", "unknown", object_path=object_path)]}))

    def reference(self, from_id, target_path, kind="invocation", attributes=None, line=1):
        _string(from_id, "reference source")
        _string(target_path, "reference path", 10000)
        _attributes({} if attributes is None else attributes)
        if kind not in EDGE_KINDS or len(self.references) >= self.config["budgets"]["max_nodes_per_adapter"]:
            raise ValueError("invalid SDK reference kind/budget")
        self.references.append(redact({"from_id": from_id, "target_path": target_path,
            "kind": kind, "attributes": attributes or {}, "artifact_id": self.artifact["id"],
            "source_id": self.artifact["source_id"], "base_path": self.artifact["path"],
            "evidence": [self.evidence(line, "static artifact reference")]}))

    def result(self):
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values()),
                "evidence": list(self.evidences.values()), "issues": self.issues, "references": self.references, "links": self.links}

    def link(self, source_selector, target_selector, kind, attributes=None, line=1, object_path=None):
        if kind not in EDGE_KINDS or len(self.links) >= self.config["budgets"]["max_nodes_per_adapter"]:
            raise ValueError("invalid semantic link kind/budget")
        selectors = []
        for selector in (source_selector, target_selector):
            _selector(selector)
            # Preserve exact identity before display redaction, just as node().
            node_id = stable_id(selector["kind"], selector["environment"], selector["namespace"], selector["name"])
            selectors.append(redact({**selector, "node_id": node_id}))
        attrs = redact(_attributes({} if attributes is None else attributes))
        eid = self.evidence(line, "explicit semantic binding declaration", object_path=object_path)
        self.links.append({"id": stable_id("link", self.artifact["id"], *selectors, kind, attrs, object_path),
            "source_selector": selectors[0], "target_selector": selectors[1], "kind": kind,
            "attributes": attrs, "artifact_id": self.artifact["id"], "evidence": [eid]})
