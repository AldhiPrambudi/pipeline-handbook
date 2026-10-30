# Synthetic fixtures and labels

Every fixture is synthetic. `legacy/dev` and `legacy/prod` are offline Pentaho,
shell/cron and SQL definitions. `modern/dev` contains a synthetic dbt v12 manifest,
Airflow 2.10-style definitions and declared client dependencies. None is evidence
of a deployed vendor service or successful run. PROD is an identity test label.

`adversarial` contains misleading filenames, unsupported SQL, hostile Python,
untrusted prompt instructions, an unknown format, an XML entity attack and fake
secret canaries. These files are data for scanner tests. Do not import or run them.

The manually specified inventory and edge labels in `tests/expectations.json`
define the tested scope. Other files intentionally demonstrate coverage gaps.
No fixture includes business rows. The separate `demos/data_demo.py` creates a
small synthetic SQLite dataset only when a person explicitly invokes it.
