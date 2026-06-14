#!/usr/bin/env bash
#
# release.sh - cut a py_solar_assistant release.
#
# Versioning is driven by Conventional Commits via commitizen: the next semver
# is computed from the commits since the last release, CHANGELOG.md is updated,
# a "bump" commit and a vX.Y.Z tag are created, the package is built and
# uploaded to PyPI, and a matching GitHub release is published. Run from a
# developer machine - no GitHub Actions, by design.
#
# Requirements: git, gh (authenticated), python, curl, and pipx (used to run
# commitizen, build, and twine without polluting your environment). PyPI
# credentials must be available to twine (~/.pypirc or TWINE_USERNAME /
# TWINE_PASSWORD - use an API token: username __token__).
#
# Recovery: commitizen makes the bump commit + tag BEFORE the package is built
# and uploaded. If a later step fails, the local bump is already in place but
# nothing was pushed. Fix the cause, then finish by hand:
#     pipx run build && pipx run twine upload dist/*
#     git push origin <branch> <tag>
#     gh release create <tag> dist/* --title <tag> --notes-file <notes>
# Or undo it: git tag -d <tag> && git reset --hard HEAD~1

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/release.sh [options]

Compute the next version from Conventional Commits, update CHANGELOG.md, tag
vX.Y.Z, build the package, upload it to PyPI, and publish a GitHub release.

Options:
  --dry-run     Run all read-only checks, validate the package builds, and print
                the plan. Commits/tags/uploads nothing.
  -y, --yes     Skip the confirmation prompt (for non-interactive use).
  -h, --help    Show this help.

Versioning is automatic: feat -> minor, fix/refactor/perf -> patch, breaking ->
major (capped to a minor bump while 0.x). Reword non-compliant commits first.

Requirements: git, gh (authenticated), python, curl, pipx, and PyPI credentials
available to twine (~/.pypirc or TWINE_USERNAME/TWINE_PASSWORD).
EOF
}

die()  { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

# Run these via pipx so they need not be installed globally.
CZ=(pipx run --spec commitizen cz)
BUILD=(pipx run build)
TWINE=(pipx run twine)
RUFF=(pipx run ruff)

PKG="py-solar-assistant"   # PyPI distribution name

# Print just the changelog section the next release would add (writes no file).
# --start-rev scopes generation to commits after the last tag; --unreleased-version
# labels them as the next version. With no prior tag, generate the full history.
changelog_preview() {
  if [ -n "$LAST_TAG" ]; then
    "${CZ[@]}" changelog --dry-run --start-rev "$LAST_TAG" --unreleased-version "$TAG" 2>/dev/null
  else
    "${CZ[@]}" changelog --dry-run --unreleased-version "$TAG" 2>/dev/null
  fi
}

# --- Parse args ------------------------------------------------------------
DRY_RUN=false
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -y|--yes)  ASSUME_YES=true ;;
    -h|--help) usage; exit 0 ;;
    *)         usage >&2; die "unknown argument: $arg" ;;
  esac
done

if $DRY_RUN; then
  info "Dry run - nothing committed, tagged, uploaded, or published."
fi

# Resolve repo root from this script's location (scripts/ -> repo root).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# --- Preflight -------------------------------------------------------------
command -v git  >/dev/null || die "git not found"
command -v gh   >/dev/null || die "GitHub CLI (gh) not found - https://cli.github.com"
command -v pipx >/dev/null || die "pipx not found - https://pipx.pypa.io"
command -v curl >/dev/null || die "curl not found"
[ -f "$ROOT/pyproject.toml" ] || die "pyproject.toml not found (run from the py_solar_assistant repo)"

if ! $DRY_RUN; then
  gh auth status >/dev/null 2>&1 || die "gh is not authenticated - run: gh auth login"
fi

# --- Refuse a dirty tree ---------------------------------------------------
[ -z "$(git status --porcelain)" ] || die "working tree has uncommitted changes - commit or stash them first"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# --- Lint commit messages since the last release ---------------------------
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [ -n "$LAST_TAG" ]; then
  info "Checking Conventional Commits compliance since $LAST_TAG"
  "${CZ[@]}" check --rev-range "$LAST_TAG..HEAD" \
    || die "non-compliant commit messages in $LAST_TAG..HEAD - reword them first"
fi

# --- Lint + test preflight (gate the release) ------------------------------
# Releases are gated on a clean lint, clean formatting, and a green test run.
info "Linting with ruff"
"${RUFF[@]}" check .
"${RUFF[@]}" format --check .

info "Running the test suite"
python -c 'import py_solar_assistant, pytest, pytest_asyncio, aiohttp' 2>/dev/null \
  || die "test dependencies missing - run: python -m pip install -e . --group dev"
python -m pytest -q

# --- Compute the next version ----------------------------------------------
CURRENT="$("${CZ[@]}" version -p)"
# cz bump --dry-run exits non-zero by design; --get-next prints just the next
# version. Tolerate its non-zero exit for the "nothing to bump" case.
NEXT="$("${CZ[@]}" bump --get-next --yes 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)" || true
[ -n "$NEXT" ] || die "no version-bumping commits since ${LAST_TAG:-the start} - nothing to release"
TAG="v$NEXT"
info "Current version $CURRENT -> next version $NEXT (tag $TAG)"

# --- Guard against re-releasing --------------------------------------------
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists locally"
fi
if curl -fsS "https://pypi.org/pypi/$PKG/$NEXT/json" >/dev/null 2>&1; then
  die "$PKG $NEXT is already on PyPI - a version can never be re-uploaded"
fi

# --- Dry run: validate the package builds, print the plan, stop ------------
if $DRY_RUN; then
  info "Validating the package builds (current tree, version $CURRENT)"
  rm -rf "$ROOT/dist"
  "${BUILD[@]}" >/dev/null
  "${TWINE[@]}" check "$ROOT"/dist/*
  echo
  info "CHANGELOG.md preview - the $TAG section that would be added:"
  echo
  changelog_preview | sed 's/^/    /' || true
  echo
  info "Plan (not executed):"
  echo "    - bump $CURRENT -> $NEXT, update CHANGELOG.md, commit, tag $TAG"
  echo "    - build sdist+wheel and upload to PyPI ($PKG $NEXT)"
  echo "    - push $BRANCH + $TAG to origin"
  echo "    - create GitHub release $TAG with the dist artifacts"
  exit 0
fi

# --- Confirm before mutating anything --------------------------------------
echo
info "About to release $TAG. This will:"
echo "    - bump $CURRENT -> $NEXT, update CHANGELOG.md, commit, and tag $TAG"
echo "    - build and upload $PKG $NEXT to PyPI (irreversible)"
echo "    - push $BRANCH and $TAG to origin"
echo "    - create GitHub release $TAG with the built artifacts attached"
echo
if ! $ASSUME_YES; then
  printf 'Proceed? [y/N] '
  read -r reply || reply=""
  [[ "$reply" =~ ^[yY]([eE][sS])?$ ]] || die "aborted"
fi

# --- Bump version + changelog + tag (commitizen) ---------------------------
info "Bumping to $NEXT and updating CHANGELOG.md"
"${CZ[@]}" bump --yes --changelog   # creates the bump commit and the $TAG tag

# --- Build + validate ------------------------------------------------------
info "Building sdist + wheel"
rm -rf "$ROOT/dist"
"${BUILD[@]}" >/dev/null
"${TWINE[@]}" check "$ROOT"/dist/*

# --- Upload to PyPI (the irreversible step) --------------------------------
info "Uploading $PKG $NEXT to PyPI"
"${TWINE[@]}" upload "$ROOT"/dist/*

# --- Push git + publish the GitHub release ---------------------------------
info "Pushing $BRANCH and $TAG to origin"
git push origin "$BRANCH" "$TAG"

info "Creating GitHub release $TAG"
NOTES="$(mktemp)"
awk '/^## /{n++} n==1' "$ROOT/CHANGELOG.md" > "$NOTES"   # the just-added top section
gh release create "$TAG" "$ROOT"/dist/* --title "$TAG" --notes-file "$NOTES"
rm -f "$NOTES"

info "Done. $PKG $NEXT published to PyPI and GitHub release $TAG created."
