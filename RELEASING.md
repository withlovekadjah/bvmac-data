# First PyPI release

The package metadata is set to version `0.1.0`. The GitHub Actions publishing
workflow uses PyPI Trusted Publishing, so the repository does not need a
long-lived PyPI API token.

## One-time account setup

1. Create or sign in to a PyPI account and verify its email address.
2. Open [PyPI's Trusted Publisher setup](https://pypi.org/manage/account/publishing/).
3. Add a **pending publisher** with these exact values:

   - PyPI project name: `bvmac-data`
   - Owner: `withlovekadjah`
   - Repository: `bvmac-data`
   - Workflow filename: `publish.yml`
   - GitHub environment: `pypi`

4. In the GitHub repository, open **Settings → Environments**, create an
   environment named `pypi`, and optionally require a maintainer's approval
   before a release can publish.

The pending publisher is for a new PyPI project. PyPI creates the project
when the first matching GitHub Actions workflow successfully publishes it.

## Publish a release

1. Confirm the GitHub `Tests` workflow is green on the commit to release.
2. Confirm the version in `pyproject.toml` matches the release tag. The first
   release should use `0.1.0` and the tag `v0.1.0`.
3. In GitHub, create a release for tag `v0.1.0` and publish it. This starts
   `.github/workflows/publish.yml`.
4. Review the **Publish to PyPI** workflow run. After it succeeds, verify the
   project page at [pypi.org/project/bvmac-data](https://pypi.org/project/bvmac-data/).

Each PyPI version can be uploaded only once. For later releases, update the
version in `pyproject.toml` and use a new matching tag.

