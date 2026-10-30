"""Conservative PostgreSQL SELECT/CTAS/INSERT analysis; never execute SQL.

This is deliberately a small grammar, not a general SQL parser. Unsupported
statements stay visible as gaps rather than producing guessed lineage.
"""

import re

VERSION = "1.0.0"
IDENT = r'(?:"[A-Za-z_][A-Za-z0-9_$]*"|[A-Za-z_][A-Za-z0-9_$]*)'
QUALIFIED = IDENT + r'(?:\s*\.\s*' + IDENT + r'){0,2}'


def name(value):
    """Preserve quoted case and PostgreSQL's unquoted lower-case identity."""
    return ".".join(part[1:-1] if part.startswith('"') else part.lower()
                    for part in re.findall(IDENT, value))


def _clean(text):
    """Strip comments/strings lexically, preserving string boundaries and lines."""
    out, pos = [], 0
    token = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\$[A-Za-z_0-9]*\$", re.S)
    for match in token.finditer(text):
        out.append(text[pos:match.start()])
        value = match.group()
        if value.startswith("$"):
            raise ValueError("dollar-quoted or dynamic SQL is unsupported")
        out.append(" " * len(value) if value.startswith(("--", "/*")) else " __literal__ ")
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def parse_select(sql):
    """Return single-source table lineage and proven direct projection mappings.

    Supports SELECT [DISTINCT] projections FROM qualified_table [AS alias]
    with an optional WHERE clause. Joins, set operations, CTEs, subqueries,
    functions and expressions in projections are intentionally unsupported.
    """
    clean = _clean(sql).strip().rstrip(";").strip()
    if re.search(r"\b(with|join|union|intersect|except|lateral|group|having|window|limit|offset)\b", clean, re.I):
        raise ValueError("SELECT uses a clause outside the single-source projection subset")
    m = re.fullmatch(r"SELECT\s+(?:DISTINCT\s+)?(?P<projection>.+?)\s+FROM\s+(?P<table>" + QUALIFIED + r")(?P<tail>.*)", clean, re.I | re.S)
    if not m:
        raise ValueError("SELECT is not a supported single-source projection")
    tail = m.group("tail").strip()
    alias = None
    if tail and not re.match(r"WHERE\b", tail, re.I):
        a = re.match(r"(?:AS\s+)?(" + IDENT + r")(?:\s+|$)", tail, re.I)
        if not a:
            raise ValueError("unresolved table alias or unsupported FROM clause")
        alias, tail = name(a.group(1)), tail[a.end():].strip()
    if tail and not re.match(r"WHERE\s+[^;]+$", tail, re.I | re.S):
        raise ValueError("unsupported trailing SELECT clause")
    if "(" in tail or ")" in tail or ";" in tail:
        raise ValueError("subqueries/functions in WHERE are outside this subset")
    columns = []
    for projection in m.group("projection").split(","):
        col = re.fullmatch(r"\s*(" + QUALIFIED + r")(?:\s+AS\s+(" + IDENT + r"))?\s*", projection, re.I)
        if not col or name(col.group(1)) == "__literal__":
            raise ValueError("only direct named column projections are supported; wildcards/expressions need a parser")
        parts = name(col.group(1)).split(".")
        if len(parts) > 1 and parts[-2] not in {alias, name(m.group("table")).split(".")[-1]}:
            raise ValueError("column qualifier does not match the declared source")
        columns.append((parts[-1], name(col.group(2)) if col.group(2) else parts[-1]))
    return {"source": name(m.group("table")), "columns": columns,
            "condition": "WHERE predicate declared; literals omitted" if tail else None}


def add_mapping(ctx, source_name, target_name, columns, via, line=1, attributes=None):
    """Emit table and column mappings shared by SQL and Pentaho adapters."""
    src = ctx.dataset(source_name, columns=[a for a, _ in columns], line=line)
    dst = ctx.dataset(target_name, columns=[b for _, b in columns], line=line)
    attrs = {"via": via, **(attributes or {})}
    ctx.edge(src, dst, "data_flow", attrs, line=line)
    for source, target in columns:
        source_col = ctx.node("column", f"{source_name}.{source}", {"dataset": src}, line=line,
                              namespace=ctx.artifact["service"])
        target_col = ctx.node("column", f"{target_name}.{target}", {"dataset": dst}, line=line,
                              namespace=ctx.artifact["service"])
        ctx.edge(source_col, target_col, "column_lineage", attrs, line=line)
    return src, dst


def analyze(artifact, ctx):
    text = artifact["text"]
    marker = re.search(r"^\s*--\s*dialect:\s*([A-Za-z0-9_]+)", text, re.M | re.I)
    declared = marker.group(1).lower() if marker else None
    override = ctx.overrides.get("dialect")
    dialect = override or declared
    if dialect not in {"postgres", "postgresql"}:
        ctx.issue("sql_dialect_unknown", "SQL extraction requires an explicit supported PostgreSQL dialect marker or reviewed dialect override.")
        return
    if declared and override and declared not in {override, "postgres" if override == "postgresql" else "postgresql"}:
        ctx.issue("sql_dialect_conflict", "Dialect override conflicts with the source dialect declaration; SQL remains unparsed.")
        return
    if re.search(r"\$\{|\{\{|\bEXECUTE\b|\bDO\s+\$", text, re.I):
        ctx.issue("dynamic_sql", "Runtime-generated SQL or unresolved parameters prevent static lineage.")
        return
    try:
        clean = _clean(text)
    except ValueError as exc:
        ctx.issue("unsupported_sql", str(exc))
        return
    pipeline = ctx.node("pipeline", artifact["path"], {"entrypoint": True, "dialect": dialect,
        "definition_only": True, "operation": "SQL definition; no workload executed"})
    matched = 0
    for statement in clean.split(";"):
        if not statement.strip():
            continue
        line = clean[:clean.find(statement)].count("\n") + 1
        stmt = statement.strip()
        ctas = re.fullmatch(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(" + QUALIFIED + r")\s+AS\s+(SELECT\b.+)", stmt, re.I | re.S)
        insert = re.fullmatch(r"INSERT\s+INTO\s+(" + QUALIFIED + r")\s*(?:\(([^)]+)\))?\s+(SELECT\b.+)", stmt, re.I | re.S)
        if not ctas and not insert:
            ctx.issue("unsupported_sql", "Statement is outside supported PostgreSQL CREATE TABLE AS / INSERT SELECT subset.", line=line)
            continue
        target = name((ctas or insert).group(1))
        try:
            result = parse_select(ctas.group(2) if ctas else insert.group(3))
            columns = result["columns"]
            if insert:
                if not insert.group(2):
                    # Destination column order is unknown without a catalog.
                    src, dst = ctx.dataset(result["source"], line=line), ctx.dataset(target, line=line)
                    ctx.edge(src, dst, "data_flow", {"via": pipeline, "operation": "insert_select"}, line=line)
                    ctx.issue("sql_destination_columns_unknown", "INSERT has no destination column list; only table lineage is supported.", line=line)
                    matched += 1
                    continue
                targets = [name(value.strip()) for value in insert.group(2).split(",")]
                if any(not re.fullmatch(IDENT, value.strip()) for value in insert.group(2).split(",")) or len(targets) != len(columns):
                    raise ValueError("INSERT destination columns do not match the supported SELECT projections")
                columns = [(source, target_col) for (source, _), target_col in zip(columns, targets)]
            add_mapping(ctx, result["source"], target, columns, pipeline, line,
                        {"operation": "create_table_as" if ctas else "insert_select", "condition": result["condition"]})
            matched += 1
        except ValueError as exc:
            ctx.issue("unsupported_sql", str(exc), line=line)
    if not matched:
        ctx.issue("sql_no_supported_lineage", "No supported static table mapping was extracted; definition presence does not establish execution.")
