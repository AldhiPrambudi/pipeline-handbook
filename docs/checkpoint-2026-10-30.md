# Extension checkpoint and handover — 2026-10-30

## Verified starting point

The existing standalone Pipeline Handbook MVP was rechecked before extension.
The starting suite passed **65 tests**. Baseline analyzed snapshot
`f3dc71e7b8ba5084f8f296b6` contains 25 synthetic artifacts, 57 nodes and 65 typed
edges. Definition hashes, configuration and registry matched that checkpoint.
The earlier [2026-10-29 verification record](verification.md), measurements and
baseline generated handbook remain a dated record; they are not relabeled as
measurements of the extension.

The starting product already supplied local inventory, registry-selected static
adapters, a shared evidence graph, handbook formats, impact/diff/status, reviewed
annotations and bounded inspection. Its graph did not yet express a useful
recovered component/deployment/connection view or a consolidated output walkthrough.
No real target environment has been supplied.

## Additive implementation

The architecture recovery milestone preserves the core lifecycle and existing
interfaces while adding:

- Registry-selected parsers for supplied normalized Docker Compose JSON and the
  explicitly versioned environment-map declaration/export.
- Canonical component, deployment-resource and report/form nodes plus explicitly
  declared connection relationships.
- Deferred exact semantic bindings that require extracted endpoints and their
  source/artifact evidence, and cannot bypass authorization or exclusions.
- A derived architecture projection: factual findings, components/roles,
  relationship facts, output walkthroughs, inspection points and questions.
- Offline HTML/Markdown architecture sections with a distinct deployment/connection
  map, explicit boundary labels and evidence-object pointers. Existing data/control
  diagrams remain separate. Recommendations remain a separate empty collection.

The [extension contract](extension-contract.md) records the interface and boundary
decisions. The [recovery guide](architecture-recovery.md) explains how to inspect
the resulting handbook and distinguish data ancestry from task execution order.

## Verification checkpoint

The renderer's 11 architecture tests and 3 existing renderer tests pass together.
They verify separate topology/data/control views, actual evidence links, unique
anchors, escaped input, structured-object pointers, old-snapshot compatibility,
explicit unknown boundaries and an empty recommendation state.

The complete suite passed **118 tests in 15.867 seconds** on Python 3.13.1 / macOS.
The independent architecture evaluator matched all manually expected 20 explicit
assets, 5 configured connections, 8 declared placements, 4 startup dependencies
and 2 exact task/model bindings. All 3 named report/form walkthrough checks passed.
Unsupported versions, malformed declarations, missing/excluded endpoints,
conflicting locations and cross-environment references remained visible gaps.

[Machine-readable architecture measurements](architecture-observed-metrics.json)
record the labeled subset and one fresh document scan: 34 synthetic input files,
31,083 inventoried bytes, 20 adapter invocations and zero adapter failures.
That scan took 1.699491 seconds including CLI startup and rendering, with peak
child RSS 38,567,936 bytes. These observations are specific to this small local
profile; they do not establish production scalability, universal accuracy,
live communication or successful vendor runs. The prior 65-test count and baseline
timings remain historical baseline results.

Final architecture snapshot: `ad517b6dbe554bcefacb271b` (application 0.2.0).
It contains 79 nodes, 95 typed edges, 26 explicit coverage findings and 12 generated
output walkthroughs; the manually checked report/form subset is the 3 cases above.
The architecture projection was not truncated. All 2,070 internal HTML links
resolve, with 321 unique IDs and no duplicate anchors. Derived records retain
resolvable source evidence. Canary checks passed across reports, SQLite and
snapshot history.

A clean copied checkout reproduced the same semantic snapshot and created
HTML/Markdown/JSON/SQLite outputs using only the standard library. `status`
reported current source/configuration/registry evidence. The dated baseline
generated handbook and 2026-10-29 measurement files were preserved. Exact commands,
environment and file-integrity records are in
[the extension verification record](extension-verification.json).

Reproduce the extension checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m pipeline_handbook discover --config configs/architecture.json
python3 -m pipeline_handbook document --config configs/architecture.json
python3 -m pipeline_handbook status --config configs/architecture.json
```

The architecture profile writes to `generated_architecture`, independently of the
dated baseline in `generated_handbook`. A changed analyzer/registry fingerprint
can correctly make an older baseline stale under current code without invalidating
what its historical checkpoint measured.

## Handover and exact next step

The [browser preview](architecture-preview.png) records the final offline handbook's
orientation and architecture entry point. A headless Chrome render was visually
reviewed; the automated suite additionally verifies the topology, walkthroughs,
source-object pointers and all internal links. No vendor environment was run.

Start with [generated_architecture/index.html](../generated_architecture/index.html):
choose **DEV `orders.summary`**, follow its data-ancestry inspection sequence to
the dbt manifest's final/staging/raw datasets, review the separately declared
Airflow task controls/schedule, and open each source-object evidence pointer.
Compare **DEV `orders.review_form`** with the legacy path and **PROD
`orders.summary`** with its independent identity and missing control visibility.
Confirm the unresolved binding and runtime questions before interpreting the
architecture.

For a real system, first supply a reviewed configuration authorizing specific
anonymized repository/export paths and explicit environment/service identities.
Include available component/deployment exports and owner-reviewed exact bindings;
leave missing facts unknown. Then run `discover`, inspect detected support/gaps,
and run `document` within that approved scope. No live scan or network connection
is implicitly authorized by this synthetic demonstration.

Real-environment evidence is future input, not a condition for completing this
synthetic architecture-recovery milestone. The next immediate step is the named
reader exercise above; the supplied profile already demonstrates the implemented
local extension and its explicit limits.

The next product work is broader parser/export coverage and ambiguity fixtures,
not a prescribed target architecture. [The backlog](backlog.md) distinguishes this
implemented exact-binding subset from generalized inference, live metadata and
native BI/report analyzers that remain unimplemented.
