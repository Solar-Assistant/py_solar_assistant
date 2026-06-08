# Releasing

Releases are cut from a developer machine with `scripts/release.sh` - no GitHub
Actions, by design. The script computes the next version from the commit history,
updates `CHANGELOG.md`, tags `vX.Y.Z`, builds the package, uploads it to
[PyPI](https://pypi.org/project/py-solar-assistant/), and publishes a matching
GitHub release with the built artifacts attached.

Versioning is **automatic**, driven by
[Conventional Commits](https://www.conventionalcommits.org) via
[commitizen](https://commitizen-tools.github.io/commitizen/): the next semver is
derived from the commits since the last release, so there is no manual bump flag.

## Prerequisites

- `git`, `python`, `curl`, and [`pipx`](https://pipx.pypa.io) (used to run
  commitizen, `build`, and `twine` without polluting your environment).
- The [GitHub CLI](https://cli.github.com) (`gh`) authenticated with rights to
  create releases on this repo (`gh auth login`).
- PyPI credentials available to `twine` - use an API token (username `__token__`)
  in `~/.pypirc` or via `TWINE_USERNAME` / `TWINE_PASSWORD`.

## How the version is chosen

The increment comes from the Conventional Commit types since the last tag:

| Commit                                                | Bump                                           |
| ----------------------------------------------------- | ---------------------------------------------- |
| `fix:`, `refactor:`, `perf:`                          | patch (`0.1.0` -> `0.1.1`)                     |
| `feat:`                                               | minor (`0.1.0` -> `0.2.0`)                     |
| `!` / `BREAKING CHANGE:`                              | major - capped to a **minor** bump while `0.x` |
| `build:`, `chore:`, `docs:`, `ci:`, `style:`, `test:` | none                                           |

Types that don't bump also don't appear in the changelog. Write good commit
messages, and reword non-compliant ones before releasing - a release is refused
if any commit since the last tag fails the Conventional Commits check.

## Cutting a release

Preview first - this changes nothing and prints the next version, a CHANGELOG
preview, and the full plan:

```sh
scripts/release.sh --dry-run
```

Then cut it:

```sh
scripts/release.sh
```

The script is read-only until it prints a summary of exactly what it will commit,
push, and publish, then asks for confirmation. Flags:

- `--dry-run` - run all checks, validate the package builds, and preview the
  CHANGELOG section and plan. Always safe.
- `-y`, `--yes` - skip the confirmation prompt (for non-interactive use).

## Guards

A release is refused if any of these hold:

- the working tree has uncommitted changes (commit or stash first);
- a commit since the last tag is not Conventional Commits compliant;
- the computed tag already exists locally, or the version is already on PyPI
  (a PyPI version can never be re-uploaded).

## Recovery

commitizen makes the bump commit and tag **before** the package is built and
uploaded. If a later step fails, the local bump is already in place but nothing
was pushed. Fix the cause, then finish by hand:

```sh
pipx run build && pipx run twine upload dist/*
git push origin master <tag>
gh release create <tag> dist/* --title <tag> --notes-file <notes>
```

Or undo the bump and start over:

```sh
git tag -d <tag> && git reset --hard HEAD~1
```
