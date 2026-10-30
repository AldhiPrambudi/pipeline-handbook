"""Static subset of Docker Compose normalized JSON exports.

No Docker CLI/daemon is contacted. Service, network, volume and startup-dependency
declarations do not establish container existence, host placement or traffic.
"""

from collections import deque
import re

from ..security import parse_json_text

VERSION = "1.0.0"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,1023}$")
_CONDITIONS = {"service_started", "service_healthy", "service_completed_successfully"}


def _pointer(*parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _static(value, maximum=2048):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(
        char in value for char in ("\x00", "\n", "\r", "$", "`", "{{", "}}"))


def _gap(ctx, code, message, pointer):
    ctx.issue(code, message, object_path=pointer)


def _resource(kind, label, value, project, artifact, ctx):
    pointer = _pointer(kind + "s", label)
    if not isinstance(label, str) or not _NAME.fullmatch(label) or value is not None and not isinstance(value, dict):
        _gap(ctx, "compose_resource_invalid", "Resource requires a static name and an object declaration; it was not mapped.", pointer)
        return None
    value = value or {}
    attrs = {"resource_type": "compose_" + kind, "compose_project": project,
        "boundary": project, "resource_name": label, "definition_only": True,
        "runtime_state": "unknown", "location": "unknown",
        "semantics": "declared Compose resource; actual creation and host location are unverified"}
    supported = {"name", "driver", "external"} | ({"internal"} if kind == "network" else set())
    if set(value) - supported:
        _gap(ctx, "compose_resource_fields_unsupported", "Resource has fields outside this subset; their values and runtime behavior were omitted.", pointer)
    for field in ("name", "driver"):
        if field in value:
            if not _static(value[field], 1024):
                _gap(ctx, "compose_dynamic_resource", "A resource field is nonliteral or malformed and remains unknown.", pointer + "/" + field)
            else:
                attrs["platform_name" if field == "name" else field] = value[field]
    for field in ({"internal", "external"} if kind == "network" else {"external"}):
        if field in value:
            if not isinstance(value[field], bool):
                _gap(ctx, "compose_resource_invalid", "Resource external/internal flags must be booleans; this resource was not mapped.", pointer)
                return None
            attrs[field] = value[field]
    if value.get("external") is True and set(value) - {"external", "name"}:
        _gap(ctx, "compose_resource_invalid", "An external resource has incompatible additional fields; this declaration remains unresolved.", pointer)
        return None
    return ctx.node("deployment_resource", f"{artifact['path']}::{project}::{kind}::{label}", attrs, object_path=pointer)


def analyze(artifact, ctx):
    try:
        data = parse_json_text(artifact["text"])
    except (ValueError, RecursionError):
        _gap(ctx, "compose_json_invalid", "Compose export is not unambiguous JSON; provide a reviewed normalized JSON export.", "")
        return
    if not isinstance(data, dict) or not _static(data.get("name"), 256) or not _NAME.fullmatch(data["name"]) or not isinstance(data.get("services"), dict) or not data["services"]:
        _gap(ctx, "compose_model_invalid", "Expected a static Compose project name and a nonempty services object; a filename alone does not establish Compose semantics.", "")
        return
    project = data["name"]
    if "version" in data and not isinstance(data["version"], str):
        _gap(ctx, "compose_version_invalid", "Optional Compose file version must be a string; no tool/runtime version was inferred.", "/version")
    if set(data) - {"name", "services", "networks", "volumes", "version"}:
        _gap(ctx, "compose_top_level_unsupported", "Compose export has top-level fields outside the static subset; those fields were not interpreted.", "")
    networks, volumes = {}, {}
    for kind, target in (("network", networks), ("volume", volumes)):
        declarations = data.get(kind + "s", {})
        if not isinstance(declarations, dict):
            _gap(ctx, "compose_resources_invalid", "Top-level resource declarations must be an object.", _pointer(kind + "s"))
            continue
        for label, value in sorted(declarations.items()):
            node = _resource(kind, label, value, project, artifact, ctx)
            if node:
                target[label] = node
    services = {}
    service_values = {}
    supported_service = {"image", "depends_on", "networks", "volumes"}
    for label, value in sorted(data["services"].items()):
        pointer = _pointer("services", label)
        if not isinstance(label, str) or not _NAME.fullmatch(label) or not isinstance(value, dict):
            _gap(ctx, "compose_service_invalid", "Service requires a static name and an object declaration; no component was guessed.", pointer)
            continue
        if not any(key in value for key in ("image", "build", "provider")):
            _gap(ctx, "compose_service_invalid", "Service has no image, build or provider declaration; provide a validated Compose model.", pointer)
            continue
        attrs = {"resource_type": "compose_service", "compose_project": project,
            "service_name": label, "boundary": project, "definition_only": True,
            "runtime_state": "unknown", "deployment_host": "unknown", "location": "unknown",
            "semantics": "declared Compose service; deployment and execution are unverified",
            "inspection_points": [{"kind": "definition", "location": artifact["path"] + "#" + pointer}]}
        if "image" in value:
            image = value["image"]
            if _static(image, 1024) and _IMAGE.fullmatch(image) and "://" not in image:
                attrs["image"] = image
                attrs["image_status"] = "declared reference; image tag is not an observed server version"
            else:
                _gap(ctx, "compose_image_unresolved", "Image is dynamic or malformed; no image or product version was inferred.", pointer + "/image")
        if set(value) - supported_service:
            # In particular omit command, entrypoint, environment, env_file,
            # healthcheck bodies, labels, build arguments and secret payloads.
            _gap(ctx, "compose_service_fields_unsupported", "Service has fields outside this subset. Command/environment/literal bodies and unsupported deployment behavior were omitted.", pointer)
        node = ctx.node("component", f"{artifact['path']}::{project}::{label}", attrs, object_path=pointer)
        services[label], service_values[label] = node, value
    startup = []
    for label, node in services.items():
        value = service_values[label]
        pointer = _pointer("services", label)
        startup.extend(_dependencies(value.get("depends_on", {}), services, node, ctx, pointer + "/depends_on"))
        if "network_mode" in value:
            _gap(ctx, "compose_network_mode_unsupported", "Explicit network_mode needs additional semantics; no named-network attachment was inferred for this service.", pointer + "/network_mode")
        elif "networks" not in value:
            _gap(ctx, "compose_default_network_unexpanded", "Service network membership is implicit or unexpanded. Supply a normalized export; no attachment or communication was inferred.", pointer)
        else:
            _networks(value["networks"], networks, node, ctx, pointer + "/networks")
        if "volumes" in value:
            _mounts(value["volumes"], volumes, node, ctx, pointer + "/volumes")
    _emit_dependencies(startup, ctx)


def _dependencies(value, services, node, ctx, pointer):
    if isinstance(value, list):
        if any(not isinstance(label, str) for label in value):
            _gap(ctx, "compose_dependency_invalid", "Short depends_on syntax must contain static service names.", pointer)
            return []
        value = {label: {"condition": "service_started"} for label in value}
    if not isinstance(value, dict):
        _gap(ctx, "compose_dependency_invalid", "depends_on must be an object or literal service-name list.", pointer)
        return []
    planned = []
    for dependency, settings in sorted(value.items()):
        location = pointer + "/" + str(dependency).replace("~", "~0").replace("/", "~1")
        if dependency not in services or not isinstance(settings, dict) or set(settings) - {"condition", "required", "restart"}:
            _gap(ctx, "compose_dependency_unresolved", "Dependency names an unavailable service or has unsupported settings; no startup relationship was guessed.", location)
            continue
        condition = settings.get("condition")
        if not isinstance(condition, str) or condition not in _CONDITIONS or any(key in settings and not isinstance(settings[key], bool) for key in ("required", "restart")):
            _gap(ctx, "compose_dependency_invalid", "Dependency requires a supported literal condition and boolean optional flags; no outcome is observed.", location)
            continue
        attrs = {"relation": "startup_dependency", "condition": condition,
            "semantics": "dependency service precedes dependent service in declared Compose startup; no successful run, readiness or traffic was observed"}
        for key in ("required", "restart"):
            if key in settings:
                attrs[key] = settings[key]
        planned.append((services[dependency], node, attrs, location))
    return planned


def _emit_dependencies(planned, ctx):
    """Do not present impossible cyclic startup assertions as a valid order."""
    graph, indegree = {}, {}
    for source, target, _, _ in planned:
        graph.setdefault(source, []).append(target)
        indegree.setdefault(source, 0)
        indegree[target] = indegree.get(target, 0) + 1
    queue = deque(node for node, count in indegree.items() if count == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for following in graph.get(node, []):
            indegree[following] -= 1
            if indegree[following] == 0:
                queue.append(following)
    if visited != len(indegree):
        _gap(ctx, "compose_dependency_cycle", "Supplied service startup dependencies contain a self-reference or cycle. Components remain inventoried, but no startup ordering was mapped from this inconsistent export.", "/services")
        return
    for source, target, attrs, pointer in planned:
        ctx.edge(source, target, "deployment", attrs, object_path=pointer)


def _networks(value, networks, node, ctx, pointer):
    if isinstance(value, list):
        if any(not isinstance(label, str) for label in value):
            _gap(ctx, "compose_network_reference_invalid", "Network list must contain static names.", pointer)
            return
        value = {label: {} for label in value}
    if not isinstance(value, dict):
        _gap(ctx, "compose_network_reference_invalid", "Service networks must be an object or literal name list.", pointer)
        return
    for label, settings in sorted(value.items()):
        location = pointer + "/" + str(label).replace("~", "~0").replace("/", "~1")
        if label not in networks or settings is not None and not isinstance(settings, dict):
            _gap(ctx, "compose_network_reference_unresolved", "Network attachment references an undeclared/unparsed resource or malformed settings.", location)
            continue
        if settings:
            _gap(ctx, "compose_network_options_unsupported", "Network attachment options were omitted; only named membership is mapped.", location)
        ctx.edge(node, networks[label], "deployment", {"relation": "network_attachment",
            "semantics": "declared membership; shared networks do not prove communication"}, object_path=location)


def _mounts(value, volumes, node, ctx, pointer):
    if not isinstance(value, list):
        _gap(ctx, "compose_mount_invalid", "Volumes must be a list of normalized long-form named-volume declarations.", pointer)
        return
    for index, mount in enumerate(value):
        location = pointer + "/" + str(index)
        if not isinstance(mount, dict) or mount.get("type") != "volume" or set(mount) - {"type", "source", "target", "read_only", "volume", "consistency"}:
            _gap(ctx, "compose_mount_unsupported", "Only normalized named-volume mounts are mapped; bind/tmpfs/short-form or unsupported mount semantics need a different parser subset.", location)
            continue
        source, target = mount.get("source"), mount.get("target")
        if not isinstance(source, str) or source not in volumes or not _static(target) or not target.startswith("/") or ".." in target.split("/") or "read_only" in mount and not isinstance(mount["read_only"], bool):
            _gap(ctx, "compose_mount_unresolved", "Named-volume source, container target or read-only flag is unresolved/malformed.", location)
            continue
        attrs = {"relation": "volume_mount", "container_target": target,
            "semantics": "declared named-volume mount; no files, rows or host paths were inspected"}
        if "read_only" in mount:
            attrs["read_only"] = mount["read_only"]
        if "volume" in mount or "consistency" in mount:
            _gap(ctx, "compose_mount_options_unsupported", "Mount-specific options were omitted; only named-volume attachment is mapped.", location)
        ctx.edge(node, volumes[source], "deployment", attrs, object_path=location)
