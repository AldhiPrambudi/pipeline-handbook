# Recover the architecture that the evidence describes

The architecture extension answers a different onboarding question from a
technology list: Which components and workflows does this supplied environment
actually describe, how do they relate, and where should a newcomer inspect next?

It reconstructs a bounded view from authorized metadata. It does not impose
bronze/silver/gold layers, select a preferred deployment design, or rename an
unfamiliar stack into a standard architecture. Findings describe evidence;
unknowns identify missing evidence. Recommendations are a separate collection,
currently empty.

## What supplies the facts

The existing canonical graph remains the source for pipeline definitions,
datasets, columns, schedules, invocation and task control. The additive reference
parsers accept two local metadata forms:

- **Normalized Docker Compose JSON:** supplied service/image, network, volume and
  `depends_on` declarations. These are configuration facts. They do not prove a
  host, active deployment, healthy service or successful network communication.
- **Environment-map v1:** an explicitly versioned declaration/export with
  components, optional reports/forms, inspection points and exact relationship
  bindings. This format supplies context that workflow definitions may not carry.
  It is not an independent runtime observation or a native Power BI/Tableau parser.

The map's format marker is `pipeline-handbook.environment/v1`. The schema and
bounded parsing validate records before they become graph facts. Input text is
data; it cannot provide executable instructions, plugins or commands to run.
Local authorization, redaction, size/resource guards and no-execution invariants
continue to apply.

## Reading the recovered handbook

Run `python3 -m pipeline_handbook document --config configs/architecture.json`
and open `generated_architecture/index.html` offline.

1. **Architecture overview:** read recovered findings, components and technology
   roles with their statuses/evidence. A source/service grouping means definitions
   share a configured context; it does not prove an independently deployed service.
2. **Deployment and connections:** inspect the separate diagram and relationship
   table. Boundary/project groups use labels found in supplied metadata. A Compose
   project label does not prove a physical or security boundary. “Boundary not supplied”
   means unknown context, not a discovered application layer. Connection means an
   explicit configured reference; it does not assert successful communication.
3. **Workflow walkthroughs:** choose a dataset or report/form output. Numbered data
   steps guide inspection through its ancestry and producing definitions. They are
   not inferred execution order. Actual task dependencies, trigger conditions and
   schedules appear separately when linked by evidence.
4. **Inspection guide:** use source locations and structured-object pointers to
   find the exact definition. Declared logs/report locations are pointers, not
   proof that files exist or that a run succeeded.
5. **Unknowns and questions:** identify the export, binding, permission or human
   clarification needed before drawing a stronger conclusion.
6. **Recommendations:** inspect this separate section only for separately justified
   suggestions. The initial extension generates none.

The data-flow and control-flow diagrams remain available alongside the architecture
view. A configured connection, deployment edge or report name never silently
becomes data lineage. No safe recovery procedure or business ownership is guessed.

## Exact cross-tool relationships

The environment map can bind extracted assets using a complete selector:

```json
{
  "kind": "task",
  "name": "dag.py::warehouse_orders::publish",
  "environment": "dev",
  "namespace": "modern_dev",
  "source_id": "modern_dev",
  "artifact_path": "dag.py"
}
```

The selector is illustrative: its kind/name must exactly match the target record
in that scan.
The engine also requires evidence from the stated source/artifact. Copy actual
values from `latest.json`; do not guess from a filename or display label.

Bindings resolve only after eligible extraction completes, independently of
source/artifact order. Zero or multiple matches, excluded adapters/artifacts,
dynamic references, or unsupported cross-environment links remain findings.
Selectors do not authorize extra reads, bypass filters, parse an unsupported
format, or manufacture missing endpoints. Resolved relationships retain the
binding evidence and evidence for both endpoints.

## Provenance and interpretation

Each important derived record includes factual text, status and evidence IDs.
Source evidence retains the relative line location and can additionally carry an
`object_path` JSON pointer, such as `/services/airflow/image`. This provides an
inspection target even when a whole JSON export occupies one source line.

Declared component role, location and report type remain supplied assertions.
Derived grouping/ancestry is marked inferred and remains traceable to the graph.
Unknown runtime state, ownership, deployment context and log visibility stay
explicit. Scanner inspection time is different from the export's own timestamp.

No real target environment is bundled or scanned by these examples. The generated
architecture describes the synthetic supplied profile within tested coverage.
To recover a real system, the next input is a reviewed configuration authorizing
specific anonymized exports/paths plus environment/service identities and any
reviewed component/binding metadata needed to resolve ambiguity.

## Code walkthrough

1. Review registry entries for the two new detectors and trusted adapters.
2. Read `adapters/compose.py` and `adapters/environment_map.py` for bounded local
   parsing and canonical node/relationship creation.
3. Read SDK `Context.link` and engine resolution: exact selectors retain endpoint
   provenance and cannot create assets by themselves.
4. Read `architecture.recover(snapshot)`: it projects components, technology roles,
   relationship facts, walkthroughs, inspection points and questions from the
   canonical snapshot; it has no extra source/network access.
5. Read the renderer's architecture sections, then compare them with canonical
   `nodes`, `edges` and `evidence` in `generated_architecture/latest.json`.

Tests compare manually expected supplied facts, ambiguity/unknown cases, safety
boundaries and presentation semantics. Generalized architecture inference,
native proprietary report parsing and live runtime verification remain outside
this milestone.
