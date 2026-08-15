# Follow-ups

Findings from the whole-branch review at merge time (2026-08-09), triaged and
deliberately deferred. Nothing here blocks use — the widget is working.

Everything actionable is now a GitHub issue. This file keeps what has no issue
behind it: the closed decisions, the documentation drift, and the lessons.

Severity reflects that this is a personal-use widget on a single-user desktop.

## Tracked as issues

| # | Item |
|---|---|
| [1](https://github.com/ssandys/galley/issues/1) | Extract a non-visual `Controller.qml` from `Panel.qml` — 245 lines of state machine buried under 530 of layout |
| [2](https://github.com/ssandys/galley/issues/2) | `printerGlyph()` is exported, never called, and returns the pre-`c5f83a1` glyph — wire it up or delete it |
| [3](https://github.com/ssandys/galley/issues/3) | `root.dataVersion >= 0` is inert at two sites and reads as load-bearing |
| [4](https://github.com/ssandys/galley/issues/4) | The fixture-replay test never asserts `ipptool` was not called |
| [5](https://github.com/ssandys/galley/issues/5) | No test for `mine == False` when both the job's user and the current user are empty — that gate enables a destructive button |
| [6](https://github.com/ssandys/galley/issues/6) | `Panel.qml` inlines the `COLOR_*` hex values instead of consuming the palette; `COLOR_OK` is dead *because* of it |
| [7](https://github.com/ssandys/galley/issues/7) | The threshold default `15` is declared seven times — guarded, but decide whether the guard is the permanent answer |
| [8](https://github.com/ssandys/galley/issues/8) | `cancel all` is not owner-gated while the per-job cancel is |
| [9](https://github.com/ssandys/galley/issues/9) | A `Belt Unit` reports `type: "other"`, so a belt at 12% raises a supply-low notification |
| [12](https://github.com/ssandys/galley/issues/12) | `loading` has three writes and zero reads |

## Done

**The two retained-state bugs are fixed** —
[#11](https://github.com/ssandys/galley/issues/11) and
[#10](https://github.com/ssandys/galley/issues/10).

`tooltipText` now splits the asleep case on retained content, the same way the
panel body always has: with printers retained it reports the last-known figures,
and only a genuinely empty snapshot says "nothing queued". It deliberately drops
the "<name> printing" clause while asleep — a sleeping daemon prints nothing, so
a retained printing state must not be reported as current.

Supply arming moved out of `Panel.qml` into `Model.nextArmedSupplies`, which
skips arming when `notifySupplyLow` is off. It had to move to be tested at all:
the bug was that arming and notifying disagreed about their conditions, and
proving they agree means executing both, not reading them side by side. Both now
read one `notifyOptions()` object per tick. The threshold half is an
`onSupplyThresholdChanged` handler that drops the whole armed set — redefining
"low" re-opens the question for every supply.

The QML halves — that `Model.nextArmedSupplies` resolves through the JS import
at all, and that the change handler fires — are outside what `node --test` and
`qmllint` can see (see the lint caveat in `bin/test`). They were verified by
running the same property structure under a standalone `qml` runtime.

**Cross-language duplication now has a guard** — `tests/test_cross_language.py`,
merged 2026-08-09. Covers all five crossings: `ERROR_REASONS`, state-name
strings, the threshold default across seven declarations, the `waste-toner`
exclusion, and the colour palette. The last two still have open issues
([7](https://github.com/ssandys/galley/issues/7),
[6](https://github.com/ssandys/galley/issues/6)) — the guard freezes the
duplication, it does not remove it.

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

## Documentation drift

Not filed as issues — three small edits, one PR's worth of work.

- The spec says a failed action shows an "inline error on the card"; the code
  shows one shared strip at the panel bottom. Reasonable simplification,
  undocumented.
- The spec lists job-failed as firing on "job state → stopped/aborted, **or its
  printer → stopped**". Only the job-state half is implemented; the printer half
  is covered by the separate printer-error event, so behaviour is right but the
  spec row is wrong — and leaving it invites someone to "fix" the code into
  firing two notifications for one event.
- `README.md` says `supplyLowThreshold` drives "the card's supply-low count" —
  no such count is rendered; it reaches the UI only as the amber bar colour.

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
- `armedSupplies` keys are pruned only when a supply clears the re-arm margin or
  the threshold changes — keyed by (printer, supply), six keys on this machine,
  and only grows if hardware churns.

## Not built, deliberately

Four things were specified and consciously left out. The spec's Phase 2 section
(`docs/superpowers/specs/2026-08-08-galley-design.md`) is canonical — including
the verified Arch package ownership for every external program Galley calls,
which is recorded there and nowhere else.

- **Printer admin actions** — set default, accept/reject, open the web UI.
  Tracked as [#13](https://github.com/ssandys/galley/issues/13). Each is a
  single CLI call; the cost is UI crowding and confirmation dialogs, which is
  why `galley_action.sh` dispatches on a `case` and the action row is
  data-driven from day one.
- **Event-driven refresh via D-Bus** — tracked as
  [#14](https://github.com/ssandys/galley/issues/14). No new dependencies, and
  it changes only what *triggers* a refresh, not the data path. Deferred
  because the subscription needs lease renewal, cupsd-restart handling, and a
  polling fallback that never goes away — so it adds a path rather than
  replacing one.
- **Completed-job history** with timestamps. Not filed: reprint is not viable
  without a server-side change (`PreserveJobFiles` is unset on this machine),
  so the feature is thinner than it sounds.
- **Preflight dependency check** — a `bin/preflight` that maps each missing
  program to its Arch package, paired with a `cupsd: "missing-deps"` state and
  a once-per-detection notification. Not filed: it's tooling, not a feature,
  and v1 already surfaces a missing tool as an ordinary collector error.

Do not build these while fixing a bug.

## A note on process

The most valuable finding of the whole build came from the whole-branch review,
not from any of the fifteen per-task reviews: the spec's **retain-last-known**
rule was dropped between the spec and the implementation plan. No task owned it,
so no per-task review could catch it — each was checking its task against the
plan, and the plan was already wrong. A transient `ipptool` timeout blanked the
panel and silently destroyed print-completion notifications.

If you extend this project with the same workflow, review against the **spec**
at least once, not only against the plan.
