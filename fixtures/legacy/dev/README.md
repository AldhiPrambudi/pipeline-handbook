# Legacy synthetic profile

These files describe a small legacy pipeline. They are definition-only exports.
The job declares a transformation followed by a shell invocation on success.
The SQL declares publication of staging.orders into final.orders. No fixture
establishes that a job ran, succeeded, or is deployed in a real environment.

The team considered Tableau and Kafka in a design discussion. Those names are
documentation mentions; no Tableau dashboard or Kafka deployment is defined here.

The postgres image declaration and synthetic exported server version intentionally
differ. They may describe different lifecycle states. A reviewer must resolve the
conflict; neither proves a currently running server version.

The demo configuration's reviewed service identity `legacy_orders` denotes the
`orders_demo` database on the synthetic localhost connection. This explicit scope
lets the KTR and SQL exports use the same `raw.orders`, `staging.orders`, and
`final.orders` dataset identities. It does not assert any DEV/PROD equivalence.
The working-directory comments are reviewed fixture metadata authorizing only
source-root-relative reference resolution; commands themselves are never executed.
The job uses Pentaho's explicit `${Internal.Entry.Current.Directory}` variable to
resolve sibling transformation and shell files; arbitrary relative job filenames
would leave the runtime working directory unresolved.
