# Evidence-backed backlog

Items here are unimplemented or only partially covered. Priority follows the
product lifecycle: widen discovery safely, then extraction/graph semantics,
then evidence-backed handbook utility and validation.

| Priority | Capability | Evidence motivating it | Completion evidence required |
| --- | --- | --- | --- |
| P1 | Broader SQL parser/dialect integration | Current adapter conservatively rejects joins, CTEs, dynamic expressions and ambiguous dialects. | Pin a maintained parser version/license; labeled multi-dialect fixtures; correct quoted identifiers, scopes and column lineage; no inferred PostgreSQL default. |
| P1 | Broader cross-tool project/selector recovery | The 2026-10-30 extension implements supplied exact environment-map bindings with endpoint provenance. Generalized project/selector discovery from arbitrary command bodies is still unsupported. | Broader authorized project/cwd semantics and unique references, negative same-name/project tests, evidence on every resolved edge; unresolved bindings remain gaps. |
| P1 | More representative vendor exports | Fixtures are small synthetic definition-only subsets, not exhaustive production exports. | Anonymized exports from documented versions; manually reviewed expected graphs; version/feature matrix additions and regression cases. |
| P1 | Hardened redaction and output review | Pattern redaction tests known fake canaries; unknown secret formats can exist. | Broader structured/literal/token fixtures, no leaks in SQLite/logs/reports/cache artifacts, documented residual limits. |
| P2 | Optional YAML configuration frontend | JSON-only MVP keeps a fresh setup dependency-free. | Pinned safe YAML loader/license, alias/depth/resource limits, same canonical validation, unsafe tag fixtures, no scope/trust changes. |
| P2 | Authorized live metadata connectors | MVP deliberately rejects network access settings; exported declarations cannot prove current deployments/runs. | Explicit endpoint/credential references, operation allowlists, least privilege, query/cost/pagination/time/concurrency bounds, no row sampling, permission failure tests. |
| P2 | Runtime evidence and freshness | Definitions and dbt manifests do not prove actual success; runtime columns are unsupported. | Time-bound run export parser with provenance, environment identities, observed status limited to supplied evidence, no fabricated runs. |
| P2 | Content-addressed extraction cache | MVP reparses everything for reliable invalidation. | Cache key includes source bytes, parser/rule/config fingerprints and environment; mutation/invalidation tests; no raw secrets persisted. |
| P2 | More BI/streaming/orchestrator analyzers | Power BI/Tableau/Kafka/Dagster/Spark/etc. are detection-only catalogue entries. | Separate trusted adapters, documented semantics and versions, canonical graphs with manually labeled positives/negatives and supported onboarding answers. |
| P2 | Native reports/forms and deployment variants | The architecture extension handles supplied normalized Compose/environment-map declarations; it does not parse arbitrary applications, BI exports or infer live placement. | Vendor/version-specific adapters and anonymized exports, manually reviewed component/report lineage, exact bindings, distinct definition/runtime evidence and placement ambiguity tests. |
| P3 | OpenLineage export interoperability | Canonical model adopts Job/Dataset/Run separation, but no wire exporter exists. | Validate design-time events against pinned official schema; never emit RunEvents for static definitions; namespace round-trip tests. |
| P3 | Business glossary and annotation review workflow | Purpose/ownership/SLA cannot be inferred from file names. | Preserve reviewer identity/time, handle orphaned IDs, support reviewed terminology without overwriting human edits. |
| P3 | Larger scan benchmarks | Current evaluation covers a small synthetic input set on the local machine. | Fixed input corpus/size, pinned machine/runtime details, repeated wall/CPU/RSS measurements, report per-capability accuracy and resource failures. |

Adding a technology name to the catalogue does not close an analyzer backlog
item. Each feature needs its own tested support declaration. No backlog item
authorizes scanning new paths, installing agents or making live connections.
