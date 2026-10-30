"""Validated explicit source scope, without implicit credentials or network use."""
from copy import deepcopy
from pathlib import Path
import os

from .security import safe_json, within, redact
from .validation import validate

DATA = Path(__file__).parent / "data"


def _reject_path_symlinks(candidate, base):
    # The existing shared path prefix is trusted configuration location (it can
    # include OS aliases such as /var on macOS). Reject newly traversed symlink
    # components, including a link before a '..' component, before resolving.
    shared = Path(os.path.commonpath([str(base), os.path.abspath(candidate)]))
    for component in (candidate, *candidate.parents):
        if component == shared:
            break
        if component.is_symlink():
            raise ValueError("symlink components in configured scope/component paths are not permitted")
DEFAULTS = {
    "discovery": {"mode": "auto"},
    "technologies": {"include": ["*"], "exclude": [], "overrides": {}},
    "rules": {"directories": [], "include": ["*"], "exclude": []},
    "adapters": {"trusted": ["builtin:*"], "include": ["*"], "exclude": [], "plugins": []},
    "security": {"network_enabled": False, "allowed_endpoints": [], "redact": True},
    "budgets": {"max_files": 2000, "max_file_bytes": 1_000_000, "max_total_bytes": 20_000_000,
                "scan_timeout_seconds": 60, "adapter_timeout_seconds": 5,
                "adapter_memory_mb": 512, "max_nodes_per_adapter": 10000},
    "output": {"directory": "./generated_handbook", "formats": ["markdown", "html", "json"]},
}


def _merge(defaults, given):
    result = deepcopy(defaults)
    for key, value in given.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
    return result


def load_config(path):
    if os.open not in os.supports_dir_fd:
        raise ValueError("secure inventory requires POSIX dir_fd/no-follow filesystem support")
    path = Path(path).absolute()
    raw = safe_json(path)
    validate(raw, safe_json(DATA / "config.schema.json"))
    config = _merge(DEFAULTS, raw)
    if config["security"]["network_enabled"] or config["security"]["allowed_endpoints"]:
        raise ValueError("MVP supports local files/exports only; network connectors are not implemented")
    if not config["security"]["redact"]:
        raise ValueError("redaction is an invariant and cannot be disabled")
    if config["discovery"]["mode"] == "manual" and "*" in config["technologies"]["include"]:
        raise ValueError("manual mode requires explicit technology IDs, not '*'")
    base = path.parent
    config["_base"] = str(base)
    ids = set()
    roots = []
    for source in config["sources"]:
        if source["id"] in ids:
            raise ValueError("source IDs must be unique")
        ids.add(source["id"])
        source.setdefault("service", source["id"])
        source.setdefault("include", ["*"])
        source.setdefault("exclude", [])
        source.setdefault("schema_filters", ["*"])
        source.setdefault("resource_filters", ["*"])
        candidate = base / source["path"]
        _reject_path_symlinks(candidate, base)
        # Do not resolve a symlink root into an apparently legitimate target.
        if candidate.is_symlink():
            raise ValueError("symlink source roots are not supported")
        source["_root"] = str(candidate.resolve())
        roots.append(candidate.resolve())
    output = (base / config["output"]["directory"]).resolve()
    if any(within(output, root) or within(root, output) for root in roots):
        raise ValueError("output and source scopes must be separate, non-overlapping directories")
    config["output"]["_root"] = str(output)
    for directory in config["rules"]["directories"]:
        rule_root = (base / directory).resolve()
        if any(within(rule_root, root) for root in roots):
            raise ValueError("reviewed rule directories must be outside scanned input scopes")
    for plugin in config["adapters"]["plugins"]:
        candidate = base / plugin["path"]
        _reject_path_symlinks(candidate, base)
        if candidate.is_symlink():
            raise ValueError("symlink trusted components are not permitted")
        component = candidate.resolve()
        if any(within(component, root) for root in roots) or within(component, output):
            raise ValueError("trusted adapter code must be outside scanned inputs and generated output")
        if plugin["id"] not in config["adapters"]["trusted"]:
            raise ValueError("external adapters require explicit exact-ID trust")
        plugin["_path"] = str(component)
    if config.get("annotations"):
        candidate = base / config["annotations"]
        _reject_path_symlinks(candidate, base)
        annotation_path = candidate.resolve()
        if any(within(annotation_path, root) for root in roots) or within(annotation_path, output):
            raise ValueError("reviewed annotations must be outside input scopes and generated output")
    return config


def public_config(config):
    """Publish effective settings and overrides without host paths/credential refs."""
    result = deepcopy(config)
    result.pop("_base", None)
    for source in result["sources"]:
        source.pop("_root", None)
        source["path"] = "scope:" + source["id"]
    result["rules"]["directories"] = [f"reviewed-rules:{i}" for i, _ in enumerate(result["rules"]["directories"])]
    for plugin in result["adapters"]["plugins"]:
        plugin.pop("_path", None)
        plugin["path"] = "trusted-component:" + plugin["id"]
    result["output"].pop("_root", None)
    result["output"]["directory"] = "generated-output"
    if "annotations" in result:
        result["annotations"] = "reviewed-annotations"
    return redact(result)
