"""Offline dbt manifest v12 table-dependency adapter.

Manifest dependencies describe declared model relationships. They are neither
execution observations nor proof of column lineage or materialized tables.
"""

import json
import re

VERSION = "1.0.0"
SCHEMA = "https://schemas.getdbt.com/dbt/manifest/v12.json"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _relation(node):
    values = [node.get("database"), node.get("schema"), node.get("alias") or node.get("identifier") or node.get("name")]
    if not values[-1] or not values[-2]:
        raise ValueError("relation lacks a schema and static identifier")
    if any(value is not None and (not isinstance(value, str) or not _IDENT.fullmatch(value)) for value in values):
        raise ValueError("relation contains unsupported quoted/dynamic identifier syntax")
    return ".".join(value for value in values if value)


def analyze(artifact, ctx):
    try:
        manifest = json.loads(artifact["text"])
    except (ValueError, RecursionError):
        ctx.issue("dbt_manifest_invalid", "dbt manifest is not valid bounded JSON.")
        return
    if not isinstance(manifest, dict) or not isinstance(manifest.get("metadata"), dict):
        ctx.issue("dbt_manifest_invalid", "Manifest requires an object with metadata.")
        return
    metadata = manifest["metadata"]
    if metadata.get("dbt_schema_version") != SCHEMA:
        ctx.issue("dbt_manifest_schema_unsupported", "Only dbt manifest schema v12 is supported. Export a matching manifest or add a tested adapter version.")
        return
    if not isinstance(manifest.get("nodes"), dict) or not isinstance(manifest.get("sources"), dict):
        ctx.issue("dbt_manifest_invalid", "Manifest nodes and sources must be objects.")
        return
    project = metadata.get("project_name") or "dbt_project"
    pipeline = ctx.node("pipeline", f"{artifact['path']}::{project}", {"entrypoint": True,
        "definition_only": True, "manifest_schema": "v12", "dbt_version": metadata.get("dbt_version", "unknown"),
        "metadata_generated_at": metadata.get("generated_at") if isinstance(metadata.get("generated_at"), str) else "unknown",
        "metadata_time_status": "declared export metadata; not scanner collection time or runtime observation",
        "warehouse_product": metadata.get("adapter_type", "unknown"), "warehouse_server_version": "unknown",
        "semantics": "dbt declared dependencies; no models executed"})
    datasets, model_pipelines = {}, {}
    all_nodes = {**manifest["sources"], **manifest["nodes"]}
    for unique_id, node in sorted(all_nodes.items()):
        if not isinstance(node, dict):
            ctx.issue("dbt_node_invalid", "Manifest contains a non-object node.")
            continue
        resource = node.get("resource_type")
        if resource not in {"source", "model", "seed", "snapshot", "test"}:
            ctx.issue("dbt_resource_unsupported", f"Resource type {resource or '(missing)'} is not analyzed.")
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            ctx.issue("dbt_node_invalid", "Manifest node config must be an object.")
            continue
        if config.get("enabled") is False:
            ctx.issue("dbt_disabled_node", "Disabled dbt node contributes no active definition lineage.", severity="info")
            continue
        materialization = config.get("materialized", "unknown")
        if resource == "test":
            test = ctx.node("task", f"{artifact['path']}::{unique_id}", {"resource_type": "test",
                "semantics": "validation definition, no test result observed", "original_file_path": node.get("original_file_path", "unknown")})
            ctx.edge(pipeline, test, "contains")
            continue
        if materialization == "ephemeral":
            ctx.issue("dbt_ephemeral_unsupported", f"Ephemeral model {unique_id} is logical SQL; physical lineage through it requires an additional adapter.")
            continue
        try:
            relation = _relation(node)
        except ValueError as exc:
            ctx.issue("dbt_relation_unknown", str(exc))
            continue
        cols = node.get("columns") or {}
        if not isinstance(cols, dict):
            cols = {}
            ctx.issue("dbt_columns_invalid", "Manifest columns must be an object.")
        dataset = ctx.dataset(relation, columns=list(cols))
        datasets[unique_id] = dataset
        if resource != "source":
            transform = ctx.node("pipeline", f"{artifact['path']}::{unique_id}", {
                "unique_id": unique_id, "resource_type": resource, "materialization": materialization,
                "original_file_path": node.get("original_file_path", "unknown"),
                "compiled_sql_available": bool(node.get("compiled_code") or node.get("compiled_sql")),
                "parameters": sorted((config.get("vars") or {}).keys()) if isinstance(config.get("vars"), dict) else [],
                "semantics": "declared dbt model; incremental/snapshot runtime behavior is not analyzed"})
            model_pipelines[unique_id] = transform
            ctx.edge(pipeline, transform, "contains")
            ctx.edge(transform, dataset, "data_flow", {"semantics": "declared model output"})
            if resource == "snapshot" or materialization not in {"table", "view", "incremental"}:
                ctx.issue("dbt_materialization_partial", f"Materialization {materialization} is inventoried; exact runtime data movement is unsupported.")
        if cols:
            ctx.issue("dbt_column_lineage_unsupported", "Manifest column names are metadata, not source-to-target mappings; column lineage was not inferred.", severity="info")
    for unique_id, transform in sorted(model_pipelines.items()):
        node = all_nodes[unique_id]
        depends = node.get("depends_on") or {}
        dependencies = depends.get("nodes") if isinstance(depends, dict) else None
        if not isinstance(dependencies, list):
            ctx.issue("dbt_dependencies_invalid", "Model depends_on.nodes must be a list.")
            continue
        for upstream in dependencies:
            if not isinstance(upstream, str) or upstream not in datasets:
                ctx.issue("dbt_dependency_unresolved", "dbt dependency points to a missing, disabled, ephemeral or unsupported resource.")
                continue
            ctx.edge(datasets[upstream], datasets[unique_id], "data_flow", {"via": transform,
                "semantics": "manifest depends_on.nodes; declared model dependency"})
            ctx.edge(datasets[upstream], transform, "data_flow", {"semantics": "declared model input"})
    if manifest.get("disabled"):
        ctx.issue("dbt_disabled_definitions", "Manifest includes disabled definitions; these do not contribute active lineage.", severity="info")
    if not datasets:
        ctx.issue("dbt_no_supported_relations", "No statically qualified relations were extracted from this manifest.")
