# Modern synthetic profile

The manifest is a synthetic dbt v12 artifact, not an export from a paid warehouse.
Its declared adapter is Snowflake; the dbt and Python connector versions are
client/package versions and must not become a Snowflake server version.

The Airflow DAG contains task-level dependencies and dbt command strings.
Without invocation resolution metadata, a similar task/model name does not prove
a cross-tool relationship. The manifest independently declares model lineage.

No run results, runtime logs, retries, owners, business SLA or warehouse execution
observations are available. Ask the responsible team for reviewed annotations.
