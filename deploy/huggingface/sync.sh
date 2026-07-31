#!/usr/bin/env bash
# Push the current main to a Hugging Face Space, swapping in the Space README.
#
# The Space needs YAML frontmatter in README.md that would render as a metadata
# table on GitHub. Rather than carry that in the repo, this builds a detached
# commit with the Space README substituted and pushes only that.
#
# Usage:  ./deploy/huggingface/sync.sh <user>/<space>
set -euo pipefail

SPACE="${1:-}"
if [[ -z "$SPACE" ]]; then
  echo "usage: $0 <user>/<space>" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "working tree is dirty — commit or stash first" >&2
  exit 1
fi

WORKTREE="$(mktemp -d)"
trap 'git worktree remove --force "$WORKTREE" 2>/dev/null || true' EXIT

# Build the Space contents in a throwaway worktree so the real tree is untouched.
git worktree add --detach "$WORKTREE" HEAD >/dev/null
cp deploy/huggingface/README.md "$WORKTREE/README.md"
rm -rf "$WORKTREE/deploy"

# The reference PDFs are 17 MB of the 18 MB total and nothing in app/ or src/
# reads them. They are also third-party documents — the ENISA reports are freely
# reproducible with acknowledgement, but re-hosting a company's annual report on
# a public Space is unnecessary when it is one citation away.
rm -rf "$WORKTREE/refs"

git -C "$WORKTREE" add -A
git -C "$WORKTREE" -c user.name="$(git config user.name)" \
    -c user.email="$(git config user.email)" \
    commit -q -m "Deploy $(git rev-parse --short HEAD)"

echo "pushing to https://huggingface.co/spaces/$SPACE"
git -C "$WORKTREE" push --force "https://huggingface.co/spaces/$SPACE" HEAD:main

echo "done — https://huggingface.co/spaces/$SPACE"
