#!/usr/bin/env bash
# Perform one CUPS action. Single entry point so the panel's action list
# stays data-driven and every failure is reported the same way.
#
#   galley_action.sh cancel-job  <job-id>  [--dry-run]
#   galley_action.sh cancel-all  <printer> [--dry-run]
#   galley_action.sh pause       <printer> [--dry-run]
#   galley_action.sh resume      <printer> [--dry-run]
set -uo pipefail

DRY_RUN=0
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then DRY_RUN=1; else ARGS+=("$arg"); fi
done

ACTION="${ARGS[0]:-}"
TARGET="${ARGS[1]:-}"

case "$ACTION" in
  cancel-job) CMD=(cancel "$TARGET") ;;
  cancel-all) CMD=(cancel -a "$TARGET") ;;
  pause)      CMD=(cupsdisable "$TARGET") ;;
  resume)     CMD=(cupsenable "$TARGET") ;;
  *)
    echo "galley: unknown action '${ACTION}'" >&2
    exit 2
    ;;
esac

if [[ -z "$TARGET" ]]; then
  echo "galley: missing target for '${ACTION}'" >&2
  exit 3
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "${CMD[*]}"
  exit 0
fi

if ! output=$("${CMD[@]}" 2>&1); then
  echo "galley: ${ACTION} failed: ${output}" >&2
  exit 1
fi

exit 0
