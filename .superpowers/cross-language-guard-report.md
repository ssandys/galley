# Cross-language guard tests — report

**Status:** Complete. All four requested guards implemented, `CrossLanguageErrorReasonsTest` moved unchanged, `AGENTS.md` updated, full suite green, all four guards proven load-bearing against scratch perturbations (never against the repo).

**Commit:** `2895f23` on branch `cross-language-guard` (parent `66b7dc2`).

**Branch:** `cross-language-guard`, repo `/home/sean/Src/galley`.

## What was built

- **`tests/test_cross_language.py`** (new) — home for all cross-language invariants:
  - `CrossLanguageErrorReasonsTest.test_javascript_error_reasons_match_python` — moved verbatim from `tests/test_normalize.py`. Same class name, same method name, same behavior. Verified it still runs under that exact name (`python3 -m unittest tests.test_cross_language.CrossLanguageErrorReasonsTest.test_javascript_error_reasons_match_python`) so `AGENTS.md`'s existing reference (class + method, no file path) stays valid.
  - `StateNameLiteralsTest.test_state_literals_are_valid_python_states` — Guard 1. Scrapes `state === "..."` from `Model.js` and `Panel.qml` via regex, imports `galley_normalize` directly for `PRINTER_STATES`/`JOB_STATES` (no regex on the Python side, per spec), asserts every scraped literal is in the union of values. Found 5 distinct literals (`printing`, `stopped`, `processing`, `held`, `aborted`), asserts `len(literals) >= 3` as the "not vacuously passing" floor.
  - `SupplyLowThresholdDefaultTest.test_all_seven_defaults_agree` — Guard 2. Parses `manifest.json` with `json` (both `defaults.supplyLowThreshold` and the `schema` entry's `defaultValue`), uses `inspect.signature` for `galley_collect.collect` and `galley_normalize.build_snapshot`'s Python defaults, and regex for the three source literals that aren't function defaults (`Panel.qml`'s `settingValue` fallback, `Model.js`'s `opts.threshold || N`, and the plain `threshold = 15` local assignment in `galley_collect.main()` — distinguished from the `threshold=15` keyword-default spelling by requiring surrounding spaces, matching this codebase's actual PEP8 style in each spot). All seven currently agree at `15`.
  - `WasteTonerExclusionTest` — Guard 3, two tests. `test_python_low_supplies_excludes_waste_toner_behaviourally` calls the real `gn.low_supplies()` with a waste-toner marker below threshold and asserts it comes back empty (behavioral, not string-matching). `test_javascript_skips_waste_toner_in_both_functions` extracts the `supplyColor` and `diffSnapshots` function bodies from `Model.js` (by locating `function <name>(` through the next `\nfunction `) and asserts each contains a `type === "waste-toner"` comparison — not just the bare substring, see caveat below. Docstring explicitly says this half is weak by nature.
  - `ColorPaletteTest.test_qml_hex_colors_are_all_in_the_js_palette` — Guard 4. Scrapes `COLOR_*` hex constants from `Model.js` and every `#rrggbb` literal from `Panel.qml`, asserts the QML set is a subset of the JS palette. Docstring states this freezes the duplication rather than fixing it (`Panel.qml` should still consume the palette instead of inlining).
- **`tests/test_normalize.py`** — `CrossLanguageErrorReasonsTest` removed (moved, not duplicated).
- **`AGENTS.md`** — trap #12 extended in place: still names the `ERROR_REASONS` guard specifically, now also states that `tests/test_cross_language.py` is the home for all cross-language invariants and lists the other three it covers (state-name strings, the threshold default, waste-toner, the color palette).

No changes to `Model.js`, `Panel.qml`, `manifest.json`, or `scripts/`.

## A bug caught while writing Guard 3

The first version of `test_javascript_skips_waste_toner_in_both_functions` did `assertIn("waste-toner", body)` — plain substring presence. When proving it load-bearing by renaming the `supply.type === "waste-toner"` comparison inside `supplyColor` to `"toner-waste"`, the test **still passed**, because `supplyColor`'s leading comment (`// waste-toner polarity is vendor-dependent...`) still contains the literal substring `"waste-toner"`. Caught this during the load-bearing proof step (not by inspection) and tightened the assertion to `assertRegex(body, r'type\s*===\s*"waste-toner"')`, which correctly fails on the same perturbation. This is now reflected in the committed test.

## Verification

- `python3 -m unittest discover -s tests -p 'test_*.py' -v` → **61 tests, OK** (56 previously existing + 1 moved + 4 new guard tests; net +5 from before this branch).
- `./bin/test` → **exit code 0** (manifest valid, bash syntax ok, qmllint ok, 61 Python tests OK, 32 JS tests via `node --test` OK).
- `CrossLanguageErrorReasonsTest.test_javascript_error_reasons_match_python` confirmed still resolvable under that exact dotted name after the move.

## Load-bearing evidence (each perturbed only in a throwaway `/tmp` scratch copy, never the repo; each scratch copy was fresh per guard, `__pycache__` cleared, `python3 -B` used, to avoid a bytecode-cache false-negative encountered mid-session and worked around)

**Guard 1** — `scripts/galley_normalize.py`: `4: "printing"` → `4: "print-active"`:
```
AssertionError: 'printing' not found in {'pending', 'aborted', 'processing', 'completed', 'held', 'idle', 'print-active', 'stopped', 'canceled'} : 'printing' is compared against in Model.js/Panel.qml but is not a value galley_normalize.py's PRINTER_STATES/JOB_STATES can ever emit
```

**Guard 2** — `Panel.qml`: `settingValue("supplyLowThreshold", 15)` → `..., 20)`:
```
AssertionError: 2 != 1 : supplyLowThreshold defaults have diverged: {'manifest.json barWidget.defaults.supplyLowThreshold': 15, 'manifest.json barWidget.schema[supplyLowThreshold].defaultValue': 15, 'Panel.qml settingValue("supplyLowThreshold", N)': 20, 'Model.js var threshold = opts.threshold || N': 15, 'galley_collect.collect(threshold=N) signature': 15, "galley_collect.main()'s threshold = N": 15, 'galley_normalize.build_snapshot(threshold=N) signature': 15}
```

**Guard 3** — two failures proven independently:
- `scripts/galley_normalize.py`: removed the `s.get("type") != "waste-toner" and` clause from `low_supplies`:
```
AssertionError: Lists differ: [{'name': 'Waste Toner Box', 'type': 'waste-toner', 'level': 1}] != []
... : low_supplies no longer excludes waste-toner: a marker at 1% with a threshold of 50 was reported as low
```
- `Model.js`: `supplyColor`'s `supply.type === "waste-toner")` → `... === "toner-waste")`:
```
AssertionError: Regex didn't match: 'type\\s*===\\s*"waste-toner"' not found in 'function supplyColor(supply, threshold, fallback) {\n  // waste-toner polarity is vendor-dependent and undefined by IPP, so it is\n  // shown but never warned on.\n  if (!supply || supply.type === "toner-waste") return fallback\n...' : supplyColor() in Model.js no longer skips "waste-toner"
```

**Guard 4** — `Panel.qml`: `#22c55e` → `#22c55f` (one hex digit):
```
AssertionError: '#22c55f' not found in {'#eab308', '#22c55e', '#3b82f6', '#ef4444'} : #22c55f appears in Panel.qml but is not one of Model.js's COLOR_* constants ({'#eab308', '#22c55e', '#3b82f6', '#ef4444'}) -- the two palettes have diverged
```

All four (five, counting Guard 3's two sub-tests) fail with a clear, specific message. None passed vacuously.

## Live divergence discovered

None. All seven `supplyLowThreshold` copies agree at `15`; all five state-name literals are valid Python states; `waste-toner` is excluded behaviorally in Python and by literal in both `Model.js` functions; all three `Panel.qml` hex colors are members of `Model.js`'s palette. No fix was needed or made to `Model.js`, `Panel.qml`, `manifest.json`, or `scripts/`.

## Concerns / caveats worth flagging

1. **Guard 1's regex relies on a camelCase coincidence.** `state\s*===\s*"..."` correctly ignores `Panel.qml`'s `cupsdState === "asleep"/"error"/"running"` comparisons only because `State` there is capitalized (different vocabulary — daemon status, not printer/job state) — a case-sensitive regex, not a semantic distinction. If a future `state`-suffixed (all-lowercase) variable is introduced for something outside the printer/job vocabulary, it would false-trip this guard. Currently correct; worth a comment if it ever needs revisiting.
2. **Guard 3's JS check is a heuristic function-body extraction** (regex from `function <name>(` to the next `\nfunction `), not a real JS parse. It's good enough to catch a renamed comparison (proven above) but would not survive a significant restructuring of `Model.js` (e.g., functions no longer separated by a lone `function ` line). The task explicitly called this guard "weak by nature," so this is in line with that framing.
3. **The task's motivating narrative also mentions a historical `accepting === false` divergence** as one of two real defects from this class of bug. Confirmed by inspection: `accepting` is set in `galley_normalize.py` but has no comparison against it anywhere in `Model.js` or `Panel.qml` today — it appears to have been resolved by removing the duplicated JS-side check entirely (there's a comment in `Model.js` noting "not accepting jobs is a deliberate admin state, kept out on purpose"). So there is currently nothing to guard there; flagging only so it's a known, considered gap rather than an overlooked one.
4. Scratch-copy perturbation testing hit one methodological trap worth remembering for next time: reusing the same scratch directory across sequential perturb/restore cycles for the same file can produce a false pass if the perturbed and restored byte counts collide within the same mtime second (Python's default timestamp-based `.pyc` cache). Worked around by using a fresh `cp -r` scratch directory per guard and `python3 -B` (no bytecode cache) — mentioned here in case it recurs in future guard-writing work on this repo.

## Round 2 — review fix (Critical)

**Finding:** `WasteTonerExclusionTest.test_javascript_skips_waste_toner_in_both_functions` passed against a reviewer perturbation that kept the string `"waste-toner"` in `supplyColor` (moved into a dead `var neverUsed = supply && supply.type === "waste-toner"` statement) while deleting its actual effect — a real regression that would color a 1%-full waste-toner marker with `COLOR_ERROR` in the live panel. The regex-based assertion (`type\s*===\s*"waste-toner"`) matched the vestigial dead statement's text and reported `ok`. Root cause: matching text instead of executing code — the same failure mode already caught once this session (a comment false-passing a substring check) recurring one layer deeper (dead code false-passing a regex check).

**Fix:** Replaced the regex-based JS test with `test_javascript_never_colors_or_alerts_waste_toner`, which shells out to `node -e` (via `subprocess.run`), `require()`s `Model.js` by absolute path, and asserts on real return values from `supplyColor` and `diffSnapshots`:
- `supplyColor({type:"waste-toner", level:1}, 15, "FALLBACK")` must return exactly `"FALLBACK"`.
- Control: `supplyColor({type:"toner", level:1}, 15, "FALLBACK")` must return something other than `"FALLBACK"` — rules out a `supplyColor` that always returns the fallback.
- `diffSnapshots` must emit 0 `supply-low` events for a waste-toner marker crossing the threshold.
- Control: `diffSnapshots` must emit >=1 event for a non-waste marker under identical conditions — rules out a `diffSnapshots` that never fires.

Guarded with `@unittest.skipUnless(shutil.which("node"), "node is required to verify Model.js behaviour")` — a visible, reasoned skip in test output, not a silent pass. The old regex-based test method was deleted, not kept alongside. `test_python_low_supplies_excludes_waste_toner_behaviourally` (already behavioral, confirmed sound by the reviewer) is unchanged.

**AGENTS.md:155** reworded instead of hardcoding a count that will rot again: now says the Python suite count "grows over time -- read it off the test output," states the current count (61) as of this writing, and notes the new JS guard shells out to `node` and skips (doesn't silently pass) if absent.

**Load-bearing proof (reviewer's exact perturbation, applied only to a fresh `/tmp` scratch copy, never the repo):** replaced `if (!supply || supply.type === "waste-toner") return fallback` in `supplyColor` with the reviewer's dead-code version (`var neverUsed = supply && supply.type === "waste-toner"` followed by `if (!supply) return fallback`). New test result:

```
AssertionError: '#ef4444' != 'FALLBACK'
- #ef4444
+ FALLBACK
 : supplyColor colored a waste-toner marker at 1% instead of returning the fallback color: got '#ef4444'
```

This is exactly the live-panel bug the reviewer described (a waste-toner marker rendered in error-red) — confirming the new test is load-bearing where the old one was not.

**Verification:** `python3 -m unittest discover -s tests -p 'test_*.py' -v` → 61 tests, OK (unchanged count: one regex test removed, one behavioral test added). `./bin/test` → exit 0.

**Commit:** `<filled in after commit below>`.
