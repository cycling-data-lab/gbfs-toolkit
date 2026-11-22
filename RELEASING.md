# Releasing

How a version of `gbfs-toolkit` gets from `main` to PyPI and to the documentation. Nobody
edits a version number by hand: [release-please](https://github.com/googleapis/release-please)
reads the commit messages on `main`, proposes the next version in a pull request, and
the release is that pull request's merge.

## The flow

```text
commits on main  ->  release PR (version, CHANGELOG)  ->  merge  ->  tag + GitHub release
                                                                          |
                          PyPI (after approval)  <-  tests, build, checks, attestation
                                                                          |
                                                          docs: /X.Y/ and "latest"
```

1. **Write conventional commits.** `feat:` is a minor release, `fix:` a patch, a `!` after
   the type (`feat!:`) or a `BREAKING CHANGE:` footer a major one. `docs:`, `perf:` and
   `refactor:` appear in the changelog; `test:`, `ci:`, `build:` and `chore:` do not. Pull
   requests are squash-merged, so the title of the pull request is the commit message:
   write it in that format.
2. **release-please keeps one release PR open** (`.github/workflows/release-please.yml`,
   on every push to `main`). It bumps `pyproject.toml`, `.release-please-manifest.json`
   and `CITATION.cff`, and prepends the changelog section. The changelog it generates is
   the one in `CHANGELOG.md`: curate the "Unreleased" notes into the PR before merging
   (headline fixes, *Open points*, anything a user must know).
3. **Review the release PR.** Check that the version is the one you expect. A patch
   release should be a patch: if the proposal is wrong, a commit is mislabelled (a `feat:`
   that was a fix, or the reverse); fix the history with a `Release-As: X.Y.Z` footer on
   an empty commit rather than editing the version.
4. **Merge it.** release-please creates the tag `gbfs-toolkit-vX.Y.Z` (the only tag
   format; the `v1.x` tags that predate it are history) and the GitHub release. Because
   a tag created with the built-in token does not trigger other workflows, the same
   workflow file carries on with the next jobs.
5. **The `publish` job** checks out the tag, runs the full test suite with the coverage
   gate, builds the sdist and wheel, then runs `twine check --strict` and
   `scripts/check_dist.py --expect <tag>`: it refuses the upload unless the wheel and the
   sdist carry exactly the tag's version, ship `py.typed`, declare the licence and
   `Requires-Python`, and contain no test or docs file. It then attests the build
   (provenance) and waits on the **`pypi` environment**: a maintainer approves the
   deployment in the GitHub Actions run, and the upload goes out by Trusted Publishing.
   No token is stored.
6. **The `docs` job** deploys the documentation of the tag with
   [mike](https://github.com/jimporter/mike): `/X.Y/` and the `latest` alias. Pushes to
   `main` deploy the moving `/dev/` docs.
7. **Zenodo** archives the GitHub release and mints the version DOI (the concept DOI in
   `CITATION.cff` does not change).

## Checks before merging the release PR

- CI is green on `main` (tests on Python 3.10 to 3.14 and on Windows and macOS, minimum
  versions, core-only install, strict docs build, built wheel).
- The release notes list what changed for a user, and any *Open points* are still true.
- If the release is the first after a long gap, install the built wheel in a clean
  environment (CI does: the `build` job) and run `python -c "import gbfs_toolkit as g; print(g.__version__)"`.

## Reproducing the checks by hand

```bash
pip install -e ".[dev]"
pytest -q --cov=gbfs_toolkit --cov-fail-under=85
mypy
mkdocs build --strict            # needs ".[docs]"
python -m build && twine check --strict dist/* && python scripts/check_dist.py dist/
```

## If something fails

- **The publish job fails before upload** (tests, `check_dist`): fix `main`, and merge a
  new `fix:` commit; release-please opens a release PR for the next patch. The tag of the
  failed release stays; do not move or delete it once the GitHub release is public.
- **The publish job fails after the tag exists and nothing reached PyPI** (network,
  approval timeout): re-run the job from the Actions page, or use the manual fallback
  workflow *Release (manual fallback)* (`.github/workflows/release.yml`) with the tag.
- **A bad version reached PyPI**: never overwrite it (PyPI does not allow it). Yank it on
  PyPI (a yanked release is skipped by `pip` unless pinned), then release the fix as the
  next patch.
- **release-please opens no PR**: the organisation may forbid Actions from creating pull
  requests. Either enable it (Settings, Actions, General), or add a personal access
  token as the `RELEASE_PLEASE_TOKEN` secret.

## One-time setup (repository owner)

- PyPI: a Trusted Publisher for the project, naming the repository, the workflow file
  `release-please.yml` and the environment `pypi` (and `release.yml` for the fallback).
- GitHub: an environment `pypi` with a required reviewer; branch protection on `main`
  requiring the CI checks; Pages source `gh-pages`.

## Supported versions

- **Python**: 3.10 and later. A Python version is dropped in a minor release when it is
  end of life and no longer in [SPEC 0](https://scientific-python.org/specs/spec-0000/)'s
  window, with a changelog entry; CI tests every supported version, and the newest stable
  Python is added to the classifiers when it is tested.
- **Core dependencies** (numpy, scipy, pandas): lower bounds only, never upper caps. The
  lower bounds are tested in CI (`min-versions`) and raised only when a release needs a
  newer API or when SPEC 0 retires the old one; the changelog says so.
- **Releases of this package**: bug fixes go to the latest minor release of the latest
  major version. An older minor release gets a fix only for a data-correctness bug, on
  request, from a maintenance branch.
- **API stability** is in the [API policy](https://cycling-data-lab.github.io/gbfs-toolkit/api-policy/): stable names are kept for the
  whole major version; experimental names may change in a minor release.
