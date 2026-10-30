# MVP implementation contract

Python 3.11+, stdlib runtime. Configuration and rule packs use JSON (a constrained,
schema-validated format); YAML is a future optional frontend. No runtime dependencies,
network connectors, target-code execution, or LLMs. Tests use unittest.

## Adapter SDK v1

An explicitly registered trusted adapter exports `analyze(artifact, ctx) -> None`.
An artifact is a dict: `id`, `source_id`, `environment`, `service`, `path` (POSIX
relative to its source root), `hash`, `text`, `format` (extension without dot),
`size`. Text is transient; never persist it. All files have a bounded size.

Context API (implemented by core model):

* `ctx.node(kind, name, attributes=None, status='declared', line=1, namespace=None)`
  returns a stable string ID. Kinds: pipeline, task, dataset, column, schedule,
  run, source_system. Names must be qualified enough to avoid collisions.
  Dataset default namespace = source service; all other kinds = source ID.
* `ctx.dataset(name, columns=None, line=1)` returns a dataset ID. Optional columns
  is a list of names. Dataset IDs include environment, service and qualified name.
* `ctx.edge(source, target, kind, attributes=None, status='declared', line=1)`
  returns an edge ID. Kinds: data_flow, control_flow, contains, invocation,
  schedule, column_lineage, deployment. Data-flow direction = upstream to downstream.
* `ctx.issue(code, message, line=1, severity='warning')` records a coverage gap.
* `ctx.reference(from_id, target_path, kind='invocation', attributes=None, line=1)`
  defers a same-source relative artifact reference; absolute/traversal/dynamic
  references remain gaps. Set `entrypoint: True` on artifact entry pipeline nodes
  to allow exact path resolution. No basename guessing.
* `ctx.artifact`, `ctx.technology`, `ctx.overrides` and `ctx.config` are available.
  `ctx.overrides` is the selected technology override object (e.g. dialect).
* `ctx.evidence(line=1, reason='definition', status='declared')` returns evidence ID.

Core attaches source hash, adapter/rule versions, collection time, sanitized path,
and evidence IDs to every node, edge, explanation and issue. Attribute values and
names pass through central redaction. Adapters must never persist raw source text,
business-row data or literal credentials. Use only static parsing: AST, JSON,
DOCTYPE/ENTITY-rejecting XML, conservative grammar. No import/exec/eval/subprocess
or network access. Adapter failures are isolated and reported.

Rules supply detector signals and explanation templates, not executable parsers.
`mapping.concept` is retained in `rule_concepts`; `mapping.attribute_aliases`
copies parser-provided attributes into normalized names without changing identity.
Registry adapter IDs map to trusted project code independently of scanned content.
Rules do not supply import paths. Multiple eligible adapters may inspect one file.

## Canonical snapshot v1

`schema_version`, `project`, `snapshot_id`, `collected_at`, `effective_config`,
`registry_fingerprint`, `sources`, `artifacts`, `detections`, `nodes`, `edges`,
`evidence`, `issues`, `references`, `annotations`, `metrics`, `capabilities`.
Lists are deterministically sorted. Timestamp/elapsed metrics are excluded from
semantic snapshot IDs and diffs. Artifact text and absolute input roots are absent.
Evidence: `id`, `artifact_id`, `location` (source_id/path:Lx), `source_hash`,
`adapter`, `adapter_version`, `rule_id`, `rule_version`, `collected_at`, `reason`,
`status`. IDs are content-addressed from stable identity and evidence facts.
Node: `id`, `kind`, `name`, `environment`, `namespace`, `status`, `attributes`,
`evidence` (list), `explanation` (template-derived or literal factual statement).
Edge: `id`, `source`, `target`, `kind`, `status`, `attributes`, `evidence`.
Issue: `code`, `message`, `severity`, `artifact_id`, `evidence`.
Detection: technology, family, artifact_id, environment, category
(mentioned/declared/recognized/observed/ambiguous), confidence (high/medium/low),
versions (declared strings), reasons, evidence, support, selected, conflicts.
`version_kinds` qualifies version facts; `client_versions` is separate from
tool/server `versions`. `source_exported_at` is an unverified export declaration,
distinct from scanner collection time. `analysis_status` is per artifact, while
registry support describes the adapter's overall bounded capability.

Reviewed annotations are a separate user-owned JSON list (`node_id`, `purpose`,
`owner`, `sla`, `reviewed_by`, `reviewed_at`). Generation reads and never overwrites
the annotations file. No business purpose is inferred from names.
