# MVP verification checkpoint — 2026-10-29

The authorized local MVP is implemented as an independent Pipeline Handbook project.
No other project was used as input. All demonstration inputs are synthetic.

## Completed checkpoints

| Milestone | Concrete result | Verification |
| --- | --- | --- |
| Discovery/registry | Validated JSON configuration; structural detection; unknown inventory; separate rules and trusted components | Labeled technology/artifact pairs, dependency-vs-doc categories, misleading filenames, manual/hybrid selection, version conflicts |
| Reference adapters | Pentaho, shell/cron, PostgreSQL subset, Airflow AST, dbt manifest v12 | Manual lineage direction and column mappings; technology-specific flow semantics; unsupported/dynamic constructs stay gaps |
| Shared graph/evidence | Environment/service identities; exact same-source invocation references; validated SDK output | DEV/PROD and connection-ambiguity tests; per-source filters; provenance and redaction-collision tests |
| Handbook/change tracking | Markdown, JSON and offline HTML; impact, diff, status; reviewed annotations | All 237 internal HTML links resolve; Chrome orientation screenshot reviewed; stale hashes and preserved annotation tests |
| Extensibility/inspection | New data-only detector and explicitly trusted Acme adapter | No core rewrite; failure/timeout isolation; metadata-only worker operation guards and no secret-canary leakage |
| Fresh setup | Clean copied checkout using only Python and bundled inputs | Same semantic snapshot; all handbook formats and SQLite created without dependencies |

`python3 -m unittest discover -s tests -v` passed **65 tests**
in 13.019 seconds on Python 3.13.1 / macOS.
SQLite 3.50.3 was supplied by that interpreter. This is a tested local
setup, not certification for all Python/OS/vendor versions.

## Scoped measurements

`python3 demos/evaluate.py` observed:

- 17 manually labeled technology/artifact pairs: all presence and category assertions correct.
- 6 manually expected direct dataset edges: all present, with no extra direct dataset edges.
- 25 input files, 11600 bytes.
- 1.107144 seconds including CLI startup; peak child RSS 31604736 bytes.
- 12 adapter invocations; zero adapter failures for the bundled scan.

This is one small synthetic measurement. It does not measure universal detection,
all graph relationships, production scalability, live connections or vendor execution.
[Machine-readable measurements](observed-metrics.json) retain per-technology counts.

The final analyzed graph has 57 nodes and 65 typed relationships.
Its 17 findings expose unknown formats, dynamic definitions, deliberately
unsafe XML, version conflicts and unsupported behavior. Zero coverage findings is
not a success criterion when visibility is incomplete.

Semantic snapshot: `f3dc71e7b8ba5084f8f296b6`.
`status --config configs/demo.json` reported matching current local definition hashes,
registry and configuration. The source export dates remain separate from inspection
time; no successful vendor run is claimed.

See [the preview](handbook-preview.png), [capability boundaries](capabilities.md),
[guided exercises](exercises.md) and [remaining backlog](backlog.md).
