"""Static shell invocation and five-field cron declarations; no execution."""

import re
import shlex

VERSION = "1.0.0"
_DYNAMIC = re.compile(r"[\$`*?{}]|<\(|>\(")


def _command(tokens, ctx, pipeline, label, line, reviewed_cwd=False):
    if not tokens:
        return None
    if any(_DYNAMIC.search(token) for token in tokens):
        ctx.issue("shell_dynamic_reference", "Command contains expansion or substitution; runtime behavior is unresolved.", line=line)
        return None
    if tokens[0] == "exec":
        tokens = tokens[1:]
    if not tokens:
        return None
    executable = tokens[0].rsplit("/", 1)[-1]
    task = ctx.node("task", f"{ctx.artifact['path']}::{label}", {"executable": executable,
        "arguments": "omitted; source evidence retains location only", "working_directory": "source root (reviewed marker)" if reviewed_cwd else "unknown"}, line=line)
    ctx.edge(pipeline, task, "contains", line=line)
    target = None
    if executable in {"sh", "bash"} and len(tokens) == 2 and not tokens[1].startswith("-"):
        target = tokens[1]
    elif executable == "psql" and "-f" in tokens:
        index = tokens.index("-f") + 1
        if index < len(tokens):
            target = tokens[index]
    elif tokens[0].startswith("./"):
        target = tokens[0]
    if target:
        if reviewed_cwd:
            ctx.reference(task, target, attributes={"path_basis": "reviewed source-directory marker"}, line=line)
        else:
            ctx.issue("shell_working_directory_unknown", "Static file argument exists, but runtime working directory is not declared. Add a reviewed handbook working-directory marker before resolving a file relationship.", line=line)
            ctx.reference(task, target, attributes={"runtime_cwd": "unknown"}, line=line)
    elif executable not in {"echo", "printf", "true", "false"}:
        ctx.issue("shell_command_unresolved", f"Executable {executable} is declared; its workflow semantics are not analyzed.", line=line)
    return task


def _tokens(command, ctx, line):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        ctx.issue("shell_syntax_unknown", "Shell command could not be tokenized safely.", line=line)
        return None


def analyze(artifact, ctx):
    text = artifact["text"]
    pipeline = ctx.node("pipeline", artifact["path"], {"entrypoint": True,
        "definition_only": True, "technology": "shell/cron"})
    reviewed_cwd = bool(re.search(r"^\s*#\s*handbook:\s*working-directory=\.\s*$", text, re.M))
    cron = ctx.technology == "cron" or artifact.get("format") in {"cron", "crontab"}
    if not cron:
        # Do not flatten bodies from branches/functions/loops into unconditional
        # invocations. This subset either understands the whole straight-line
        # script or leaves its compound control flow explicitly unresolved.
        for line_number, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if re.match(r"(?:if|for|while|until|case|function|select|fi|done|esac|then|else|elif)\b", line) or "()" in line or line.endswith("\\") or "<<" in line:
                ctx.issue("unsupported_shell_control", "Compound shell control or multiline syntax prevents straight-line script analysis.", line=line_number)
                return
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if cron:
            if re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*=", line):
                ctx.issue("cron_environment", "Cron environment assignment declared; values are not persisted.", line=line_number, severity="info")
                continue
            match = re.fullmatch(r"([0-9*/?,\-]+)\s+([0-9*/?,\-]+)\s+([0-9*/?,\-]+)\s+([0-9*/?,\-]+)\s+([0-9*/?,\-]+)\s+(.+)", line)
            if not match:
                ctx.issue("unsupported_cron", "Only user crontab five-field numeric schedules are supported; macros/system user fields need another adapter.", line=line_number)
                continue
            expression = " ".join(match.groups()[:5])
            schedule = ctx.node("schedule", f"{artifact['path']}:{line_number}", {"expression": expression,
                "timezone": "unknown", "runtime_observed": False}, line=line_number)
            ctx.edge(schedule, pipeline, "schedule", line=line_number)
            command = match.group(6)
        else:
            command = line
            if re.match(r"(?:set|export)(?:\s|$)|[A-Za-z_][A-Za-z0-9_]*=", command):
                ctx.issue("shell_environment", "Shell environment/options declaration retained as a gap; values omitted.", line=line_number, severity="info")
                continue
        tokens = _tokens(command, ctx, line_number)
        if tokens is None:
            continue
        # Redirections, pipelines and background commands need richer shell ASTs.
        if any(token in {"|", "&", ">", ">>", "<", "<<", "<<<", "&>"} for token in tokens):
            ctx.issue("unsupported_shell_operator", "Pipeline, redirection, heredoc or background semantics are unsupported.", line=line_number)
            continue
        groups, operators, current = [], [], []
        for token in tokens:
            if token in {"&&", "||", ";"}:
                groups.append(current)
                operators.append(token)
                current = []
            else:
                current.append(token)
        groups.append(current)
        if len(set(operators)) > 1:
            ctx.issue("unsupported_shell_mixed_list", "Mixed shell list operators require branch-aware list semantics; this command line is not mapped.", line=line_number)
            continue
        if any(not group for group in groups):
            ctx.issue("shell_list_invalid", "Shell list has an empty command; no control-flow relationships were inferred.", line=line_number)
            continue
        previous = None
        for index, group in enumerate(groups):
            task = _command(group, ctx, pipeline, f"line-{line_number}-command-{index + 1}", line_number, reviewed_cwd)
            if previous and task:
                operator = operators[index - 1]
                ctx.edge(previous, task, "control_flow", {"condition": {"&&": "success", "||": "failure", ";": "completion"}[operator],
                    "semantics": "explicit shell list operator"}, line=line_number)
            previous = task
