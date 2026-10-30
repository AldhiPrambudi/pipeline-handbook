"""Structural candidate recognition; no target imports or dynamic evaluation."""
from __future__ import annotations

import ast
import json
import re
import time
import xml.etree.ElementTree as ET

DOC_FORMATS = {"md", "rst", "txt"}


def field(value, path):
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class Parsed:
    def __init__(self, artifact):
        self.artifact = artifact
        self.text = artifact["text"]
        self.lower = self.text.lower()
        self._cache = {}

    def get(self, kind):
        if kind in self._cache:
            return self._cache[kind]
        value = None
        try:
            if kind == "json":
                value = json.loads(self.text)
            elif kind == "python":
                value = ast.parse(self.text)
            elif kind == "xml" and "<!DOCTYPE" not in self.text.upper() and "<!ENTITY" not in self.text.upper():
                value = ET.fromstring(self.text)
        except (ValueError, SyntaxError, ET.ParseError, RecursionError, MemoryError):
            pass
        self._cache[kind] = value
        return value

    def signal(self, signal):
        kind, values = signal["kind"], signal.get("values", [])
        version, version_kind = None, signal.get("version_kind", "unknown")
        line = 1
        match = False
        if kind == "contains_all":
            match = bool(values) and all(v.lower() in self.lower for v in values)
            if match:
                line = self.lower[:self.lower.index(values[0].lower())].count("\n") + 1
        elif kind == "python_import":
            tree = self.get("python")
            imports = []
            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend((alias.name, node.lineno) for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append((node.module, node.lineno))
            hits = [(name, loc) for name, loc in imports if any(name == v or name.startswith(v + ".") for v in values)]
            match = bool(hits)
            if hits:
                line = hits[0][1]
        elif kind == "json_fields":
            data = self.get("json")
            predicates = signal.get("fields", {})
            def check(actual, expected):
                return (isinstance(actual, dict) if expected == "$object" else
                        isinstance(actual, list) if expected == "$array" else
                        actual is not None if expected == "$present" else actual == expected)
            match = bool(predicates) and data is not None and all(check(field(data, path), expected) for path, expected in predicates.items())
            if match and signal.get("version_field"):
                found = field(data, signal["version_field"])
                if isinstance(found, (str, int, float)):
                    version = str(found)
        elif kind == "xml_structure":
            root = self.get("xml")
            match = bool(values) and root is not None and root.tag == values[0] and all(root.find(path) is not None for path in values[1:])
        elif kind == "shell":
            lines = self.text.splitlines()
            match = bool(lines) and bool(re.fullmatch(r"#!\s*(?:/usr/bin/env\s+|/bin/|/usr/bin/)(?:ba|da|k|z)?sh(?:\s+-[a-zA-Z]+)?\s*", lines[0]))
        elif kind == "cron":
            for number, text in enumerate(self.text.splitlines(), 1):
                if re.match(r"^(?:[\d*/,-]+\s+){5}(?:[^#\s].*)$", text.strip()):
                    match, line = True, number
                    break
        elif kind == "dependency":
            for number, text in enumerate(self.text.splitlines(), 1):
                for package in values:
                    found = re.fullmatch(re.escape(package) + r"(?:\[[A-Za-z0-9_,.-]+\])?\s*(?:==|~=|>=|<=|>|<)?\s*([\d][A-Za-z0-9.*+_-]*)?\s*(?:#.*)?", text.strip(), re.I)
                    if found:
                        match, line, version = True, number, found[1]
        elif kind == "docker_from":
            for number, text in enumerate(self.text.splitlines(), 1):
                found = re.match(r"\s*FROM\s+([A-Za-z0-9_./-]+)(?::([A-Za-z0-9_.-]+))?(?:\s+AS\s+\w+)?\s*$", text, re.I)
                if found and (not values or found[1].split("/")[-1].lower() in [v.lower() for v in values]):
                    # FROM tags identify the named image/product, not Docker's
                    # engine/CLI version. Only a product-specific signal with a
                    # stated version kind may publish the tag as that version.
                    match, line = True, number
                    version = found[2] if version_kind != "unknown" else None
        elif kind == "compose_image":
            data = self.get("json")
            services = data.get("services") if isinstance(data, dict) else None
            if isinstance(services, dict):
                for service in services.values():
                    image = service.get("image") if isinstance(service, dict) else None
                    if not isinstance(image, str) or any(c in image for c in ("$", "{", "}", "`", "\n")):
                        continue
                    repository = image.split("@", 1)[0]
                    last = repository.rsplit("/", 1)[-1]
                    tag = last.split(":", 1)[1] if ":" in last else None
                    base = repository.rsplit(":", 1)[0] if tag else repository
                    if base in values:
                        match = True
                        version = tag if version_kind != "unknown" else None
                        break
        elif kind == "compose_json":
            data = self.get("json")
            services = data.get("services") if isinstance(data, dict) else None
            match = (isinstance(data, dict) and isinstance(data.get("name"), str)
                     and isinstance(services, dict) and bool(services)
                     and any(isinstance(service, dict) and (isinstance(service.get("image"), str) or isinstance(service.get("build"), (str, dict)))
                             for service in services.values())
                     and any(key in data for key in ("networks", "volumes", "configs", "secrets")))
        return {"line": line, "version": version, "version_kind": version_kind} if match else None


def detect(artifact, entries, deadline=None):
    parsed = Parsed(artifact)
    findings = []
    for entry in entries:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("detection scan deadline reached")
        if any(parsed.signal(signal) for signal in entry["negative"]):
            continue
        hits = [(signal, result) for signal in entry["positive"] if (result := parsed.signal(signal))]
        documentation = artifact["format"] in DOC_FORMATS
        if not hits and documentation:
            # Word boundaries avoid declaring Kafka from the word 'kafkaesque'.
            mentioned = any(re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", parsed.lower, re.I) for term in entry["mention_terms"])
            if mentioned:
                hits = [({"reason": "documentation mention only", "category": "mentioned"}, {"line": 1, "version": None, "version_kind": "unknown"})]
        if not hits:
            continue
        rank = {"mentioned": 0, "ambiguous": 1, "declared": 2, "recognized": 3, "observed": 4}
        # requirements.txt is a structured dependency declaration, despite its
        # extension. Markdown/rst code examples remain documentation evidence.
        declaration_text = artifact["format"] == "txt" and any(signal["kind"] == "dependency" for signal, _ in hits if "kind" in signal)
        category = "mentioned" if documentation and not declaration_text else max((signal["category"] for signal, _ in hits), key=rank.get)
        # Offline files cannot establish a live observation via an arbitrary rule label.
        if category == "observed":
            category = "declared"
        versions = sorted(set(result["version"] for _, result in hits if result["version"] and result["version_kind"] != "client"))
        client_versions = sorted(set(result["version"] for _, result in hits if result["version"] and result["version_kind"] == "client"))
        result = {"technology": entry["technology"], "family": entry["family"], "artifact_id": artifact["id"],
                         "source_id": artifact["source_id"], "environment": artifact["environment"], "service": artifact["service"],
                         "category": category, "confidence": "low" if category in {"mentioned", "ambiguous"} else "high",
                         "versions": versions, "version_kinds": sorted(set(result["version_kind"] for _, result in hits if result["version"])),
                         "client_versions": client_versions,
                         "reasons": [signal["reason"] for signal, _ in hits], "line": hits[0][1]["line"],
                         "rule_id": entry["id"], "rule_version": entry["version"], "conflicts": [],
                         "support": entry["maturity"], "selected": False}
        if any(signal.get("kind") == "json_fields" for signal, _ in hits):
            data = parsed.get("json")
            exported = field(data, "metadata.generated_at") or field(data, "collected_at")
            if isinstance(exported, str):
                result["source_exported_at"] = exported
                result["source_timestamp_status"] = "declared in export; not independently observed"
        findings.append(result)
    return findings
