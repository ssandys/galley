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
