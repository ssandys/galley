"""Cross-language invariants between the Python collector/normalizer and the
Model.js / Panel.qml presentation layer.

Logic and constants are hand-duplicated across Python, JavaScript, and QML,
and every such crossing fails *silently* on a one-sided edit -- nothing
raises, the widget just quietly starts coloring, notifying, or thresholding
wrong. Each guard below scrapes (or, where Python can just read the value
directly, imports) both sides of one such duplication and asserts they
agree.

Every guard here is written so a missing file, a renamed symbol, or an empty
regex match makes the test FAIL loudly rather than pass vacuously -- see the
assertIsNotNone / assertTrue-with-message calls throughout. A guard that
silently stops guarding is worse than no guard.
"""
import inspect
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")

sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import galley_collect as gc
import galley_normalize as gn


def read(relpath):
    with open(os.path.join(ROOT, relpath)) as handle:
        return handle.read()


class CrossLanguageErrorReasonsTest(unittest.TestCase):
    """Model.js and galley_normalize.py must classify errors identically.

    The two ERROR_REASONS lists are hand-duplicated across languages: Python
    drives summary.errorPrinters, JavaScript drives the bar and card colors.
    A one-sided edit makes a red printer sit next to a "0 errors" summary.
    """

    def test_javascript_error_reasons_match_python(self):
        source = read("Model.js")

        match = re.search(r"var ERROR_REASONS = \[(.*?)\]", source, re.S)
        self.assertIsNotNone(match, "ERROR_REASONS array not found in Model.js")

        js_reasons = set(re.findall(r'"([^"]+)"', match.group(1)))
        self.assertEqual(js_reasons, set(gn.ERROR_REASONS))


class StateNameLiteralsTest(unittest.TestCase):
    """Every state string Model.js/Panel.qml compare against must be one
    Python can actually emit.

    galley_normalize.py's PRINTER_STATES/JOB_STATES dicts are the vocabulary;
    Model.js and Panel.qml both do `...state === "literal"` comparisons
    against it. Rename a value on the Python side and the JS/QML comparisons
    silently go dead: no more coloring, no more notifying, the wrong
    pause/resume label -- and nothing here fails to tell you, unless this
    test exists.
    """

    def test_state_literals_are_valid_python_states(self):
        valid_states = set(gn.PRINTER_STATES.values()) | set(gn.JOB_STATES.values())

        literals = set()
        for relpath in ("Model.js", "Panel.qml"):
            source = read(relpath)
            found = re.findall(r'state\s*===\s*"([^"]+)"', source)
            self.assertTrue(
                found,
                "no `state === \"...\"` comparisons found in %s -- the "
                "regex is broken, not passing" % relpath,
            )
            literals.update(found)

        # Sanity floor: at the time this guard was written there were 5
        # distinct literals across both files (processing, held, aborted,
        # stopped, printing). A regex that only ever matches 1 or 2 is
        # suspicious even though it isn't literally empty.
        self.assertGreaterEqual(
            len(literals), 3,
            "only found %r -- suspiciously few for two files that both "
            "branch heavily on printer/job state" % (literals,),
        )

        for literal in sorted(literals):
            self.assertIn(
                literal, valid_states,
                "%r is compared against in Model.js/Panel.qml but is not a "
                "value galley_normalize.py's PRINTER_STATES/JOB_STATES can "
                "ever emit" % literal,
            )


class SupplyLowThresholdDefaultTest(unittest.TestCase):
    """The supply-low threshold default (15) is hand-copied seven times.

    If the manifest default ever diverged from the QML fallback,
    summary.lowSupplies (computed in Python) and the card colors (computed
    in JavaScript) would disagree -- an amber supply card next to a calm bar
    icon. inspect.signature is used for the two real Python defaults because
    it is exact and cannot drift from what the code actually does; the
    manifest is parsed as JSON; everything else is a source literal that has
    to be scraped.
    """

    def test_all_seven_defaults_agree(self):
        manifest = json.loads(read("manifest.json"))

        manifest_default = manifest["barWidget"]["defaults"]["supplyLowThreshold"]

        schema = manifest["barWidget"]["schema"]
        schema_entry = next(
            (entry for entry in schema if entry.get("key") == "supplyLowThreshold"),
            None,
        )
        self.assertIsNotNone(
            schema_entry,
            "no supplyLowThreshold entry in manifest.json's barWidget.schema",
        )
        schema_default = schema_entry["defaultValue"]

        qml_source = read("Panel.qml")
        qml_match = re.search(
            r'settingValue\("supplyLowThreshold",\s*(\d+)\)', qml_source
        )
        self.assertIsNotNone(
            qml_match,
            'settingValue("supplyLowThreshold", N) fallback not found in '
            "Panel.qml",
        )
        qml_default = int(qml_match.group(1))

        js_source = read("Model.js")
        js_match = re.search(
            r"var threshold = opts\.threshold \|\| (\d+)", js_source
        )
        self.assertIsNotNone(
            js_match,
            "`var threshold = opts.threshold || N` not found in Model.js",
        )
        js_default = int(js_match.group(1))

        collect_default = inspect.signature(gc.collect).parameters["threshold"].default

        collect_source = read("scripts/galley_collect.py")
        main_match = re.search(r"threshold = (\d+)", collect_source)
        self.assertIsNotNone(
            main_match,
            "`threshold = N` literal (the pre-argv-parsing default) not "
            "found in galley_collect.py's main()",
        )
        main_default = int(main_match.group(1))

        build_snapshot_default = inspect.signature(
            gn.build_snapshot
        ).parameters["threshold"].default

        defaults = {
            "manifest.json barWidget.defaults.supplyLowThreshold": manifest_default,
            "manifest.json barWidget.schema[supplyLowThreshold].defaultValue": schema_default,
            'Panel.qml settingValue("supplyLowThreshold", N)': qml_default,
            "Model.js var threshold = opts.threshold || N": js_default,
            "galley_collect.collect(threshold=N) signature": collect_default,
            "galley_collect.main()'s threshold = N": main_default,
            "galley_normalize.build_snapshot(threshold=N) signature": build_snapshot_default,
        }

        self.assertEqual(
            len(set(defaults.values())), 1,
            "supplyLowThreshold defaults have diverged: %r" % (defaults,),
        )


class WasteTonerExclusionTest(unittest.TestCase):
    """waste-toner must be excluded from low-supply logic in both languages.

    IPP does not define whether a waste-toner level means percent full or
    percent remaining, and vendors disagree, so it is displayed but never
    alerted on -- in Python's low_supplies and in both Model.js.supplyColor
    and Model.js.diffSnapshots.

    The string-presence half below is a weak guard by nature: a synchronized
    rename in both languages would still pass it. It is kept deliberately
    simple. The behavioural half is the real guard -- it calls the actual
    Python function and checks what it does, not what it says.
    """

    def test_python_low_supplies_excludes_waste_toner_behaviourally(self):
        printer = {"supplies": [
            {"name": "Waste Toner Box", "type": "waste-toner", "level": 1},
        ]}
        self.assertEqual(
            gn.low_supplies(printer, threshold=50), [],
            "low_supplies no longer excludes waste-toner: a marker at 1%% "
            "with a threshold of 50 was reported as low",
        )

    def test_javascript_skips_waste_toner_in_both_functions(self):
        source = read("Model.js")

        for name in ("supplyColor", "diffSnapshots"):
            match = re.search(r"function %s\(" % name, source)
            self.assertIsNotNone(match, "function %s not found in Model.js" % name)
            next_fn = re.search(r"\nfunction ", source[match.end():])
            end = match.end() + next_fn.start() if next_fn else len(source)
            body = source[match.start():end]
            # Match the actual comparison, not just the substring anywhere in
            # the function -- both functions carry a comment mentioning
            # "waste-toner" that would still be present even if the real
            # `type === "waste-toner"` check were renamed underneath it.
            self.assertRegex(
                body, r'type\s*===\s*"waste-toner"',
                '%s() in Model.js no longer skips "waste-toner"' % name,
            )


class ColorPaletteTest(unittest.TestCase):
    """Every hex color literal in Panel.qml must be one of Model.js's
    COLOR_* constants, so the two cannot silently drift apart.

    Model.js defines COLOR_OK/WARN/ERROR/BUSY; Panel.qml hardcodes the same
    hex values inline instead of importing them (COLOR_OK is unused in
    Model.js *because* Panel.qml inlines its value). This test does NOT fix
    that duplication -- consuming the palette properly in Panel.qml is still
    the real fix -- it only freezes the current state so a one-sided edit is
    caught instead of shipped silently.
    """

    def test_qml_hex_colors_are_all_in_the_js_palette(self):
        js_source = read("Model.js")
        palette = dict(re.findall(
            r'var (COLOR_\w+) = "(#[0-9a-fA-F]{6})"', js_source
        ))
        self.assertTrue(
            palette,
            "no COLOR_* constants found in Model.js -- the regex is broken, "
            "not passing",
        )
        palette_values = set(palette.values())

        qml_source = read("Panel.qml")
        qml_colors = set(re.findall(r"#[0-9a-fA-F]{6}", qml_source))
        self.assertTrue(
            qml_colors,
            "no hex color literals found in Panel.qml -- the regex is "
            "broken, not passing",
        )

        for color in sorted(qml_colors):
            self.assertIn(
                color, palette_values,
                "%s appears in Panel.qml but is not one of Model.js's "
                "COLOR_* constants (%r) -- the two palettes have diverged"
                % (color, palette_values),
            )


if __name__ == "__main__":
    unittest.main()
