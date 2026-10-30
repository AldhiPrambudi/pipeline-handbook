# Synthetic architecture-recovery evidence

These local JSON exports are supplied declarations, not observations of running
services. The Compose exports describe services, images, networks, storage and
startup conditions. The environment maps supply boundaries, synthetic placement
locations, inspection points, consumers and exact cross-tool bindings. No host,
warehouse, dashboard or application exists because these files name one.

`dev` and `prod` deliberately repeat component and report names to test environment
identity. DEV uses a dbt-manifest dataset for its dashboard and a legacy SQL dataset
for its form. PROD references only the separately exported legacy PROD dataset.
Airflow task/model bindings are explicit map declarations; command-name similarity
in the Python definition is insufficient evidence for those bindings.

Negative and incomplete evidence is intentional:

* `environment-conflict.json` disagrees with the DEV warehouse location.
* `future-map.json` uses an unsupported environment-map version.
* `malformed-map.json` supplies an unknown executable-looking field that must be
  rejected as data rather than interpreted.
* `dynamic-map.json` contains an unresolved template in an artifact selector.
* `compose-misleading.json` has a suggestive filename and prose, without a Compose
  service schema.
* One DEV link points to unavailable metadata; one PROD link incorrectly targets
  DEV data. Neither must manufacture an edge or a node.
* `unplaced.worker` lacks location and inspection metadata. Missing visibility
  remains a question. Runtime observations, owners and log locations are absent.

All credential-looking values are fake canaries. The scanner must omit/redact
them. The supplied metadata does not authorize additional file reads, commands,
network requests, discovery of real deployments or execution of any fixture.
