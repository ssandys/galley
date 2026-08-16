# Printer admin actions: set default, open the web UI

**Status:** design, 2026-08-16. Implements [#13](https://github.com/ssandys/galley/issues/13).
**Supersedes:** the Phase 2 "Admin actions" bullet in
`docs/superpowers/specs/2026-08-08-galley-design.md`, which specified three
actions and estimated the cost as "UI crowding and confirmation dialogs".
Neither cost survives the narrowed scope — see "What the original estimate got
wrong".

## Scope

Two actions:

| Action | Kind | Command |
|---|---|---|
| Set default | per-printer | `lpoptions -d <printer>` |
| Open the CUPS web UI | global | `xdg-open http://localhost:631` |

**Accept/reject jobs is dropped.** That removes the two things the issue treated
as central: rendering `accepting` (collected at `galley_normalize.py:109`, never
displayed), and deciding how a rejecting printer shows without
`printerHasError` reclassifying it as a fault. `printerHasError` and
`galley_normalize.has_error` are untouched by this work.

## The finding that shapes everything

`lpoptions -d` and the collector's existing default-printer read **target
different scopes**. Verified on the target machine, 2026-08-16:

| | before `lpoptions -d Brother@Home` | after |
|---|---|---|
| `~/.cups/lpoptions` | absent | `Default Brother@Home` |
| `lpstat -d` (client view) | Canon@OLP | **Brother@Home** |
| `CUPS-Get-Default` (IPP — what galley reads) | Canon@OLP | **Canon@OLP, unchanged** |

`lpoptions -d`, run unprivileged, writes a **per-user** default to
`~/.cups/lpoptions`. `scripts/get-printers.test`'s second operation asks cupsd
via `CUPS-Get-Default` for the **system** default, which never sees it.

So the naive implementation — the one the issue describes as "a single CLI
call" — would write a real change, leave the ★ at `Panel.qml`'s
`modelData.isDefault` exactly where it was, and read as a broken button. That
makes set-default the *expensive* action of the two, not the cheap one.

The machine was restored afterwards: `~/.cups/lpoptions` deleted, the `~/.cups`
directory it created removed, both views back to `Canon@OLP`.

## Decision: change the read, not the write

The fix is to report the **client's** default rather than cupsd's, so
`lpoptions -d` and the ★ agree.

The rejected alternative was `lpadmin -d`, setting the *system* default to match
the existing read. The two commands are two layers of the same setting, and
`lpoptions` sits on top — from their man pages:

> **`lpadmin -d`**: "sets the default printer or class to *destination*.
> Subsequent print jobs submitted via the `lp` or `lpr` commands will use this
> destination **unless the user specifies otherwise with the `lpoptions`
> command**."

> **`lpoptions -d`**: "Sets the **user** default printer to *destination*… This
> option **overrides the system default printer for the current user**."

| | Scope | Written to | Seen by `CUPS-Get-Default`? |
|---|---|---|---|
| `lpadmin -d` | system, all users | cupsd's own config | yes |
| `lpoptions -d` | current user | `~/.cups/lpoptions` | no |
| `sudo lpoptions -d` | all users, client-side | `/etc/cups/lpoptions` | no |

That third row is why "client default" and "system default" are not simply
"user" and "machine": a root-written `lpoptions` file is machine-wide and still
invisible to cupsd. The precedence chain below therefore reads both `lpoptions`
locations, not just the user's.

**Recording honestly that the rejected option's risk was lower than I first
estimated:** the original design spec verified `cupsctl` succeeds unauthenticated
on this machine and concluded "admin ops are viable for phase 2", so `lpadmin -d`
would most likely have worked without a password prompt. It was not chosen
anyway, for reasons that stand independently:

- For a personal-use widget on a single-user desktop, the per-user default is the
  more useful notion — it is what `lp` and applications will actually use *for
  you*.
- It needs no privileges at all, on any machine, which matters for something
  living in a bar where an interactive password prompt cannot be answered.
- It does not depend on a cupsd policy that a future config change could revoke,
  turning a working button into a stderr blob.

**Semantic consequence, stated because it changes an existing displayed field:**
★ comes to mean *your* default rather than the system's. On the target machine
they are identical — there is no `lpoptions` file — and diverge only once a
per-user default is set.

## Resolving the client default

The collector resolves the default in the order the CUPS client library does,
first hit wins:

1. `~/.cups/lpoptions` — a line `Default <name>`
2. `/etc/cups/lpoptions` — same
3. the existing `CUPS-Get-Default` IPP result

Not `lpstat -d`. Its output (`system default destination: NAME`) is localised, so
parsing it is fragile in a way that fails silently on a non-English system. File
reads are deterministic, add no subprocess to a collector that currently shells
out only to `ipptool` and `systemctl`, and add no dependency.

`lpoptions` files may contain per-destination option lines as well as the
`Default` line; only a line whose first token is `Default` is read, and only its
second token.

### Known limitation: `LPDEST` and `PRINTER` are not honoured

The CUPS client library consults two environment variables **above** both
`lpoptions` files: `LPDEST` first, then `PRINTER`. This design deliberately
ignores them, so the chain above is three of CUPS' five sources.

The consequence, stated plainly: **if either variable is set, the ★ can disagree
with the printer `lp` actually uses.** The widget would show the `lpoptions`
default while the environment overrode it.

Two reasons that trade is accepted rather than papered over:

- The collector runs as a child of the shell that launched the Omarchy shell, so
  it sees *that* environment — not the environment of whatever terminal the user
  is typing in. Honouring the variables would therefore be right only when the
  two happen to agree, and silently wrong otherwise. A rule that is correct
  sometimes, in a way the user cannot see, is worse than a rule that is simple
  and documented.
- `lpoptions -d` — the action this feature adds — writes to `~/.cups/lpoptions`.
  So the layer the button controls is always in the chain. The variables can only
  ever shadow a value the widget itself did not set.

If this ever bites, the fix is two `os.environ` lookups at the front of the
chain, plus a note that the collector's environment is the shell's.

## Actions

`scripts/galley_action.sh` gains two verbs:

| verb | command | target |
|---|---|---|
| `set-default` | `lpoptions -d "$TARGET"` | required |
| `web-ui` | `xdg-open http://localhost:631` | **none** |

Its target check is currently blanket — a single `[[ -z "$TARGET" ]]` after the
`case`, pinned by `test_missing_target_exits_3`. It becomes per-verb, so
target-taking verbs still exit 3 without one and `web-ui` does not. The existing
test keeps passing unchanged, because `pause` still requires a target.

`http://localhost:631` is hardcoded. It is the IANA IPP port and CUPS' default,
and the original spec verified `WebInterface: Yes` on this machine. Discovering a
non-default `Listen` port is out of scope.

**No confirmation dialogs.** The issue asked for them because set-default is
"quietly disruptive and neither is undoable from the panel". Under the chosen
design it is neither: the ★ moves on the next poll, and it is undone by setting
another printer default from the same row. A dialog would guard a reversible,
visible, per-user preference change. The `web-ui` action mutates nothing.

## Placement

- **`set default`** joins the card action row beside `pause`/`resume`, and is
  **hidden** on the printer that is already the default, so it never renders as a
  no-op.
- **The web UI button** joins the panel header beside `Refresh`. That row already
  hosts the one existing global action; a per-printer row is the wrong home for
  something that is not per-printer.

**No overflow menu.** The issue proposed one because "the card action row is
already three buttons wide at times". It is not: the row is `pause`/`resume` plus
`cancel all`, and `cancel all` is `visible: modelData.queuedJobCount > 0`, so it
is frequently a single button. One action added to the card and one to the header
crowds nothing, and no new UI component is introduced.

## Dependencies

`lpoptions` ships with `cups`, already a hard runtime dependency —
`pacman -Qo` confirms `cups 2:2.4.19-1`.

`xdg-open` comes from **`xdg-utils`, a new runtime dependency**, and needs a row
in `README.md`'s runtime table. Galley does not verify dependencies at startup by
design, so a missing `xdg-open` surfaces as a collector/action error in the panel
— which is exactly the behaviour `README.md` already documents for a missing
tool.

## Testing

**Python — where the real logic is.** The default-resolution chain gets a test
per precedence level plus each fallback: the user file wins over the system file,
the system file over the IPP result, and the IPP result when neither file is
present. Plus one asserting `LPDEST`/`PRINTER` are ignored, so the documented
limitation is a tested property rather than a claim. Also: an
`lpoptions` file with option lines but no `Default` line falls through, and a
malformed line does not raise. Driven with `tmp_path` and patched `os.environ`,
no real files touched.

**Action script — via `--dry-run`,** as `tests/test_action.py` already does:
`set-default` emits `lpoptions -d <printer>`; `web-ui` emits the `xdg-open` line
and succeeds with no target; a target-taking verb still exits 3 without one.

**QML — not unit-testable here.** `bin/test`'s own comment records that qmllint
resolves neither Quickshell imports nor `Model.*` lookups, so binding errors
render as defaults and pass. Verified live instead: click `set default` on a
non-default printer, confirm the ★ moves on the next poll; click the web UI
button, confirm a browser opens; confirm `set default` is absent on the printer
that is already default.

## Out of scope

- **Accept/reject jobs**, and therefore rendering `accepting`.
- **An overflow menu** and **confirmation dialogs** — the two costs the original
  Phase 2 bullet named, neither of which applies now.
- **Setting the system default** (`lpadmin -d`). Deferred, not refused; if the
  system default is ever wanted, the read stays as it is and only a verb is
  added.
- **Discovering a non-default cupsd port.**
- **Honouring `LPDEST`/`PRINTER`** — see "Known limitation" above. Listed here
  too so a reader skimming for scope does not have to infer it from the
  precedence chain.

## What the original estimate got wrong

Worth recording, because the same trap is easy to re-enter.

The Phase 2 bullet said the three actions were "each a single CLI call" and that
"the cost is UI crowding and confirmation dialogs". Both halves were wrong for
this scope:

- The **cost was in neither place.** Crowding evaporates once the global action
  goes in the header, and confirmation is unnecessary for a reversible, visible,
  per-user change. The real cost was a read/write scope mismatch invisible from
  the command line alone — `lpoptions -d` genuinely is a single call, and it
  genuinely does not do what the widget would need it to.
- "A single CLI call" measured the *action* and ignored whether the widget could
  **see the result**. An action whose effect is invisible is not done.
