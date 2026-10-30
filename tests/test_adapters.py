"""Reference adapter semantics, with hand-written expectations."""

import hashlib
import unittest
from pathlib import Path

from pipeline_handbook.adapters import airflow, dbt, pentaho, shell, sql
from pipeline_handbook.model import Context

ROOT = Path(__file__).resolve().parents[1]


def context(text, path, technology, overrides=None):
    artifact = {"id": "fixture", "source_id": "fixture_dev", "environment": "dev",
        "service": "orders", "path": path, "hash": hashlib.sha256(text.encode()).hexdigest(),
        "text": text, "format": path.rsplit(".", 1)[-1], "size": len(text.encode())}
    config = {"technologies": {"overrides": {technology: overrides or {}}},
              "budgets": {"max_nodes_per_adapter": 1000}}
    return artifact, Context(artifact, technology, config,
        {"id": "builtin:test", "version": "1.0.0"},
        {"id": "test", "version": "1.0.0"}, "2026-10-29T00:00:00Z")


class AdaptersTest(unittest.TestCase):
    def data_edges(self, ctx):
        return {(ctx.nodes[e["source"]]["name"], ctx.nodes[e["target"]]["name"])
                for e in ctx.edges.values() if e["kind"] == "data_flow"
                and ctx.nodes[e["source"]]["kind"] == ctx.nodes[e["target"]]["kind"] == "dataset"}

    def test_sql_direct_columns_and_direction(self):
        artifact, ctx = context("-- dialect: postgres\nCREATE TABLE final.orders AS SELECT order_id, amount FROM staging.orders;", "load.sql", "postgresql")
        sql.analyze(artifact, ctx)
        self.assertEqual({("staging.orders", "final.orders")}, self.data_edges(ctx))
        self.assertEqual(2, sum(edge["kind"] == "column_lineage" for edge in ctx.edges.values()))

    def test_sql_ambiguous_and_dynamic_are_not_inferred(self):
        for text in ("CREATE TABLE final.orders AS SELECT order_id FROM raw.orders;",
                     "-- dialect: postgres\nEXECUTE 'CREATE TABLE x AS SELECT * FROM y';"):
            artifact, ctx = context(text, "misleading_postgres.sql", "postgresql")
            sql.analyze(artifact, ctx)
            self.assertFalse(self.data_edges(ctx))
            self.assertTrue(ctx.issues)

    def test_sql_joins_and_wildcards_stay_gaps(self):
        for select in ("SELECT * FROM raw.orders", "SELECT x.id FROM raw.x x JOIN raw.y y ON x.id=y.id"):
            with self.assertRaises(ValueError):
                sql.parse_select(select)

    def test_insert_column_order_requires_explicit_destination(self):
        artifact, ctx = context("-- dialect: postgres\nINSERT INTO final.orders (id, total) SELECT order_id, amount FROM raw.orders;", "load.sql", "postgresql")
        sql.analyze(artifact, ctx)
        edges = [e for e in ctx.edges.values() if e["kind"] == "column_lineage"]
        mapping = {(ctx.nodes[e["source"]]["name"], ctx.nodes[e["target"]]["name"]) for e in edges}
        self.assertEqual({("raw.orders.order_id", "final.orders.id"), ("raw.orders.amount", "final.orders.total")}, mapping)

    def test_pentaho_transform_is_data_not_control(self):
        text = (ROOT / "fixtures/legacy/dev/transform.ktr").read_text()
        artifact, ctx = context(text, "transform.ktr", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertEqual({("raw.orders", "staging.orders")}, self.data_edges(ctx))
        self.assertFalse(any(edge["kind"] == "control_flow" for edge in ctx.edges.values()))

    def test_pentaho_job_success_and_unconditional(self):
        text = (ROOT / "fixtures/legacy/dev/load.kjb").read_text()
        # Exercise the supported predefined variable rather than relying on
        # the process cwd for a plain relative filename.
        text = text.replace("<filename>transform.ktr", "<filename>${Internal.Entry.Current.Directory}/transform.ktr").replace("<filename>publish.sh", "<filename>${Internal.Entry.Current.Directory}/publish.sh")
        artifact, ctx = context(text, "load.kjb", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertEqual({"unconditional", "success"}, {edge["attributes"]["condition"] for edge in ctx.edges.values() if edge["kind"] == "control_flow"})
        self.assertEqual({"transform.ktr", "publish.sh"}, {ref["target_path"] for ref in ctx.references})
        self.assertTrue(all(ref["attributes"]["path_basis"] == "Pentaho Internal.Entry.Current.Directory" for ref in ctx.references))

    def test_pentaho_plain_relative_job_reference_remains_unresolved(self):
        artifact, ctx = context("<job><entries><entry><name>Stage</name><type>TRANS</type><filename>stage.ktr</filename></entry></entries></job>", "load.kjb", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertEqual("unknown", ctx.references[0]["attributes"]["runtime_cwd"])
        self.assertIn("pentaho_working_directory_unknown", {issue["code"] for issue in ctx.issues})

    def test_pentaho_multiple_physical_connections_do_not_merge_datasets(self):
        original = (ROOT / "fixtures/legacy/dev/transform.ktr").read_text()
        additional = "<connection><name>unrelated</name><type>POSTGRESQL</type><server>other-service</server><database>orders_demo</database></connection>"
        artifact, ctx = context(original.replace("</transformation>", additional + "</transformation>"), "transform.ktr", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertTrue(any(node["kind"] == "task" for node in ctx.nodes.values()))
        self.assertFalse(any(node["kind"] in {"dataset", "column"} for node in ctx.nodes.values()))
        self.assertIn("pentaho_connection_identity_ambiguous", {issue["code"] for issue in ctx.issues})

    def test_pentaho_conflicting_named_connection_is_ambiguous(self):
        original = (ROOT / "fixtures/legacy/dev/transform.ktr").read_text()
        additional = "<connection><name>orders_local</name><type>POSTGRESQL</type><server>second-service</server><database>orders_demo</database></connection>"
        artifact, ctx = context(original.replace("</transformation>", additional + "</transformation>"), "transform.ktr", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertFalse(any(node["kind"] in {"dataset", "column"} for node in ctx.nodes.values()))
        self.assertIn("pentaho_connection_identity_ambiguous", {issue["code"] for issue in ctx.issues})

    def test_unsafe_xml_is_rejected_before_parse(self):
        artifact, ctx = context('<!DOCTYPE transformation [<!ENTITY x SYSTEM "file:///etc/passwd">]><transformation>&x;</transformation>', "hostile.ktr", "pentaho")
        pentaho.analyze(artifact, ctx)
        self.assertFalse(ctx.nodes)
        self.assertEqual("unsafe_xml", ctx.issues[0]["code"])

    def test_shell_cwd_is_explicit(self):
        artifact, ctx = context("#!/bin/sh\npsql -f publish.sql\n", "publish.sh", "shell")
        shell.analyze(artifact, ctx)
        self.assertEqual("unknown", ctx.references[0]["attributes"]["runtime_cwd"])
        artifact, ctx = context("#!/bin/sh\n# handbook: working-directory=.\npsql -f publish.sql\n", "publish.sh", "shell")
        shell.analyze(artifact, ctx)
        self.assertNotIn("runtime_cwd", ctx.references[0]["attributes"])
        self.assertFalse(any(e["kind"] == "data_flow" for e in ctx.edges.values()))

    def test_shell_does_not_flatten_conditional_body(self):
        artifact, ctx = context("#!/bin/sh\n# handbook: working-directory=.\nif test -e input; then\npsql -f publish.sql\nfi\n", "publish.sh", "shell")
        shell.analyze(artifact, ctx)
        self.assertFalse(ctx.references)
        self.assertEqual("unsupported_shell_control", ctx.issues[0]["code"])

    def test_shell_mixed_short_circuit_lists_remain_unmapped(self):
        for command in ("true && false || true", "true && false ; true", "false || true && true"):
            artifact, ctx = context("#!/bin/sh\n" + command, "commands.sh", "shell")
            shell.analyze(artifact, ctx)
            self.assertFalse(any(edge["kind"] == "control_flow" for edge in ctx.edges.values()))
            self.assertIn("unsupported_shell_mixed_list", {issue["code"] for issue in ctx.issues})

    def test_shell_uniform_lists_preserve_declared_conditions(self):
        artifact, ctx = context("#!/bin/sh\ntrue && false && true", "commands.sh", "shell")
        shell.analyze(artifact, ctx)
        flows = [edge for edge in ctx.edges.values() if edge["kind"] == "control_flow"]
        self.assertEqual(2, len(flows))
        self.assertEqual({"success"}, {edge["attributes"]["condition"] for edge in flows})

    def test_airflow_static_edges_and_no_dynamic_execution(self):
        text = '''from airflow import DAG
from airflow.operators.bash import BashOperator
with DAG(dag_id="orders", schedule="0 3 * * *"):
    a = BashOperator(task_id="a", bash_command="echo hi")
    b = BashOperator(task_id="b", bash_command="echo hi")
    c = BashOperator(task_id="c", bash_command="echo hi")
    a >> [b, c]
    for i in range(100):
        raise RuntimeError("must not execute")
'''
        artifact, ctx = context(text, "dag.py", "airflow")
        airflow.analyze(artifact, ctx)
        pairs = {(ctx.nodes[e["source"]]["attributes"].get("task_id"), ctx.nodes[e["target"]]["attributes"].get("task_id")) for e in ctx.edges.values() if e["kind"] == "control_flow"}
        self.assertEqual({("a", "b"), ("a", "c")}, pairs)
        self.assertIn("airflow_dynamic_graph", {issue["code"] for issue in ctx.issues})

    def test_manifest_dependencies_not_column_lineage(self):
        text = (ROOT / "fixtures/modern/dev/manifest.json").read_text()
        artifact, ctx = context(text, "manifest.json", "dbt")
        dbt.analyze(artifact, ctx)
        self.assertEqual({("DEMO.RAW.ORDERS", "DEMO.STAGING.ORDERS"), ("DEMO.STAGING.ORDERS", "DEMO.FINAL.ORDERS")}, self.data_edges(ctx))
        self.assertFalse(any(e["kind"] == "column_lineage" for e in ctx.edges.values()))
        export = next(node for node in ctx.nodes.values() if node["kind"] == "pipeline" and node["attributes"].get("entrypoint"))
        self.assertEqual("2026-01-15T00:00:00Z", export["attributes"]["metadata_generated_at"])
        self.assertEqual("declared", export["status"])

    def test_airflow_reassigned_import_is_not_a_dag_constructor(self):
        text = '''from airflow import DAG
from airflow.operators.bash import BashOperator
DAG = None
with DAG(dag_id="orders"):
    a = BashOperator(task_id="a", bash_command="echo hi")
'''
        artifact, ctx = context(text, "dag.py", "airflow")
        airflow.analyze(artifact, ctx)
        self.assertFalse(any(node["kind"] in {"pipeline", "task"} for node in ctx.nodes.values()))
        self.assertIn("airflow_binding_shadowed", {issue["code"] for issue in ctx.issues})

    def test_airflow_dependency_binding_uses_statement_time(self):
        text = '''from airflow import DAG
from airflow.operators.bash import BashOperator
with DAG(dag_id="orders"):
    a = BashOperator(task_id="a", bash_command="echo hi")
    b = BashOperator(task_id="b", bash_command="echo hi")
    a >> b
    a = "reassigned"
    a >> b
'''
        artifact, ctx = context(text, "dag.py", "airflow")
        airflow.analyze(artifact, ctx)
        self.assertEqual(1, sum(edge["kind"] == "control_flow" for edge in ctx.edges.values()))
        self.assertIn("airflow_binding_shadowed", {issue["code"] for issue in ctx.issues})
        self.assertIn("airflow_dependency_unresolved", {issue["code"] for issue in ctx.issues})

    def test_airflow_conditional_shadow_does_not_reuse_stale_import(self):
        text = '''from airflow import DAG
if condition_from_runtime:
    DAG = None
with DAG(dag_id="orders"):
    pass
'''
        artifact, ctx = context(text, "dag.py", "airflow")
        airflow.analyze(artifact, ctx)
        self.assertFalse(any(node["kind"] == "pipeline" for node in ctx.nodes.values()))


if __name__ == "__main__":
    unittest.main()
