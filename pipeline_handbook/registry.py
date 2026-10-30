"""Versioned data-only rule packs and explicitly trusted executable components."""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import sys

from .config import DATA
from .security import digest, safe_json
from .validation import validate

BUILTINS = {
    "builtin:pentaho": "pipeline_handbook.adapters.pentaho",
    "builtin:shell": "pipeline_handbook.adapters.shell",
    "builtin:sql": "pipeline_handbook.adapters.sql",
    "builtin:airflow": "pipeline_handbook.adapters.airflow",
    "builtin:dbt": "pipeline_handbook.adapters.dbt",
    "builtin:compose": "pipeline_handbook.adapters.compose",
    "builtin:environment_map": "pipeline_handbook.adapters.environment_map",
}


def matches(value, patterns):
    return any(fnmatchcase(value, pattern) for pattern in patterns)


class Registry:
    def __init__(self, config):
        self.config = config
        schema = safe_json(DATA / "rule-pack.schema.json")
        files = [DATA / "builtin.json"]
        for directory in config["rules"]["directories"]:
            root = Path(config["_base"]) / directory
            if not root.is_dir():
                raise ValueError("configured reviewed rule directory is missing")
            # Only direct JSON files; symlinks and schema/example files are not packs.
            files.extend(p for p in sorted(root.glob("*.json")) if p.name.endswith(".rules.json"))
        self.entries = []
        by_id = {}
        for file in files:
            if file.is_symlink():
                raise ValueError("symlink rule packs are not permitted")
            pack = safe_json(file)
            validate(pack, schema)
            for entry in pack["entries"]:
                if entry["id"] in by_id:
                    if by_id[entry["id"]] == entry:
                        continue  # referring to the shipped rules twice is harmless
                    raise ValueError("duplicate rule ID with conflicting content: " + entry["id"])
                by_id[entry["id"]] = entry
                if matches(entry["id"], config["rules"]["include"]) and not matches(entry["id"], config["rules"]["exclude"]):
                    self.entries.append(entry)
        self.entries.sort(key=lambda entry: (-entry["priority"], entry["id"]))
        if len(self.entries) > 500:
            raise ValueError("reviewed registry exceeds the 500-rule budget")
        self.adapters = {key: {"id": key, "module": value, "version": "1.0.0", "priority": 100}
                         for key, value in BUILTINS.items()}
        for plugin in config["adapters"]["plugins"]:
            if plugin["id"].startswith("builtin:") or plugin["id"] in self.adapters:
                raise ValueError("plugin IDs cannot shadow registered components")
            path = Path(plugin["_path"])
            if not path.is_file() or path.is_symlink() or path.suffix != ".py":
                raise ValueError("trusted adapter must be an explicit local Python file")
            self.adapters[plugin["id"]] = {**plugin, "hash": digest(path.read_bytes())}
        code = []
        for path in sorted(Path(__file__).parent.rglob("*.py")):
            code.append((str(path.relative_to(Path(__file__).parent)), digest(path.read_bytes())))
        descriptors = {key: {k: v for k, v in component.items() if k not in {"path", "_path"}}
                       for key, component in self.adapters.items()}
        schemas = [(name, digest((DATA / name).read_bytes())) for name in ("config.schema.json", "rule-pack.schema.json")]
        self.fingerprint = digest({"entries": self.entries, "adapters": descriptors, "code": code,
                                   "schemas": schemas, "python_grammar": list(sys.version_info[:2])})

    def select(self, technology, rule):
        options = list(rule["adapters"])
        options += [key for key, item in self.adapters.items() if technology in item.get("technologies", [])]
        forced = self.config["technologies"]["overrides"].get(technology, {}).get("adapter")
        if forced:
            options = [forced] if forced in options else []
        settings = self.config["adapters"]
        return sorted([self.adapters[key] for key in set(options) if key in self.adapters
                       and matches(key, settings["trusted"]) and matches(key, settings["include"])
                       and not matches(key, settings["exclude"])], key=lambda item: (-item["priority"], item["id"]))

    def capabilities(self):
        rows = [{key: entry[key] for key in (
            "technology", "family", "version", "applicable_versions", "features", "limitations",
            "maturity", "tests", "fixtures", "official_references", "adapters")}
            for entry in self.entries]
        for entry, row in zip(self.entries, rows):
            row["architecture_features"] = entry.get("architecture_features", {})
        return rows
