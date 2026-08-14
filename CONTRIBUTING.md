# Contributing to Galley

This file covers working *on* Galley — running it from a source checkout,
the edit/reload loop, and the test suite. If you just want to use the
widget, `README.md` is the whole story.

Two documents sit behind this one, and both are worth reading before a
non-trivial change:

- **`AGENTS.md`** — the layer map, the two load-bearing invariants (Python
  stays stdlib-only; `Model.js` stays pure and QML-safe), and a catalogue of
  the traps that have already cost someone an hour.
- **`docs/superpowers/specs/2026-08-08-galley-design.md`** — the
  authoritative design record, including the IPP quirks observed on the real
  target hardware and the reasoning behind what was deliberately left out.

`docs/FOLLOWUPS.md` tracks known-and-deferred work. If something looks
missing, check there before treating it as an oversight.

## Development prerequisites

On top of the runtime requirements in `README.md`:

| Program | Used for | Arch package |
|---|---|---|
| `rsync` | `bin/dev` | `rsync` |
| `inotifywait` | `bin/dev-watch` | `inotify-tools` |
| `jq` | Manifest validation in `bin/test` | `jq` |
| `node` | `Model.js` tests | `nodejs` |

Install anything missing with `omarchy pkg add <package>`. On a machine
where `python3` or `node` are managed by a version manager like mise rather
than pacman, `pacman -Qo` will report them as unowned — that's expected, not
a sign anything is broken.

## Running from a source checkout

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

`bin/dev` has four verbs, and every one of them takes `--dry-run`, which
prints the exact command sequence instead of performing any of it:

| Verb | What it does |
|---|---|
| `up` | deploy, register, enable, restart the shell |
| `down` | disable the dev plugin and restart the shell — a no-op, with no restart, if there is nothing to disable |
| `deploy` | deploy only; never touches the running shell |
| `status` | the dev id, whether it is deployed, and whether the registry has it enabled |

The registration step in `up` is not decoration. `omarchy plugin enable`
exits non-zero for an id the registry has never seen, which is every first
deploy of a fresh clone, so `up` runs `omarchy-shell shell rescanPlugins`
first. `bin/install` skipped that and only worked on a machine where the dev
id already existed. That rescan itself is asynchronous — it returns before
the shell has actually finished registering the id — so `up` then waits,
polling the registry until the id lands, before calling `enable`.

That deploys to `~/.config/omarchy/plugins/ssandys.galley-dev/` under the
plugin id **`ssandys.galley-dev`**, excluding everything not needed at
runtime (`.git`, `tests/`, `bin/`, `docs/`, and the markdown docs). You can
keep the published `ssandys.galley` installed and on the bar at the same
time; the two are separate plugins as far as the shell is concerned. The dev
copy announces itself — the bar catalogue lists it as "Galley (dev)", the
panel header and its desktop notifications say the same.

**The id, not the directory name, is what keeps them apart.** The registry
keys `installedPlugins` by `manifest.id` (`PluginRegistry.qml`,
`parseScanOutput`), and a third-party plugin claiming an id another
third-party plugin already used silently overwrites it in that map — no
warning, and which copy survives comes down to glob order. Renaming only the
directory would give you a dev install that is sometimes the code you're
editing and sometimes isn't.

So `bin/dev` rewrites the identity *in the deployed copy* — the manifest id,
the display name, and the `moduleName`/`ipcTarget` properties in every
top-level QML file — and then asserts the rewrite landed rather than
trusting the `sed`. The source tree stays canonical, which is the point: no
permanent dirt in `git status`, and nothing to remember not to commit. If
you ever change the id in `manifest.json`, `bin/dev` picks it up
automatically; it derives the dev id from the source manifest instead of
hardcoding it.

Because settings in `shell.json` are keyed by plugin id, the dev copy starts
from the manifest defaults and keeps its own configuration. Tuning a poll
interval on `ssandys.galley-dev` will not touch your real one.

To take the dev copy down when you're done:

```bash
./bin/dev down
```

That disables the dev plugin and restarts the shell — unless there was nothing
to disable, in which case it says so and leaves your shell alone rather than
flickering the whole bar for a no-op. It deliberately leaves
`~/.config/omarchy/plugins/ssandys.galley-dev/` in place, so the dev copy's
settings survive and the next `bin/dev up` is cheap; `rsync --delete` makes
the redeploy idempotent regardless. `./bin/dev status` reports what is
deployed and whether it is enabled. To reclaim the disk as well:

```bash
rm -rf ~/.config/omarchy/plugins/ssandys.galley-dev
```

## The edit loop

`./bin/dev-watch` watches the source tree with `inotifywait` and reruns
`bin/dev deploy` on every save, so the deployed copy always matches your
working tree. It uses `deploy` rather than `up` on purpose: `up` restarts the
shell, and doing that on every keystroke-to-disk would flicker the whole bar
continuously.

**It does not solve the restart gotcha.** Quickshell hot-reloads a plugin's
*code* on file change, but if you changed the widget's *structure* — a new
property, a new binding, a new top-level QML element — the already-running
widget is not recreated to match, and you'll keep looking at the old shape no
matter how many times `dev-watch` reinstalls the files underneath it. This
has already cost real debugging time on this exact plugin. When a save
doesn't seem to take effect, run:

```bash
omarchy restart shell
```

before spending any time debugging the "bug." That restarts your whole
shell, not just Galley — expect a brief flicker across the bar and any open
panels.

To drive the panel through a state you don't have hardware for, replay a
recorded fixture instead of calling `ipptool`:

```bash
GALLEY_FIXTURE=tests/fixtures/busy python3 scripts/galley_collect.py
```

## Porting the dev toolchain to another plugin

`bin/dev`, `bin/dev-watch` and `bin/test` contain **no plugin-specific
literal**. The id and display name come from `manifest.json`, the files
carrying them are globbed rather than named, and the lint and syntax checks
glob too. So the three scripts are byte-identical across every plugin, and
porting them is a copy with no edits:

```bash
cd ~/Src/<other-plugin>
cp ../galley/bin/dev ../galley/bin/dev-watch ../galley/bin/test bin/
cp ../galley/tests/test_dev.py tests/
chmod +x bin/dev bin/dev-watch bin/test
git rm bin/install
bin/test
```

`tests/__init__.py` must exist — `unittest discover -t .` needs `tests/` to be
importable — and nothing in `bin/test` checks the executable bit, hence the
`chmod`.

**If a port needs you to edit a copied script, the derivation is incomplete
and it is this repo's bug to fix, not the destination's to patch.**
`tests/test_dev.py`'s `PortabilityTest` enforces that: it reads the id and
name from whichever `manifest.json` it finds, so it ports unchanged and fails
in the destination repo if a literal slipped through.

One limit worth knowing, because it decides where a mistake surfaces. The
guard only knows *its own* repo's names, so another plugin's name written into
these scripts is invisible here and only fails in the repo you copy them into —
at that first `bin/test`, not before. The reasoning behind all of this is in
`docs/superpowers/specs/2026-08-13-plugin-devkit-design.md`, which is the
canonical copy; sibling repos reference it rather than holding their own.

## Tests

```bash
./bin/test
```

That runs the lot: `jq` manifest validation, `bash -n` on the shell scripts,
`qmllint` on the QML, the Python suite, and `node --test tests/model.test.js`.

**A green run does not mean the panel works.** `qmllint` can't resolve
Quickshell or Omarchy imports, so an unknown component, a typo'd property, or
a reference to something that doesn't exist all pass silently. It tells you
`Panel.qml` *parses*. QML correctness is verified by hand against the live
shell — see the edit loop above. `AGENTS.md` has the full breakdown of what
each layer of the suite does and doesn't cover.

## Never edit `/usr/share/omarchy/`

It's overwritten wholesale on `omarchy update`. Reading it to understand how
the shell's `PluginRegistry`, `WidgetButton`, or other shared components
behave is fine and often the fastest way to answer a question — just don't
write there.
