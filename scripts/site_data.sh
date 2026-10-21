#!/usr/bin/env bash
# Published company and sector data lives on the site-data branch, not on main: one commit,
# replaced on every save, so weekly refreshes don't grow the repository's history.
#
#   scripts/site_data.sh load              # site-data branch -> site/data (empty if the branch doesn't exist yet)
#   scripts/site_data.sh save "message"    # site/data -> a fresh one-commit site-data branch (force-pushed)
#
# Pipeline and Refresh share the pipeline-publish concurrency group, so two saves never race.
set -euo pipefail
BRANCH=site-data
DIR=site/data

case "${1:-}" in
  load)
    mkdir -p "$DIR"
    if git fetch -q --depth=1 origin "$BRANCH" 2>/dev/null; then
      git archive FETCH_HEAD | tar -x -C "$DIR"
      echo "loaded $BRANCH into $DIR"
    else
      echo "no $BRANCH branch yet; starting from what's in $DIR"
    fi
    ;;
  save)
    msg="${2:?commit message}"
    export GIT_INDEX_FILE="$(mktemp -u)"
    trap 'rm -f "$GIT_INDEX_FILE"' EXIT
    git --work-tree="$DIR" add -A .
    tree=$(git write-tree)
    commit=$(git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit-tree "$tree" -m "$msg")
    git push -q -f origin "$commit:refs/heads/$BRANCH"
    echo "saved $DIR to $BRANCH ($commit)"
    ;;
  *)
    echo "usage: $0 load | save MESSAGE" >&2; exit 2 ;;
esac
