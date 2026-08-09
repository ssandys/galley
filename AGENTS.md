# AGENTS.md — extending Galley

Galley is a CUPS bar widget for the Omarchy shell (Quickshell). This file is
for an agent (or a human) changing the code, not installing it — see
`README.md` for that. Read
`docs/superpowers/specs/2026-08-08-galley-design.md` first if you haven't;
it's the authoritative design record, including the exact IPP quirks
observed on the real target hardware and the phase-2 boundary referenced
below.

## Layer map

```
galley_collect.py   I/O only: subprocess, systemctl, fixture replay, the CLI
galley_normalize.py pure transforms: plist dict -> Galley's snapshot schema
Model.js             pure presentation + diffing: snapshot -> glyphs, colors,
                     filtered lists, notification events
Panel.qml            render only: binds to Model.js output and to
                     root.snapshot; owns the Process objects and timers
```

Data flows one direction: `galley_collect.py` calls `galley_normalize.py`
and prints one JSON object; `Panel.qml` spawns the collector as a
`Process`, hands the raw stdout to `Model.parseSnapshot`, and everything
else in the panel reads from the resulting `snapshot` plus other pure
`Model.js` helpers. Nothing downstream reaches back upstream.

**Two invariants, both load-bearing:**

1. **Python stays stdlib-only.** Permitted imports across `galley_collect.py`
   and `galley_normalize.py`: `plistlib`, `json`, `subprocess`, `os`, `sys`,
   `getpass`. No pip installs, ever — this is what lets the collector run
   with zero setup on a bare Omarchy install.
2. **`Model.js` stays pure and QML-safe.** No I/O, no QML imports, no
   timers — it's loaded by both `Panel.qml` (via `import "Model.js" as
   Model"`) and by `node --test` for the JS test suite, and the two engines
   don't support the same syntax. Concretely, everything at the top level of
   `Model.js` must be `var` or `function` declarations only. Do **not**
   introduce: arrow functions, spread (`...`), template literals,
   `let`/`const`, `Object.assign`, `.includes(`, or `.endsWith(`. (The test
   file `tests/model.test.js` is not bound by this — it only runs under
   node — which is why you'll see modern JS like `Object.assign` and spread
   there and nowhere in `Model.js` itself.)

`printerGlyph(state)` in `Model.js` is exported but has no caller anywhere
in `Panel.qml` — the bar glyph is currently the fixed `root.barIcon`
constant, not state-dependent. It's dead code left over from an earlier
design; either wire it up or remove it, but it's a deliberate open question,
not an oversight to silently "fix" one way.

## Traps

These are the things that will cost you an hour if you don't know they're
there. Each one already has a test guarding it — if you're touching related
code and its guard test isn't red, you probably haven't reintroduced the
bug, but if you're removing code, check whether it's what's silencing one of
these before you delete it.

### IPP / collector quirks

| # | Trap | Guard |
|---|---|---|
| 1 | Without `requesting-user-name`, cupsd applies `JobPrivateValues` and redacts `job-name` and `job-originating-user-name` — the queue silently renders nameless, ownerless jobs instead of erroring. | `test_redacted_job_name_falls_back` |
| 2 | `ipptool -X` appends a plain-text `Summary:` footer after the closing `</plist>` whenever the request file holds more than one operation. That makes the raw output invalid XML. `parse_plist` truncates at the *last* `</plist>` before handing off to `plistlib`. | `test_truncates_trailing_summary_footer` |
| 3 | Single-valued IPP attributes arrive as bare scalars, not one-element lists — `printer-state-reasons` is the string `'none'`, not `['none']`. Always run `*-reasons` and marker arrays through `as_list`. | `test_wraps_scalar` |
| 4 | `marker-names` and `marker-levels` can differ in length on real hardware (one printer here returns 4 names against 11 levels). `normalize_supplies` zips to the **shortest** array. | `test_zips_to_shortest_array` |
| 5 | A marker level of `-1` means "unknown," not zero. Dropped, not rendered as an empty bar. One printer here reports `-1` for all four toners while giving real values for its waste box and drum. | `test_drops_unknown_levels` |
| 6 | Page counts don't exist before a job actually starts printing — `job-media-sheets` isn't returned at all by either printer here, and `job-impressions-completed` is `0` until printing starts. The queue shows **size**, not a page count, for anything still pending. | `test_pages_none_until_printing` |
| 7 | A job carries no printer-name attribute — only `job-printer-uri`. The printer name is the URI's trailing path segment, and names may contain `@` (`Canon@OLP`), so don't split naively. | `test_extracts_trailing_segment` |
| 8 | `waste-toner` level polarity (percent full vs. percent remaining) is undefined by IPP and vendors disagree. It's displayed but must never trigger a low-supply alert. | `test_waste_toner_never_counts_as_low` |
| 9 | `ipptool` can emit a fully parseable plist **and** exit non-zero when a `STATUS` assertion fails. A parseable response is not a successful one — without checking `test_succeeded`, a failed request looks identical to "no printers configured." | `test_succeeded`, `test_failed_ipp_status_is_an_error_not_an_empty_printer_list` |

### QML / JS gotchas

| # | Trap | Guard |
|---|---|---|
| 10 | Quickshell's `Process` never calls `streamEnded()` and never emits `exited()` when the process fails to spawn (e.g. the interpreter or script path is wrong) — only `runningChanged()` fires. Handling only `onExited` latches state forever the first time a helper fails to spawn. This produced a real Critical defect where every action button in the panel became permanently disabled. | The `onRunningChanged` handlers on `collectProc` and `actionProc` in `Panel.qml`, plus the `actionExited` flag that lets `onRunningChanged` tell a normal exit from a failed spawn. |
| 11 | Assigning `Process.command` while that `Process` is still `running` is a silent no-op — it doesn't queue, doesn't error, doesn't warn. Firing several `notify-send` calls back-to-back in a loop by reassigning `command` and `running` delivers only the first and drops the rest until the last write wins. | `notifyQueue` + `sendNextNotification()` in `Panel.qml` — one notification is sent at a time; the next is dequeued from `notifyProc.onRunningChanged` only once the process has actually stopped running. |
| 12 | `ERROR_REASONS` is hand-duplicated: once in `scripts/galley_normalize.py` (drives `summary.errorPrinters`) and once in `Model.js` (drives the bar icon and card colors). Edit one without the other and you get a red printer card sitting next to a "0 errors" tooltip. This is one of several things that cross the Python/JS/QML boundary with hand-duplicated logic and fail *silently* on a one-sided edit; `tests/test_cross_language.py` is the home for all of them. It also guards: the printer/job state-name strings `Model.js`/`Panel.qml` compare against (must all be values `galley_normalize.PRINTER_STATES`/`JOB_STATES` can emit), the `supplyLowThreshold` default `15` (copied across `manifest.json`, `Panel.qml`, `Model.js`, and `galley_collect.py`/`galley_normalize.py`), the `waste-toner` low-supply exclusion, and the hex color palette (`Model.js`'s `COLOR_*` constants vs. `Panel.qml`'s inlined hex literals). | `CrossLanguageErrorReasonsTest.test_javascript_error_reasons_match_python`, which parses both source files with a regex and diffs the sets; see `tests/test_cross_language.py` for the rest. |
| 13 | Supply-low repeat suppression is **not self-contained** in `Model.diffSnapshots` — the hysteresis logic reads `opts.armedSupplies` but never writes it back anywhere. The caller (`Panel.qml`'s `updateArmedSupplies()`) is responsible for maintaining that map across polls. Call `diffSnapshots` without threading a real `armedSupplies` through and every poll re-notifies the same low supply. | No single unit test can catch a caller that forgets this — it's an integration property. Read `updateArmedSupplies()` in `Panel.qml` alongside `diffSnapshots` before changing either. |

## Adding a printer action

The action surface is data-driven on purpose — this is the whole reason
`galley_action.sh` exists instead of shelling out to `cancel`/`cupsenable`
directly from QML. To add one:

1. Add a verb to the `case` in `scripts/galley_action.sh` (see `cancel-job`,
   `cancel-all`, `pause`, `resume` for the pattern — each just maps a verb
   to a `CMD` array).
2. Add a `--dry-run` assertion in `tests/test_action.py` asserting the
   right command gets built (see `DryRunTest`).
3. Add a `Button` in the relevant card's action row in `Panel.qml`, wired to
   `root.runAction(verb, target)`.

Nothing else changes. `runAction` already handles `actionInProgress`,
`actionError`, the spawn-failure trap (#10 above), and the post-action
refresh.

## Adding a notification type

1. Extend `diffSnapshots(prev, next, options)` in `Model.js` with the new
   comparison, pushing an event object (`type`, `urgency`, `title`,
   `message`, `key`).
2. Add a boolean toggle to both `defaults` and `schema` in `manifest.json`.
3. Read the new toggle in `Panel.qml`'s `notifyOptions()` and gate your new
   branch in `diffSnapshots` on it.

Follow the **hysteresis convention** already used for supply-low: fire once
on a threshold crossing, and don't re-arm until the underlying condition
clears by a margin (see `Model.supplyRearmed` and trap #13 above — if your
new type needs repeat-suppression across polls, you need a caller-owned
"armed" map just like `armedSupplies`, not state inside `Model.js` itself,
since `Model.js` holds no state between calls).

## Capturing a fixture

**Standing rule, no exceptions: no test, script, or manual check may ever
submit a job that reaches paper.** Every existing real fixture (the four
`.plist` files in `tests/fixtures/`) was captured this way:

1. Submit a **held** job — `-H hold` means CUPS accepts and queues it but
   never sends it to the printer — guarded by a shell `trap` so it's
   cancelled even if something in between fails:

   ```bash
   trap 'for j in "${JOBS[@]:-}"; do [ -n "$j" ] && cancel "$j"; done; lpstat -o' EXIT
   out=$(lp -H hold -d "<printer>" -t "<title>" /path/to/some/file)
   JOBS+=("$(sed -n 's/.*request id is \([^ ]*\).*/\1/p' <<<"$out")")
   ```

2. While the job(s) sit held, run the real `ipptool` request and save the
   raw output as the new fixture:

   ```bash
   ipptool -d "user=$USER" -X ipp://localhost/ scripts/get-jobs.test \
     > tests/fixtures/some-new-condition.plist
   ```

3. Let the `trap` cancel the held job(s) on exit. Confirm `lpstat -o` is
   empty afterward.

Conditions you can't produce on demand against real hardware (a jam, a
mismatched marker array, a malformed plist, a job owned by another user) are
authored as synthetic fixtures instead — plain Python dicts built directly
in the test file, not hand-written plist XML. `galley_normalize.py`'s
functions all take plain dicts, so only the plist-parsing layer
(`parse_plist`) needs real captured files; everything downstream of it is
tested against dicts you can write by hand. See any of the tests in
`tests/test_normalize.py` that don't call `load(...)` for the pattern.

## Running things

- `./bin/test` runs everything: `jq` manifest validation, `bash -n` on the
  shell scripts, `qmllint` on `*.qml`, `python3 -m unittest discover` (the
  count grows over time -- read it off the test output rather than trusting
  a number here), and `node --test tests/model.test.js` (same caveat -- read
  the count off the test output rather than trusting a number here). As of
  this writing the Python suite is 61 tests, one of which
  (`tests/test_cross_language.py`'s waste-toner JS guard) shells out to
  `node` itself and is skipped, not silently passed, if `node` is missing,
  and the JS suite is 37 tests.

  **`qmllint` only catches syntax errors.** It cannot resolve Quickshell or
  Omarchy imports (`qs.Commons`, `qs.Ui`, `Panel`, `WidgetButton`, and so
  on are all unknown to it), so an unknown component, a typo'd property, or
  a reference to something that doesn't exist on `root.bar` all pass
  silently. A green `./bin/test` run tells you `Panel.qml` *parses* — it
  tells you nothing about whether it's *correct*. QML correctness is
  verified by hand against the live shell (see the dev loop below), not by
  this suite.

- `./bin/dev-watch` watches the source tree with `inotifywait` and reruns
  `bin/install` on every save, so the deployed copy under
  `~/.config/omarchy/plugins/ssandys.galley-dev/` always matches your working
  tree.

  **That deployed copy is a different plugin than the published one.**
  `bin/install` rewrites the manifest id, the display name, and `Panel.qml`'s
  `moduleName`/`ipcTarget` to `ssandys.galley-dev` on the way out, so a dev
  install can sit alongside `ssandys.galley` without colliding — the registry
  keys plugins by manifest id, and duplicate third-party ids overwrite each
  other silently. The rewrite happens in `$DEST`, never in the source tree:
  if you find yourself editing `manifest.json`'s id or those two `Panel.qml`
  properties to make something work, you're solving it in the wrong place.
  `CONTRIBUTING.md` has the full reasoning.

  **This does not solve the restart gotcha.** Quickshell hot-reloads a
  plugin's *code* on file change, but if you changed the widget's
  *structure* — a new property, a new binding, a new top-level QML element
  — the already-instantiated widget is not recreated to match, and you'll
  keep looking at the stale shape no matter how many times `dev-watch`
  reinstalls the files underneath it. This has already cost real debugging
  time on this exact plugin (someone assumed the widget was broken when it
  was just stale). When a save doesn't seem to take effect, run:

  ```bash
  omarchy restart shell
  ```

  before spending time debugging the "bug." This restarts the whole shell,
  not just Galley, so expect the whole bar to flicker.

- `GALLEY_FIXTURE=tests/fixtures/busy python3 scripts/galley_collect.py`
  replays a recorded snapshot instead of invoking `ipptool` at all — useful
  for driving the live panel through a state (busy queue, idle, or a
  fixture you've captured yourself per above) without needing real hardware
  in that state. Point `collectProc.command` at a fixture-backed invocation
  temporarily to see it rendered in the actual running panel.

- `omarchy-shell shell rescanPlugins` forces the shell to rediscover
  plugins on disk. Use it if `inotifywait` misses a change (rare, but it
  happens after replacing a lot of files at once, e.g. right after
  `rm -rf`-ing and reinstalling a plugin directory).

## Never edit `/usr/share/omarchy/`

It's overwritten wholesale on `omarchy update`. Anything you put there
disappears without warning at the next update. Reading it to understand how
the shell's `PluginRegistry`, `WidgetButton`, or other shared components
work is fine and often the fastest way to answer a "how does this actually
behave" question — just don't write there.

## Phase-2 boundary

The design spec's "Phase 2 — documented, not built" section lists four
things deliberately left out of this MVP: **D-Bus event subscription**
(replacing polling with cupsd's IPP notify mechanism), **admin actions**
(set default, accept/reject, open the web UI), **completed-job history**
with timestamps, and a **preflight dependency check** (`bin/preflight`
mapping a missing binary to its Arch package). Each is scoped and reasoned
about in the spec already — read it there before building any of them.

If you're fixing a bug and find yourself reaching for one of these as part
of the fix, stop: it's very likely you've misdiagnosed the bug as a missing
feature. These were deferred deliberately, not accidentally.
