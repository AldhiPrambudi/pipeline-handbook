"""Airflow static AST subset: literal DAG/operators and declared dependencies.

Target Python is parsed, never imported. Dynamically generated tasks remain gaps.
"""

import ast

VERSION = "1.0.0"


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(value) for value in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal(key): _literal(value) for key, value in zip(node.keys, node.values)}
    raise ValueError("nonliteral expression")


def _qualified(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def analyze(artifact, ctx):
    try:
        tree = ast.parse(artifact["text"], filename="inspected.py")
    except (SyntaxError, ValueError, RecursionError):
        ctx.issue("airflow_ast_unparsed", "Python definition could not be parsed; target code was not imported.")
        return
    imports = {}

    def resolved(node):
        raw = _qualified(node)
        first, _, suffix = raw.partition(".")
        if first not in imports:
            return ""
        return imports[first] + ("." + suffix if suffix else "")

    tasks, dags, deferred, dag_names = {}, {}, [], {}

    def invalidate(names, line):
        for bound in names:
            if bound in imports or bound in tasks or bound in dags:
                ctx.issue("airflow_binding_shadowed", "A previously imported or workflow-bound name is reassigned; its old meaning is no longer used.", line=line)
                imports.pop(bound, None)
                tasks.pop(bound, None)
                dags.pop(bound, None)

    def kwargs(call):
        result = {}
        for kw in call.keywords:
            if kw.arg is None:
                raise ValueError("expanded kwargs")
            result[kw.arg] = _literal(kw.value)
        return result

    def make_dag(call, line):
        try:
            values = {}
            # Nonliteral dates do not prevent extracting independent literal
            # schedules/IDs, but their omission is always disclosed.
            for kw in call.keywords:
                if kw.arg is None:
                    ctx.issue("airflow_dynamic_argument", "DAG has expanded keyword arguments.", line=line)
                    continue
                try:
                    values[kw.arg] = _literal(kw.value)
                except ValueError:
                    ctx.issue("airflow_dynamic_argument", f"DAG argument {kw.arg} is nonliteral and unresolved.", line=line)
            dag_id = values.get("dag_id") or (_literal(call.args[0]) if call.args else None)
            if not isinstance(dag_id, str) or any(char in dag_id for char in "${}"):
                raise ValueError("DAG ID unresolved")
        except ValueError:
            ctx.issue("airflow_dag_identity_unknown", "DAG ID is not a supported literal.", line=line)
            return None
        pipeline = ctx.node("pipeline", f"{artifact['path']}::{dag_id}", {"entrypoint": True,
            "dag_id": dag_id, "definition_only": True, "technology": "airflow"}, line=line)
        dag_names[pipeline] = dag_id
        if "schedule" in values or "schedule_interval" in values:
            schedule_value = values.get("schedule", values.get("schedule_interval"))
            if isinstance(schedule_value, (str, type(None))):
                schedule = ctx.node("schedule", f"{artifact['path']}::{dag_id}::schedule", {"expression": schedule_value,
                    "timezone": values.get("timezone", "unknown"), "runtime_observed": False}, line=line)
                ctx.edge(schedule, pipeline, "schedule", line=line)
            else:
                ctx.issue("airflow_schedule_unknown", "Only literal string/null schedules are supported.", line=line)
        return pipeline

    def walk(body, current_dag=None):
        for node in body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    imports.pop(bound, None)
                    tasks.pop(bound, None)
                    dags.pop(bound, None)
                    if (node.module or "").startswith("airflow"):
                        imports[bound] = f"{node.module}.{alias.name}"
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    imports.pop(bound, None)
                    tasks.pop(bound, None)
                    dags.pop(bound, None)
                    if alias.name.startswith("airflow"):
                        imports[bound] = alias.name if alias.asname else bound
                continue
            if isinstance(node, ast.With):
                selected = current_dag
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call) and resolved(item.context_expr.func) in {"airflow.DAG", "airflow.sdk.DAG", "airflow.models.DAG"}:
                        selected = make_dag(item.context_expr, node.lineno)
                        if isinstance(item.optional_vars, ast.Name) and selected:
                            invalidate({item.optional_vars.id}, node.lineno)
                            dags[item.optional_vars.id] = selected
                    else:
                        ctx.issue("airflow_unsupported_context", "Non-DAG context manager is not evaluated.", line=node.lineno)
                walk(node.body, selected)
                continue
            call = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            variable = targets[0].id if len(targets) == 1 and isinstance(targets[0], ast.Name) else None
            # Resolve aliases in lexical order. Reassignment invalidates an
            # import or task binding rather than retaining a stale meaning.
            bound_names = {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
            invalidate(bound_names, node.lineno)
            if isinstance(call, ast.Call):
                function = resolved(call.func)
                if function in {"airflow.DAG", "airflow.sdk.DAG", "airflow.models.DAG"}:
                    pipeline = make_dag(call, node.lineno)
                    if variable and pipeline:
                        dags[variable] = pipeline
                    continue
                if function.startswith("airflow.") and function.rsplit(".", 1)[-1].endswith("Operator"):
                    values, nonliteral = {}, []
                    explicit_dag = None
                    for kw in call.keywords:
                        if kw.arg == "dag" and isinstance(kw.value, ast.Name):
                            explicit_dag = dags.get(kw.value.id)
                            continue
                        try:
                            if kw.arg is None:
                                raise ValueError("kwargs")
                            values[kw.arg] = _literal(kw.value)
                        except ValueError:
                            nonliteral.append(kw.arg or "**kwargs")
                    pipeline = explicit_dag or current_dag
                    task_id = values.get("task_id")
                    if not pipeline or not variable or not isinstance(task_id, str) or any(char in task_id for char in "${}"):
                        ctx.issue("airflow_task_identity_unknown", "Task requires a literal task_id, assigned variable and unambiguous DAG context.", line=node.lineno)
                        continue
                    attrs = {"task_id": task_id, "operator": function, "definition_only": True}
                    for key in ("trigger_rule", "retries", "depends_on_past", "pool", "queue"):
                        if key in values:
                            attrs[key] = values[key]
                    # Never publish bash_command, SQL text or arbitrary literals.
                    task = ctx.node("task", f"{artifact['path']}::{dag_names[pipeline]}::{task_id}", attrs, line=node.lineno)
                    tasks[variable] = task
                    ctx.edge(pipeline, task, "contains", line=node.lineno)
                    for arg in nonliteral:
                        ctx.issue("airflow_dynamic_argument", f"Task argument {arg} is nonliteral; that behavior is unresolved.", line=node.lineno)
                    if any(key in values for key in ("bash_command", "sql", "python_callable")):
                        ctx.issue("airflow_operator_body_unparsed", "Operator body is declared but not executed or linked to external tools by command-name guessing.", line=node.lineno, severity="info")
                    continue
            if isinstance(node, ast.Expr):
                if isinstance(node.value, ast.BinOp) or (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr in {"set_upstream", "set_downstream"}):
                    deferred.append((node.value, dict(tasks)))
                elif not isinstance(node.value, ast.Constant):
                    ctx.issue("airflow_unresolved_expression", "Python expression is outside supported static Airflow declarations.", line=node.lineno)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
                ctx.issue("airflow_dynamic_graph", "Conditional, loop, function or class-generated DAG content is not evaluated.", line=node.lineno)
                possibly_bound = {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
                possibly_bound.update(item.name for item in ast.walk(node) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                for item in ast.walk(node):
                    if isinstance(item, ast.ImportFrom):
                        possibly_bound.update(alias.asname or alias.name for alias in item.names)
                    elif isinstance(item, ast.Import):
                        possibly_bound.update(alias.asname or alias.name.split(".", 1)[0] for alias in item.names)
                invalidate(possibly_bound, node.lineno)
            elif isinstance(node, (ast.Delete, ast.AugAssign)):
                invalidate({item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))}, node.lineno)
                ctx.issue("airflow_unresolved_assignment", "Deletion or augmented assignment is outside literal workflow declarations.", line=node.lineno)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not isinstance(call, (ast.Constant, ast.Dict, ast.List, ast.Tuple)):
                ctx.issue("airflow_unresolved_assignment", "Assignment is outside literal DAG/operator declarations.", line=node.lineno)

    walk(tree.body)

    def endpoints(expr, bindings):
        if isinstance(expr, ast.Name) and expr.id in bindings:
            return [bindings[expr.id]]
        if isinstance(expr, (ast.List, ast.Tuple)):
            result = []
            for item in expr.elts:
                result.extend(endpoints(item, bindings))
            return result
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.RShift, ast.LShift)):
            if isinstance(expr.left, (ast.List, ast.Tuple)) and isinstance(expr.right, (ast.List, ast.Tuple)):
                raise ValueError("list-to-list shift is not valid Airflow dependency syntax")
            left, right = endpoints(expr.left, bindings), endpoints(expr.right, bindings)
            for source in left:
                for target in right:
                    upstream, downstream = (source, target) if isinstance(expr.op, ast.RShift) else (target, source)
                    ctx.edge(upstream, downstream, "control_flow", {"semantics": "declared Airflow dependency; trigger rules govern eligibility, not execution order guarantees"}, line=expr.lineno)
            return right
        raise ValueError("dependency endpoint is dynamic, unbound or unsupported")

    for expr, bindings in deferred:
        try:
            if isinstance(expr, ast.Call):
                if len(expr.args) != 1 or expr.keywords:
                    raise ValueError("dependency method requires one static argument")
                left, right = endpoints(expr.func.value, bindings), endpoints(expr.args[0], bindings)
                for source in left:
                    for target in right:
                        upstream, downstream = (source, target) if expr.func.attr == "set_downstream" else (target, source)
                        ctx.edge(upstream, downstream, "control_flow", {"semantics": "declared Airflow dependency method"}, line=expr.lineno)
            else:
                endpoints(expr, bindings)
        except ValueError as exc:
            ctx.issue("airflow_dependency_unresolved", str(exc), line=expr.lineno)
    if not dags and not any(node for node in tree.body if isinstance(node, ast.With)):
        ctx.issue("airflow_no_static_dag", "Imports indicate Airflow, but no supported static DAG definition was extracted.")
