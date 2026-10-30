# Add a detector and trusted adapter without changing core code

Acme is a fictional teaching format. There is no vendor support claim or external
official reference. The JSON rule pack recognizes an explicit schema and tasks
object. `acme.py` maps qualified input/output declarations into the same canonical
pipeline, task, dataset and data-flow contracts used by built-in adapters.

The adapter is reviewed executable project code. Its path and exact adapter ID
must be configured separately from the scanned input. Adapter workers provide
failure/resource isolation; they are not an OS sandbox for untrusted plugins.

From the repository root:

```sh
mkdir -p .demo-data/acme-input
cp examples/trusted_plugins/acme-export.json .demo-data/acme-input/acme.json
python3 -m pipeline_handbook analyze --config examples/acme.json
python3 -m pipeline_handbook document --config examples/acme.json
```

Open `generated_acme/index.html`. To demonstrate detector-only support, copy the
config and remove the `adapters.plugins` entry and `example:acme` trust entry; the
candidate remains visible while no executable Acme analyzer is selected.

Tests in `tests/test_core.py` create a reviewed detector pack in a temporary
directory, register a trusted adapter outside the input scope, and validate shared
graph output. They also verify that wildcard trust cannot authorize external
plugins, scanned files cannot nominate themselves as adapters, adapter failures
and timeouts preserve other successful analyses, and rule/code changes invalidate
the semantic snapshot.
