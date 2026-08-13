# Plugin Devkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `bin/install` with a `bin/dev up`/`down`/`deploy`/`status` lifecycle, and make `bin/dev`, `bin/dev-watch`, and `bin/test` byte-identical across every `ssandys.*` Omarchy plugin so porting is a copy with no edits.

**Architecture:** One bash script with `case` verb dispatch, following `scripts/galley_action.sh`'s house pattern (header usage block, stderr prefix, exit 2 on unknown verb, `--dry-run`). Every plugin-specific value is derived at runtime — the id and display name from `manifest.json`, the files carrying them by globbing `*.qml` — so no literal in any script names this plugin. A `run()` wrapper routes all side effects through one place, making the command sequence assertable without deploying or restarting anything.

**Tech Stack:** bash 5, `jq`, `rsync`, `python3` (stdlib `json`/`unittest`), `omarchy` CLI, `omarchy-shell` IPC.

**Spec:** `docs/superpowers/specs/2026-08-13-plugin-devkit-design.md`

## Global Constraints

- **No plugin-specific literal may appear in `bin/dev`, `bin/dev-watch`, or `bin/test`.** Not the plugin id (`ssandys.galley`), not the display name (`Galley`), not the short name (`galley`). Task 8 enforces this with a test. This is the invariant that makes the scripts portable; every task is subject to it.
- Derive the id from `manifest.json` → `.id` and the display name from `manifest.json` → `.name`. Never hardcode either.
- Identity rewrite targets are `manifest.json` plus `$DEST/*.qml` (top-level glob), never a named QML file.
- `set -euo pipefail` in every script.
- Exit codes follow `scripts/galley_action.sh`: `0` success, `2` unknown or missing verb.
- Errors go to stderr prefixed `dev: `.
- `up` must run `omarchy-shell shell rescanPlugins` **before** `omarchy plugin enable`.
- `up` passes **no** placement argument to `omarchy plugin enable`.
- `bin/dev-watch` must never restart the shell.
- Commit after every task.

## File Structure

| File | Responsibility |
|---|---|
| `bin/dev` (create) | The whole dev lifecycle. Derivation, dispatch, `deploy`/`up`/`down`/`status`, `run()` dry-run wrapper. |
| `bin/install` (delete) | Retired. Its body moves into `bin/dev`'s `deploy`. |
| `bin/dev-watch` (modify, 2 lines) | Unchanged except calling `bin/dev deploy` instead of `bin/install`. |
| `bin/test` (modify) | Adopt colophon's both-suites-always-run structure; glob the bash syntax check. |
| `tests/__init__.py` (create, empty) | Makes `tests/` importable so `unittest discover -t .` works. Verified prerequisite — see Task 6. |
| `tests/test_dev.py` (create) | `--dry-run` behavioural tests for `bin/dev`, plus the portability guard. |
| `CONTRIBUTING.md` (modify) | Prerequisites table, checkout section, teardown block, edit loop. |
| `AGENTS.md` (modify) | Dev loop section at `:173-186`. |

---

### Task 1: `bin/dev` skeleton — derivation, dispatch, dry-run

**Files:**
- Create: `bin/dev`
- Test: `tests/test_dev.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `bin/dev` with `$ID`, `$NAME`, `$DEV_ID`, `$DEST`, `$DRY_RUN`, and functions `fail(msg)`, `usage()`, `manifest_field(path, key)`, `run(cmd...)`. All later tasks add verb functions that use these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dev.py`:

```python
# tests/test_dev.py
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEV = os.path.join(ROOT, "bin", "dev")


def run(args, env=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(["bash", DEV] + args, capture_output=True,
                          timeout=30, env=merged, cwd=ROOT)


def lines(proc):
    """Non-blank stdout lines. In a dry run these are the commands, in order."""
    return [line for line in proc.stdout.decode().splitlines() if line.strip()]


class DispatchTest(unittest.TestCase):
    def test_unknown_verb_exits_2(self):
        proc = run(["obliterate"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown verb", proc.stderr.decode())

    def test_no_verb_exits_2(self):
        proc = run([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr.decode().lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`

Use this form for every task up to Task 6. `tests/__init__.py` does not exist yet, so the `-t .` form that `bin/test` will use after Task 6 fails with `ImportError: Start directory is not importable` until then.

Expected: FAIL — `bin/dev` does not exist, so `bash` exits 127.

- [ ] **Step 3: Write minimal implementation**

Create `bin/dev`:

```bash
#!/usr/bin/env bash
# Bring the working tree up as a dev plugin, or take it down again.
#
#   bin/dev up      [--dry-run]  deploy, register, enable, restart the shell
#   bin/dev down    [--dry-run]  disable the dev plugin, restart the shell
#   bin/dev deploy  [--dry-run]  deploy only; never touches the running shell
#   bin/dev status               report what is deployed, registered, enabled
#
# Nothing in this script is plugin-specific. The id and display name come from
# manifest.json and the files carrying them are globbed, so this file is
# byte-identical across every plugin and is ported by copying it with no edits.
# See docs/superpowers/specs/2026-08-13-plugin-devkit-design.md
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "dev: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
usage: bin/dev <verb> [--dry-run]

  up      deploy, register, enable the dev plugin, restart the shell
  down    disable the dev plugin, restart the shell
  deploy  deploy only; never touches the running shell
  status  report what is deployed, registered, and enabled
EOF
}

manifest_field() {
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    "$1" "$2"
}

# --dry-run is accepted in any position and stripped, matching the plugin's
# action script under scripts/.
DRY_RUN=0
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then DRY_RUN=1; else ARGS+=("$arg"); fi
done
VERB="${ARGS[0]:-}"

# Every side effect routes through here, so a dry run emits the exact command
# sequence without performing any of it. "$*" flattens arguments, so a dry run
# renders an argument containing spaces ambiguously while real execution via
# "$@" stays correct -- the same accepted trade as the action script's --dry-run,
# recorded in docs/FOLLOWUPS.md. Deliberate; do not "fix" it into a divergence.
run() {
  if (( DRY_RUN )); then printf '%s\n' "$*"; else "$@"; fi
}

[[ -f "$SRC/manifest.json" ]] || fail "no manifest.json in $SRC"
ID="$(manifest_field "$SRC/manifest.json" id)"
NAME="$(manifest_field "$SRC/manifest.json" name)"
DEV_ID="$ID-dev"
DEST="$HOME/.config/omarchy/plugins/$DEV_ID"

case "$VERB" in
  "")
    usage >&2
    exit 2
    ;;
  *)
    echo "dev: unknown verb '$VERB'" >&2
    usage >&2
    exit 2
    ;;
esac
```

Then make it executable — nothing in `bin/test` checks the bit:

```bash
chmod +x bin/dev
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add bin/dev tests/test_dev.py
git commit -m "Add bin/dev skeleton: manifest derivation, verb dispatch, --dry-run"
```

---

### Task 2: `deploy` — rsync, generic identity rewrite, verification

This is `bin/install`'s body with two generalizations: the display name comes from the manifest instead of a literal, and the rewrite targets every top-level QML file instead of `Panel.qml` by name. The second one fixes a real bug — see the spec's evidence section and colophon#5.

**Files:**
- Modify: `bin/dev`
- Modify: `tests/test_dev.py`

**Interfaces:**
- Consumes: `$ID`, `$NAME`, `$DEV_ID`, `$DEST`, `$DRY_RUN`, `run()`, `fail()`, `manifest_field()` from Task 1.
- Produces: `deploy()` and `verify()`. Task 3's `up()` calls `deploy`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dev.py`, above the `if __name__` block:

```python
class DeployTest(unittest.TestCase):
    def test_dry_run_emits_rsync_and_sed(self):
        out = "\n".join(lines(run(["deploy", "--dry-run"])))
        self.assertIn("rsync", out)
        self.assertIn("sed", out)

    def test_deploy_never_touches_the_running_shell(self):
        # deploy is what bin/dev-watch calls on every save. If it could restart
        # or enable anything, the edit loop would flicker the whole bar on each
        # keystroke-to-disk. Checked on the LEADING token only: $DEST is
        # ~/.config/omarchy/plugins/<id>-dev, so the mkdir and rsync lines
        # legitimately contain "omarchy" inside their path.
        for line in lines(run(["deploy", "--dry-run"])):
            first = line.split()[0]
            self.assertNotIn(first, ("omarchy", "omarchy-shell"),
                             f"deploy emitted a shell command: {line}")

    def test_dry_run_deploys_nothing(self):
        proc = run(["deploy", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        # mkdir routes through run() like everything else, so a dry run cannot
        # create the destination as a side effect.
        self.assertTrue(any("mkdir" in line for line in lines(proc)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: FAIL — `deploy` is an unknown verb, exit 2, so stdout is empty.

- [ ] **Step 3: Write minimal implementation**

In `bin/dev`, add after the `run()` definition:

```bash
# Escape BRE metacharacters, including the / used as sed's delimiter. The old
# bin/install escaped only dots, which was enough for an id and is not enough
# for an arbitrary display name.
escape_bre() {
  printf '%s' "$1" | sed 's/[.[\*^$/]/\\&/g'
}
```

Add the two verb functions before the `case`:

```bash
deploy() {
  run mkdir -p "$DEST"
  run rsync -a --delete \
    --exclude '.git' --exclude 'tests' --exclude 'bin' --exclude 'docs' \
    --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.github' \
    --exclude '.superpowers' --exclude '.gitignore' \
    --exclude 'README.md' --exclude 'AGENTS.md' --exclude 'CONTRIBUTING.md' \
    "$SRC/" "$DEST/"

  # The registry keys plugins by manifest id, not directory name, and one
  # third-party plugin claiming another's id silently overwrites it in the map
  # rather than warning (PluginRegistry.qml, parseScanOutput). So the dev copy
  # needs its own id -- rewritten here, in the deployed copy, to keep the
  # source tree canonical and `git status` clean.
  #
  # Both substitutions tolerate already-rewritten input, so a run that finds
  # stale output in $DEST cannot compound it into `-dev-dev`.
  local id_re name_re rewrite
  id_re="$(escape_bre "$ID")"
  name_re="$(escape_bre "$NAME")"
  # The name substitution anchors on the CLOSING quote, not the opening one, so
  # it catches a padded panel title -- two leading spaces then the name -- as
  # well as the bare literals.
  rewrite="s/$id_re\(-dev\)\?/$DEV_ID/g; s/$name_re\( (dev)\)\?\"/$NAME (dev)\"/g"
  # Every top-level QML file, not a named one. A hardcoded list silently
  # narrows every time the code is refactored: colophon's identity rewrite
  # missed Service.qml for exactly this reason, leaving its dev copy sending
  # notifications branded identically to the published plugin (colophon#5).
  run sed -i "$rewrite" "$DEST/manifest.json" "$DEST"/*.qml

  (( DRY_RUN )) && return 0
  verify
}

verify() {
  # A no-op sed would deploy a second plugin claiming the published id -- the
  # exact silent collision this is here to avoid -- so prove the rewrite landed
  # rather than trusting it.
  local deployed_id stale
  deployed_id="$(manifest_field "$DEST/manifest.json" id)"
  [[ "$deployed_id" == "$DEV_ID" ]] ||
    fail "deployed manifest id is '$deployed_id', expected '$DEV_ID'"

  # These mirror the sed's own quote anchors, so they discriminate rewritten
  # from unrewritten without any escaping: "$ID" does not match "$DEV_ID", and
  # $NAME" does not match $NAME (dev)". grep exits 1 on no match, which is the
  # success case here, hence `|| true` under `set -e`.
  stale="$(grep -Fl "\"$ID\"" "$DEST"/*.qml || true)"
  [[ -z "$stale" ]] ||
    fail "deployed QML still claims the published id: $stale"

  stale="$(grep -Fl "$NAME\"" "$DEST"/*.qml || true)"
  [[ -z "$stale" ]] ||
    fail "deployed QML still carries the published name: $stale"
}
```

Add the verb to the `case`, before the `""` arm:

```bash
  deploy) deploy ;;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS, 5 tests.

Then confirm a real deploy still works and the new assertions hold:

Run: `bin/dev deploy && echo OK`
Expected: `OK`. Then verify the rewrite reached every QML file:

Run: `grep -l 'ssandys.galley-dev' ~/.config/omarchy/plugins/ssandys.galley-dev/*.qml`
Expected: `Panel.qml` listed.

- [ ] **Step 5: Commit**

```bash
git add bin/dev tests/test_dev.py
git commit -m "Add bin/dev deploy: rsync, manifest-derived rewrite, generic verification

Rewrites every top-level QML file rather than Panel.qml by name. A hardcoded
target list silently narrows on every refactor -- colophon's rewrite missed
Service.qml, leaving its dev copy's notifications indistinguishable from the
published plugin (colophon#5). Verification now asserts no deployed QML still
carries the published id or name, which is what would have caught it."
```

---

### Task 3: `up` — rescan before enable

**Files:**
- Modify: `bin/dev`
- Modify: `tests/test_dev.py`

**Interfaces:**
- Consumes: `deploy()`, `run()`, `$DEV_ID`, `$DEST`, `$DRY_RUN`.
- Produces: `up()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dev.py`:

```python
class UpTest(unittest.TestCase):
    def setUp(self):
        self.out = lines(run(["up", "--dry-run"]))

    def index_of(self, needle):
        for i, line in enumerate(self.out):
            if needle in line:
                return i
        self.fail(f"`up --dry-run` never emitted {needle!r}; got {self.out}")

    def test_rescans_before_enabling(self):
        # `omarchy plugin enable` exits 1 on an id the registry has never seen,
        # which is every first deploy of a fresh clone. The official install
        # sequence rescans first; bin/install skipped it and only worked on a
        # machine where the dev id already existed.
        self.assertLess(self.index_of("rescanPlugins"),
                        self.index_of("plugin enable"))

    def test_deploys_before_rescanning(self):
        self.assertLess(self.index_of("rsync"), self.index_of("rescanPlugins"))

    def test_restarts_the_shell_last(self):
        self.assertEqual(self.index_of("restart shell"), len(self.out) - 1)

    def test_passes_no_placement_to_enable(self):
        # manifest.json's barWidget.defaultSection already declares placement.
        # `up` runs repeatedly, so stamping one here would overwrite a position
        # the user has since moved by hand.
        enable = self.out[self.index_of("plugin enable")]
        self.assertRegex(enable, r"^omarchy plugin enable \S+$")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: FAIL — `up` is an unknown verb; every `index_of` call fails the test.

- [ ] **Step 3: Write minimal implementation**

Add to `bin/dev` after `verify()`:

```bash
up() {
  deploy
  # Registering a NEW id needs an explicit rescan. Code hot-reload under
  # ~/.config/omarchy/plugins/ is automatic -- that is what bin/dev-watch
  # relies on -- but `omarchy plugin enable` exits 1 on an id the registry has
  # never seen, and its own error message names rescanPlugins as the fix. The
  # documented install sequence is put-files, rescan, enable, in that order.
  run omarchy-shell shell rescanPlugins
  # No placement argument: manifest.json's barWidget.defaultSection already
  # declares it and `enable` honours it, so a down/up cycle restores the widget
  # unaided. Passing one on every `up` would overwrite a hand-moved position.
  run omarchy plugin enable "$DEV_ID"
  run omarchy restart shell
  (( DRY_RUN )) || {
    echo "up -> $DEST"
    echo "  id: $DEV_ID   toggle: omarchy-shell shell toggle $DEV_ID"
  }
}
```

Add to the `case`:

```bash
  up) up ;;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add bin/dev tests/test_dev.py
git commit -m "Add bin/dev up: deploy, rescan, enable, restart

bin/install went straight from rsync to enable, skipping the rescanPlugins step
the documented install sequence requires. omarchy-plugin-enable exits 1 on an
unregistered id, so that worked only where the dev id already existed and would
have failed on a fresh clone's first deploy. The dry-run test pins the ordering."
```

---

### Task 4: `down` — state guard, conditional restart

**Files:**
- Modify: `bin/dev`
- Modify: `tests/test_dev.py`

**Interfaces:**
- Consumes: `run()`, `$DEV_ID`.
- Produces: `down()` and `plugin_state()`, which prints exactly one of `enabled`, `disabled`, `absent`. Task 5's `status()` calls `plugin_state()`.

`plugin_state()` honours a `DEV_STATE_FIXTURE` environment variable so tests can drive all three branches without depending on what is installed on the machine. This mirrors `GALLEY_FIXTURE` in `scripts/galley_collect.py`, which substitutes recorded state for a live `ipptool` call for the same reason. The variable name is deliberately plugin-agnostic — a `GALLEY_`-prefixed name would violate the Global Constraint and fail Task 8.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dev.py`:

```python
class DownTest(unittest.TestCase):
    def out(self, state):
        return lines(run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": state}))

    def test_absent_is_a_noop_and_does_not_restart(self):
        # `omarchy plugin disable` exits 1 on an unregistered id, which under
        # `set -e` would abort before the restart with an omarchy error rather
        # than a useful one.
        proc = run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": "absent"})
        self.assertEqual(proc.returncode, 0)
        joined = "\n".join(lines(proc))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("not registered", joined)

    def test_already_disabled_is_a_noop_and_does_not_restart(self):
        # A shell restart flickers the whole bar and closes open panels, which
        # is too rude for a no-op.
        joined = "\n".join(self.out("disabled"))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("already disabled", joined)

    def test_enabled_disables_then_restarts(self):
        out = self.out("enabled")
        self.assertTrue(any("plugin disable" in line for line in out), out)
        self.assertTrue(any("restart shell" in line for line in out), out)
        disable_at = next(i for i, l in enumerate(out) if "plugin disable" in l)
        restart_at = next(i for i, l in enumerate(out) if "restart shell" in l)
        self.assertLess(disable_at, restart_at)

    def test_down_does_not_remove_the_deployed_directory(self):
        # Retaining $DEST preserves the dev copy's shell.json settings, and
        # rsync --delete already makes `up` idempotent over a stale directory.
        joined = "\n".join(self.out("enabled"))
        self.assertNotIn("rm ", joined)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: FAIL — `down` is an unknown verb, exit 2, empty stdout.

- [ ] **Step 3: Write minimal implementation**

Add to `bin/dev` after `up()`:

```bash
# Prints exactly one of: enabled, disabled, absent.
#
# DEV_STATE_FIXTURE substitutes for the live registry query so tests can drive
# all three branches deterministically, the same way GALLEY_FIXTURE substitutes
# for ipptool in the collector. Test-only; unset in normal use.
plugin_state() {
  if [[ -n "${DEV_STATE_FIXTURE:-}" ]]; then
    printf '%s\n' "$DEV_STATE_FIXTURE"
    return 0
  fi
  local json
  json="$(omarchy plugin list --json)"
  if ! jq -e --arg id "$DEV_ID" 'any(.[]; .id == $id)' >/dev/null <<<"$json"; then
    printf 'absent\n'
  elif jq -e --arg id "$DEV_ID" 'any(.[]; .id == $id and .enabled)' \
       >/dev/null <<<"$json"; then
    printf 'enabled\n'
  else
    printf 'disabled\n'
  fi
}

down() {
  # Guard on registration, not enablement: `omarchy plugin disable` returns ok
  # for a known-but-disabled plugin and exits 1 only for an id the registry
  # does not know. Unguarded under `set -e` that aborts before the restart.
  #
  # Neither no-op branch restarts the shell. A restart flickers the whole bar
  # and closes any open panels, which is too rude for "there was nothing to do".
  case "$(plugin_state)" in
    absent)
      echo "dev: $DEV_ID is not registered; nothing to take down"
      return 0
      ;;
    disabled)
      echo "dev: $DEV_ID is already disabled; nothing to take down"
      return 0
      ;;
  esac
  # $DEST is deliberately left in place: it preserves the dev copy's settings,
  # and rsync --delete already makes the next `up` idempotent over it.
  run omarchy plugin disable "$DEV_ID"
  run omarchy restart shell
}
```

Add to the `case`:

```bash
  down) down ;;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add bin/dev tests/test_dev.py
git commit -m "Add bin/dev down: registration guard, no restart on a no-op

omarchy plugin disable exits 1 on an id the registry does not know, so an
unguarded call aborts down before the restart in exactly the already-torn-down
case. down now reports and exits 0 instead, and skips the shell restart when
nothing changed -- a restart flickers the whole bar and closes open panels.

plugin_state honours DEV_STATE_FIXTURE so tests drive all three branches
without depending on what is installed, mirroring GALLEY_FIXTURE in the
collector."
```

---

### Task 5: `status`

**Files:**
- Modify: `bin/dev`
- Modify: `tests/test_dev.py`

**Interfaces:**
- Consumes: `plugin_state()` from Task 4, `$DEV_ID`, `$DEST`.
- Produces: `status()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dev.py`:

```python
class StatusTest(unittest.TestCase):
    def test_reports_id_deployment_and_registry_state(self):
        proc = run(["status"], env={"DEV_STATE_FIXTURE": "enabled"})
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertIn("-dev", out)
        self.assertIn("deployed:", out)
        self.assertIn("enabled", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: FAIL — exit 2, unknown verb.

- [ ] **Step 3: Write minimal implementation**

Add to `bin/dev` after `down()`:

```bash
status() {
  local deployed="no"
  [[ -d "$DEST" ]] && deployed="yes ($DEST)"
  echo "id:        $DEV_ID"
  echo "deployed:  $deployed"
  echo "registry:  $(plugin_state)"
}
```

Add to the `case`:

```bash
  status) status ;;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS, 14 tests.

Then eyeball it against reality:

Run: `bin/dev status`
Expected: the dev id, `deployed: yes (...)`, and a registry state matching `omarchy plugin list | grep -- -dev`.

- [ ] **Step 5: Commit**

```bash
git add bin/dev tests/test_dev.py
git commit -m "Add bin/dev status: deployed, registered, enabled at a glance"
```

---

### Task 6: `bin/test` — both suites always run, globbed syntax check

Galley's `bin/test` exits on a Python failure and never reaches the JavaScript suite, so a Python failure masks every JS regression (galley#16). Colophon already fixed this. This task adopts colophon's structure and globs the syntax check so `bin/dev` is covered automatically.

`unittest discover -t .` requires `tests/` to be importable. Galley has no `tests/__init__.py` and currently fails with `ImportError: Start directory is not importable`; colophon has one and discovers 121 tests. Both verified 2026-08-13. So this task creates the empty `tests/__init__.py`.

**Files:**
- Create: `tests/__init__.py` (empty)
- Modify: `bin/test`

**Interfaces:**
- Consumes: nothing.
- Produces: a `bin/test` identical to colophon's plus the globbed syntax check.

- [ ] **Step 1: Write the failing test**

This task's subject is the test runner itself, so the check is a manual one run against the real script. First prove the current bug exists.

Create a temporary failing test in each language:

```bash
printf 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_fails(self):\n        self.fail("deliberate")\n' > tests/test_zzz_temp.py
printf 'const test = require("node:test")\nconst assert = require("node:assert/strict")\ntest("deliberate js failure", () => { assert.equal(1, 2) })\n' >> tests/model.test.js
```

- [ ] **Step 2: Run it to confirm the bug**

Run: `bin/test 2>&1 | tail -20`
Expected (the bug): output ends in the Python failure. **`== javascript ==` never appears**, so the deliberate JS failure is invisible.

- [ ] **Step 3: Write the implementation**

Create the empty package marker:

```bash
touch tests/__init__.py
```

Replace `bin/test` entirely with:

```bash
#!/usr/bin/env bash
# Run every test suite. Python uses stdlib unittest: the active python3 is
# mise-managed and has no pytest.
set -euo pipefail
shopt -s nullglob

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SRC"

echo "== manifest =="
jq -e . manifest.json >/dev/null && echo "  valid json"

echo "== bash syntax =="
# Globbed, not named. A by-name list silently omits every script added later --
# a new bin/ entry with a syntax error would pass this suite green. bin/ holds
# only bash by convention in these plugins; a non-bash entry must revisit this.
# nullglob covers a plugin with no scripts/*.sh, and bin/* is never empty since
# bin/test is itself running, so `bash -n` can never fall through to stdin.
bash -n bin/* scripts/*.sh
echo "  ok"

echo "== qml syntax =="
# qmllint catches parse errors only. It does NOT resolve Quickshell/omarchy
# imports, so unknown components and bad property references still pass. Treat
# this as "the file parses", not "the QML is correct".
#
# nullglob is set above, so an unmatched *.qml yields no iterations rather than
# a literal pattern; the -e guard below is redundant but kept, since it costs
# nothing and keeps the loop correct if nullglob is ever moved or scoped.
if command -v qmllint >/dev/null 2>&1; then
  for qml in *.qml; do
    [ -e "$qml" ] || continue
    qmllint "$qml" || { echo "  qmllint failed on $qml"; exit 1; }
  done
  echo "  ok"
else
  echo "  qmllint not installed, skipped"
fi

echo "== python =="
python_rc=0
python3 -m unittest discover -s tests -t . -p 'test_*.py' -v || python_rc=$?
# 5 means "no tests collected" (Python 3.12+), which is valid only before the
# first suite lands. Any other non-zero is a real failure.
if [ "$python_rc" -eq 5 ]; then
  echo "  no python tests collected yet"
  python_rc=0
fi

echo "== javascript =="
js_rc=0
if [ -f tests/model.test.js ]; then node --test tests/model.test.js || js_rc=$?; fi

# Both suites always run, and the exit code is decided here. Exiting early on a
# Python failure -- as an earlier version did -- silently skipped the JS suite
# entirely, so a JS regression could hide behind an unrelated Python one.
if [ "$python_rc" -ne 0 ] || [ "$js_rc" -ne 0 ]; then
  echo "FAILED: python=$python_rc javascript=$js_rc" >&2
  exit 1
fi
```

- [ ] **Step 4: Verify both failures now surface, then clean up**

Run: `bin/test 2>&1 | tail -25`
Expected: the Python failure **and** `== javascript ==` with the deliberate JS failure, ending in `FAILED: python=1 javascript=1`, exit 1.

Remove both deliberate failures:

```bash
rm tests/test_zzz_temp.py
git checkout tests/model.test.js
```

Run: `bin/test` — expected: green, exit 0, and the Python count must be unchanged from before this task (`-t .` must not have dropped any suite). Confirm `bin/dev` is being syntax-checked:

Run: `bash -x bin/test 2>&1 | grep 'bash -n'`
Expected: a line listing `bin/dev` among the arguments.

- [ ] **Step 5: Commit**

```bash
git add bin/test tests/__init__.py
git commit -m "Run both test suites unconditionally; glob the bash syntax check

bin/test exited on a Python failure and never reached the JavaScript suite, so
any Python failure masked every JS regression (galley#16). Colophon fixed this
and the fix never propagated. Adopts colophon's structure: both suites run, the
exit code is decided at the end, and the failing suite is named.

The syntax check now globs bin/* and scripts/*.sh rather than naming files, so
bin/dev is covered automatically and a by-name list cannot silently omit a new
script. unittest discover -t . needs tests/ importable, hence the empty
tests/__init__.py -- galley had none and colophon does.

Closes #16"
```

---

### Task 7: Retire `bin/install`, point `bin/dev-watch` at `bin/dev deploy`

**Files:**
- Delete: `bin/install`
- Modify: `bin/dev-watch:8` and `bin/dev-watch:14`

**Interfaces:**
- Consumes: `bin/dev deploy` from Task 2.
- Produces: nothing new.

- [ ] **Step 1: Make the two edits**

In `bin/dev-watch`, line 8:

```bash
"$SRC/bin/dev" deploy
```

and line 14:

```bash
    "$SRC/bin/dev" deploy >/dev/null && echo "reinstalled $(date +%H:%M:%S)"
```

Leave everything else, including the comment about the inotify watcher following only real paths so a symlinked source tree would not hot-reload.

- [ ] **Step 2: Delete `bin/install`**

```bash
git rm bin/install
```

- [ ] **Step 3: Verify no reference survives**

Run: `grep -rn 'bin/install' bin/ scripts/ tests/ *.md`

No `--include` filters: nothing in `bin/` has a file extension, so an `--include='*.sh'` filter would exclude `bin/dev`, `bin/dev-watch`, and `bin/test` — the very files being checked — and report a false clean.

Expected: hits only in `*.md` at the repo root, which Task 9 handles. No hits under `bin/`, `scripts/`, or `tests/`.

Run: `bin/test`
Expected: green. The globbed syntax check now covers `bin/dev` and `bin/dev-watch` and no longer references the deleted file.

- [ ] **Step 4: Verify the watch loop does not restart the shell**

Run: `bash -n bin/dev-watch && grep -c 'restart' bin/dev-watch`
Expected: `0` — the watch loop must never restart the shell, because it runs on every save.

- [ ] **Step 5: Commit**

```bash
git add bin/dev-watch
git commit -m "Retire bin/install; point bin/dev-watch at bin/dev deploy

bin/dev-watch reruns the deploy on every save, so it must not restart the
shell -- a restart flickers the whole bar and closes open panels. Keeping the
restart in bin/dev up and calling bin/dev deploy here is what separates the two."
```

---

### Task 8: The portability guard

This is the test that makes "byte-identical across plugins" an enforced invariant rather than an aspiration. `bin/test`'s own history is the argument for having it: that script was fixed in colophon and the fix never reached galley, and nothing noticed.

**Files:**
- Modify: `tests/test_dev.py`

**Interfaces:**
- Consumes: `bin/dev`, `bin/dev-watch`, `bin/test`, `manifest.json`.
- Produces: nothing.

- [ ] **Step 1: Write the test**

Add to `tests/test_dev.py`:

```python
class PortabilityTest(unittest.TestCase):
    """The dev scripts must be byte-identical across plugin repos.

    Everything plugin-specific is derived at runtime from manifest.json, so a
    port is a copy with no edits. This asserts the invariant that makes that
    true: no script mentions this plugin's id, display name, or short name.

    The literals are read from manifest.json rather than hardcoded, so this
    test itself ports unchanged -- which is the whole point.

    Necessarily textual, unlike the behavioural tests above: absence of a
    literal is a textual property. Scoped to exactly that and nothing else.
    """

    SCRIPTS = ("bin/dev", "bin/dev-watch", "bin/test")

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        plugin_id = manifest["id"]
        self.literals = {
            "manifest id": plugin_id,
            "display name": manifest["name"],
            "short name": plugin_id.split(".")[-1],
        }

    def test_scripts_carry_no_plugin_specific_literal(self):
        for relative in self.SCRIPTS:
            path = os.path.join(ROOT, relative)
            with open(path) as handle:
                source = handle.read()
            for label, literal in self.literals.items():
                self.assertNotIn(
                    literal, source,
                    f"{relative} hardcodes the {label} '{literal}'. Derive it "
                    f"from manifest.json instead, so this script stays "
                    f"byte-identical across plugins and ports by copying.")

    def test_every_dev_script_is_covered(self):
        # A guard listing files by name is only as good as the list. If a new
        # bin/ script appears, it must be added above or explicitly excused.
        present = {
            os.path.join("bin", name)
            for name in os.listdir(os.path.join(ROOT, "bin"))
        }
        self.assertEqual(present, set(self.SCRIPTS),
                         "bin/ contents changed; update SCRIPTS or excuse the "
                         "new file explicitly")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_dev.py' -v`
Expected: PASS. If `test_scripts_carry_no_plugin_specific_literal` fails, a script still hardcodes something — fix the script, not the test.

- [ ] **Step 3: Prove the guard actually bites**

Temporarily add a literal and confirm the guard catches it:

```bash
echo '# Galley' >> bin/dev
python3 -m unittest discover -s tests -p 'test_dev.py' -v 2>&1 | grep -c FAIL
git checkout bin/dev
```

Expected: a non-zero FAIL count, then a clean tree. A guard that never fires is not a guard — this is exactly the mistake `docs/FOLLOWUPS.md` records about the `waste-toner` check passing twice against broken code.

- [ ] **Step 4: Run the full suite**

Run: `bin/test`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_dev.py
git commit -m "Guard the devkit's portability invariant

Asserts no dev script hardcodes this plugin's id, display name, or short name,
reading all three from manifest.json so the test ports unchanged. bin/test was
fixed in colophon and the fix never reached galley with nothing noticing; this
is what makes byte-identical enforced rather than hoped."
```

---

### Task 9: Documentation

**Files:**
- Modify: `CONTRIBUTING.md` — prerequisites table `:26`, checkout section `:36-46`, teardown `:76-81`, edit loop `:85-87`
- Modify: `AGENTS.md:173-186`

**Interfaces:**
- Consumes: the finished `bin/dev`.
- Produces: nothing.

- [ ] **Step 1: Update the prerequisites table**

`CONTRIBUTING.md:26` — change the `rsync` row's "Used for" from `bin/install` to `bin/dev`.

- [ ] **Step 2: Update the checkout section**

`CONTRIBUTING.md:38-46` — replace the deploy instructions:

```markdown
Don't install the published plugin and edit it in place; work from a clone
and bring it up with `bin/dev`:

```bash
git clone https://github.com/ssandys/galley.git ~/Src/galley
cd ~/Src/galley
./bin/dev up
```

`bin/dev up` deploys the working tree, registers the dev id with the running
shell, enables the plugin, and restarts the shell. The widget lands in the
section `manifest.json` declares as `barWidget.defaultSection`, so no
separate `omarchy bar move` is needed.
```

Note the `omarchy bar move ssandys.galley-dev --section right` line is deleted, not reworded — `manifest.json` already declares `defaultSection: "right"` and `omarchy plugin enable` honours it.

Then update `:64` and `:69`, which name `bin/install` as the thing that rewrites the identity, to name `bin/dev` — and correct the claim about *which* files it rewrites: it is now every top-level QML file, not `Panel.qml` alone.

- [ ] **Step 3: Replace the manual teardown block**

`CONTRIBUTING.md:76-81` — replace the two hand-typed commands:

```markdown
To take the dev copy down when you're done:

```bash
./bin/dev down
```

That disables the dev plugin and restarts the shell. It deliberately leaves
`~/.config/omarchy/plugins/ssandys.galley-dev/` in place, so the dev copy's
settings survive and the next `bin/dev up` is cheap; `rsync --delete` makes
the redeploy idempotent regardless. `./bin/dev status` reports what is
deployed and whether it is enabled. To reclaim the disk as well:

```bash
rm -rf ~/.config/omarchy/plugins/ssandys.galley-dev
```
```

- [ ] **Step 4: Update the edit loop**

`CONTRIBUTING.md:85-87` — `bin/dev-watch` now reruns `bin/dev deploy` on every save. Add a sentence making the division explicit:

```markdown
`./bin/dev-watch` watches the source tree with `inotifywait` and reruns
`bin/dev deploy` on every save, so the deployed copy always matches your
working tree. It uses `deploy` rather than `up` on purpose: `up` restarts the
shell, and doing that on every keystroke-to-disk would flicker the whole bar
continuously.
```

- [ ] **Step 5: Update AGENTS.md**

`AGENTS.md:173-186` — the same three corrections: `bin/dev-watch` reruns `bin/dev deploy`; `bin/dev` (not `bin/install`) performs the rewrite; and the rewrite covers every top-level QML file, so the sentence about "those two `Panel.qml` properties" becomes "the `moduleName`/`ipcTarget` properties in any QML file". Add a pointer to the spec:

```markdown
  The full reasoning is in `CONTRIBUTING.md`; the portable-devkit design is in
  `docs/superpowers/specs/2026-08-13-plugin-devkit-design.md`.
```

- [ ] **Step 6: Verify no stale references remain**

Run: `grep -rn 'bin/install' *.md`
Expected: no hits.

Run: `grep -rn 'omarchy bar move' *.md`
Expected: no hits in the dev-setup instructions.

Run: `bin/test`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add CONTRIBUTING.md AGENTS.md
git commit -m "Document bin/dev and retire bin/install from the docs

Also drops the redundant 'omarchy bar move --section right' step: manifest.json
declares barWidget.defaultSection and omarchy plugin enable honours it. Corrects
the claim that the identity rewrite touches Panel.qml -- it now covers every
top-level QML file."
```

---

### Task 10: End-to-end verification in the live shell

Everything above is verified by `--dry-run` and by unit tests. Nothing so far proves the real thing works, and `bin/test:22-24` is explicit that qmllint does not resolve `Model.*` lookups or Quickshell imports — a green suite is not a working widget.

**Files:** none.

**Interfaces:** none.

- [ ] **Step 1: Full teardown and rebuild from a clean state**

```bash
bin/dev down
bin/dev status
rm -rf ~/.config/omarchy/plugins/ssandys.galley-dev
bin/dev status
```

Expected: `down` disables and restarts. After the `rm`, `status` reports `deployed: no` and `registry: absent`.

- [ ] **Step 2: Verify `down` is a safe no-op from that state**

```bash
bin/dev down
```

Expected: `dev: ssandys.galley-dev is not registered; nothing to take down`, exit 0, **and no shell restart** (the bar does not flicker). This is the case that would have aborted with an omarchy error before the guard existed.

- [ ] **Step 3: First-ever `up` — the rescan path**

```bash
bin/dev up
```

Expected: succeeds. This is the case `bin/install` could not handle: the dev id is not in the registry, so `enable` would have exited 1 without the preceding `rescanPlugins`.

- [ ] **Step 4: Confirm the widget and its identity**

Confirm on the bar that the Galley widget appears in the right-hand section. Then:

```bash
bin/dev status
grep -c 'ssandys.galley-dev' ~/.config/omarchy/plugins/ssandys.galley-dev/Panel.qml
grep -rn '"Galley"' ~/.config/omarchy/plugins/ssandys.galley-dev/*.qml
```

Expected: `status` reports deployed and `enabled`; the dev id appears in the deployed `Panel.qml`; and the last grep finds **nothing** — no deployed QML still carries the published name.

- [ ] **Step 5: Confirm the two fixes from the previous commit in the real widget**

The `#10`/`#11` fixes were verified under a standalone `qml` runtime, never in the live shell. With the dev copy running, confirm:

- Open the panel; the tooltip on the bar glyph reports printers and jobs.
- Change `supplyLowThreshold` in the dev widget's settings and confirm the widget keeps working — this exercises `onSupplyThresholdChanged`, which clears the armed set.

- [ ] **Step 6: Confirm the watch loop does not restart the shell**

```bash
./bin/dev-watch
```

In another terminal, `touch Panel.qml`. Expected: `bin/dev-watch` prints `reinstalled HH:MM:SS` and **the bar does not flicker**. Stop it with ctrl-c. This is the regression the whole `deploy`/`up` split exists to prevent.

- [ ] **Step 7: Commit any fixes, then close the issues**

If steps 1-6 surfaced problems, fix them with a test first and commit. Then:

```bash
gh issue close 15 --reason completed --comment "Implemented in the plugin devkit work; see docs/superpowers/specs/2026-08-13-plugin-devkit-design.md and docs/superpowers/plans/2026-08-13-plugin-devkit.md."
```

`#16` is closed by Task 6's commit trailer. Leave `colophon#5` open — it closes when `bin/dev` is ported to colophon, which is separate work.

---

## Porting to colophon (follow-up, not part of this plan)

Once the above is green, the spec's porting procedure applies:

```bash
cd ~/Src/colophon
cp ../galley/bin/dev ../galley/bin/dev-watch ../galley/bin/test bin/
cp ../galley/tests/test_dev.py tests/
chmod +x bin/dev bin/dev-watch bin/test
git rm bin/install
bin/test
```

No copied script is edited. Colophon already has `tests/__init__.py`. Porting fixes colophon#5 as a side effect, because the rewrite target becomes `$DEST/*.qml` and picks up `Service.qml` — verify by triggering a notification from the dev copy and confirming it reads **"Colophon (dev)"**. Then update colophon's `AGENTS.md` and close colophon#5.
