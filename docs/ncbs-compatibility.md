# NCBS source-only compatibility test — 2026-10-30

Pipeline Handbook was tested against the current authorized local NCBS working
tree. The product remains independent of NCBS. Existing modifications and
untracked work were preserved; no NCBS tests, wrappers, builds, scripts, SQL
workloads, schedules or services were run.

The bounded scan covered 186 selected code/metadata artifacts (about 1.66 MB).
It reconstructed 43 nodes and 26 typed relationships, including all 12 manually
expected service declarations across five primary Compose definition profiles.
These are configuration records, not twelve observed running instances. The
scan had zero adapter failures. Scope excluded environment files, business-row
data, logs, backups, archived implementations and most test/demo overlays.

Declared/detected candidates include PostgreSQL, Python, Docker, dbt, SeaweedFS,
Metabase, shell and ambiguous object-storage client evidence. New image/dependency
detectors do not supply native SeaweedFS/Metabase metadata analyzers. A PostgreSQL
client import does not establish a server version or successful connection.
Container base-image tags do not establish the Docker engine version.

Compose YAML was normalized through the trusted metadata-only `docker compose
config` operation with explicit files, a neutral export project label,
`--env-file /dev/null`, `--no-interpolate`, `--no-env-resolution` and
`--no-path-resolution`. Input files were reviewed for include/extends references.
Output was held in memory; only supported nonliteral service/image/dependency/
network/named-volume fields were retained before persistence. Source hashes and
normalization provenance remain in the private audit. Docker was never asked to
build, start or inspect a runtime service. Neutral profile labels are test export
identities, not observed deployment names.

The first actual-project test makes current coverage limits clear:

- No compatible dbt manifest was available. Native dbt graph extraction was not
  performed; the scanner did not run dbt to manufacture an artifact.
- Raw SQL/Jinja, custom Python orchestration and unsupported YAML remain gaps.
  No complete NCBS dataset lineage, report semantics or safe recovery procedure
  is claimed by this test.
- 93 artifacts lacked supported structural recognition in this selected scope.
  Other findings include unresolved metadata references and intentionally omitted
  fields. Missing visibility does not establish absence.
- No successful communication, actual deployment, workflow execution or runtime
  freshness was established.

The local scan rehashed all 186 inspected source artifacts and checked the NCBS
Git working-tree status before/after. Both remained unchanged. The private audit,
full handbook and public-to-private identifier mapping remain in `.local/ncbs/`.
They are excluded from Git and the deployment artifact.

## Public projection

The user explicitly authorized a sanitized NCBS handbook. Its publication uses a
closed allowlisted projection rather than pattern redaction alone. All private
component/dataset/pipeline/source/namespace names and source/object locations
become aliases. Arbitrary attributes, original free-text explanations, paths,
annotations, literals and connection details are removed. Only typed graph facts,
known product categories, bounded numeric versions/metrics and opaque hashes are
retained. Architecture explanations are regenerated from the validated graph.

`publication/ncbs/snapshot.json` and its exact-byte manifest are the only committed
case-study inputs. The builder checks both digest and projection policy; changing
a marker or digest cannot authorize private fields. CI never fetches the private
NCBS repository. Public aliases demonstrate compatibility and limits; the full
private report retains the inspection mapping for the project owner.
