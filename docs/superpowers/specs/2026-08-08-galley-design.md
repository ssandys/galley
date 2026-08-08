# Galley — CUPS printers and queues for the Omarchy shell

**Date:** 2026-08-08
**Status:** Approved, ready for planning
**Plugin ID:** `ssandys.galley`
**Repo:** `~/Src/galley/` → deploys to `~/.config/omarchy/plugins/ssandys.galley/`

## Purpose

A bar widget for the Omarchy shell that shows the state of every CUPS printer
and the active print queue, and lets you act on both without leaving the bar.

The problem it solves: print failures on Linux are silent. A job vanishes, a
printer quietly stops on `ErrorPolicy=stop-printer`, and nothing tells you until
you walk to the printer. Galley puts that state in the bar.

## Verified environment

Every claim below was verified on the target machine on 2026-08-08, not assumed.

| Fact | Value | Consequence |
|---|---|---|
| CUPS version | 2.4.19 | `ipptool -X` (XML plist) available; `-j` (JSON) is **not** — that landed in CUPS 2.5 |
| Printers | `Brother@Home`, `Canon@OLP` | Two-printer development target |
| `cupsctl` unauthenticated | Succeeds, no password | Admin ops are viable for phase 2 |
| `_user_cancel_any` | `0` | Can only cancel **own** jobs |
| `IdleExitTimeout` | `60` | cupsd sleeps when unused; polling must not wake it |
| `ErrorPolicy` | `stop-printer` | Printer errors surface as `printer-state = stopped` |
| `WebInterface` | `Yes` | `localhost:631` reachable for phase 2 |
| `JobPrivateValues` | `default` | **Job name and owner are redacted without `requesting-user-name`** |
| `Get-Jobs` at `ipp://localhost/` | `successful-ok` | All queues retrievable in **one** call |
| Trimmed `requested-attributes` | 4.4 KB vs 37.6 KB | 8.5× smaller responses |

## Architecture

Three layers, each independently testable.

### 1. Collector — `scripts/galley_collect.py`

A short-lived Python process. Prints one JSON object to stdout, exits. No
third-party packages: `plistlib`, `json`, `subprocess`, `os` are all stdlib.

```
cups.service inactive? ──► {"cupsd":"asleep", ...}     (does NOT wake cupsd)
otherwise ──► ipptool -X ×2 ──► plistlib ──► normalize ──► JSON to stdout
```

Invocation per poll:

```
ipptool -d user=$USER -X ipp://localhost/ scripts/get-printers.test
ipptool -d user=$USER -X ipp://localhost/ scripts/get-jobs.test
```

Both wrapped in a 10-second timeout.

**The `cupsd` asleep check is load-bearing.** `IdleExitTimeout=60` means cupsd
shuts down when unused. Polling it every 30s would keep it alive permanently. A
stopped cupsd has no jobs by definition, so the collector reports idle without
waking it.

### 2. Model — `Model.js`

Pure functions, no I/O, no QML imports: state→glyph, state→color, supply→bar
geometry, queue filtering, and snapshot diffing for notifications.

### 3. View — `Panel.qml`

Bar widget plus panel, following the existing `djjeane.docker-monitor` structure:
`Panel` root, `WidgetButton`, `KeyboardPanel`, `PanelKeyCatcher`, `BorderSurface`
cards, `Style.*` tokens and `bar.foreground` for theme compliance.

### Actions — `scripts/galley_action.sh`

A thin wrapper over `cancel`, `cancel -a`, `cupsdisable`, `cupsenable`.

A wrapper rather than direct CLI calls from QML because it gives one place for
error capture, a `--dry-run` mode for tests, and — the reason that matters — it
makes the action surface **data-driven**, which is what keeps the phase-2 admin
actions additive rather than a rewrite.

## Collector output schema

```json
{
  "schema": 1,
  "cupsd": "running | asleep | error",
  "error": null,
  "defaultPrinter": "Canon@OLP",
  "printers": [{
    "name": "Brother@Home",
    "info": "Brother MFC-9560CDW",
    "location": "Home",
    "makeAndModel": "Brother MFC-9560CDW CUPS",
    "state": "idle | printing | stopped",
    "stateReasons": ["none"],
    "stateMessage": "",
    "accepting": true,
    "isDefault": false,
    "queuedJobCount": 0,
    "supplies": [{"name": "Drum Unit", "type": "opc", "level": 76, "color": "#000000"}]
  }],
  "jobs": [{
    "id": 53,
    "name": "report.pdf",
    "printer": "Canon@OLP",
    "user": "sean",
    "state": "pending | held | processing | stopped",
    "stateReasons": ["job-hold-until-specified"],
    "pages": null,
    "sizeKb": 1,
    "createdAt": 1786228376,
    "mine": true
  }],
  "summary": {"printers": 2, "activeJobs": 3, "errorPrinters": 0, "lowSupplies": 1}
}
```

## Normalization rules

Each rule exists because of a quirk observed on real hardware, not in theory.

1. **Scalar → list coercion.** Single-valued IPP attributes arrive as scalars,
   not one-element arrays. Observed: `printer-state-reasons` is the string
   `'none'`; `job-state-reasons` is `'job-hold-until-specified'`. Always coerce
   `*-reasons` to a list.

2. **`requesting-user-name` is mandatory.** With `JobPrivateValues=default`,
   cupsd redacts `job-name` and `job-originating-user-name` from unauthenticated
   requests. Verified: identical requests with and without it returned jobs with
   and without names. Omitting it yields a queue of nameless jobs.

3. **Marker arrays can disagree in length.** `Canon@OLP` returns 4
   `marker-names` but 11 `marker-levels`. Zip to the **shortest** array.

4. **Marker level `-1` means unknown.** `Brother@Home` reports `-1` for all four
   toners while reporting real values for its waste box and drum. Drop unknowns
   rather than rendering them as empty.

5. **Waste-toner polarity is undefined.** IPP does not specify whether a
   `waste-toner` level means "percent full" or "percent remaining", and vendors
   disagree. Display it; never raise a low-supply alert on it.

6. **Printer name comes from `job-printer-uri`.** Jobs carry no printer-name
   attribute; parse the last path segment of
   `ipp://localhost:631/printers/Canon@OLP`. Note names may contain `@`.

7. **Page counts are usually unavailable.** `job-media-sheets` is not returned
   by either printer, and `job-impressions-completed` is `0` until a job starts
   printing. The queue therefore shows **size** as its metric, and pages only
   once actually known. (This corrects the original mockup, which showed a page
   count for pending jobs — that data does not exist pre-print.)

8. **Job IDs are server-global**, not per-printer.

### IPP state codes

Job: `3` pending · `4` pending-held · `5` processing · `6` processing-stopped ·
`7` canceled · `8` aborted · `9` completed.
Printer: `3` idle · `4` processing · `5` stopped.

## UI

### Bar widget

- Glyph `󰐪`, **always visible**.
- Count badge when `activeJobs > 0`.
- Color: normal → `bar.foreground`; amber → any printer stopped or job held;
  red → error reason (`media-jam`, `media-empty`, `offline-report`, `toner-empty`).
- Tooltip: `2 printers · Canon@OLP printing · 3 jobs`.
- Middle-click refreshes, matching `docker-monitor`.

### Panel

Printer cards on top, queue always visible below. Clicking a card selects it and
filters the queue; clicking again clears. Action buttons are always visible on
every card.

```
󰐪  Galley                  2 printers · 3 jobs
─────────────────────────────────────────────
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  ◀ selected
┃ ● Brother@Home                 idle       ┃
┃   Brother MFC-9560CDW · Home              ┃
┃   waste 83  drum 76            1 job      ┃
┃   [ pause ]  [ cancel all ]               ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┌───────────────────────────────────────────┐
│ ● Canon@OLP                    idle       │
│   K41 C38 M48 Y56              2 jobs     │
│   [ pause ]  [ cancel all ]               │
└───────────────────────────────────────────┘
─────────────────────────────────────────────
QUEUE · Brother@Home                  clear ✕
 55 ⏸ slides.pdf          1 KB  sean  [ ✕ ]
─────────────────────────────────────────────
        r refresh · esc closes
```

Keyboard: `r` refreshes, `esc` clears the filter if one is set, otherwise closes.

Empty states: no printers → "No printers configured"; cupsd asleep → "CUPS idle
— no queued jobs"; queue empty → dim "No active jobs" (cards still shown).

## Actions (MVP)

| Action | Command | Scope |
|---|---|---|
| Cancel job | `cancel <id>` | Own jobs only (`_user_cancel_any=0`) |
| Cancel all on printer | `cancel -a <printer>` | Own jobs only |
| Pause printer | `cupsdisable <printer>` | Admin; verified unauthenticated locally |
| Resume printer | `cupsenable <printer>` | Admin; verified unauthenticated locally |

Jobs owned by another user render with the cancel button **disabled**, rather
than offering an action that will fail. Every action triggers an immediate
refresh on completion.

## Notifications

Diff two consecutive snapshots; suppressed on first load so startup is silent.

| Event | Trigger | Default |
|---|---|---|
| Job failed | job state → `stopped`/`aborted`, or its printer → `stopped` | on |
| Printer error | printer enters `stopped`, or gains an error reason | on |
| Job completed | job left the active queue **and** appears in completed | on |
| Supply low | marker crosses below threshold | on |

**Completed-vs-cancelled disambiguation.** A completed job and a cancelled job
both simply vanish from the active queue. To tell them apart the collector
issues one extra `Get-Jobs which-jobs=completed limit=10` call — but **only when
a job has disappeared**, not on every poll. That result classifies the
notification and is never displayed. This is the one place the design queries
completed jobs despite "active queue only" being the display decision.

Supply-low alerts use hysteresis: fire below `supplyLowThreshold`, re-arm only
after the level returns above `threshold + 10`, so a printer hovering at the
boundary cannot nag.

## Polling

Adaptive, since event-driven D-Bus was explicitly deferred to phase 2:

- Panel open → `pollIntervalOpenSec` (default 3)
- Panel closed, jobs active → `pollIntervalOpenSec`, so the badge tracks a job
  you just started
- Panel closed, everything idle → `pollIntervalIdleSec` (default 30)
- `cups.service` inactive → skip the IPP calls entirely

## Error handling

| Condition | Behavior |
|---|---|
| cupsd asleep | Calm empty state, no error styling |
| Collector exits non-zero | Error strip with stderr tail; **last-known data retained** |
| Malformed plist / JSON | Same as above; never clears a good previous snapshot |
| `ipptool` hang | 10s timeout, then error strip |
| Action fails | Inline error on the card showing stderr |

The retain-last-known rule matters: a transient cupsd restart should not blank
the panel.

## Configuration (manifest schema)

| Key | Type | Default | Range |
|---|---|---|---|
| `pollIntervalOpenSec` | integer | 3 | 1–30 |
| `pollIntervalIdleSec` | integer | 30 | 5–300 |
| `showSupplies` | boolean | true | — |
| `supplyLowThreshold` | integer | 15 | 5–50 |
| `notifyJobFailed` | boolean | true | — |
| `notifyPrinterError` | boolean | true | — |
| `notifyJobCompleted` | boolean | true | — |
| `notifySupplyLow` | boolean | true | — |

## Testing

**Collector unit tests** (`pytest`) against recorded plist fixtures. Four real
fixtures are already captured from the target machine:

| Fixture | Contents |
|---|---|
| `printers-idle.plist` | Both printers idle, `queued-job-count = 0` |
| `printers-busy.plist` | Brother `queued=1`, Canon `queued=2` |
| `jobs-held.plist` | 3 real held jobs with names, owners, timestamps |
| `jobs-empty.plist` | Empty queue |

Real fixtures were captured by submitting held jobs (`lp -H hold`) that never
reach paper, then cancelling them under a shell `trap` guaranteeing cleanup.

Synthetic fixtures to author: printer jammed (`media-jam`), printer stopped with
a state message, low toner, mismatched marker arrays, malformed plist, and a job
owned by another user.

**Fixture replay.** `GALLEY_FIXTURE=<dir>` makes the collector read
`printers.plist` and `jobs.plist` from that directory instead of invoking
`ipptool` — so the live QML panel can be driven through a jammed printer or a
busy queue without owning broken hardware.

**QML** is verified manually via `bin/dev-watch`.

## Repo layout

```
~/Src/galley/
├── manifest.json
├── Panel.qml
├── Model.js
├── scripts/
│   ├── galley_collect.py
│   ├── galley_action.sh
│   ├── get-printers.test
│   └── get-jobs.test
├── tests/
│   ├── test_collect.py
│   └── fixtures/*.plist
├── bin/
│   ├── install          # rsync → ~/.config/omarchy/plugins/ssandys.galley/
│   └── dev-watch        # inotifywait + install on save
├── docs/
├── README.md            # for humans installing and using it
├── AGENTS.md            # for agents extending it
└── LICENSE              # MIT
```

`bin/install` excludes `.git`, `tests/`, `bin/`, and `docs/` from the deployed
copy.

## Documentation deliverables (MVP)

Both files ship with v1, not after.

### `README.md` — for someone installing it

- What Galley is and the problem it solves, with a screenshot of the panel.
- Requirements: Omarchy shell, CUPS ≥ 2.4 with `ipptool` (ships with
  `cups`/`libcups`), Python 3, and a running `cups.service`.
- Install: clone to `~/Src/galley`, run `bin/install`, then add the widget via
  `omarchy bar move ssandys.galley --section right` or the shell settings panel.
- Verifying it works, and what each bar color and badge means.
- Every configuration key with its default and effect (the manifest schema
  table).
- Troubleshooting: empty job names (missing `requesting-user-name`), no supply
  levels (printer reports `-1`), panel blank (check `cups.service`), and how to
  run the collector by hand to see raw JSON.
- Known limitations, copied from this spec so users hit no surprises.
- Uninstall: remove the plugin directory and the bar entry.

### `AGENTS.md` — for an agent extending it

- **Layer map**: which file owns what, and the rule that `Model.js` stays pure
  (no I/O, no QML imports) and the collector stays dependency-free (stdlib only).
- **The IPP quirks that will bite you**, each tied to the fixture that proves it:
  `requesting-user-name` redaction, scalar-vs-list `*-reasons`, mismatched marker
  array lengths, `-1` unknown levels, missing page counts, printer name only
  available via `job-printer-uri`.
- **How to add a printer action** — the data-driven action list is the extension
  point; adding to it should not require touching layout code.
- **How to add a notification type** — where the snapshot diff lives and the
  hysteresis convention.
- **How to capture a new fixture** safely: the `lp -H hold` + `trap` cleanup
  pattern, and the standing rule that **no test may ever send a job that reaches
  paper**.
- **How to run things**: `pytest`, `bin/dev-watch`, `GALLEY_FIXTURE` replay, and
  `omarchy-shell shell rescanPlugins` when hot-reload misses.
- **Never edit `/usr/share/omarchy/`** — it is overwritten on `omarchy update`.
- Pointer to this spec for the phase-2 boundary, so an agent does not
  accidentally build D-Bus subscriptions or admin actions while fixing a bug.

**Why a deploy script rather than developing in place.** The shell's
`PluginRegistry` hot-reloads via `inotifywait -m -r` on
`~/.config/omarchy/plugins`, and it rejects any path not literally under that
prefix (`localPluginIdForPath`). A symlinked source tree would be *discovered*
(the scan globs `*/` and follows symlinks) but would **not** hot-reload. The
`dev-watch` script preserves both the source-tree location and instant reload.

## Phase 2 — documented, not built

1. **D-Bus event subscription.** `/usr/lib/cups/notifier/dbus` exists and
   `gdbus`/`busctl` are available, so no new dependencies — but it needs an IPP
   subscription with `notify-recipient-uri=dbus://` plus lease renewal, cupsd
   restart handling, and a polling fallback. Deferred as disproportionate for an
   MVP. It changes only what *triggers* a refresh, not the data path, so it
   drops in without touching the collector, schema, or UI.
2. **Admin actions:** set default (`lpoptions -d`), accept/reject
   (`cupsaccept`/`cupsreject`), open the web UI. Each is a single CLI call; the
   cost is UI crowding and confirmation dialogs, which is why the action row is
   data-driven from day one.
3. **Completed-job history** with timestamps. Reprint is **not** viable without
   a server-side change — `PreserveJobFiles` is unset on this machine.

## Known limitations

- Cancel is restricted to your own jobs by `_user_cancel_any=0`.
- Page counts are unavailable for pending jobs; size is shown instead.
- Waste-toner levels are displayed without interpretation.
- Local cupsd only. Remote `CUPS_SERVER` is out of scope.
- Job-completed notifications depend on the job appearing in the completed list;
  if cupsd is restarted mid-job the classification degrades to silence.
