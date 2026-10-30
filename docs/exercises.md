# Guided exercises and interview walkthrough

Use only the bundled synthetic artifacts. None of the scanner commands below
executes an inspected workflow. The separate [SQLite teaching exercise](../demos/README.md)
has explicit setup/run commands and does not establish vendor runtime behavior.

## 1. Trace a legacy output (10 minutes)

Run `python3 -m pipeline_handbook document --config configs/demo.json`, then open
the generated HTML. Find `final.orders` in DEV. Follow data flow back through
`staging.orders` to `raw.orders`. Open the evidence links. Explain which relationship
comes from `publish.sql` and which comes from `transform.ktr`.

**Expected answer:** static PostgreSQL and Pentaho definitions contribute to the
same canonical dataset model because environment/service/qualified names match.
The graph establishes declared dependencies in the supported subset, not that
the workflow ran. The matching PROD names have independent identities.

Read `pipeline_handbook/model.py` next. Locate `dataset`, `node` and `edge`.
Explain why environment and namespace enter the ID, while collection time does not.

## 2. Distinguish data from control (10 minutes)

Inspect `load.kjb` and its control-flow evidence. Compare its conditional hops
with the enabled stream hop in `transform.ktr`. Then inspect the modern DAG's
`stage >> publish` relationship.

**Expected answer:** a Pentaho job hop carries control/result conditions; a
transformation hop carries rows. Airflow task dependencies do not themselves
declare data transfer. None of these definitions proves deployment, successful
execution, retries that occurred, or a safe recovery action.

Read the adapters' `analyze` entry points. Point to where unsupported/dynamic
constructs are reported instead of evaluated. Explain why `ast.parse` is different
from importing a DAG module.

## 3. Inspect discovery limits (10 minutes)

Run `discover` and inspect `generated_handbook/discovery.json`. Compare the
misleading `fixtures/adversarial/airflow.py` with `fixtures/modern/dev/dag.py`.
Find Kafka/Tableau documentation mentions and the unknown workflow artifact.
Find the conflicting PostgreSQL version declarations.

**Expected answer:** imports/structures/declarations are evidence; a filename is
not. A docs mention is neither a deployment nor an active pipeline. Multiple
conflicting declared versions must remain visible. A Snowflake client version
does not establish the warehouse server version.

Read `pipeline_handbook/detection.py` and the PostgreSQL/DBT registry entries.
Explain the signal kinds, positive/negative handling and support boundaries.

## 4. Change selection and compare snapshots (15 minutes)

Run the manual and hybrid example configurations. Review recorded overrides,
excluded analysis and evidence conflicts. In a separate copy of the fixture
scope, change a single supported SQL target and scan with its own output path.
Pass the two stored snapshot JSON paths to `diff`.

**Expected answer:** an override is an auditable assumption, not a server
observation. Repeating the same inputs/rules/config produces the same semantic
snapshot ID even though collection timestamps change. Source/rule/adapter changes
invalidate semantic identity. Removed visibility does not prove a production
object was deleted.

## 5. Prove an extension (20 minutes)

Follow [the SDK guide](extending.md) to add a detector for a versioned synthetic
JSON export in a reviewed rule directory. First leave it detection-only. Then
write a trusted static adapter using `ctx.node`, `ctx.edge` and `ctx.issue`.
Register the local module and exact trust ID. Add a false-positive fixture and
manual graph expectation before running it.

**Expected answer:** detectors, rule packs and adapters have different jobs.
The extension changes configuration/reviewed code rather than the core engine.
A rule cannot invent a parser. Explicit executable trust is a stronger boundary
than merely parsing a file that claims to be a plugin.

## 6. Recover the supplied environment (15 minutes)

Run `python3 -m pipeline_handbook document --config configs/architecture.json`
and open the architecture handbook. Choose **DEV `orders.summary`** in workflow
walkthroughs. Trace its supplied report-consumer relationship through
`DEMO.FINAL.ORDERS`, `DEMO.STAGING.ORDERS` and `DEMO.RAW.ORDERS`. Inspect the
separately evidenced Airflow task/model bindings, task dependency and schedule.

Then choose **DEV `orders.review_form`**. Its supplied consumer binding points
to the legacy `final.orders` path. Compare Pentaho/SQL lineage with shell/job/cron
control evidence. Finally compare **PROD `orders.summary`**: identical report
names do not merge identities, and missing PROD controls remain unknown.

Read the separate deployment/connection map. Find the supplied Compose project,
reporting component and warehouse declarations; open object pointers for the
facts you use. Locate the deliberately conflicting location, unavailable metadata
binding and cross-environment reference. Explain why none can justify a guessed
edge or a claim that a service is running.

**Expected answer:** the architecture view recovers supplied evidence. Data
ancestry is an inspection sequence, not execution order. Invocation references,
actual task controls, schedules and configured topology stay distinct. Component
roles and report/form metadata are supplied declarations, not invented layers or
native proprietary report parsing. Findings and unknowns are separate from the
currently empty recommendations section.

Read `pipeline_handbook/architecture.py` and the two new adapter entry points.
Explain how the projection reuses the canonical graph and why it needs no extra
source/network access. Use [the 2026-10-30 checkpoint](checkpoint-2026-10-30.md)
to distinguish the reverified baseline from extension results.

## Interview explanation (about two minutes)

“I built an offline pipeline discovery and onboarding tool. It inventories only
authorized paths, recognizes multiple technologies from structural evidence,
and selects registered trusted adapters. Those adapters normalize different
workflow formats into one environment-aware graph. Every relationship links to
source evidence, content hashes and parser/rule versions.

“The important modeling choice is separating data lineage, task control flow,
runtime evidence and business interpretation. My reference legacy and modern
profiles show extensibility without claiming complete support for every tool.
The scanner never runs inspected code or queries business rows. Its generated
handbook exposes unknown/dynamic definitions and unsupported features alongside
the useful traceable subset.

“I verified the subset against manually labeled synthetic inventories, graph
edges, onboarding answers, malicious input fixtures and reproducible snapshots.
The next steps are a pinned SQL parser, broader fixtures and explicitly bounded
metadata connectors, each with its own capability evidence.”

Use the evaluation report's measured counts/timing when discussing results.
Do not describe fixture accuracy as universal accuracy or imply vendor workflows
were executed by the scanner.
