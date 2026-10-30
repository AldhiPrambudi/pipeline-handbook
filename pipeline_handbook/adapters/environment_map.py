"""Vendor-neutral, explicitly supplied environment declarations, format v1.

This is not a vendor report parser or runtime probe. Exact selectors can request
relationships only between assets independently extracted in authorized scopes.
"""

from collections import Counter
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

from ..security import parse_json_text, redact

VERSION = "1.0.0"
FORMAT = "pipeline-handbook.environment/v1"
_KINDS = {"component", "deployment_resource", "report", "pipeline", "task", "dataset", "column", "schedule", "run", "source_system"}
_LINK_KINDS = {"invocation", "deployment", "connection", "data_flow"}
_SELECTOR_FIELDS = {"kind", "name", "environment", "namespace", "source_id", "artifact_path"}
_COMPONENT_FIELDS = {"name", "technology", "role", "boundary", "location", "inspection_points", "resource_type"}
_REPORT_FIELDS = {"name", "report_type", "technology", "inspection_points"}
_ATTRIBUTE_STRINGS = {"relation", "condition", "protocol", "database", "schema", "binding", "note"}


def _pointer(*parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _text(value, maximum=2048):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(
        char in value for char in ("\x00", "\n", "\r", "$", "`", "{{", "}}"))


def _location(value):
    if not _text(value) or re.match(r"\s*(?:javascript|data|vbscript):", value, re.I):
        raise ValueError("unsafe or dynamic location")
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credential-bearing location")
    # Metadata locations are descriptive only. Remove query/fragment payloads
    # that look sensitive; no discovered URI is opened or made executable.
    return redact(value)


def _inspection_points(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("inspection points must be a bounded list")
    result = []
    for point in value:
        if not isinstance(point, dict) or set(point) != {"kind", "location"} or not _text(point["kind"], 64) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", point["kind"]):
            raise ValueError("inspection point has unsupported fields/type")
        result.append({"kind": point["kind"], "location": _location(point["location"])})
    return result


def _selector(value):
    if not isinstance(value, dict) or set(value) != _SELECTOR_FIELDS:
        raise ValueError("exact selector requires six identity/scope fields")
    if any(not _text(value[field], 1024) for field in _SELECTOR_FIELDS) or value["kind"] not in _KINDS:
        raise ValueError("selector identity is malformed or dynamic")
    path = value["artifact_path"]
    parts = PurePosixPath(path)
    if parts.is_absolute() or path in {".", ""} or ".." in parts.parts or any(char in path for char in ("\\", "*", "?", "[", "]")) or ":" in path or path != parts.as_posix():
        raise ValueError("selector artifact path is not a literal relative POSIX path")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value["source_id"]):
        raise ValueError("selector source ID is invalid")
    return dict(value)


def _attributes(value):
    allowed = _ATTRIBUTE_STRINGS | {"port", "required", "read_only", "parameter_names"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("link attributes contain unsupported/literal-body fields")
    result = {}
    for key, item in value.items():
        if key in _ATTRIBUTE_STRINGS:
            if not _text(item):
                raise ValueError("link metadata strings must be static and bounded")
            result[key] = redact(item)
        elif key in {"required", "read_only"}:
            if not isinstance(item, bool):
                raise ValueError("link metadata flags must be booleans")
            result[key] = item
        elif key == "port":
            if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 65535:
                raise ValueError("link port must be a bounded integer")
            result[key] = item
        else:
            if not isinstance(item, list) or len(item) > 100 or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) for name in item):
                raise ValueError("parameter_names must contain names without literal values")
            result[key] = item
    return result


def _node(record, kind):
    allowed = _REPORT_FIELDS if kind == "report" else _COMPONENT_FIELDS
    if not isinstance(record, dict) or "name" not in record or set(record) - allowed or not _text(record["name"], 1024):
        raise ValueError("component/report fields or stable name are invalid")
    attrs = {"definition_only": True, "declaration_format": FORMAT,
        "runtime_state": "unknown", "semantics": "supplied metadata declaration; not independently observed"}
    if kind == "report":
        report_type = record.get("report_type", "report")
        if report_type not in {"report", "dashboard", "form"}:
            raise ValueError("unsupported report type")
        attrs["report_type"] = report_type
    else:
        resource_type = record.get("resource_type", "component")
        if resource_type not in {"component", "deployment_resource"}:
            raise ValueError("unsupported component resource type")
        kind = resource_type
        attrs["resource_type"] = resource_type
    for field in ("technology", "role", "boundary"):
        if field in record:
            if not _text(record[field], 1024):
                raise ValueError("component metadata must be static text")
            attrs[field] = redact(record[field])
    if "location" in record:
        attrs["location"] = _location(record["location"])
    if "inspection_points" in record:
        attrs["inspection_points"] = _inspection_points(record["inspection_points"])
    return kind, record["name"], attrs


def analyze(artifact, ctx):
    try:
        data = parse_json_text(artifact["text"])
    except (ValueError, RecursionError):
        ctx.issue("environment_map_json_invalid", "Environment map is not unambiguous JSON; provide a reviewed v1 export.", object_path="")
        return
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        ctx.issue("environment_map_version_unsupported", "Only pipeline-handbook.environment/v1 is supported; other formats/versions remain unparsed declarations.", object_path="/format")
        return
    if set(data) - {"format", "components", "links", "reports"} or not isinstance(data.get("components"), list) or not isinstance(data.get("links"), list) or "reports" in data and not isinstance(data["reports"], list):
        ctx.issue("environment_map_schema_invalid", "Map requires components/links arrays and only documented top-level fields; malformed input was not partially guessed.", object_path="")
        return
    for collection, kind in (("components", "component"), ("reports", "report")):
        values = data.get(collection, [])
        identities = Counter((record.get("resource_type", "component") if kind == "component" else "report", record.get("name"))
            for record in values if isinstance(record, dict) and isinstance(record.get("name"), str) and isinstance(record.get("resource_type", "component"), str))
        for index, record in enumerate(values):
            pointer = _pointer(collection, index)
            try:
                node_kind, name, attrs = _node(record, kind)
                if identities[(node_kind, name)] > 1:
                    ctx.issue("environment_map_duplicate_identity", "Multiple declarations share one identity inside this map; all conflicting local declarations remain unmapped.", object_path=pointer)
                    continue
            except (ValueError, TypeError):
                ctx.issue("environment_map_record_invalid", "Component/report contains malformed, unknown, sensitive-reference or unsupported fields; this local declaration was not guessed.", object_path=pointer)
                continue
            ctx.node(node_kind, name, attrs, object_path=pointer)
    for index, record in enumerate(data["links"]):
        pointer = _pointer("links", index)
        try:
            if not isinstance(record, dict) or not {"source", "target", "kind"} <= set(record) or set(record) - {"source", "target", "kind", "attributes"} or not isinstance(record["kind"], str) or record["kind"] not in _LINK_KINDS:
                raise ValueError("link shape/kind invalid")
            source, target = _selector(record["source"]), _selector(record["target"])
            attrs = _attributes(record.get("attributes", {}))
        except (ValueError, TypeError):
            ctx.issue("environment_map_link_invalid", "Link requires exact safe six-field selectors, a supported relationship and constrained factual attributes; no relationship was guessed.", object_path=pointer)
            continue
        attrs["declaration_format"] = FORMAT
        attrs["semantics"] = "supplied explicit relationship assertion; resolution requires independently extracted endpoints, and no execution or communication is observed"
        ctx.link(source, target, record["kind"], attrs, object_path=pointer)
