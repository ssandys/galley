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
| `rsync` | `bin/install` | `rsync` |
| `inotifywait` | `bin/dev-watch` | `inotify-tools` |
| `jq` | Manifest validation in `bin/test` | `jq` |
| `node` | `Model.js` tests | `nodejs` |

Install anything missing with `omarchy pkg add <package>`. On a machine
where `python3` or `node` are managed by a version manager like mise rather
than pacman, `pacman -Qo` will report them as unowned — that's expected, not
a sign anything is broken.

## Running from a source checkout

Don't install the published plugin and edit it in place; work from a clone
and deploy into the plugin directory:

```bash
git clone https://github.com/ssandys/galley.git ~/Src/galley
cd ~/Src/galley
./bin/install
omarchy bar move ssandys.galley --section right
```

`bin/install` rsyncs the working tree into
`~/.config/omarchy/plugins/ssandys.galley/`, excluding everything that isn't
needed at runtime (`.git`, `tests/`, `bin/`, `docs/`, and the markdown docs).

If you already added Galley with `omarchy plugin add`, remove it first —
`omarchy plugin remove ssandys.galley` — so the git-managed copy and your
`bin/install` copy aren't fighting over the same directory.

## The edit loop

`./bin/dev-watch` watches the source tree with `inotifywait` and reruns
`bin/install` on every save, so the deployed copy always matches your working
tree.

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
