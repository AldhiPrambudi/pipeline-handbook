"""Offline Pentaho KTR/KJB adapter for a documented, deliberately small subset."""

import re
import xml.etree.ElementTree as ET

from .sql import parse_select, add_mapping

VERSION = "1.0.0"


def _get(element, path, default=""):
    value = element.findtext(path)
    return value.strip() if value else default


def _qualified(schema, table):
    return f"{schema}.{table}" if schema else table


def _dynamic(value):
    return not value or bool(re.search(r"\$|\{|\}|%", value))


def analyze(artifact, ctx):
    text = artifact["text"]
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        ctx.issue("unsafe_xml", "XML containing DOCTYPE or ENTITY declarations is rejected.")
        return
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        ctx.issue("malformed_xml", "Pentaho XML could not be parsed safely.")
        return
    if root.tag == "transformation":
        _transformation(root, artifact, ctx)
    elif root.tag == "job":
        _job(root, artifact, ctx)
    else:
        ctx.issue("unsupported_pentaho_root", "Expected a transformation or job export root.")


def _transformation(root, artifact, ctx):
    pipeline = ctx.node("pipeline", artifact["path"], {"entrypoint": True,
        "label": _get(root, "info/name", artifact["path"]), "definition_only": True,
        "technology": "pentaho", "semantics": "KTR enabled hops carry row streams; they are not execution-order guarantees"})
    connections, physical_contexts = {}, set()
    connection_identity_safe = True
    for connection in root.findall("connection"):
        connection_name = _get(connection, "name")
        context = {
            "type": _get(connection, "type"), "server": _get(connection, "server"),
            "database": _get(connection, "database"), "port": _get(connection, "port")}
        physical_contexts.add(tuple(context[key] for key in ("type", "server", "database", "port")))
        if not connection_name or connection_name in connections and connections[connection_name] != context:
            connection_identity_safe = False
        connections[connection_name] = context
    if len(physical_contexts) != 1:
        connection_identity_safe = False
    if not connection_identity_safe:
        ctx.issue("pentaho_connection_identity_ambiguous", "Missing, multiple physical, or conflicting named connections cannot safely share the configured service identity. Task/connection inventory is retained; dataset and column extraction is omitted until a reviewed connection mapping is supplied.")
    tasks, inputs, outputs = {}, {}, {}
    for step in root.findall("step"):
        label, typ = _get(step, "name"), _get(step, "type")
        if not label:
            ctx.issue("pentaho_step_unnamed", "Step has no stable name and was not mapped.")
            continue
        if label in tasks:
            ctx.issue("pentaho_duplicate_step", "Duplicate step names make hop resolution ambiguous.")
            return
        connection_name = _get(step, "connection")
        connection = connections.get(connection_name, {})
        task = ctx.node("task", f"{artifact['path']}::{label}", {"type": typ,
            "connection_name": connection_name, "connection": connection})
        tasks[label] = task
        ctx.edge(pipeline, task, "contains")
        if typ in {"TableInput", "TableOutput"} and not connection_identity_safe:
            continue
        if typ in {"TableInput", "TableOutput"} and not connection:
            ctx.issue("pentaho_connection_unknown", "Step references a missing connection definition; dataset identity remains unresolved.")
            continue
        if typ == "TableInput":
            if connection.get("type", "").upper() not in {"POSTGRESQL", "POSTGRES"}:
                ctx.issue("pentaho_sql_dialect_unknown", "TableInput SQL has no supported PostgreSQL connection declaration.")
                continue
            sql = _get(step, "sql")
            if _dynamic(sql) or re.search(r"\bEXECUTE\b", sql, re.I):
                ctx.issue("dynamic_sql", "Pentaho TableInput has dynamic SQL or unresolved parameters.")
                continue
            try:
                inputs[label] = {**parse_select(sql), "connection": connection_name}
                dataset = ctx.dataset(inputs[label]["source"], columns=[col for col, _ in inputs[label]["columns"]])
                ctx.edge(dataset, task, "data_flow", {"semantics": "TableInput declares database read", "via": pipeline})
            except ValueError as exc:
                ctx.issue("unsupported_pentaho_sql", str(exc))
        elif typ == "TableOutput":
            table, schema = _get(step, "table"), _get(step, "schema")
            if _dynamic(table) or (schema and _dynamic(schema)):
                ctx.issue("pentaho_dynamic_target", "TableOutput target name is empty or dynamic.")
                continue
            mapping = []
            if _get(step, "specify_fields", "N").upper() == "Y":
                for field in step.findall("fields/field"):
                    source, dest = _get(field, "stream_name"), _get(field, "column_name")
                    if source and dest and not _dynamic(source + dest):
                        mapping.append((source, dest))
            else:
                ctx.issue("pentaho_output_columns_unknown", "TableOutput does not enable explicit field mappings; destination columns are not inferred.")
            target = _qualified(schema, table)
            outputs[label] = {"target": target, "columns": mapping, "connection": connection_name}
            ds = ctx.dataset(target, columns=[dest for _, dest in mapping])
            ctx.edge(task, ds, "data_flow", {"semantics": "TableOutput declares database write", "via": pipeline})
        else:
            ctx.issue("unsupported_pentaho_step", f"Step type {typ or '(missing)'} is inventoried but its transformation semantics are unsupported.")
    enabled = []
    for hop in root.findall("order/hop"):
        source, target = _get(hop, "from"), _get(hop, "to")
        if _get(hop, "enabled", "Y").upper() != "Y":
            ctx.issue("disabled_hop", "Disabled KTR hop is preserved as a coverage note and contributes no active row-flow edge.", severity="info")
            continue
        if source not in tasks or target not in tasks:
            ctx.issue("unresolved_pentaho_hop", "KTR hop references an unavailable step.")
            continue
        ctx.edge(tasks[source], tasks[target], "data_flow", {"semantics": "declared enabled row-stream hop", "via": pipeline})
        enabled.append((source, target))
    # Proven direct TableInput -> TableOutput only. Unsupported intermediates
    # never acquire identity/column semantics merely because arrows connect them.
    for source, target in enabled:
        if source not in inputs or target not in outputs:
            continue
        src, dst = inputs[source], outputs[target]
        if src["connection"] != dst["connection"]:
            ctx.issue("pentaho_cross_connection", "Input/output connection names differ; cross-service dataset identity requires a reviewed connection mapping.")
            continue
        src_columns = {output: origin for origin, output in src["columns"]}
        columns = [(src_columns[stream], output) for stream, output in dst["columns"] if stream in src_columns]
        add_mapping(ctx, src["source"], dst["target"], columns, pipeline,
                    attributes={"semantics": "direct supported TableInput-to-TableOutput row mapping", "condition": src["condition"]})
        if len(columns) != len(dst["columns"]) or not dst["columns"]:
            ctx.issue("pentaho_column_mapping_partial", "Missing or unresolved explicit output field mappings limit column lineage.")


def _job(root, artifact, ctx):
    pipeline = ctx.node("pipeline", artifact["path"], {"entrypoint": True,
        "label": _get(root, "name", artifact["path"]), "definition_only": True,
        "semantics": "KJB hops declare conditional control flow; successful execution is not observed"})
    tasks = {}
    for entry in root.findall("entries/entry"):
        label, typ = _get(entry, "name"), _get(entry, "type")
        if not label or label in tasks:
            ctx.issue("pentaho_entry_identity", "Unnamed or duplicate job entries prevent unambiguous control-flow extraction.")
            continue
        task = ctx.node("task", f"{artifact['path']}::{label}", {"type": typ})
        tasks[label] = task
        ctx.edge(pipeline, task, "contains")
        if typ in {"TRANS", "JOB", "SHELL"}:
            target = _get(entry, "filename")
            if target:
                prefix = "${Internal.Entry.Current.Directory}/"
                if target.startswith(prefix) and len(target) > len(prefix):
                    ctx.reference(task, target[len(prefix):], attributes={
                        "path_basis": "Pentaho Internal.Entry.Current.Directory",
                        "declared_reference": target})
                else:
                    ctx.issue("pentaho_working_directory_unknown", "Job entry filename lacks the supported Internal.Entry.Current.Directory prefix; relative working-directory or other variable semantics remain unresolved.")
                    ctx.reference(task, target, attributes={"runtime_cwd": "unknown"})
            elif typ == "SHELL" and _get(entry, "script"):
                ctx.issue("pentaho_inline_shell", "Inline shell script is declared but not interpreted or executed.")
            else:
                ctx.issue("pentaho_missing_target", "Job entry has no static file reference; repository-based or parameterized entries need further metadata.")
        elif typ != "SPECIAL":
            ctx.issue("unsupported_pentaho_entry", f"Job entry type {typ or '(missing)'} has unsupported execution semantics.")
    for hop in root.findall("hops/hop"):
        if _get(hop, "enabled", "Y").upper() != "Y":
            ctx.issue("disabled_hop", "Disabled job hop contributes no control-flow edge.", severity="info")
            continue
        source, target = _get(hop, "from"), _get(hop, "to")
        if source not in tasks or target not in tasks:
            ctx.issue("unresolved_pentaho_hop", "KJB hop references an unavailable job entry.")
            continue
        unconditional = _get(hop, "unconditional", "N").upper() == "Y"
        condition = "unconditional" if unconditional else ("success" if _get(hop, "evaluation", "Y").upper() == "Y" else "failure")
        ctx.edge(tasks[source], tasks[target], "control_flow", {"condition": condition,
            "semantics": "KJB declared transition", "execution_observed": False})
