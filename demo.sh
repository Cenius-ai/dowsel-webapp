#!/usr/bin/env bash
# A recordable, non-interactive tour of Dowsel: every feature, every state.
# It works in a throwaway directory, so your own .dowsel.json is never touched.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
CLI=( "$PYTHON" dowsel.py )

BENCH="$(mktemp -d)"
trap 'rm -rf "$BENCH"' EXIT
export DOWSEL_STATE_FILE="$BENCH/.dowsel.json"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "${CLI[@]}" "$@"; }

# The same command, but a non-zero exit is the expected outcome.
expect_failure() {
    printf '$ %s\n' "$*"
    set +e
    "${CLI[@]}" "$@"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        printf '!! expected a non-zero exit, got 0\n' >&2
        exit 1
    fi
    printf '   -> exit %s, as expected\n' "$status"
}

step "1. Help - the whole command family"
"${CLI[@]}" --version
run peg --help
run grain --help
run kerf --help

step "2. Empty states invite the next command"
run peg list
run grain show
run kerf show

step "3. Peg tallies: labelled adds, ids, then the total"
run peg add 8 --diameter 10 --spacing 20 --label "Oak frame, north wall"
run peg add 4 --diameter 12.5 --spacing 20 --label "Pine trestle"
run peg add 6 --diameter 8 --spacing 18
run peg list

step "4. Remove a tally by the id that was printed"
run peg remove 2
run peg list

step "5. End-grain direction boards"
run grain set Oak --direction north
run grain set Pine --direction south
run grain show

step "6. Saw kerf reminder: set, read the half-kerf offset, clear"
run kerf set 0.5
run kerf show
run kerf clear
run kerf show

step "7. Bad input is refused, non-zero, and leaves the store alone"
expect_failure peg add 0 --diameter 10 --spacing 20
expect_failure peg add 8 --diameter abc --spacing 20
expect_failure peg remove 99
expect_failure grain set "" --direction north
expect_failure kerf set -0.5
run peg list

step "8. Scriptable JSON, one object per endpoint"
run peg list --json
run grain show --json
run kerf set 2.4 --json

printf '\nDemo complete. State lives in %s and is removed on exit.\n' "$DOWSEL_STATE_FILE"
