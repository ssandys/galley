# Follow-ups

Findings from the whole-branch review at merge time (2026-08-09), triaged and
deliberately deferred. Nothing here blocks use — the widget is working. This
exists so the reasoning is not lost.

Severity reflects that this is a personal-use widget on a single-user desktop.

## Done

**Cross-language duplication now has a guard** — `tests/test_cross_language.py`,
merged 2026-08-09. Covers all five crossings: `ERROR_REASONS`, state-name
strings, the threshold default across seven declarations, the `waste-toner`
exclusion, and the colour palette.

Worth knowing how it got there, because the lesson generalises. The
`waste-toner` guard passed against broken code **twice** before it was real:
its first version matched a comment containing the string, its second matched a
dead statement that kept the string but had lost its effect. Only executing the
code caught it — the guard now spawns `node`, calls the real `supplyColor` and
`diffSnapshots`, and asserts on return values. It also carries **control**
assertions, because a test that only checks "waste toner returns the fallback"
is satisfied by an implementation that returns the fallback unconditionally.

A guard that pattern-matches source text is guarding the text, not the
behaviour. If you add a sixth crossing, execute it.

The original entry follows, for context on what was duplicated and why.

## Should fix soon

**Cross-language duplication** (now guarded — see above). `ERROR_REASONS` was
guarded by `CrossLanguageErrorReasonsTest`, which parses both source files and
diffs the sets. Four more things crossed the Python/JavaScript boundary with no
such guard, and all failed *silently*:

- **State-name strings.** `galley_normalize.py` maps IPP codes to `"printing"`,
  `"stopped"`, `"held"`, `"processing"`, `"aborted"`. `Model.js` and `Panel.qml`
  compare against those literals. Rename one in Python and the JavaScript stops
  colouring, stops notifying, and shows the wrong pause/resume label — with no
  test failure.
- **The `waste-toner` exclusion** — one rule, three literals, two languages.
- **The threshold default `15`** — six copies across `galley_collect.py`,
  `galley_normalize.py`, `Model.js`, `Panel.qml`, and `manifest.json` twice.
  If the manifest default diverged from the QML fallback, `summary.lowSupplies`
  (Python) and the card colours (JavaScript) would disagree.
- **The colour palette.** `Model.js` defines `COLOR_OK/WARN/ERROR/BUSY`;
  `Panel.qml` hardcodes the same hex values inline. `COLOR_OK` is unused *because*
  `Panel.qml` inlines its value — two sources of truth, one of them dead.

Extending `CrossLanguageErrorReasonsTest` covers most of this with the same
regex technique, already proven to work.

**Split `Panel.qml` at one seam.** The first ~215 lines are pure state machine —
five mutable variables, three `Process` objects, one `Timer`, and every
accumulated bug fix — with zero visual content, followed by ~430 lines of
layout. The state machine is the hard part and currently cannot be read, tested,
or reviewed without the layout in the way. Extract a non-visual `Controller.qml`
exposing `snapshot`, `actionInProgress`, `actionError`, `refresh()`,
`runAction()`. In-tree precedent: `plugins/panels/tailscale/` ships `Service.qml`
alongside `Panel.qml`.

Do **not** split by visual section (header / cards / queue) — those share too many
`root` properties, and you would trade 600 lines for 600 lines plus four
property-forwarding surfaces. `PrinterCard.qml` and `JobRow.qml` are clean seams
worth doing when the next feature touches them.

**`printerGlyph()` in `Model.js` is exported, never called, and now stale** — it
returns the pre-`c5f83a1` Material Design glyph while the bar ships ``.
Decide: wire it up for state-aware icons, or delete it.

**`root.dataVersion >= 0` is inert** (`Panel.qml`, two sites) — always true. It
reads as load-bearing, so the next person will carefully preserve a no-op. The
real rebind trigger is `visibleJobs()` reading `snapshot`/`selectedPrinter`
directly. Delete both.

**Two tests promise more than they check:**

- `test_replays_a_fixture_directory_without_calling_ipptool` never asserts that
  `ipptool` was not called. Point `PATH` at an empty directory.
- A missing test for `mine == False` when both the job's user and the current
  user are empty — that gate enables a destructive button.

**`COLOR_OK` should be consumed rather than inlined** (see palette, above).

## Fine as is

- `isinstance(level, int)` admits `bool` in `normalize_supplies` — unreachable
  via `plistlib`.
- `lowSupplies` counts individual markers rather than printers-with-a-low-marker
  — only ever consumed as `> 0`.
- A target literally named `--dry-run` is consumed as the flag — fails safe.
- `dry-run` prints `"${CMD[*]}"`, cosmetically ambiguous for a spaced printer
  name; real execution uses `"${CMD[@]}"` correctly.
- `job-failed` messages say "stopped" even for an `aborted` transition.
- `diffSnapshots` duplicates events if called twice on the same `(prev, next)` —
  stateless by design, single caller, edge-triggered by `previousSnapshot`.
- `visibleJobs()` is called three times per rebind — pure, no binding loop, and
  the data is tens of rows at most.
- `armedSupplies` keys are never pruned — keyed by (printer, supply), six keys on
  this machine, and only grows if hardware churns.

## Known behavioural choices, not defects

- **`cancel all` is not owner-gated** while the per-job cancel is. With
  `_user_cancel_any=0` only your own jobs can be cancelled, so on a shared queue
  the button offers an action that will fail. Low impact on a single-user
  desktop; the inconsistency with the per-job button is the real point.
- **A `Belt Unit` reports `type: "other"`**, and `low_supplies` excludes only
  `waste-toner` — so a belt at 12% *will* raise a supply-low notification.
  Probably desirable. Now a conscious choice.
- **Lowering `supplyLowThreshold` strands armed supplies.** Arming uses
  `level < threshold`; re-arming uses `level > threshold + 10`. Drop the
  threshold from 50 to 15 and a supply armed at 50 never re-arms.
  `updateArmedSupplies` also arms while `notifySupplyLow` is off, so enabling it
  later stays silent until the supply refills.
- **`Model.tooltipText` returns "CUPS idle, nothing queued" whenever `cupsd` is
  asleep**, ignoring retained content — so the tooltip can say "nothing queued"
  while the panel body correctly shows stale jobs.
- **`loading` has three writes and zero reads.** A whole commit went into fixing
  it getting stuck on spawn failure, for a property with no UI. Wire it to a
  spinner or delete it.

## Documentation drift

- The spec specifies the old `󰐪` glyph; the code ships ``, changed
  deliberately in `c5f83a1`/`1210340` and never written back.
- The spec says a failed action shows an "inline error on the card"; the code
  shows one shared strip at the panel bottom. Reasonable simplification,
  undocumented.
- The spec lists job-failed as firing on "job state → stopped/aborted, **or its
  printer → stopped**". Only the job-state half is implemented; the printer half
  is covered by the separate printer-error event, so behaviour is right but the
  spec row is wrong.
- `README.md` says `supplyLowThreshold` drives "the card's supply-low count" —
  no such count is rendered; it reaches the UI only as the amber bar colour.

## Not built, deliberately

See the spec's Phase 2 section: D-Bus event subscription, admin actions
(set-default, accept/reject, web UI), completed-job history, and the preflight
dependency check. Do not build these while fixing a bug.

## A note on process

The most valuable finding of the whole build came from the whole-branch review,
not from any of the fifteen per-task reviews: the spec's **retain-last-known**
rule was dropped between the spec and the implementation plan. No task owned it,
so no per-task review could catch it — each was checking its task against the
plan, and the plan was already wrong. A transient `ipptool` timeout blanked the
panel and silently destroyed print-completion notifications.

If you extend this project with the same workflow, review against the **spec**
at least once, not only against the plan.
