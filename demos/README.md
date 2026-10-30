# Explicit synthetic data exercise

The scanner never executes an inspected workflow. Fixture definitions therefore
prove only discovery and static analysis. This separate teaching demo uses Python
and SQLite to make raw, transformed and final data tangible without cloud accounts,
vendor runtimes, LLMs or paid APIs. It is an analogue; it does not execute Pentaho,
Airflow, dbt or PostgreSQL fixtures and supplies no run evidence for those tools.

From the repository root, run these commands deliberately:

```sh
python3 demos/data_demo.py setup --database .demo-data/orders.sqlite
python3 demos/data_demo.py inspect --database .demo-data/orders.sqlite
python3 demos/data_demo.py run --database .demo-data/orders.sqlite
python3 demos/data_demo.py inspect --database .demo-data/orders.sqlite --export .demo-data/csv
```

`setup` creates three synthetic raw orders and refuses to overwrite an existing
database. `run` converts cents to amounts and filters a negative amount, producing
two transformed rows and one final aggregate: `order_count=2`, `total_amount=30.0`.
It changes only the explicitly selected local demo database. `inspect` opens that
database in read-only mode; the optional export writes only these synthetic rows.
The demo output directory is outside every configured scanner source.

For another run, choose a fresh path, such as `.demo-data/exercise2.sqlite`.
No cleanup command deletes user data. To inspect independently, open the CSV files
or use a SQLite viewer after the explicit export.

Exercises:

1. Inspect raw data before running. Predict which row is filtered and the final sum.
2. Run the explicit workflow, then compare all three exported CSV files.
3. Run `python3 -m pipeline_handbook analyze --config configs/demo.json` and
   `python3 -m pipeline_handbook document --config configs/demo.json`. Explain why
   this static handbook still cannot claim the vendor workflows succeeded.
4. Compare the SQLite process with the legacy and modern fixture definitions.
   Identify which operations are merely analogous and which are evidenced in each.

## Recover architecture from supplied metadata

The architecture exercise adds synthetic Compose JSON and reviewed environment
maps to the existing offline pipeline profiles. Its separate config writes to
`generated_architecture`; the original demo scopes and handbook remain separate.

```sh
python3 -m pipeline_handbook document --config configs/architecture.json
python3 -m pipeline_handbook status --config configs/architecture.json
python3 -m pipeline_handbook impact --config configs/architecture.json --asset orders.summary --environment dev --service arch_dev --direction upstream
python3 -m unittest tests.test_architecture_acceptance -v
python3 demos/evaluate_architecture.py
```

Open `generated_architecture/index.html`. Inspect the discovered components,
declared boundaries, placement resources, consumer reports/forms and walkthroughs.
The evaluator compares the result with independent manual labels in
`tests/architecture_expectations.json` and writes a separate observed metrics
report. These declarations do not prove deployments, successful communication or
execution. Inspection locations describe evidence to request or review; they do
not authorize extra reads, network access or commands.

Exercises:

1. Find the Airflow-to-PostgreSQL connection and the PostgreSQL-to-Airflow startup
   dependency. Explain why they are separate relationships with different evidence.
   Confirm that sharing a Compose network does not create an inferred connection.
2. Trace the DEV `orders.summary` dashboard back through final and staging datasets
   to `DEMO.RAW.ORDERS`. Follow the producing dbt definitions and the exact reviewed
   Airflow task/model bindings. A command string alone did not establish a binding.
3. Trace `orders.review_form` to legacy raw data. Locate its cron definition and
   the Pentaho success condition; explain why neither proves a successful run.
4. Compare DEV and PROD `orders.summary`. Name all identity fields that prevent
   these similarly named consumers and their datasets from being merged.
5. Find both warehouse location declarations and the resulting conflict. Identify
   the unplaced worker and the missing runtime, ownership and log metadata. Describe
   which evidence a responsible reviewer would need to resolve each question.
6. Inspect rejected future/malformed/dynamic map inputs and unavailable/excluded
   link tests. Explain why a selector cannot manufacture or authorize its target.
