# Official references, standards and dependencies

Reviewed on 2026-10-29. Documentation versions below are the pages actually
reviewed, not a claim that their current integrations were implemented or that
all vendor versions were tested.

## Approaches compared

| Project / reviewed documentation | Relevant approach | Pipeline Handbook decision |
| --- | --- | --- |
| OpenLineage object model, docs 1.54.0 | Job, Dataset and Run are distinct. Design-time Job/Dataset events differ from runtime Run events. | Reuse that conceptual separation and namespace-based identity. Retain static evidence as declared; do not fabricate RunEvents. An OpenLineage exporter is backlog work. |
| DataHub ingestion, docs 1.8.0 | Source connectors produce metadata, with pull/push ingestion and graph-backed catalog features. | Reuse modular source/adapter boundaries and explicit capabilities, while avoiding a server/service deployment for the offline MVP. No MCP compatibility is claimed. |
| OpenMetadata lineage ingestion, docs 2.0.x | Lineage is connector/entity-specific; query parsing and qualified identity resolution have explicit source assumptions. | Preserve per-adapter scope and qualified service/environment identities. Require evidence for cross-tool resolution and leave unresolved links visible. No OpenMetadata API compatibility is claimed. |

Primary references: [OpenLineage object model](https://openlineage.io/docs/spec/object-model/),
[DataHub ingestion framework](https://docs.datahub.com/docs/metadata-ingestion/),
[OpenMetadata lineage ingestion](https://docs.open-metadata.org/v2.0.x/connectors/ingestion/lineage).
The initially consulted OpenMetadata v1.12.x URL redirects to v2.0.x; the table
records the destination actually read. These are architectural comparisons,
not benchmark comparisons or replacement claims.

## Semantics used by the reference adapters

- **Pentaho PDI:** transformation hops convey rows between steps; job hops
  convey conditional control. A success/failure/unconditional job hop cannot be
  treated as data lineage. [Official PDI concepts](https://docs.pentaho.com/pdia-data-integration/basic-concepts-of-pdi).
- **Airflow 2.10.5:** upstream/downstream relationships express task dependencies;
  tasks do not pass data by default. The scanner statically reads a literal AST
  subset instead of importing the DAG. [Official task relationships](https://airflow.apache.org/docs/apache-airflow/2.10.5/core-concepts/tasks.html).
- **dbt manifest v12:** artifact schema version and dbt tool version are distinct.
  Model/source dictionaries and explicit node dependencies support the implemented
  definition lineage. Warehouse adapter type is not a warehouse server version.
  [Manifest reference](https://docs.getdbt.com/reference/artifacts/manifest-json),
  [v12 JSON schema](https://schemas.getdbt.com/dbt/manifest/v12.json).
- **PostgreSQL 18 language reference:** CTAS names a target filled from a query;
  INSERT SELECT also has a target/source distinction. The adapter handles only
  its documented grammar subset and does not implement the entire reference.
  [CREATE TABLE AS](https://www.postgresql.org/docs/18/sql-createtableas.html),
  [INSERT](https://www.postgresql.org/docs/18/sql-insert.html).

## Versions, licenses and reuse

| Component | Version used/reviewed | License / use |
| --- | --- | --- |
| Python | Runtime requires 3.11+; local verification records exact interpreter in evaluation | Python Software Foundation license; standard-library modules provide JSON, SQLite, AST, XML, CLI and tests. |
| SQLite | Version provided by the selected Python interpreter | [Public domain](https://sqlite.org/copyright.html); local metadata store and separate synthetic teaching demo. |
| OpenLineage | Documentation 1.54.0; no package installed or source vendored | [Apache 2.0 license](https://github.com/OpenLineage/OpenLineage/blob/main/LICENSE); conceptual model inspiration only. |
| DataHub | Documentation 1.8.0; no package installed or source vendored | [Apache 2.0 license](https://github.com/datahub-project/datahub/blob/master/LICENSE); ingestion architecture comparison only. |
| OpenMetadata | Documentation 2.0.x; no package installed or source vendored | [Apache 2.0 license](https://github.com/open-metadata/OpenMetadata/blob/main/LICENSE); connector/lineage comparison only. |

No vendor client library is a runtime dependency. No copied vendor implementation
is distributed. dbt schemas and platform documentation are references; the
bundled synthetic minimal manifest is not a production dbt export and the parser
validates only fields used by the supported subset. A future external dependency
or copied source requires a pinned version and its applicable license notice.

JSON Schema draft 2020-12 is the published schema dialect. The built-in validator
is intentionally constrained to the keywords used by the project schemas. It is
not a general JSON Schema implementation and does not download `$ref` resources.

## Architecture extension references — reviewed 2026-10-30

The [official Compose config reference](https://docs.docker.com/reference/cli/docker/compose/config/)
describes normalized model output and its JSON format. The scanner accepts a
supplied static subset of that model; it never invokes the Docker CLI or daemon.
The [official service/dependency reference](https://docs.docker.com/reference/compose-file/services/#depends_on)
supplies the startup-dependency meanings. Those declarations remain deployment
relationships, distinct from task control, data lineage and observed outcomes.

Structured source evidence uses [JSON Pointer, RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)
to identify fields inside supplied JSON documents. These pointers supplement
relative file/line locations. They do not authorize opening extra resources.
No Docker library or RFC implementation code was copied or installed; the two
new parsers use the existing standard-library implementation and SDK.
