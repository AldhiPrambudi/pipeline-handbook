# Detector, rule-pack and adapter SDK guide

Read [the implementation contract](implementation-contract.md) for exact artifact,
Context and snapshot fields. Extensions have three distinct responsibilities:
detectors recognize candidates, rule packs state applicability/capabilities and
explanation templates, and adapters parse supported semantics into canonical facts.

## Add a detector without changing core code

Put a reviewed `*.rules.json` file in a configured `rules.directories` directory
outside every scanned scope. Packs have `schema_version: "1"` and an `entries`
list validated against [the rule-pack schema](../schemas/rule-pack.schema.json).
Unknown fields fail validation. Rule directories are not recursively scanned;
symlink packs are rejected. Rule IDs must be unique; conflicting duplicate IDs
are configuration errors.

The [shipped registry](../pipeline_handbook/data/builtin.json) provides complete
entries to copy. Every entry includes a stable ID/version, technology/family,
applicable versions, positive/negative signals, mention terms, applicability,
conflict policy, formats/prerequisites, feature matrix, access/configuration
requirements, test/fixture references, maturity, official references and mapping.

A detector for an internal JSON export can use this positive signal:

```json
{
  "kind": "json_fields",
  "fields": {"format": "example-flow/v1", "tasks": "$array"},
  "category": "recognized",
  "reason": "versioned export signature and task array",
  "version_field": "exporter_version",
  "version_kind": "tool"
}
```

Declare `adapters: []` and detection-only maturity until an analyzer is implemented.
Place a negative signal for a known conflicting schema in `negative` rather than
silently choosing a product. Multiple positive signals are alternatives; each
signal may itself require a structural combination. `contains_all` requires all
listed literals, while `json_fields` requires all field predicates. Dot-separated
field paths inspect objects; `$object`, `$array` and `$present` are constrained
predicate values, not executable expressions.

Other implemented signal kinds are `python_import`, `xml_structure`, `dependency`,
`docker_from`, `shell`, and `cron`. The latter static recognizers are built-in
parsers; a new syntax requires code, not an arbitrary regex or expression in a
rule. File extensions do not serve as the sole positive signal. Documentation
terms produce mention-level evidence. Offline rule labels cannot manufacture a
live runtime observation.

`mapping.explanation` supports literal replacements for `{name}`, `{kind}` and
`{technology}`. `mapping.concept` is retained in each node's `rule_concepts`.
The adapter controls actual node/edge creation. `mapping.attribute_aliases`
can copy already parsed attributes to normalized names, for example
`{"label": "display_name"}`. Identity/relationship attributes are reserved.
These declarative mappings cannot add a parser or justify business interpretation.

Include the reviewed directory in configuration and rerun `discover`. Verify a
positive structural fixture, negative lookalike, documentation-only mention and
version conflict. Add manually expected outputs before trusting the new rule.

## Add a trusted adapter without rewriting the core

Create a reviewed Python module **outside the input and output scopes**. It exports:

```python
import json

def analyze(artifact, ctx):
    data = json.loads(artifact["text"])
    if data.get("format") != "example-flow/v1":
        return
    pipeline = ctx.node("pipeline", artifact["path"] + ":example", {"entrypoint": True})
    previous = None
    for item in data.get("tasks", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            ctx.issue("example_invalid_task", "Expected a literal task name.")
            continue
        task = ctx.node("task", artifact["path"] + ":" + item["name"])
        ctx.edge(pipeline, task, "contains")
        # This example export must explicitly define list order as execution order.
        if previous is not None:
            ctx.edge(previous, task, "control_flow", {"condition": "declared list order"})
        previous = task
```

Only use this ordering logic for an export whose documented semantics actually
define list order as execution order. Names/arrows alone do not justify it.
Treat input as data; never import/exec/eval/source it. Static parser failures and
unsupported constructs must become `ctx.issue` findings, not guessed edges.

Register an explicit component in the configuration:

```json
{
  "adapters": {
    "trusted": ["builtin:*", "portfolio:example"],
    "plugins": [{
      "id": "portfolio:example",
      "path": "../examples/trusted_plugins/example.py",
      "version": "1.0.0",
      "technologies": ["example-flow"],
      "priority": 100
    }]
  }
}
```

The snippet describes registration; create that module and a matching complete
rule entry before using it. `plugins` is explicit local project code registration,
not package discovery. Exact-ID trust is required for external components; input
files cannot suggest an import or installation. A new adapter can share a
technology with another one; priority determines inspection order, all eligible
components may run, and conflicts remain reportable. Per-technology
`overrides.adapter` can select an eligible adapter ID explicitly.

Workers bound wall time and input/node resources; CPU/address-space rlimits apply
where available. Application audit guards reject process/socket operations,
filesystem writes, reads of inspected files and dynamic execution. Adapters receive
the bounded input in memory and may load their trusted component and installed
parser modules. Worker stdout/stderr is discarded, and errors persist only safe
exception types. These guards are not an OS security sandbox for malicious native
code. Review executable adapter code before adding it to the trust list.

## Context and graph rules

- `node` and `dataset` create stable environment-aware IDs. Dataset/column defaults
  use source `service`; other definitions default to source ID. Use qualified names.
- `edge` requires an explicit relationship kind and direction. `data_flow` and
  `column_lineage` point upstream to downstream. Control flow preserves the
  technology's actual conditions. A hop cannot automatically be both kinds.
- `reference` defers a literal same-source file relationship to an artifact's
  `entrypoint` pipeline. Unresolved/dynamic targets remain gaps. Never guess by
  basename or read outside the authorized inventory.
- Core attaches evidence: relative path/line, original source hash, parser/rule
  version, timestamp and declared/inferred/observed/unknown status. Central
  redaction sanitizes facts before persistence. Do not emit raw SQL bodies,
  command secrets, business rows or credential values as attributes.
- Use `ctx.overrides` for the selected technology's reviewed dialect/version
  assumptions. Overrides must remain distinguishable from detected evidence.

Node attributes must be objects, dataset columns must be lists of strings, and
`entrypoint` must be boolean when present. Workers validate the complete JSON tree,
counts/depth/size, provenance and endpoint references before merging results;
malformed component output is discarded as a whole. IDs hash the original stable
identity while published names/namespaces remain redacted, avoiding collisions
between different sensitive names that redact to the same display label.

## Additive architecture SDK interface

The 2026-10-30 extension adds `component`, `deployment_resource` and `report`
node kinds plus `connection` edges. A connection is an explicitly configured
reference, not a successful communication or data-flow assertion. A report may
carry a supplied `report_type` such as dashboard or form; the node is not evidence
that the scanner parsed a proprietary vendor definition.

`ctx.evidence`, `ctx.node`, `ctx.edge` and `ctx.issue` accept an optional
`object_path` JSON pointer. Preserve the normal relative line location too.
For example, `/services/airflow/image` identifies a field in a supplied Compose
JSON export without copying its whole raw body into persisted metadata.

`ctx.link(source_selector, target_selector, kind, attributes=None, line=1,
object_path=None)` defers an exact semantic binding until eligible adapters have
finished. Each selector requires `kind`, `name`, `environment`, `namespace`,
`source_id` and `artifact_path`. The engine requires an extracted node with that
exact identity and evidence from the specified inventoried artifact. Missing or
ambiguous endpoints and cross-environment bindings remain gaps. This method cannot
authorize reads, bypass exclusions or create missing assets. Supported declared
binding kinds are invocation, deployment, connection and data_flow.

`ctx.result()` now includes `links`; old adapter result objects without that
field remain valid. The architecture projection is derived from canonical facts,
with significant records carrying `text`, `status` and evidence IDs. It keeps
findings/questions separate from recommendations. See the
[extension contract](extension-contract.md) and [recovery guide](architecture-recovery.md).

Application 0.2.0 retains SDK v1 compatibility. Registry entries may additionally
declare `architecture_features` for component inventory, deployment configuration,
configured connections, report consumers, exact bindings, architecture views,
workflow walkthroughs and technology-role evidence. This field is optional for
existing reviewed packs; omission yields an empty architecture declaration rather
than inventing support. Old snapshots and adapter results remain renderable.

## Reviewed annotations and regeneration

Set `annotations` to a JSON file outside scanned sources and generated output. It contains a list
of reviewed records such as:

```json
[{
  "node_id": "copy-an-exact-node-id-from-latest.json",
  "purpose": "Owner-reviewed synthetic order demonstration",
  "owner": "Demo engineering team",
  "sla": "No production SLA; teaching fixture",
  "reviewed_by": "Portfolio author",
  "reviewed_at": "2026-10-29"
}]
```

Generation reads and never overwrites this file. A changed identity may leave an
annotation unmatched; review it rather than transferring it by name to another
environment/service. Annotations are reviewed business context, not runtime facts.

## Extension acceptance checklist

Prove expected inventories and canonical graphs on manual fixtures, exact
provenance, false-positive/conflict cases, error isolation, no target execution,
redaction canaries, deterministic snapshots, and useful handbook answers. Record
versions/features actually tested. The new adapter should require only a reviewed
module, registry/configuration entries and tests; core parsing/orchestration code
should remain unchanged.
