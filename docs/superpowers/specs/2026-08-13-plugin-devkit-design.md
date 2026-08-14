# Plugin devkit: a portable `bin/` for Omarchy plugin development

**Status:** design, 2026-08-13. Supersedes `bin/install`.
**Scope:** `bin/dev`, `bin/dev-watch`, `bin/test` — the dev toolchain shared by
every `ssandys.*` Omarchy plugin.
**Canonical location:** this file. Other plugin repos reference it rather than
holding a copy, so the spec cannot drift the way the scripts did.

## Purpose

Two problems, one design.

**The lifecycle is half-built.** `bin/install` can bring a dev session up and
nothing takes it down. Teardown exists only as prose — `CONTRIBUTING.md:76-81`
tells you to type two commands by hand, one an `rm -rf` with a literal path that
the script would have derived for you.

**The scripts are copied between repos and drift.** galley and colophon carry
near-identical `bin/` trees that have diverged in both directions. Fixes do not
propagate, and neither repo knows it is behind.

The design goal is therefore stronger than "write `bin/dev`": make the three
scripts **byte-identical across every plugin**, so porting is `cp` and drift is
detectable by a test rather than by reading two files side by side.

## Evidence: the drift is real and bidirectional

Measured 2026-08-13 between `~/Src/galley` and `~/Src/colophon`.

**`bin/dev-watch` — already byte-identical.** `diff` exits 0. This is the
proof of concept: a dev script with no plugin-specific content stays identical
on its own.

**`bin/install` — differs functionally in exactly one place.** Everything else
is comment punctuation and line wrapping. The sole functional difference is the
display-name literal in the rewrite:

```bash
REWRITE="...; s/Colophon\( (dev)\)\?\"/Colophon (dev)\"/g"   # colophon
REWRITE="...; s/Galley\( (dev)\)\?\"/Galley (dev)\"/g"       # galley
```

Both repos already declare that name in `manifest.json` as `.name`. The script
derives `.id` from the manifest and hardcodes `.name`, for no reason beyond
history.

**`bin/test` — genuinely diverged, and galley is the one behind.** Galley exits
early when the Python suite fails, so a Python failure hides every JavaScript
regression behind it. Colophon fixed this and carries the reason in a comment:

> Both suites always run, and the exit code is decided here. Exiting early on a
> Python failure -- as an earlier version did -- silently skipped the JS suite
> entirely, so a JS regression could hide behind an unrelated Python one.

Colophon also passes `-t .` to `unittest discover`. Galley has neither change.

## Evidence: hardcoded rewrite targets have already caused a bug

`bin/install:37` rewrites the dev identity into two named files:

```bash
sed -i "$REWRITE" "$DEST/manifest.json" "$DEST/Panel.qml"
```

Colophon's identity has outgrown that list. `Service.qml:200`:

```qml
notifyProc.command = ["notify-send", "-a", "Colophon", "-u", "critical",
```

`Service.qml` is not a rewrite target, so **colophon's dev copy sends desktop
notifications branded identically to the published plugin.** When one fires there
is no way to tell which copy produced it — precisely the confusion the dev
identity exists to prevent. Galley's `CONTRIBUTING.md:53-54` promises otherwise:

> The dev copy announces itself — the bar catalogue lists it as "Galley (dev)",
> the panel header and its desktop notifications say the same.

That is true for galley and false for colophon. Extracting `Service.qml` moved
the notify call out of the one file `sed` knew about, and nothing failed.

**This is load-bearing for galley issue #1.** Galley's identity currently sits at
`Panel.qml:12,13` (`moduleName`, `ipcTarget`), `:102` (the `notify-send` app
name), and `:373` (the padded panel title). Issue #1 proposes extracting a
non-visual `Controller.qml`, and `notifyProc` is exactly the state it names for
moving. Performing that extraction against the current `bin/install` reproduces
colophon's bug in galley, silently. Deriving the rewrite targets is a
prerequisite for #1, not a cleanup.

## Principle: derive, do not parameterize

The instinct for shared tooling is a config file or exported variables per
plugin. Reject it. Every value the scripts need is already declared somewhere
authoritative:

| Value | Source of truth |
|---|---|
| Plugin id | `manifest.json` → `.id` |
| Display name | `manifest.json` → `.name` |
| Files carrying the identity | every deployed file `grep -I` treats as text |
| QML to lint | `*.qml` |
| Shell to syntax-check | `bin/*` and `scripts/*.sh` |
| Bar placement | `manifest.json` → `.barWidget.defaultSection` |

A parameter block would be a second declaration of things the manifest already
states, which is the same class of duplication that
`tests/test_cross_language.py` exists to police. Derivation leaves nothing to
keep in sync, and it is what makes the scripts identical rather than merely
similar.

**Consequence: no plugin-specific literal appears in any of the three scripts.**
That is the invariant the guard test in "Testing" enforces.

## `bin/dev`

Replaces `bin/install`. Single entry point, `case` dispatch, following the house
pattern already set by `scripts/galley_action.sh`: a usage block in the header
comment, `case` on the verb, errors to stderr, and a `--dry-run` flag.

### Verbs

| Verb | Sequence |
|---|---|
| `deploy` | `rsync -a --delete` → identity rewrite → verify. Never touches the running shell. |
| `up` | `deploy` → `omarchy-shell shell rescanPlugins` → `omarchy plugin enable $DEV_ID` → `omarchy restart shell` |
| `down` | Guard on registration, then `omarchy plugin disable $DEV_ID` → `omarchy restart shell` |
| `status` | Dev id; whether `$DEST` exists; whether registered; whether enabled |

`up` is idempotent. `deploy` and `rescanPlugins` are idempotent, `enable` on an
already-enabled id returns `ok`, and the restart is the reason you ran it again.

`down` disables without removing `$DEST`. `rsync --delete` already makes `up`
idempotent over a stale directory, so retaining it costs only disk while
preserving the dev copy's `shell.json` settings and keeping `up`/`down` a cheap
symmetric toggle. Removal stays the documented manual one-liner.

### `up` must rescan before enabling

`/usr/share/omarchy/shell/README.md:129-136` gives the hand-install sequence:

1. put files in `~/.config/omarchy/plugins/<id>/`
2. `omarchy-shell shell rescanPlugins`
3. `omarchy plugin enable <id>`

`bin/install:52` goes straight from `rsync` to `enable`, skipping step 2.
`omarchy-plugin-enable:83-88` exits 1 when the id is not in the registry, with an
error naming `rescanPlugins` as the fix. This works on a machine where the dev id
is already registered and **fails on the first deploy of a fresh clone.**

Code hot-reload under `~/.config/omarchy/plugins/` is automatic
(`README.md:161`) — that is what `bin/dev-watch` relies on. It is *registering a
new id* that needs the rescan. So the rescan belongs in `up`, not in `deploy`.

**The rescan is asynchronous, and rescanning is not enough on its own.**
`rescanPlugins` returns over IPC before the shell finishes re-walking the
plugin directories in the background. Measured live, on a genuinely cold
start — nothing deployed, the registry never having heard of the dev id —
the registry caught up roughly 373ms after the call returned. `up` used to
call `enable` microseconds after the rescan, so it lost that race every
time: the correct ordering (rescan before enable) was already in place, and
the first-ever deploy of a fresh clone still failed with omarchy's own "is
not known; run: rescanPlugins" error, even though the rescan had, in fact,
already been run. No `--dry-run` test could catch this, since a dry run
inspects only printed strings and performs no rescan to be caught by; nor
could `RealDeployTest`, which never touches the registry.

`up` therefore waits after the rescan: it polls the registry (via
`plugin_state`, the same query `status` and `down` use, driven in tests by
`DEV_STATE_FIXTURE`) until it reports the dev id as something other than
absent, bounded by a timeout so a genuine failure to register surfaces as a
clear error rather than a hang. This wait, not just the ordering, is what
makes a first-ever deploy on a fresh clone actually succeed.

### `down` must guard on registration, not enablement

`omarchy-plugin-disable:22-24` fails only when the id is unknown to the registry.
Disabling a known-but-already-disabled plugin returns `ok` and exits 0. Both
scripts run under `set -euo pipefail`, so an unguarded `disable` in the
never-deployed case aborts `down` before it reaches the restart, with an omarchy
error rather than a useful one.

```bash
omarchy plugin list --json | jq -e --arg id "$DEV_ID" 'any(.[]; .id == $id and .enabled)'
```

- not registered → report and exit 0, **no restart**
- registered but already disabled → report and exit 0, **no restart**
- otherwise → `disable`, then restart

Skipping the restart when nothing changed is deliberate. A shell restart flickers
the whole bar and closes open panels (`CONTRIBUTING.md:101-102`), which is too
rude for a no-op.

### No placement argument

`manifest.json` declares `barWidget.defaultSection: "right"` in both plugins, and
`omarchy plugin enable` honours it, so a `down`/`up` cycle returns the widget to
its declared section unaided. `up` passes no placement: it runs repeatedly, and
stamping a placement on every run would overwrite a position the user has since
changed by hand.

This also makes `CONTRIBUTING.md:45`'s `omarchy bar move ... --section right`
redundant; that line goes.

### `--dry-run`

Scanned position-independently and stripped from the verb arguments, as
`galley_action.sh` does. A single wrapper decides print-versus-execute:

```bash
run() { if (( DRY_RUN )); then printf '%s\n' "$*"; else "$@"; fi; }
```

This is the load-bearing testability decision. `bin/dev --dry-run up` emits its
exact command sequence with zero side effects, which is the only way to assert
**rescan precedes enable** without a machine that has never had the plugin
installed. `rsync` and `sed` route through `run` too, so a dry run touches
nothing at all.

`"$*"` flattens arguments, so a dry run renders an argument containing spaces
ambiguously while real execution via `"$@"` stays correct. This matches
`galley_action.sh` exactly, where the same trade is recorded as accepted in
`docs/FOLLOWUPS.md` under "Fine as is". Deliberate, not an oversight — do not
"fix" it into a divergence from the house pattern.

### Identity rewrite

```bash
manifest_field() {
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}

ID="$(manifest_field "$SRC/manifest.json" id)"
NAME="$(manifest_field "$SRC/manifest.json" name)"
DEV_ID="$ID-dev"
DEST="$HOME/.config/omarchy/plugins/$DEV_ID"
```

Both substitutions keep the existing property of tolerating already-rewritten
input, so a run over stale output cannot compound into `-dev-dev`. The name
substitution keeps anchoring on the **closing** quote, which is what catches the
padded panel title (`"  Galley"`) as well as the bare literal. Both patterns are
BRE-escaped rather than relying on the current dot-only expansion.

Targets are derived, not listed — every deployed file `grep` treats as text:

```bash
readarray -t targets < <(find "$DEST" -type f -exec grep -Il . {} + || true)
(( ${#targets[@]} )) || fail "no deployed text files found under $DEST"
sed -i "$REWRITE" "${targets[@]}"
```

**No name list and no extension list.** This design first replaced a named file
(`Panel.qml`) with a `*.qml` glob, and that glob then missed a deployed
`Model.js` in exactly the same way — a file-*type* list narrows on refactor for
the same reason a file-*name* list does. `grep -I` reports binary as
non-matching, which is what keeps `preview.png` out of `sed`'s path.

The empty-list guard is load-bearing, not tidiness: `grep -Fl PATTERN` with zero
file arguments reads stdin and hangs, and `verify()` passes this array straight
to `grep`. Without the guard, a failed rsync would produce a wedged deploy
rather than a failed one. `find -exec ... +` runs no `grep` at all when nothing
matches, so the enumeration itself cannot hang.

### Verification

A no-op `sed` would deploy a second plugin claiming the published id — the exact
silent collision the rewrite prevents — so the rewrite is proved, not trusted.
The existing manifest-id assertion stays. The `Panel.qml`-specific `ipcTarget`
grep is replaced by two generic assertions that mirror the `sed`'s own anchors:

```bash
grep -Fl "\"$ID\""   "$DEST"/*.qml    # must match nothing
grep -Fl "$NAME\""   "$DEST"/*.qml    # must match nothing
```

`grep -F` avoids escaping entirely. The quote anchors do the discriminating:
`"ssandys.galley"` does not match `"ssandys.galley-dev"`, and `Galley"` does not
match `Galley (dev)"`. Any QML file still carrying the published identity fails
the deploy and is named in the error.

This is strictly stronger than the check it replaces, which could only see
`Panel.qml`.

### Exit codes

Matching `galley_action.sh`: `0` success, `2` unknown or missing verb. Failures
from the underlying `omarchy` commands propagate under `set -euo pipefail`.

## `bin/test`

Adopt colophon's structure, plus the derived syntax check.

- Both suites always run; the exit code is decided at the end. Galley's current
  early exit lets a Python failure mask every JS regression.
- `unittest discover -s tests -t . -p 'test_*.py'`.
- The bash syntax check globs instead of naming files:

```bash
shopt -s nullglob
bash -n bin/* scripts/*.sh
```

This covers `bin/dev` automatically and any script added later. Galley's current
by-name list would silently omit `bin/dev`, letting a syntax error pass the suite
green. `nullglob` handles colophon, which has no `scripts/*.sh` — its action
script is Python and is covered by the Python suite. `bin/*` is never empty,
since `bin/test` is itself running, so `bash -n` can never fall through to
reading stdin.

This assumes the convention that `bin/` holds only bash. Both repos satisfy it. A
plugin adding a non-bash `bin/` entry must revisit this line.

Note the interaction with the QML lint below it: `nullglob` is shell-wide once
set, so `for qml in *.qml` stops iterating over a literal unmatched pattern and
its existing `[ -e "$qml" ] || continue` guard becomes redundant. Harmless, and
the guard should stay — it costs nothing and keeps the loop correct if `nullglob`
is ever moved or scoped.

## `bin/dev-watch`

Already byte-identical between repos; keep it, including the comment explaining
that the shell's inotify watcher follows only real paths, so a symlinked source
tree would not hot-reload.

Two one-line edits, at `:8` and `:14`, from `bin/install` to `bin/dev deploy`.
This is the fix for the restart problem: with the restart living in `bin/dev up`,
a `bin/dev-watch` that called `up` would restart the entire shell on every file
save.

## Testing

**`tests/test_dev.py`**, modeled on `tests/test_action.py::DryRunTest`, driving
`bin/dev --dry-run`:

- `up` emits `rescanPlugins` **before** `plugin enable` — the ordering bug above,
  otherwise reproducible only on a machine that has never had the plugin
- `deploy` emits no shell-interaction commands at all
- unknown verb exits 2; no verb exits 2
- `--dry-run` emits no `rsync` or `sed` execution

**The portability guard.** One test asserting the three scripts contain no
plugin-specific literal — not the plugin id, not the display name, not the repo
name — read from `manifest.json` rather than hardcoded, so the test itself ports
unchanged. This makes "byte-identical" an enforced invariant for this repo's
own literals, and `bin/test`'s own history is the argument for having it. Its
limit: the guard derives those literals from this repo's own `manifest.json`,
so it structurally cannot see *another* plugin's name written into these
scripts — a stray `colophon` literal here passes galley's `bin/test` clean and
only surfaces as a failure in colophon's own copy of the same test, at the
moment of porting.

Per the lesson recorded in `docs/FOLLOWUPS.md` and enforced throughout
`tests/test_cross_language.py`: a guard that pattern-matches source text is
guarding the text, not the behaviour. The `--dry-run` tests execute the real
script and assert on its real output. The portability guard is necessarily
textual, because absence-of-a-literal is a textual property — it is scoped to
exactly that and nothing else.

## Porting to another plugin

The procedure this spec exists to make possible:

1. `cp ../galley/bin/dev ../galley/bin/dev-watch ../galley/bin/test bin/`
2. `chmod +x bin/dev bin/dev-watch bin/test` — nothing in `bin/test` checks the
   executable bit
3. `cp ../galley/tests/test_dev.py tests/`
4. `rm bin/install`
5. Update the repo's own docs (`AGENTS.md`, and `CONTRIBUTING.md` where present)
   to name `bin/dev`, and link this spec
6. `bin/test`

There is no step where you edit a copied script. If a port requires one, the
derivation is incomplete and this spec is wrong — fix the script, not the copy.

**Prerequisite for colophon specifically:** its identity rewrite missed
`Service.qml`, and after the `*.qml` glob fixed that, it still missed
`Model.js`. Porting `bin/dev` now fixes both, because the rewrite covers every
deployed text file.

Verify by deploying into a scratch `HOME` and confirming **no** deployed file
carries the published id or display name — not by checking that notifications
read "Colophon (dev)", which was the acceptance criterion originally proposed
here and which passed while the `Model.js` tooltip leak stood. Confirmed
against colophon's real tree: `Model.js:263`, `tooltipText`'s early return,
deploys as `return "Colophon (dev)"`.

The lesson worth keeping: an acceptance check aimed at the surface where a bug
was *noticed* will pass while the same bug survives on a surface nobody
thought to look at. Check the property, not the symptom.

## Out of scope, filed separately

Both are pre-existing bugs in shipped code. Folding them into this spec would
blur what is a new pattern against what is a repair.

- **galley's `bin/test` early exit** —
  [galley#16](https://github.com/ssandys/galley/issues/16). A Python failure
  currently skips the JS suite. Fixed incidentally by adopting colophon's
  structure here; close that issue when this lands, or fix it directly there if
  this work slips.
- **colophon's notification identity** —
  [colophon#5](https://github.com/ssandys/colophon/issues/5), now closed. The
  dev copy was indistinguishable from the published plugin in `notify-send`.
  Porting `bin/dev` fixed the `Service.qml` half; the `Model.js` tooltip half
  was filed as [galley#17](https://github.com/ssandys/galley/issues/17) and is
  fixed here by deriving the rewrite target set rather than listing file types.

Also out of scope: generalizing beyond the `ssandys.*` plugins, any shared-repo
or submodule vending of `bin/`, and galley issue #1's `Controller.qml`
extraction — though #1 should not be attempted until `bin/dev` lands, for the
reason given above.

## Decisions recorded

| Decision | Chosen | Why |
|---|---|---|
| Share via copy, or vend from a shared repo | Copy | Plugins are distributed by `omarchy plugin add <git-url>`; a submodule is not fetched by a plain clone. The cost lands on the distribution path to serve files `rsync` already excludes from the deployed copy. |
| `down` removes `$DEST` | No | Preserves dev settings; `rsync --delete` already makes `up` idempotent. Removal stays a documented manual step. |
| `bin/dev-watch` folded into `bin/dev watch` | No | It already works and is already identical across repos. Two one-line edits beat a rewrite. |
| `bin/dev status` included | Yes | ~3 lines atop the state query `down` needs anyway, and it answers "is the widget I am looking at my working tree?" — the confusion the whole dev-identity scheme addresses. |
| Per-plugin config block | No | Every value is already declared in `manifest.json`. See "Principle". |
