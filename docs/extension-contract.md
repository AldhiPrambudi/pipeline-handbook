# Architecture recovery extension contract (2026-10-30)

Baseline verified: 65 tests; analyzed snapshot `f3dc71e7b8ba5084f8f296b6`;
25 synthetic artifacts, 57 nodes, 65 typed edges. `status` reports definition
hashes/configuration/registry current. No running agent work or Git metadata.
The existing local CLI, registry, five adapters, safety boundaries and human
annotation files are preserved. No real target environment has been supplied.

## Smallest useful milestone

Reuse the canonical evidence graph and add architecture recovery as a derived
view, not a prescribed target architecture. Add component, deployment_resource
and report node kinds. Existing data_flow, control_flow, deployment and invocation
relationships retain their semantics; new connection relationships mean only
explicit configured references, never successful communication.

Two registry-selected trusted parsers add bounded local metadata coverage:

1. `builtin:compose` (`adapters/compose.py`): Docker Compose normalized JSON
   exports, static service/image/network/volume/depends_on declarations. Host and
   actual deployment/running state remain unknown unless separately declared.
2. `builtin:environment_map` (`adapters/environment_map.py`): an explicitly
   versioned, vendor-neutral declaration/export format for component boundaries,
   location/inspection points, reports/forms and exact cross-tool bindings.
   This is declared supplied metadata, not independent runtime observation or
   a parser for Tableau/Power BI/proprietary reports.

## Additive SDK v1 additions (root implements)

`ctx.evidence(..., object_path=None)`, `ctx.node(..., object_path=None)`,
`ctx.edge(..., object_path=None)`, `ctx.issue(..., object_path=None)` accept an
optional JSON pointer such as `/services/airflow/image`. Evidence retains its
source-relative line location and additionally stores `object_path`.

`ctx.link(source_selector, target_selector, kind, attributes=None, line=1,
object_path=None)` stores a deferred exact semantic relationship. `ctx.result()`
adds `links`; validators accept old results without it. Root resolves links only
after all eligible adapters complete, independent of artifact/source order.

Each selector has six required fields: `kind`, `name`, `environment`, `namespace`,
`source_id`, `artifact_path`. They must match an extracted node and evidence from
that exact inventoried artifact. Non-dataset namespaces default to source ID;
dataset/column namespaces default to configured source service. Selectors do not
authorize reads or parsing, bypass exclusions, or manufacture missing assets.
Cross-environment links are unsupported in this milestone and remain gaps. Zero
or multiple matches remain unresolved. Status is declared; exported assertions
cannot manufacture observed events. All resolved edges retain binding and
endpoint evidence; connection/deployment/invocation are separate from data flow.

## Environment-map format v1

JSON object with `format: "pipeline-handbook.environment/v1"`, `components` and
`links` arrays (both required). Optional `reports` array. A component record has
`name` (stable qualified identity), optional `technology`, `role`, `boundary`,
`location`, `inspection_points` (array of `{kind, location}`), and `resource_type`
(default component; deployment_resource allowed). All are explicit declarations.
A report has `name`, optional `report_type` (report/dashboard/form), `technology`,
`inspection_points`. Use links for data consumers and deployments; no name guesses.
Components/reports created by the map use source ID namespace. Field validation
must reject malformed/unknown keys, unsupported versions and unsafe references.

A link has `source`, `target` selectors, `kind` (invocation/deployment/connection/
data_flow), optional `attributes` object. Ordinary node and edge evidence comes
from its structured-object pointer. Map attributes are constrained factual
metadata, never instructions/plugins/commands to run. Known sensitive fields
and literal bodies are omitted; central redaction remains mandatory.

## Derived view (root implements architecture.py)

`recover(snapshot) -> dict` returns `schema_version`, `findings`, `components`,
`technology_roles`, `relationships`, `walkthroughs`, `inspection_points`,
`questions`, `recommendations`. Every significant record has `id`, `status`,
`evidence` and factual `text`; node/edge references where applicable. Findings are
separate from recommendations (empty unless a separately justified suggestion is
implemented). No standard bronze/silver/gold or application layers are assumed.
Components include explicitly extracted component/resource/report nodes and
definition-backed service/source groupings; mentions/dependencies do not become
deployed services. Walkthroughs trace dataset/report outputs to upstream datasets,
producing definitions, schedules, control conditions and inspection locations,
without equating data ancestry/topological presentation with execution order.
Unknown deployment/runtime/ownership/log visibility is explicit. Readable graph
views group only found environments and boundaries with evidence.

Snapshot adds `architecture` after canonical graph extraction. Existing snapshot
fields, commands and annotations remain compatible. `discover` does no adapter
extraction. New graph kinds are an additive SDK change, not a core rewrite.
