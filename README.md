# Galley

Galley is an Omarchy shell bar widget that shows the state of every CUPS
printer and the active print queue, and lets you act on both without leaving
the bar.

Print failures on Linux are silent: a job vanishes, a printer quietly stops
because of `ErrorPolicy=stop-printer`, and nothing tells you until you walk
over and find a blinking light. Galley puts that state in the bar — idle vs.
printing vs. stopped, supply levels, who owns what's queued — and lets you
cancel a job or pause/resume a queue on the spot.

> **Screenshot:** not included yet. This needs a human at the keyboard and a
> queue with a job or two sitting in it — open the panel
> (`omarchy-shell shell toggle ssandys.galley` or click the bar icon), run
> `omarchy capture screenshot`, and save the PNG as `docs/panel.png`. Once it
> exists, reference it here as:
> `![Galley panel with two printer cards and a filtered queue](docs/panel.png)`

## Prerequisites

**Runtime — required:**

| Program | Used for | Arch package |
|---|---|---|
| `ipptool` | All printer and job queries | `cups` |
| `cancel` | Cancelling jobs | `cups` |
| `cupsenable` / `cupsdisable` | Resuming and pausing queues | `cups` |
| `python3` | The collector | `python` |
| `systemctl` | Detecting whether cupsd is asleep | `systemd` |
| `notify-send` | Desktop notifications | `libnotify` |

Also required: **CUPS ≥ 2.4** (for `ipptool -X`, the XML plist output format —
JSON output via `-j` didn't land until CUPS 2.5) and a running `cups.service`
or `cups.socket`. There are no pip or npm dependencies at runtime.

**Development only** (not needed just to run the widget):

| Program | Used for | Arch package |
|---|---|---|
| `rsync` | `bin/install` | `rsync` |
| `inotifywait` | `bin/dev-watch` | `inotify-tools` |
| `jq` | Manifest validation in `bin/test` | `jq` |
| `node` | `Model.js` tests | `nodejs` |

Install anything missing with `omarchy pkg add <package>`. On a machine where
`python3` or `node` are managed by a version manager like mise rather than
pacman, `pacman -Qo` will report them as unowned — that's expected, not a
sign anything is broken.

Galley does **not** verify any of this at startup. A missing tool surfaces
as a collector error in the panel (see Troubleshooting below), not as a
friendly "please install X" message. An automated preflight check that maps
a missing binary to its package is deliberately deferred — see Known
Limitations.

## Install

```bash
git clone <this-repo> ~/Src/galley
cd ~/Src/galley
./bin/install
```

`bin/install` rsyncs the working tree into
`~/.config/omarchy/plugins/ssandys.galley/` (excluding `.git`, `tests/`,
`bin/`, and `docs/`). Then add the widget to the bar, either through the
shell's settings panel or from the command line:

```bash
omarchy bar move ssandys.galley --section right
```

## Reading the bar

| Bar shows | Meaning |
|---|---|
| Plain glyph | Idle — no active jobs |
| Glyph + `N` | `N` jobs currently active |
| Amber glyph | A job is held, or a supply is running low |
| Red glyph | A printer is stopped, or the collector itself failed |

Hovering the icon shows a tooltip summary, e.g. `2 printers · Canon@OLP
printing · 3 jobs`.

## Using the panel

- **Click a printer card** to filter the queue to that printer's jobs; click
  it again (or the `clear ✕` button) to show every printer's jobs again.
- **`r`** refreshes printers and the queue immediately.
- **`Esc`** clears the printer filter if one is set; press it again (or press
  it with no filter set) to close the panel.
- **Middle-click** the bar icon to refresh in the background without opening
  the panel.

## Configuration

Set these from the shell's widget settings panel for `ssandys.galley`, or
directly in `shell.json`. Defaults and ranges below come straight from
`manifest.json`.

| Key | Type | Default | Effect |
|---|---|---|---|
| `pollIntervalOpenSec` | integer (1–30) | `3` | How often (seconds) Galley polls CUPS while the panel is open. Also used while the panel is **closed** if a job is currently active, so the badge count stays current without waiting for the slow interval. |
| `pollIntervalIdleSec` | integer (5–300) | `30` | How often (seconds) it polls while the panel is closed **and** nothing is active. Has no effect whenever the panel is open or a job is active — see `pollIntervalOpenSec`. |
| `showSupplies` | boolean | `true` | Show ink/toner/drum levels on each printer card. |
| `supplyLowThreshold` | integer (5–50) | `15` | Percent level below which a supply counts as low — drives the amber bar color, the card's supply-low count, and the supply-low notification. |
| `notifyJobFailed` | boolean | `true` | Desktop notification when a job stops or aborts. |
| `notifyPrinterError` | boolean | `true` | Desktop notification when a printer stops or picks up an error reason. |
| `notifyJobCompleted` | boolean | `true` | Desktop notification when a job finishes printing. |
| `notifySupplyLow` | boolean | `true` | Desktop notification when a supply crosses below `supplyLowThreshold`. |

Supply-low notifications use hysteresis: once fired, the same supply won't
notify again until its level climbs back above `supplyLowThreshold + 10`.
This keeps a printer hovering right at the line from nagging you every poll.

## Troubleshooting

**The widget looks stale or broken after an edit — try `omarchy restart
shell` before assuming something is wrong.** Saving a plugin file hot-reloads
its *code* immediately, but if you changed the widget's *structure* (added a
new property, a new binding, a new top-level element) the running instance
is not re-created to match — you'll keep looking at the old shape. This has
already cost real debugging time on this exact plugin. `bin/dev-watch`
reinstalls the files on every save but does **not** solve this — it still
takes a full shell restart to pick up a structural change:

```bash
omarchy restart shell
```

(This restarts your whole shell, not just Galley — expect a brief flicker
across the whole bar and any open panels.)

**A job shows as "Job 42" with no owner.** The collector lost
`requesting-user-name` on that IPP request. With `JobPrivateValues=default`
(the CUPS default), cupsd redacts `job-name` and
`job-originating-user-name` from any request that omits it — you get a
queue of nameless, ownerless jobs instead of an error. If you've modified
`scripts/get-jobs.test` or `galley_collect.py`'s `run_ipptool`, check that
`-d user=$USER` (or the `requesting-user-name` attribute in the `.test`
file) is still present.

**A printer is missing some or all of its supply levels.** A level of `-1`
means CUPS doesn't know the value, and Galley drops it rather than showing
an empty bar. This is normal for some hardware — one of the two printers
this plugin was built against reports `-1` for all four toners while
reporting real levels for its waste box and drum, so seeing toner
percentages for one printer and not the other is expected, not a bug.

**The panel is nearly empty, showing only "CUPS idle — nothing queued."**
That's the calm/expected state when `cups.service` isn't currently running
(CUPS has an idle-exit timeout and can shut itself down between jobs — see
Known Limitations). Galley deliberately does not "poke" cupsd awake just to
poll it. Confirm with:

```bash
systemctl is-active cups.service
```

If it reports `inactive` and printing still works, this is expected — cupsd
will restart itself on the next real print job or IPP request. If it
reports `failed`, that's a real problem outside Galley's scope.

**Something looks wrong and you want to see the raw data.** Run the
collector directly — it's a standalone script, no widget required:

```bash
python3 scripts/galley_collect.py | jq .
```

This prints the exact JSON snapshot the panel is working from: printer
states, supplies, the active queue, and (on error) the full error message
the panel would otherwise truncate.

## Known limitations

- Cancel is restricted to your own jobs by `_user_cancel_any=0`.
- Page counts are unavailable for pending jobs; size is shown instead.
- Waste-toner levels are displayed without interpretation.
- Local cupsd only. Remote `CUPS_SERVER` is out of scope.
- Job-completed notifications depend on the job appearing in the completed
  list; if cupsd is restarted mid-job the classification degrades to
  silence.

## Uninstall

```bash
omarchy plugin disable ssandys.galley   # removes it from the bar
rm -rf ~/.config/omarchy/plugins/ssandys.galley
```
