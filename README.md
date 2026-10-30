# Pipeline Handbook

Recover the existing architecture and workflows described by authorized local
evidence. Discover the stack, select trusted analysis adapters, and turn supported
definitions into an onboarding handbook with technology roles, inspection points
and explicit unknowns. Recovered findings stay separate from recommendations;
the tool does not prescribe a target architecture.
This is an independent portfolio project with a technology-agnostic core. The
included legacy and modern stacks are reference profiles, not the product boundary.

The local MVP uses **Python 3.11+ and its standard library only**. No LLM, paid API,
cloud account, database server, package download or vendor runtime is required.
Bundled demonstration fixtures are synthetic, definition-only exports. A separately
labeled public case study uses an anonymized projection of an authorized NCBS scan.
Secure file inspection requires POSIX filesystem APIs; verification was performed
on macOS. Windows support has not been implemented.

## Fresh setup

From the repository root:

```sh
python3 --version
python3 -m unittest discover -s tests -v
python3 -m pipeline_handbook discover --config configs/demo.json
python3 -m pipeline_handbook analyze --config configs/demo.json
python3 -m pipeline_handbook document --config configs/demo.json
```

Open [generated_handbook/index.html](generated_handbook/index.html) in a browser.
It works offline and includes evidence links, separate data/control diagrams,
assets, column mappings, capability declarations and coverage findings. The same
scan produces [Markdown](generated_handbook/handbook.md) and
[JSON](generated_handbook/handbook.json). Snapshot records live in
`generated_handbook/snapshots/`; `latest.json` and `metadata.sqlite` retain local
sanitized metadata. `document` performs a fresh scan, analysis and generation.

## Architecture recovery example

The additive architecture example includes normalized Docker Compose JSON,
an explicitly versioned environment-map declaration, and the existing pipeline
exports. It demonstrates found components/boundaries, deployment and configured
connections, reports/forms, exact cross-tool links and output walkthroughs.

```sh
python3 -m pipeline_handbook discover --config configs/architecture.json
python3 -m pipeline_handbook document --config configs/architecture.json
python3 -m pipeline_handbook status --config configs/architecture.json
```

Open [generated_architecture/index.html](generated_architecture/index.html).
The walkthroughs distinguish data ancestry from actual declared task dependencies;
the deployment/connection view is separate from both. Structured evidence links
include source-object pointers. A Compose declaration does not prove a running
container; a supplied report/form description is not a native BI analyzer.

This profile writes to `generated_architecture`, leaving the dated baseline
handbook in `generated_handbook` available for comparison. Both demonstration
profiles use synthetic declarations. See the
[2026-10-30 checkpoint and handover](docs/checkpoint-2026-10-30.md) and
[architecture-recovery guide](docs/architecture-recovery.md) for boundaries and
the next evidence needed for a real system.

## Public handbook and deployment

Public target: [GitHub repository](https://github.com/AldhiPrambudi/pipeline-handbook)
and [GitHub Pages handbook](https://aldhiprambudi.github.io/pipeline-handbook/).
The public site presents the synthetic demonstration and a separately labeled
anonymized NCBS case study. Private source paths, asset names and local scan state
are excluded from the publication input.

```sh
python3 demos/build_public_site.py --output public_site
```

The builder accepts only reviewed bundled fixtures and the explicitly approved
public case projection; it stages a strict file allowlist. CI runs on pushes/PRs;
Pages publishing is an explicit `main` workflow dispatch. See the
[deployment guide](docs/deployment.md) for reproducible builds, permissions,
immutable action pins and exact publication boundaries.

The authorized NCBS test inspected 186 local source/metadata files and matched
all 12 independently counted service declarations across five primary Compose
profiles. No NCBS code or services were run, and existing working-tree changes
were preserved. Its dbt lineage remains unsupported without a compatible exported
manifest. See [NCBS scope and limits](docs/ncbs-compatibility.md) and the
[anonymized public report](https://aldhiprambudi.github.io/pipeline-handbook/ncbs/).

## Working commands

```sh
python3 -m pipeline_handbook capabilities
python3 -m pipeline_handbook capabilities --json
python3 -m pipeline_handbook analyze --config configs/manual.json
python3 -m pipeline_handbook analyze --config configs/hybrid.json
python3 -m pipeline_handbook status --config configs/demo.json
python3 -m pipeline_handbook impact --config configs/demo.json --asset staging.orders --environment dev --service legacy_orders
python3 -m pipeline_handbook impact --config configs/demo.json --asset final.orders --environment dev --service legacy_orders --direction upstream --kind data_flow
python3 -m pipeline_handbook diff generated_handbook/latest.json generated_handbook/latest.json
python3 demos/evaluate.py
```

`diff` accepts any two snapshot JSON files; the same-file example is an intentional
zero-change check. Impact follows only extracted relationships. When a name is
ambiguous across environments, supply `--environment` and `--service`, or use
the exact node ID from `latest.json`. `status` rechecks file hashes and the current
registry/configuration against `latest.json`; its coverage flag warns when the
check was incomplete. A saved handbook does not poll its source files.

## Configure a new scan

Copy [configs/demo.json](configs/demo.json), authorize only the paths you intend
to inspect, and choose a separate output directory. Relative paths resolve against
the configuration file. Sources carry explicit environment and service identities.
DEV and PROD names remain distinct. Keep real credentials out of configuration.

The MVP accepts **JSON configuration and JSON rule packs**. YAML is deferred to
keep a fresh setup dependency-free. Schemas are in [schemas/](schemas/); unsupported
keys and values fail validation. Auto mode discovers eligible candidates; manual
mode requires explicit technology IDs; hybrid combines discovery with reviewed
overrides/exclusions. Overrides stay recorded assumptions, not observed facts.

The scanner does not import or execute inspected code, run pipelines or SQL,
sample business rows, contact services, or install suggested plugins. Its local
inspection boundaries, redaction and resource limits are documented in
[architecture](docs/architecture.md). Trusted executable extensions are project
code with explicit configuration; they are not an operating-system sandbox.

## Learn and extend

- [Product brief, architecture and ADRs](docs/architecture.md)
- [Architecture recovery and output walkthroughs](docs/architecture-recovery.md)
- [Tested capabilities and limitations](docs/capabilities.md)
- [Detector/rule-pack and adapter SDK guide](docs/extending.md)
- [Guided exercises and interview walkthrough](docs/exercises.md)
- [Separate explicit synthetic data demo](demos/README.md)
- [Official references, standards comparison and licenses](docs/references.md)
- [Evidence-backed backlog](docs/backlog.md)
- [Manual fixture expectations](tests/expectations.json)
- [Completed verification checkpoints and measurements](docs/verification.md)
- [2026-10-30 extension checkpoint and handover](docs/checkpoint-2026-10-30.md)
- [Public build and GitHub deployment](docs/deployment.md)

Detection is not proof of complete parsing, deployment, active use or execution.
Runtime metadata connectors and generalized SQL/column lineage are future work.
