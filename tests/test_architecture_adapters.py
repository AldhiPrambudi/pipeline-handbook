"""Static architecture parser boundaries and exact, declared metadata."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from pipeline_handbook.adapters import compose, environment_map
from pipeline_handbook.config import DEFAULTS, _merge
from pipeline_handbook.detection import detect
from pipeline_handbook.model import Context, validate_result
from pipeline_handbook.registry import Registry
from tests.test_acceptance import run_cli


def context(data, path="compose.json", technology="docker", source="architecture_dev", environment="dev"):
    text = data if isinstance(data, str) else json.dumps(data)
    artifact = {"id": "artifact:" + hashlib.sha256((source + path).encode()).hexdigest()[:24],
        "source_id": source, "environment": environment, "service": "orders",
        "path": path, "hash": hashlib.sha256(text.encode()).hexdigest(), "text": text,
        "format": "json", "size": len(text.encode())}
    config = _merge(DEFAULTS, {"project": "architecture_tests", "_base": str(Path.cwd()), "sources": []})
    ctx = Context(artifact, technology, config, {"id": "builtin:test", "version": "1.0.0"},
        {"id": "test", "version": "1.0.0"}, "2026-10-30T00:00:00Z")
    return artifact, ctx


def compose_export():
    return {"name": "orders-platform", "services": {
        "postgres": {"image": "postgres:16.4", "networks": {"data": {}},
            "volumes": [{"type": "volume", "source": "orders_data", "target": "/var/lib/postgresql/data"}]},
        "app": {"image": "example/app:1.2", "depends_on": {"postgres": {"condition": "service_healthy", "required": True}},
            "networks": {"data": {}}}},
        "networks": {"data": {}}, "volumes": {"orders_data": {}}}


def selector(kind, name, *, source="architecture_dev", path="environment.json", environment="dev", namespace=None):
    return {"kind": kind, "name": name, "environment": environment,
        "namespace": namespace or source, "source_id": source, "artifact_path": path}


def environment_export():
    return {"format": environment_map.FORMAT,
        "components": [{"name": "warehouse.orders", "technology": "warehouse-example", "role": "query service",
            "boundary": "declared internal reporting", "location": "https://warehouse.example.invalid/query",
            "inspection_points": [{"kind": "metadata", "location": "exports/catalog.json"}]}],
        "reports": [{"name": "orders.dashboard", "report_type": "dashboard", "technology": "report-example",
            "inspection_points": [{"kind": "report_ui", "location": "https://reports.example.invalid/orders"}]}],
        "links": [{"source": selector("dataset", "final.orders", source="legacy_dev", path="publish.sql", namespace="legacy_orders"),
            "target": selector("report", "orders.dashboard"), "kind": "data_flow", "attributes": {"relation": "declared_consumer"}}]}


class ComposeAdapterTests(unittest.TestCase):
    def test_startup_network_and_volume_are_deployment_not_data_or_control(self):
        artifact, ctx = context(compose_export())
        compose.analyze(artifact, ctx)
        names = {node["name"]: node for node in ctx.nodes.values()}
        self.assertEqual(4, len(names))
        self.assertIn("compose.json::orders-platform::postgres", names)
        self.assertIn("compose.json::orders-platform::network::data", names)
        self.assertIn("compose.json::orders-platform::volume::orders_data", names)
        startup = [edge for edge in ctx.edges.values() if edge["attributes"].get("relation") == "startup_dependency"]
        self.assertEqual(1, len(startup))
        edge = startup[0]
        self.assertTrue(ctx.nodes[edge["source"]]["name"].endswith("::postgres"))
        self.assertTrue(ctx.nodes[edge["target"]]["name"].endswith("::app"))
        self.assertEqual("service_healthy", edge["attributes"]["condition"])
        self.assertEqual({"deployment"}, {edge["kind"] for edge in ctx.edges.values()})
        self.assertTrue(all(node["status"] == "declared" for node in names.values()))
        self.assertTrue(all("object_path" in evidence for evidence in ctx.evidences.values()))
        validate_result(ctx.result(), ctx.config, artifact)

    def test_images_do_not_become_observed_server_versions_or_hosts(self):
        _, ctx = context(compose_export())
        compose.analyze(ctx.artifact, ctx)
        node = next(node for node in ctx.nodes.values() if node["name"].endswith("::postgres"))
        self.assertEqual("postgres:16.4", node["attributes"]["image"])
        self.assertEqual("unknown", node["attributes"]["deployment_host"])
        self.assertEqual("unknown", node["attributes"]["runtime_state"])
        self.assertNotIn("server_version", node["attributes"])
        self.assertFalse(any(node["kind"] == "run" for node in ctx.nodes.values()))

    def test_command_environment_and_healthcheck_literals_are_omitted(self):
        data = compose_export()
        data["services"]["postgres"].update({"environment": {"POSTGRES_PASSWORD": "FAKE_ARCH_SECRET_CANARY_7231"},
            "command": ["echo", "FAKE_ARCH_COMMAND_CANARY"], "healthcheck": {"test": ["CMD", "echo", "FAKE_ARCH_HEALTH_CANARY"]}})
        _, ctx = context(data)
        compose.analyze(ctx.artifact, ctx)
        output = json.dumps(ctx.result())
        self.assertNotIn("FAKE_ARCH_SECRET_CANARY_7231", output)
        self.assertNotIn("FAKE_ARCH_COMMAND_CANARY", output)
        self.assertNotIn("FAKE_ARCH_HEALTH_CANARY", output)
        self.assertIn("compose_service_fields_unsupported", {issue["code"] for issue in ctx.issues})

    def test_dynamic_images_and_missing_resources_stay_unknown(self):
        data = compose_export()
        data["services"]["postgres"]["image"] = "postgres:${POSTGRES_VERSION}"
        data["services"]["app"]["networks"] = {"missing": {}}
        _, ctx = context(data)
        compose.analyze(ctx.artifact, ctx)
        node = next(node for node in ctx.nodes.values() if node["name"].endswith("::postgres"))
        self.assertNotIn("image", node["attributes"])
        self.assertFalse(any(node["name"].endswith("::network::missing") for node in ctx.nodes.values()))
        self.assertTrue({"compose_image_unresolved", "compose_network_reference_unresolved"} <= {issue["code"] for issue in ctx.issues})

    def test_malformed_local_dependency_does_not_erase_other_service_metadata(self):
        data = compose_export()
        data["services"]["app"]["depends_on"]["postgres"]["condition"] = {"malformed": True}
        data["services"]["invalid"] = "not an object"
        _, ctx = context(data)
        compose.analyze(ctx.artifact, ctx)
        self.assertEqual(2, sum(node["kind"] == "component" for node in ctx.nodes.values()))
        self.assertFalse(any(edge["attributes"].get("relation") == "startup_dependency" for edge in ctx.edges.values()))
        self.assertTrue({"compose_dependency_invalid", "compose_service_invalid"} <= {issue["code"] for issue in ctx.issues})

    def test_bind_mounts_and_implicit_networks_are_not_invented(self):
        data = {"name": "isolated", "services": {"app": {"image": "example/app:1", "volumes": [
            {"type": "bind", "source": "/private/FAKE_HOST_PATH_CANARY", "target": "/data"}]}}, "volumes": {}}
        _, ctx = context(data)
        compose.analyze(ctx.artifact, ctx)
        self.assertEqual(1, len(ctx.nodes))
        self.assertFalse(ctx.edges)
        self.assertNotIn("FAKE_HOST_PATH_CANARY", json.dumps(ctx.result()))
        self.assertTrue({"compose_mount_unsupported", "compose_default_network_unexpanded"} <= {issue["code"] for issue in ctx.issues})

    def test_different_source_namespaces_cannot_merge_same_compose_names(self):
        data = compose_export()
        _, first = context(data, source="dev_scope")
        _, second = context(data, source="other_dev_scope")
        compose.analyze(first.artifact, first)
        compose.analyze(second.artifact, second)
        self.assertFalse(set(first.nodes) & set(second.nodes))
        self.assertEqual({"dev_scope"}, {node["namespace"] for node in first.nodes.values()})

    def test_cyclic_startup_export_keeps_inventory_without_impossible_order(self):
        for dependency in ("postgres", "app"):
            data = compose_export()
            data["services"]["postgres"]["depends_on"] = {dependency: {"condition": "service_started"}}
            _, ctx = context(data)
            compose.analyze(ctx.artifact, ctx)
            self.assertEqual(2, sum(node["kind"] == "component" for node in ctx.nodes.values()))
            self.assertFalse(any(edge["attributes"].get("relation") == "startup_dependency" for edge in ctx.edges.values()))
            self.assertIn("compose_dependency_cycle", {issue["code"] for issue in ctx.issues})


class EnvironmentMapTests(unittest.TestCase):
    def test_map_declares_nodes_and_exact_links_without_manufacturing_targets(self):
        artifact, ctx = context(environment_export(), "environment.json", "environment-map")
        environment_map.analyze(artifact, ctx)
        self.assertEqual({"component", "report"}, {node["kind"] for node in ctx.nodes.values()})
        self.assertFalse(ctx.edges)
        self.assertEqual(1, len(ctx.links))
        link = ctx.links[0]
        self.assertEqual("legacy_dev", link["source_selector"]["source_id"])
        self.assertEqual("publish.sql", link["source_selector"]["artifact_path"])
        self.assertEqual("architecture_dev", link["target_selector"]["namespace"])
        self.assertFalse(any(node["name"] == "final.orders" for node in ctx.nodes.values()))
        self.assertIn("/components/0", {item.get("object_path") for item in ctx.evidences.values()})
        self.assertIn("/links/0", {item.get("object_path") for item in ctx.evidences.values()})
        validate_result(ctx.result(), ctx.config, artifact)

    def test_unsupported_version_and_unknown_root_fields_remain_unparsed(self):
        for field, value, code in (("format", "pipeline-handbook.environment/v2", "environment_map_version_unsupported"),
                                   ("unrecognized", True, "environment_map_schema_invalid")):
            data = environment_export()
            data[field] = value
            _, ctx = context(data, "environment.json", "environment-map")
            environment_map.analyze(ctx.artifact, ctx)
            self.assertFalse(ctx.nodes)
            self.assertFalse(ctx.links)
            self.assertIn(code, {issue["code"] for issue in ctx.issues})

    def test_malformed_local_record_does_not_erase_valid_report(self):
        data = environment_export()
        data["components"][0]["command"] = "FAKE_MAP_COMMAND_CANARY"
        _, ctx = context(data, "environment.json", "environment-map")
        environment_map.analyze(ctx.artifact, ctx)
        self.assertEqual({"report"}, {node["kind"] for node in ctx.nodes.values()})
        self.assertNotIn("FAKE_MAP_COMMAND_CANARY", json.dumps(ctx.result()))
        self.assertIn("environment_map_record_invalid", {issue["code"] for issue in ctx.issues})

    def test_unsafe_dynamic_or_incomplete_selector_does_not_create_link(self):
        for badpath in ("../outside.json", "/absolute.json", "${EXPORT}.json", "https://example.invalid/a", "a//b.json", "*.json"):
            data = environment_export()
            data["links"][0]["source"]["artifact_path"] = badpath
            _, ctx = context(data, "environment.json", "environment-map")
            environment_map.analyze(ctx.artifact, ctx)
            self.assertFalse(ctx.links)
            self.assertIn("environment_map_link_invalid", {issue["code"] for issue in ctx.issues})
        data = environment_export()
        del data["links"][0]["target"]["namespace"]
        _, ctx = context(data, "environment.json", "environment-map")
        environment_map.analyze(ctx.artifact, ctx)
        self.assertFalse(ctx.links)

    def test_sensitive_link_bodies_and_credential_locations_are_rejected(self):
        data = environment_export()
        data["links"][0]["attributes"]["sql"] = "SELECT FAKE_MAP_SQL_LITERAL_CANARY"
        data["components"][0]["location"] = "https://user:FAKE_MAP_URI_CANARY@example.invalid/metadata"
        _, ctx = context(data, "environment.json", "environment-map")
        environment_map.analyze(ctx.artifact, ctx)
        self.assertFalse(ctx.links)
        self.assertFalse(any(node["kind"] == "component" for node in ctx.nodes.values()))
        self.assertNotIn("FAKE_MAP_SQL_LITERAL_CANARY", json.dumps(ctx.result()))
        self.assertNotIn("FAKE_MAP_URI_CANARY", json.dumps(ctx.result()))

    def test_local_duplicate_identity_does_not_silently_overwrite(self):
        data = environment_export()
        other = deepcopy(data["components"][0])
        other["location"] = "https://other.example.invalid/query"
        data["components"].append(other)
        _, ctx = context(data, "environment.json", "environment-map")
        environment_map.analyze(ctx.artifact, ctx)
        self.assertFalse(any(node["kind"] == "component" for node in ctx.nodes.values()))
        self.assertIn("environment_map_duplicate_identity", {issue["code"] for issue in ctx.issues})


class ArchitectureRegistryTests(unittest.TestCase):
    def test_misleading_filename_is_not_compose_detection(self):
        artifact, ctx = context({"name": "generic", "services": {"db": {"description": "unrelated registry"}}, "networks": {}})
        entries = Registry(ctx.config).entries
        self.assertFalse(any(item["technology"] == "docker" for item in detect(artifact, entries, time.monotonic() + 5)))
        artifact, ctx = context(compose_export())
        self.assertTrue(any(item["technology"] == "docker" and item["category"] == "declared" for item in detect(artifact, entries, time.monotonic() + 5)))

    def test_other_environment_map_versions_are_visible_candidates(self):
        data = environment_export()
        data["format"] = "pipeline-handbook.environment/v2"
        artifact, ctx = context(data, "future.json", "environment-map")
        findings = detect(artifact, Registry(ctx.config).entries, time.monotonic() + 5)
        self.assertTrue(any(item["technology"] == "environment-map" and item["category"] == "ambiguous" for item in findings))

    def test_conflicting_maps_keep_both_artifact_evidence_and_report_conflict(self):
        with tempfile.TemporaryDirectory(prefix="pipeline-architecture-maps-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            first = {"format": environment_map.FORMAT, "components": [{"name": "warehouse.orders", "location": "declared-host-a"}], "links": []}
            second = deepcopy(first)
            second["components"][0]["location"] = "declared-host-b"
            (source / "first.json").write_text(json.dumps(first))
            (source / "second.json").write_text(json.dumps(second))
            config = {"project": "conflicting_map_declarations", "sources": [{"id": "maps", "kind": "directory", "environment": "test", "service": "orders", "path": "source"}], "output": {"directory": "output"}}
            path = root / "config.json"
            path.write_text(json.dumps(config))
            run_cli("analyze", "--config", str(path))
            snapshot = json.loads((root / "output/latest.json").read_text())
            node = next(node for node in snapshot["nodes"] if node["name"] == "warehouse.orders")
            evidence = {item["id"]: item for item in snapshot["evidence"]}
            self.assertEqual(2, len(node["evidence"]))
            self.assertEqual({"maps/first.json:L1", "maps/second.json:L1"}, {evidence[key]["location"] for key in node["evidence"]})
            self.assertEqual({"declared-host-a", "declared-host-b"}, set(node["conflicts"][0]["values"]))
            self.assertIn("adapter_conflict", {issue["code"] for issue in snapshot["issues"]})


if __name__ == "__main__":
    unittest.main()
