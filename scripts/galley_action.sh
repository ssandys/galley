#!/usr/bin/env bash
# Perform one CUPS action. Single entry point so the panel's action list
# stays data-driven and every failure is reported the same way.
#
#   galley_action.sh cancel-job  <job-id>  [--dry-run]
#   galley_action.sh cancel-all  <printer> [--dry-run]
#   galley_action.sh pause       <printer> [--dry-run]
#   galley_action.sh resume      <printer> [--dry-run]
#   galley_action.sh set-default <printer> [--dry-run]
#   galley_action.sh web-ui                [--dry-run]
set -uo pipefail

# CUPS' default and the IANA-assigned IPP port. The design spec records that
# WebInterface is Yes on the target machine; discovering a non-default Listen
# port is deliberately out of scope.
CUPS_WEB_UI="http://localhost:631"

DRY_RUN=0
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then DRY_RUN=1; else ARGS+=("$arg"); fi
done

ACTION="${ARGS[0]:-}"
TARGET="${ARGS[1]:-}"

# NEEDS_TARGET, rather than one blanket check after the case: web-ui is a global
# action with nothing to target, and a single `[[ -z "$TARGET" ]]` rule cannot
# express that. Every target-taking verb keeps exiting 3 without one.
case "$ACTION" in
  cancel-job)  CMD=(cancel "$TARGET");            NEEDS_TARGET=1 ;;
  cancel-all)  CMD=(cancel -a "$TARGET");         NEEDS_TARGET=1 ;;
  pause)       CMD=(cupsdisable "$TARGET");       NEEDS_TARGET=1 ;;
  resume)      CMD=(cupsenable "$TARGET");        NEEDS_TARGET=1 ;;
  set-default) CMD=(lpoptions -d "$TARGET");      NEEDS_TARGET=1 ;;
  web-ui)      CMD=(xdg-open "$CUPS_WEB_UI");     NEEDS_TARGET=0 ;;
  *)
    echo "galley: unknown action '${ACTION}'" >&2
    exit 2
    ;;
esac

if [[ "$NEEDS_TARGET" == "1" && -z "$TARGET" ]]; then
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
