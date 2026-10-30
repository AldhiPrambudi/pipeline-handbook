"""Fictional Acme export adapter demonstrating the v1 SDK, not a vendor integration.

The administrator must register this exact file outside the scanned scope and
explicitly trust its adapter ID. A scanned file can never nominate this module.
"""

import json
import re


VERSION = "1.0.0"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,2}")


def analyze(artifact, ctx):
    export = json.loads(artifact["text"])
    if export.get("technology") != "acme" or not isinstance(export.get("tasks"), dict):
        ctx.issue("acme_invalid_export", "Expected a fictional Acme export with a tasks object.")
        return
    pipeline = ctx.node("pipeline", artifact["path"], {
        "entrypoint": True, "definition_only": True, "format": "fictional-acme-v1",
    })
    for label, declaration in sorted(export["tasks"].items()):
        if not isinstance(declaration, dict):
            ctx.issue("acme_invalid_task", "Task definitions must be objects; no code is interpreted.")
            continue
        source, target = declaration.get("input", ""), declaration.get("output", "")
        if not isinstance(source, str) or not isinstance(target, str) or not NAME.fullmatch(source) or not NAME.fullmatch(target):
            ctx.issue("acme_dynamic_reference", "Task input/output requires explicit qualified dataset names.")
            continue
        task = ctx.node("task", f"{artifact['path']}::{label}")
        ctx.edge(pipeline, task, "contains")
        src, dst = ctx.dataset(source), ctx.dataset(target)
        ctx.edge(src, dst, "data_flow", {"via": task, "semantics": "explicit fictional export input/output declaration"})
