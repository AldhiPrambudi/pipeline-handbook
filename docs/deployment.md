# Public GitHub deployment

The public deployment target is
[AldhiPrambudi/pipeline-handbook](https://github.com/AldhiPrambudi/pipeline-handbook),
with the handbook at
[aldhiprambudi.github.io/pipeline-handbook](https://aldhiprambudi.github.io/pipeline-handbook/).
The repository contains the implementation and reviewed public examples; Pages
receives only the publication allowlist described below.

Verified deployment on 2026-10-30: both public pages returned HTTP 200, and the
hosted NCBS JSON matched the reviewed bundle and passed the strict publication
validator. Local tests passed **137 checks**; GitHub CI passed on Python 3.11 and
3.13. Both Pages build/deploy jobs passed. Exact run URLs, commit and measured
scope are in [the deployment verification record](deployment-verification-2026-10-30.json).

## Reproduce the public build locally

From this project's root, choose a new or empty staging directory:

```sh
python3 -m unittest discover -s tests -v
python3 demos/build_public_site.py --output public_site
```

Open `public_site/index.html`. The command rebuilds the fixed bundled synthetic
profile in a temporary directory and writes a small publication record with
snapshot/fixture digests and output hashes. It has no arbitrary source/config
argument and does not copy an existing local scan directory.

The [reviewed fixture manifest](../demos/public-fixtures.json) pins the public
configuration and the bytes of each synthetic input. The builder requires the
six fixed bundled fixture scopes and excludes newly added unreviewed files.
Changed fixture/configuration bytes require review and an intentional manifest
update. Adding a file to a local scan folder does not authorize public release.

## Published contents

The synthetic root contains only `index.html`, `handbook.md`, `handbook.json` and
`publication.json`. The separately approved, anonymized NCBS case uses the same
three handbook formats plus a publication record below `ncbs/`. It is rendered from an explicitly marked,
validated public projection committed under `publication/ncbs/`; Actions never
fetches the private source repository or uses its credentials. Public aliases
replace private paths and asset identities, and unsupported/unknown coverage
remains visible. The unredacted local scan is not a publication input.

SQLite databases, snapshot history, private configuration, local scan folders,
raw inspected source files and unrelated generated output are excluded. Staging
uses exact filenames without recursive copying, rejects symlink/hardlink inputs,
and refuses a nonempty destination so old private files cannot remain beside a
new build. The final Pages artifact path is `public_site`, never
`generated_architecture` or a general workspace directory.

## CI and release workflow

[CI](../.github/workflows/ci.yml) runs automatically for pushes to `main` and pull
requests. It tests Python 3.11 and 3.13 with the standard-library test suite, then
rebuilds the reviewed public site. No application package installation is needed.

[Pages](../.github/workflows/pages.yml) is a manually dispatched release from
`main`. Its build job has `contents: read`, performs the tests/build, and uploads
only the staged allowlist. The separate deploy job needs that build and grants
only `pages: write` plus `id-token: write`, using the `github-pages` environment.
The Pages concurrency group serializes deployments. Pull requests cannot trigger
the publishing workflow. This follows GitHub's documented
[custom Pages workflow requirements](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

Configure the repository's Pages publishing source as **GitHub Actions** and keep
the `github-pages` deployment environment restricted to `main`, as described in
[GitHub's publishing-source guide](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
Then run the release from Actions → Publish handbook and anonymized NCBS case → Run workflow,
or use the [documented GitHub CLI dispatch](https://cli.github.com/manual/gh_workflow_run):

```sh
gh workflow run pages.yml --repo AldhiPrambudi/pipeline-handbook --ref main
```

The workflow's deployment output supplies the actual Pages URL. A successful build
is distinct from a successful deployment; inspect both jobs and open the final URL.

## Reviewed action pins

Reviewed on 2026-10-30. Each workflow pins a full immutable commit, with the
corresponding release comment, following GitHub's
[action pinning guidance](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions).

| Action | Release | Pinned commit |
| --- | --- | --- |
| [checkout](https://github.com/actions/checkout/releases/tag/v7.0.1) | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| [setup-python](https://github.com/actions/setup-python/releases/tag/v7.0.0) | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| [upload-pages-artifact](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0) | v5.0.0 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| [deploy-pages](https://github.com/actions/deploy-pages/releases/tag/v5.0.1) | v5.0.1 | `368f82528645a54fb793d4d04e342629a3f51346` |

These actions are CI/release tooling, not scanner adapters or product runtime
dependencies. Updating a pin requires checking the official release/commit and
rerunning CI. No workflow discovers or installs plugins from inspected content.

The NCBS bundle is validated by both an exact-byte manifest and a closed-field
projection policy. A marker or edited digest cannot authorize private attributes,
annotations, source/object names or arbitrary prose. Its reverse mapping stays
under gitignored `.local/ncbs/`; see [the measured NCBS scope](ncbs-compatibility.md).
