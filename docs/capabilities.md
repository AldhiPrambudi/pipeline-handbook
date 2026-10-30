# Tested support boundaries

The application is version **0.2.0**. Reference executable adapters are version
**1.0.0**, SDK **1** with additive backwards-compatible architecture fields, and
experimental portfolio implementations. The registry's feature declarations are emitted
by `python3 -m pipeline_handbook capabilities --json`. They are the authoritative
per-entry declarations; this guide explains the actually tested subsets.
Registry/rule versions are independent: the Docker rule entry is 1.1.0 for its
additional Compose detector/adapter selection. Use the emitted capability record
for each exact rule version.

**S** means a supported subset proven against the synthetic fixtures, **D** means
detection/declaration or documentation only, and **—** means unsupported. No row
means complete vendor/version compatibility. A declared dependency or image tag
does not prove installed server version or actual use.

| Technology / tested input version | Detect | Version | Metadata | Table lineage | Column lineage | Control | Schedules | Runtime | Handbook |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pentaho / PDI-style 9.4 XML fixture subset | S | — | S | S | S | S | — | — | S |
| PostgreSQL / 16 SQL subset; conflicting 15/16 image/export declarations | S | S | S | S | S | — | — | — | S |
| Shell / literal POSIX-like script subset, interpreter version unknown | S | — | S | — | — | S | — | — | S |
| cron / numeric five-field definition subset, implementation version unknown | S | — | S | — | — | — | S | — | S |
| Airflow / 2.10-style literal AST, dependency declaration 2.10.3 | S | S | S | — | — | S | S | — | S |
| dbt / manifest v12, tool declaration 1.8.8 | S | S | S | S | — | — | — | — | S |
| Snowflake / dbt adapter type, server version unknown | S | — | — | — | — | — | — | — | D |
| Docker / FROM declarations only; engine version unknown | S | — | — | — | — | — | — | — | D |
| Other catalogued technology candidates | D | — | — | — | — | — | — | — | D |

Snowflake dataset dependencies in this demo come from the **dbt artifact adapter**,
not a Snowflake SQL parser or live warehouse connector. The Snowflake client and
dbt-snowflake dependency versions never become a server version.
The synthetic PostgreSQL export's `collected_at` is 2026-01-15, independently of
the scanner's inspection time. Its declared server version is not a current live
observation. This release has no generic runtime/run metadata ingestion.

## Reference parsing subsets

- **Pentaho:** safe XML; TableInput with explicit PostgreSQL connection and a
  supported select, TableOutput declarations, enabled transformation stream hops,
  and job entry/hop conditions. KTR stream hops are data flow; KJB hops are control
  flow. TRANS/SHELL file references using the explicit
  `${Internal.Entry.Current.Directory}/` path basis can point to inventoried
  same-source files; a plain relative filename has unknown cwd and stays unresolved.
  Unknown plugins, dynamic paths, complex SQL and disabled hops do not become
  invented lineage. Direct TableInput projections plus explicitly enabled
  TableOutput field mappings provide the narrow column-mapping subset. Column
  lineage through arbitrary Pentaho steps is unsupported. Multiple physical
  connections or conflicting same-name connection definitions retain task metadata
  but omit dataset lineage until connection identity can be resolved.
- **SQL:** a PostgreSQL dialect marker or explicit reviewed override is required.
  Conservative CTAS and INSERT SELECT identify table sources/targets. Only direct,
  single-source named projections provide column mappings; INSERT mappings need
  an explicit target column list. CTEs, joins, aggregates, runtime SQL generation, wildcards,
  proprietary syntax and unsupported expressions need broader parsing/evidence.
- **Shell/cron:** shebang-based script recognition and numeric five-field cron
  definitions. Straight-line literal commands and explicit operators are the
  control subset. File invocation needs established working-directory context;
  dynamic expansion, loops, pipelines, mixed `&&`/`||`/`;` lists and unknown cwd remain findings. No shell
  command is run, and command order is not data lineage.
- **Airflow:** static AST imports, literal DAG/task IDs, declared schedule, operator
  attributes and literal `>>`, `<<`, `set_downstream` / `set_upstream` relationships,
  including literal task lists. Dynamic graph generation and compound flow are
  reported. TaskFlow, TaskGroups, arbitrary operator behavior, templated SQL/bash
  bodies, XCom data movement and runtime state are not reconstructed.
- **dbt:** manifest v12 metadata and qualified static model/source dependencies.
  Declared columns populate the dictionary; they do not prove column mappings.
  Runtime tests, actual materialization, macros, ephemeral/dynamic behavior and
  warehouse query semantics require separate analysis/evidence. A manifest is
  design metadata, not a successful run record.

## Catalogue breadth versus tested analysis

The expandable catalogue includes database/warehouse candidates (PostgreSQL,
SQL Server, Snowflake, BigQuery), ETL (Pentaho/dbt), orchestration (Airflow,
Dagster/cron), compute/languages (Python, shell, Spark, Databricks), messaging and
storage (Kafka, object storage), BI (Power BI, Tableau), and deployment
(Docker/Kubernetes). These are detector targets using the specific registry
signals. Detection-only candidates have no extraction adapter. Documentation-only
mentions remain mentions; ambiguous product signatures require clarification.

Only [tests/expectations.json](../tests/expectations.json) defines the manually
labeled detection pairs and dataset graph expectations used by the evaluation.
Accuracy on that small set does not establish accuracy across all catalog entries,
all files or real repositories. Negative cases include a misleading `airflow.py`,
an unlabeled SQL dialect and an unknown workflow. Adversarial inputs include
dynamic definitions, an unsafe XML entity declaration, fake secrets and embedded
prompt instructions.

## Verification and metrics

Run `python3 -m unittest discover -s tests -v` for acceptance and boundary tests.
Run `python3 demos/evaluate.py` for the documented labeled detection/graph counts
and measured scan duration/resource observations for the bundled input size.
The generated evaluation report records what was measured; it is not a universal
accuracy or performance claim. Definition-only fixtures cannot establish vendor
runtime compatibility.

Fresh setup, evidence anchors, JSON/Markdown/HTML outputs, manual/hybrid selection,
stable semantic snapshots, environment separation, rule/adapter extension and
fake-secret/no-execution boundaries are covered by explicit tests. Resource limits
are input/worker guards; optional OS rlimits vary by platform. No reusable
extraction cache exists: every scan reparses, avoiding stale cache hits by design.

## Architecture recovery extension — 2026-10-30

The extension adds two reference adapters, version 1.0.0, without adding runtime
dependencies or making Docker/vendor services prerequisites. The original
2026-10-29 measurements above remain baseline measurements, not extension accuracy.
The optional registry `architecture_features` object reports component inventory,
deployment configuration, configured connections, report consumers, exact bindings,
architecture views, workflow walkthroughs and technology-role evidence separately.
Older rule packs without this object remain valid and expose an empty declaration.
The handbook includes a folded architecture capability table in addition to the
original extraction/lineage feature matrix.

| Supplied input / feature | Implemented subset | Explicit boundary |
| --- | --- | --- |
| Normalized Docker Compose JSON | Static project/service/image declarations, named networks/volumes, literal startup dependencies/conditions and named-resource attachments | No Compose CLI/daemon invocation, implicit network guessing, bind-mount reads, command/environment/secret-body interpretation or observed runtime/placement |
| Environment-map `pipeline-handbook.environment/v1` | Explicit component/resource/report/form metadata, role/boundary/location/inspection declarations and exact semantic bindings between extracted endpoints | Supplied assertions remain declared; no native proprietary report parser, generalized name matching, excluded-asset bypass or cross-environment link resolution |
| Architecture projection | Evidence-backed findings, definition-backed source groups, technology roles, deployment/connection facts, output ancestry walkthroughs, separate controls/schedules, inspection points and unknowns | No prescribed architecture, guessed deployment layers, invented ownership/log locations, inferred successful communication or actual run sequence |
| Handbook extension | Offline HTML/Markdown architecture sections, distinct topology/data/control diagrams and JSON-pointer evidence locations | Existing snapshots without the new projection remain renderable; recommendations are empty unless separately justified in future work |

Compose project group labels do not establish physical/security boundaries, and
`depends_on` startup declarations are not data lineage. Named-volume attachments
do not prove files or business rows were inspected. A supplied environment-map
`data_flow` assertion is labeled declared and retains binding/endpoint evidence;
it is not independent parsing of a vendor report or runtime query history.

The new fixtures and tests include repeated DEV/PROD names, conflicting locations,
unsupported map versions, unknown/malformed fields, dynamic selectors, unavailable
metadata, excluded endpoints, misleading filenames and fake secret canaries.
See [the 2026-10-30 handover](checkpoint-2026-10-30.md) for extension verification
and [the recovery guide](architecture-recovery.md) for exact working commands.
