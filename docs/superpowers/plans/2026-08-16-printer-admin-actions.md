# Printer Admin Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two printer admin actions — set the default printer, and open the CUPS web UI — and change the collector to report the *client's* default so the first action's effect is visible.

**Architecture:** The collector resolves the default printer from the client-side `lpoptions` files before falling back to the existing IPP `CUPS-Get-Default` result, because `lpoptions -d` writes a per-user default that cupsd never sees. `scripts/galley_action.sh` gains two verbs and a per-verb target rule so `web-ui` can take no target. `Panel.qml` gains one per-printer button on the card and one global button in the header — no overflow menu, no confirmation dialogs.

**Tech Stack:** Python 3 (stdlib only), bash, QML/Quickshell, `lpoptions` and `xdg-open` CLIs, node for the JS suite (untouched by this work).

**Spec:** `docs/superpowers/specs/2026-08-16-printer-admin-actions-design.md`

## Global Constraints

- **Python stays stdlib-only.** No new imports beyond `os`, which `galley_collect.py` already uses.
- **Default-printer precedence is exactly three sources, first hit wins:** `~/.cups/lpoptions`, then `/etc/cups/lpoptions`, then the existing `CUPS-Get-Default` IPP result. `LPDEST` and `PRINTER` are **deliberately not honoured** — that is a documented limitation with a test asserting it.
- **Fixture replay must never read the live `lpoptions` files.** Both fixtures ship a `default` file and `if not default:` makes it win, but the chain must be *skipped entirely* in fixture mode rather than merely ordered after it. Otherwise `tests/test_collect.py` becomes machine-dependent — which is the same class of defect as `#4`, where a test's name promised isolation it did not enforce.
- **Only a line whose first token is `Default` is read**, and only its second token. `lpoptions` files also carry per-destination option lines.
- **An instance suffix is stripped:** `lpoptions -d` accepts `destination[/instance]`, so `Default Brother@Home/duplex` yields `Brother@Home`.
- **No confirmation dialogs**, and **no overflow menu**. Both were costed by the original Phase 2 bullet and neither applies at this scope.
- `http://localhost:631` is hardcoded. Port discovery is out of scope.
- Errors go to stderr prefixed `galley: ` in the action script, matching its existing arms. Exit codes stay: `0` success, `2` unknown verb, `3` missing target.
- Commit after every task.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/galley_collect.py` | Client-default resolution and its wiring into `collect()` | Modify |
| `tests/test_collect.py` | Precedence chain, parsing edge cases, fixture isolation | Modify |
| `scripts/galley_action.sh` | Two new verbs; blanket target check becomes per-verb | Modify |
| `tests/test_action.py` | Dry-run output for both verbs; target rules both directions | Modify |
| `Panel.qml` | `set default` on the card, web UI button in the header | Modify |
| `README.md` | `xdg-utils` runtime row; explain the ★ and what sets it | Modify |

No new files. Nothing in `Model.js`, `Controller.qml`, or the JS suite changes — the actions route through the existing verb-agnostic `controller.runAction(verb, target)`.

---

### Task 1: Resolve the default printer from `lpoptions`

**Files:**
- Modify: `scripts/galley_collect.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lpoptions_paths()` returning a tuple of two path strings, and `default_from_lpoptions(paths)` returning a printer name or `""`. Nothing in later tasks calls these — they are consumed inside `collect()` in this task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_collect.py`, before the `if __name__` block. `gc` is already imported at the top of that file as `import galley_collect as gc`.

```python
class ClientDefaultTest(unittest.TestCase):
    """The default printer comes from the client's lpoptions, then IPP.

    `lpoptions -d` writes a per-user default to ~/.cups/lpoptions that cupsd
    never sees, so a widget reading only CUPS-Get-Default would show a stale
    star after the user set a default from the panel. See the design spec.

    Paths are injected rather than patched via HOME, because the system file is
    an absolute path (/etc/cups/lpoptions) that a test cannot relocate. Passing
    them in keeps these tests off the real filesystem entirely.
    """

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def test_user_file_supplies_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent/system")),
                "Brother@Home")

    def test_user_file_wins_over_the_system_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            system = os.path.join(tmp, "system", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            self._write(system, "Default Canon@OLP\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, system)), "Brother@Home")

    def test_system_file_is_used_when_the_user_file_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            system = os.path.join(tmp, "system", "lpoptions")
            self._write(system, "Default Canon@OLP\n")
            self.assertEqual(
                gc.default_from_lpoptions(
                    (os.path.join(tmp, "absent"), system)), "Canon@OLP")

    def test_no_files_yields_empty_so_the_caller_falls_back_to_ipp(self):
        self.assertEqual(
            gc.default_from_lpoptions(("/nonexistent/a", "/nonexistent/b")), "")

    def test_option_lines_without_a_default_line_yield_empty(self):
        # A real lpoptions file usually carries per-destination option lines.
        # Only a line whose FIRST token is Default names the default.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Dest Canon@OLP copies=1 number-up=1\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")), "")

    def test_an_instance_suffix_is_stripped(self):
        # `lpoptions -d` accepts destination[/instance]; the printer names the
        # snapshot matches against never carry an instance.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home/duplex\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")),
                "Brother@Home")

    def test_a_bare_default_keyword_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")), "")

    def test_a_directory_in_place_of_a_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gc.default_from_lpoptions((tmp, "/nonexistent")), "")

    def test_lpdest_and_printer_env_vars_are_ignored(self):
        # Documented limitation, pinned so honouring them later is a deliberate
        # decision rather than an accident. CUPS consults these ABOVE both
        # lpoptions files; galley does not, because the collector inherits the
        # shell's environment rather than the user's terminal.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            env = dict(os.environ)
            env["LPDEST"] = "Canon@OLP"
            env["PRINTER"] = "Canon@OLP"
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    gc.default_from_lpoptions((user, "/nonexistent")),
                    "Brother@Home")

    def test_lpoptions_paths_are_the_documented_two(self):
        user, system = gc.lpoptions_paths()
        self.assertTrue(user.endswith(os.path.join(".cups", "lpoptions")), user)
        self.assertEqual(system, "/etc/cups/lpoptions")
```

Add `import unittest.mock` to the imports at the top of `tests/test_collect.py`. It is **not** currently there — the file imports `unittest`, and plain `import unittest` does not expose the `mock` submodule, so `unittest.mock.patch.dict` would raise `AttributeError`. `os` and `tempfile` are already imported and need no change.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -t . -p 'test_collect.py' -v`
Expected: FAIL — `AttributeError: module 'galley_collect' has no attribute 'default_from_lpoptions'`

- [ ] **Step 3: Write the implementation**

In `scripts/galley_collect.py`, add these two functions immediately after `_default_from_printers` (which ends with the `return groups[0].get(...)` line):

```python
def lpoptions_paths():
    """The two client-side lpoptions files CUPS reads, in precedence order.

    Computed rather than module-level constants so a test can relocate HOME,
    and so the user path is resolved at call time rather than import time.
    """
    return (os.path.join(os.path.expanduser("~"), ".cups", "lpoptions"),
            "/etc/cups/lpoptions")


def default_from_lpoptions(paths):
    """The client-side default printer name, or "" if no file names one.

    `lpoptions -d` writes `Default <name>` here, and cupsd never sees it -- so
    this is the only way the panel's star can track a default the panel itself
    set. See docs/superpowers/specs/2026-08-16-printer-admin-actions-design.md.

    LPDEST and PRINTER are deliberately NOT consulted, though CUPS ranks them
    above both files: the collector inherits the environment of the shell that
    launched the Omarchy shell, not the user's terminal, so honouring them would
    be right only when those two happen to agree. Documented limitation, with a
    test pinning it.
    """
    for path in paths:
        try:
            with open(path) as handle:
                for line in handle:
                    parts = line.split()
                    # Only a line whose first token is Default names the
                    # default; the rest are per-destination option lines.
                    if len(parts) >= 2 and parts[0] == "Default":
                        # destination[/instance] -- the snapshot's printer names
                        # never carry an instance.
                        return parts[1].split("/")[0]
        except OSError:
            # Missing, unreadable, or a directory: try the next one.
            continue
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -t . -p 'test_collect.py' -v`
Expected: PASS, 10 new tests.

- [ ] **Step 5: Write the failing test for the wiring**

The functions exist but nothing calls them. Add to the same class:

```python
    def test_fixture_replay_never_reads_the_live_lpoptions(self):
        # The chain must be SKIPPED in fixture mode, not merely ordered after
        # the fixture's own default file. Both fixtures ship one, so ordering
        # alone would pass today and break the moment a fixture omitted it --
        # at which point replay would read the developer's real default and
        # these tests would differ per machine. Same class of defect as #4.
        source = read_source(COLLECTOR)
        body = source[source.index("def collect("):]
        self.assertIn("directory", body)
        marker = "default_from_lpoptions"
        self.assertIn(
            marker, body,
            "collect() never consults the lpoptions chain")
        call_line = next(line for line in body.splitlines() if marker in line)
        self.assertIn(
            "not directory", call_line,
            "the lpoptions chain is not gated on fixture mode: %r" % call_line)
```

And add this helper near the top of `tests/test_collect.py`, after the `COLLECTOR` constant:

```python
def read_source(path):
    with open(path) as handle:
        return handle.read()
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -t . -p 'test_collect.py' -v`
Expected: FAIL — `collect() never consults the lpoptions chain`

- [ ] **Step 7: Wire it into `collect()`**

In `scripts/galley_collect.py`, find this block inside `collect()`:

```python
        if not default:
            default = _default_from_printers(parsed_printers)
```

Replace it with:

```python
        # Fixture mode is deliberately excluded: replaying a recorded snapshot
        # must not read the developer's live default, or these tests would
        # differ per machine. The fixture's own `default` file is the only
        # client-side source consulted there.
        if not default and not directory:
            default = default_from_lpoptions(lpoptions_paths())
        if not default:
            default = _default_from_printers(parsed_printers)
```

- [ ] **Step 8: Run the full Python suite**

Run: `python3 -m unittest discover -s tests -t . -p 'test_*.py'`
Expected: OK. Both fixture-replay tests still pass — the fixtures' `default` files still win, and the chain is now unreachable in fixture mode.

- [ ] **Step 9: Verify against the live machine**

Run: `python3 scripts/galley_collect.py | python3 -c 'import json,sys; print(json.load(sys.stdin)["defaultPrinter"])'`
Expected: `Canon@OLP` — unchanged, because no `lpoptions` file exists yet, so the chain falls through to the IPP result exactly as before.

- [ ] **Step 10: Commit**

```bash
git add scripts/galley_collect.py tests/test_collect.py
git commit -m "Resolve the default printer from lpoptions before falling back to IPP

lpoptions -d writes a per-user default to ~/.cups/lpoptions that cupsd never
sees, so a panel reading only CUPS-Get-Default would show a stale star after
setting a default from the widget. The collector now reads ~/.cups/lpoptions,
then /etc/cups/lpoptions, then the existing IPP result.

Fixture mode skips the chain entirely rather than merely ordering it after the
fixture's own default file. Both fixtures ship one, so ordering alone would pass
today and break silently the moment a fixture omitted it, at which point replay
would read the developer's real default. A test asserts the gate exists.

LPDEST and PRINTER are not honoured, though CUPS ranks them above both files:
the collector inherits the shell's environment, not the user's terminal, so
honouring them would be right only when those agree. Documented limitation with
a test pinning it, so honouring them later is a decision rather than a drift."
```

---

### Task 2: Add the `set-default` and `web-ui` verbs

**Files:**
- Modify: `scripts/galley_action.sh`
- Test: `tests/test_action.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: two verbs invocable as `galley_action.sh set-default <printer>` and `galley_action.sh web-ui`. Task 3's QML calls them via `controller.runAction("set-default", <name>)` and `controller.runAction("web-ui", "")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_action.py`. `run(args)` and the two existing test classes are already there.

```python
class AdminActionTest(unittest.TestCase):
    def test_set_default_uses_lpoptions(self):
        proc = run(["set-default", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stdout.decode().strip(),
                         "lpoptions -d Canon@OLP")

    def test_set_default_still_requires_a_target(self):
        proc = run(["set-default", "--dry-run"])
        self.assertEqual(proc.returncode, 3)
        self.assertIn("missing target", proc.stderr.decode())

    def test_web_ui_opens_the_cups_interface(self):
        proc = run(["web-ui", "--dry-run"])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stdout.decode().strip(),
                         "xdg-open http://localhost:631")

    def test_web_ui_needs_no_target(self):
        # The blanket `[[ -z "$TARGET" ]]` check this replaces would have
        # exited 3 here. The per-verb rule is what makes a global action
        # expressible at all.
        proc = run(["web-ui", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing target", proc.stderr.decode())

    def test_web_ui_ignores_a_stray_target(self):
        # runAction always passes two arguments, so the QML side sends "".
        # A stray value must not change the command.
        proc = run(["web-ui", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode().strip(),
                         "xdg-open http://localhost:631")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s tests -t . -p 'test_action.py' -v`
Expected: FAIL — `set-default` and `web-ui` hit the `*)` arm, exit 2 with "unknown action".

- [ ] **Step 3: Write the implementation**

In `scripts/galley_action.sh`, extend the header comment's usage block:

```bash
#   galley_action.sh cancel-job  <job-id>  [--dry-run]
#   galley_action.sh cancel-all  <printer> [--dry-run]
#   galley_action.sh pause       <printer> [--dry-run]
#   galley_action.sh resume      <printer> [--dry-run]
#   galley_action.sh set-default <printer> [--dry-run]
#   galley_action.sh web-ui                [--dry-run]
```

Add the URL constant just after `set -uo pipefail`:

```bash
# CUPS' default and the IANA-assigned IPP port. The design spec records that
# WebInterface is Yes on the target machine; discovering a non-default Listen
# port is deliberately out of scope.
CUPS_WEB_UI="http://localhost:631"
```

Replace the `case` block and the target check with:

```bash
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s tests -t . -p 'test_action.py' -v`
Expected: PASS. `test_missing_target_exits_3` still passes — `pause` is unchanged.

- [ ] **Step 5: Verify the script parses and the existing verbs are untouched**

```bash
bash -n scripts/galley_action.sh
bash scripts/galley_action.sh pause Canon@OLP --dry-run
bash scripts/galley_action.sh cancel-job 42 --dry-run
```
Expected: no syntax error; `cupsdisable Canon@OLP`; `cancel 42`.

- [ ] **Step 6: Commit**

```bash
git add scripts/galley_action.sh tests/test_action.py
git commit -m "Add set-default and web-ui action verbs

set-default runs lpoptions -d and takes a printer. web-ui runs xdg-open against
http://localhost:631 and takes nothing.

The blanket target check becomes per-verb via NEEDS_TARGET. One
\`[[ -z \"\$TARGET\" ]]\` rule after the case cannot express a global action, and
web-ui has nothing to target. Every target-taking verb still exits 3 without
one, so test_missing_target_exits_3 passes unchanged.

web-ui also ignores a stray target, because runAction always passes two
arguments and the QML side sends an empty string."
```

---

### Task 3: Add the two buttons

**Files:**
- Modify: `Panel.qml`

**Interfaces:**
- Consumes: the two verbs from Task 2, and `controller.snapshot`'s per-printer `isDefault` field (already present, already rendering the ★).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the card button**

In `Panel.qml`, find the `pause`/`resume` button — it opens with:

```qml
                  Button {
                    text: modelData.state === "stopped" ? "resume" : "pause"
```

Immediately **after** that `Button`'s closing brace, and **before** the `cancel all` `Button` that follows it, insert:

```qml
                  Button {
                    // Hidden rather than disabled on the printer that already
                    // is the default: a disabled button invites a click and
                    // explains nothing, while an absent one reads correctly --
                    // the star beside the name already says which printer this
                    // is. `isDefault` comes from the snapshot, which now
                    // resolves the CLIENT default, so this button's effect is
                    // visible on the next poll. See the design spec.
                    visible: !modelData.isDefault
                    text: "set default"
                    foreground: root.fg
                    tooltipText: "Make this your default printer"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: controller.runAction("set-default", modelData.name)
                  }
```

- [ ] **Step 2: Add the header button**

Find the header's `Refresh` button:

```qml
          Button {
            text: "Refresh"
```

Immediately **before** it, insert:

```qml
          Button {
            // The header, not a printer card: this is a global action, and the
            // card rows are per-printer. Refresh, the only other global action,
            // already lives here.
            text: "Web UI"
            foreground: root.fg
            tooltipText: "Open the CUPS web interface at localhost:631"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            enabled: controller.actionInProgress === ""
            opacity: enabled ? 1.0 : 0.4
            // web-ui takes no target, but runAction's signature is
            // (verb, target) and galley_action.sh ignores a stray one.
            onClicked: controller.runAction("web-ui", "")
          }
```

- [ ] **Step 3: Lint and run the suite**

```bash
for q in *.qml; do qmllint "$q" || echo "LINT FAIL $q"; done
bin/test
```
Expected: qmllint clean; `bin/test` green. No test covers QML, so this only proves nothing else broke.

- [ ] **Step 4: Deploy and verify live**

`bin/test` cannot see QML wiring — `bin/test`'s own comment records that qmllint resolves neither Quickshell imports nor `Model.*` lookups, so a bad binding renders as a default and passes. Verify by hand:

```bash
bin/dev up
```

Then, in the panel:
1. **`set default` is absent** on the printer with the ★, present on the others.
2. **Click `set default`** on a non-default printer. Within one poll (3s with the panel open) the ★ moves to it and the button disappears from that row, appearing on the previously-default one.
3. **Confirm the write landed:** `cat ~/.cups/lpoptions` shows `Default <that printer>`.
4. **Click `Web UI`** — a browser opens `localhost:631`.
5. **Restore:** click `set default` on the printer that was default originally, or `rm ~/.cups/lpoptions` to return to the system default.

Report what steps 1, 2 and 4 actually showed. If the ★ does not move, the collector change from Task 1 is not reaching the panel and that is the bug to chase — not the button.

- [ ] **Step 5: Commit**

```bash
git add Panel.qml
git commit -m "Add set default and Web UI buttons

set default joins the card action row, hidden on the printer that already is the
default -- a disabled button invites a click and explains nothing, while an
absent one reads correctly next to the star that already marks the default.

Web UI joins the panel header beside Refresh, which is where the one existing
global action lives. A per-printer row is the wrong home for something that is
not per-printer, which is also why no overflow menu was needed: the card row is
pause/resume plus a conditional cancel all, not the three buttons the issue
assumed.

Verified live -- qmllint resolves neither Quickshell imports nor Model.* lookups,
so a bad binding here would render as a default and pass the suite."
```

---

### Task 4: Document the new dependency and the ★

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the finished feature.
- Produces: nothing.

- [ ] **Step 1: Add the `xdg-utils` runtime row**

In `README.md`'s runtime prerequisites table, after the `notify-send` row, add:

```markdown
| `xdg-open` | Opening the CUPS web interface | `xdg-utils` |
```

- [ ] **Step 2: Document the ★ and what sets it**

`README.md`'s "Using the panel" section lists the panel's interactions but never explains the ★, which is now user-controllable. Add to that bullet list, after the **Middle-click** bullet:

```markdown
- **`set default`** on a printer card makes it your default printer. The ★
  beside a printer's name marks the current default, and moves on the next
  poll. This sets *your* default (`lpoptions -d`, written to
  `~/.cups/lpoptions`), not the machine's — it is what `lp` and your
  applications will use for you, and it needs no password. Remove
  `~/.cups/lpoptions` to fall back to the system default.
- **`Web UI`** in the panel header opens the CUPS web interface at
  `localhost:631`, which can do considerably more than this widget exposes.
```

- [ ] **Step 3: Verify no stale claims remain**

```bash
grep -n 'xdg\|★' README.md
bin/test
```
Expected: the new rows present; `bin/test` green. (`bin/test` validates `manifest.json` and the scripts, not README prose — this is a sanity run, not a check of the docs.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document xdg-utils and what the star means

xdg-open is a new runtime dependency, from xdg-utils. Galley does not verify
dependencies at startup by design, so a missing one surfaces as an action error
in the panel -- which README already documents as the expected behaviour.

The star was never explained, which mattered less when nothing could move it.
Now that set default can, README says which default it sets: yours, via
lpoptions -d, not the machine's -- and how to undo it.

Closes #13"
```

---

## Notes for whoever executes this

**The one thing most likely to go wrong** is Task 3 step 4, and it will look like a UI bug when it is not. If `set default` clicks cleanly but the ★ does not move, the fault is almost certainly in Task 1's wiring — either the `not directory` gate is inverted, or `default_from_lpoptions` is reading a path that does not exist. Check `cat ~/.cups/lpoptions` first: if the file has the right content and the ★ is still wrong, the collector is the problem, not `Panel.qml`.

**Do not add confirmation dialogs**, however tempting `set default` looks. The spec argues them away specifically: the change is per-user, immediately visible, and undone from the same row. Adding one would be scope the design rejected.

**Do not honour `LPDEST`/`PRINTER`** to "improve" the chain. There is a test asserting they are ignored and a documented reason. If they should be honoured, that is a spec change first.
