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
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
MODEL_JS_PATH = os.path.abspath(os.path.join(ROOT, "Model.js"))

sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import galley_collect as gc
import galley_normalize as gn


def read(relpath):
    with open(os.path.join(ROOT, relpath)) as handle:
        return handle.read()


def qml_sources():
    """Every top-level QML file, as (name, source) pairs.

    Globbed rather than naming Panel.qml, because the presentation layer is
    not one file and has not been since Controller.qml was split out of it.
    A guard that names the file it scrapes stops guarding the moment the
    thing it looks for moves -- which is exactly what happened here: the
    supplyLowThreshold scrape below was pinned to Panel.qml and went red when
    settingValue() moved to Controller.qml. It failed loudly, which is the
    design, but the fix is to stop listing files. Same lesson as bin/dev's
    identity rewrite, for the same reason.
    """
    names = sorted(
        name for name in os.listdir(ROOT) if name.endswith(".qml")
    )
    assert names, "no *.qml files found at the repo root -- the glob is broken"
    return [(name, read(name)) for name in names]


class CrossLanguageErrorReasonsTest(unittest.TestCase):
    """Model.js and galley_normalize.py must classify errors identically.

    The two ERROR_REASONS lists are hand-duplicated across languages: Python
    drives summary.errorPrinters, JavaScript drives the bar and card colors.
    A one-sided edit makes a red printer sit next to a "0 errors" summary.
    """

    def _js_list(self, name):
        source = read("Model.js")
        match = re.search(r"var %s = \[(.*?)\]" % name, source, re.S)
        self.assertIsNotNone(match, "%s array not found in Model.js" % name)
        return set(re.findall(r'"([^"]+)"', match.group(1)))

    def test_javascript_error_reasons_match_python(self):
        self.assertEqual(self._js_list("ERROR_REASONS"), set(gn.ERROR_REASONS))

    def test_javascript_warn_reasons_match_python(self):
        # Same hazard as ERROR_REASONS, one tier down: Python drives
        # summary.warnPrinters and JavaScript drives the amber glyph, so a
        # one-sided edit gives an amber printer beside a "0 warnings" summary.
        self.assertEqual(self._js_list("WARN_REASONS"), set(gn.WARN_REASONS))

    def test_the_two_tiers_do_not_overlap(self):
        # has_warning yields to has_error, so an overlapping entry would be
        # unreachable in the warning tier -- a silent no-op rather than a
        # visible contradiction, which is worse.
        self.assertEqual(set(gn.ERROR_REASONS) & set(gn.WARN_REASONS), set())


class StateNameLiteralsTest(unittest.TestCase):
    """Every state string Model.js or any *.qml compares against must be one
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
        # Model.js always compares states; the QML files are scanned as a set,
        # and only their union has to be non-empty -- Controller.qml holds the
        # state machine while Panel.qml renders, so which file carries a given
        # comparison is an implementation detail that may move again.
        sources = [("Model.js", read("Model.js"))] + qml_sources()
        qml_found_any = False
        for name, source in sources:
            found = re.findall(r'state\s*===\s*"([^"]+)"', source)
            if name == "Model.js":
                self.assertTrue(
                    found,
                    "no `state === \"...\"` comparisons found in Model.js -- "
                    "the regex is broken, not passing",
                )
            elif found:
                qml_found_any = True
            literals.update(found)
        self.assertTrue(
            qml_found_any,
            "no `state === \"...\"` comparisons found in any *.qml file -- "
            "the regex is broken, not passing",
        )

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
                "%r is compared against in Model.js or a *.qml file but is "
                "not a "
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

        qml_match, qml_where = None, None
        for name, source in qml_sources():
            found = re.search(
                r'settingValue\("supplyLowThreshold",\s*(\d+)\)', source
            )
            if found:
                qml_match, qml_where = found, name
                break
        self.assertIsNotNone(
            qml_match,
            'settingValue("supplyLowThreshold", N) fallback not found in any '
            "*.qml file",
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


NODE_WASTE_TONER_SCRIPT = """
var Model = require(%s);
var out = {};

out.wasteColor = Model.supplyColor(
  {name: "Waste", type: "waste-toner", level: 1}, 15, "FALLBACK");
out.tonerColor = Model.supplyColor(
  {name: "Black", type: "toner", level: 1}, 15, "FALLBACK");

var opts = {threshold: 15, notifySupplyLow: true, armedSupplies: {}};

var wastePrev = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Waste", type: "waste-toner", level: 50}]}]};
var wasteNext = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Waste", type: "waste-toner", level: 1}]}]};
out.wasteEvents = Model.diffSnapshots(wastePrev, wasteNext, opts).length;

var tonerPrev = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Black", type: "toner", level: 50}]}]};
var tonerNext = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Black", type: "toner", level: 1}]}]};
out.tonerEvents = Model.diffSnapshots(tonerPrev, tonerNext, opts).length;

// "other" is deliberately NOT excluded (galley#9). A Belt Unit arrives as
// marker-type "other" and, unlike waste-toner, still follows the normal
// percent-remaining convention -- so it must colour and notify like a toner.
out.otherColor = Model.supplyColor(
  {name: "Belt Unit", type: "other", level: 1}, 15, "FALLBACK");
var otherPrev = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Belt Unit", type: "other", level: 50}]}]};
var otherNext = {cupsd: "running", jobs: [], printers: [
  {name: "P1", supplies: [{name: "Belt Unit", type: "other", level: 1}]}]};
out.otherEvents = Model.diffSnapshots(otherPrev, otherNext, opts).length;

process.stdout.write(JSON.stringify(out));
""" % json.dumps(MODEL_JS_PATH)


class WasteTonerExclusionTest(unittest.TestCase):
    """waste-toner must be excluded from low-supply logic in both languages.

    IPP does not define whether a waste-toner level means percent full or
    percent remaining, and vendors disagree, so it is displayed but never
    alerted on -- in Python's low_supplies and in both Model.js.supplyColor
    and Model.js.diffSnapshots.

    Both halves are behavioural: the Python half calls the real
    low_supplies() directly; the JS half shells out to `node` (already a
    project test dependency -- bin/test runs `node --test`) to call the real
    supplyColor()/diffSnapshots() and asserts on their actual return values.

    A prior version of the JS half asserted only that the string
    "waste-toner" appeared inside each function's source text. That passed
    even when the code's *effect* was neutered by dead code that kept the
    string (in a comment, then in an unused variable) but dropped its
    behavior -- a `supplyColor` that colors a waste-toner marker as an error
    would still have satisfied a string-presence check. Each assertion below
    is paired with a control using a non-waste supply under the same
    conditions, so a `supplyColor`/`diffSnapshots` that just always returns
    the fallback / never fires cannot pass by accident. Do not regress this
    back to matching text instead of executing code.
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

    def test_python_low_supplies_includes_an_other_typed_marker(self):
        # The control for the test above, and the executable form of galley#9's
        # decision: only waste-toner is excluded, on the grounds that IPP leaves
        # its polarity undefined. "other" is vague but still percent-remaining
        # on this hardware, so a Belt Unit at 1%% must be reported low. Without
        # this, excluding "other" as "too vague to alert on" would pass the
        # waste-toner test and silently change behaviour.
        printer = {"supplies": [
            {"name": "Belt Unit", "type": "other", "level": 1},
        ]}
        self.assertEqual(
            len(gn.low_supplies(printer, threshold=50)), 1,
            "an \"other\"-typed marker at 1%% was not reported low -- galley#9 "
            "confirmed that only waste-toner is excluded",
        )

    @unittest.skipUnless(
        shutil.which("node"), "node is required to verify Model.js behaviour"
    )
    def test_javascript_never_colors_or_alerts_waste_toner(self):
        result = subprocess.run(
            ["node", "-e", NODE_WASTE_TONER_SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(
            result.returncode, 0,
            "node failed to execute Model.js: %s" % result.stderr,
        )
        out = json.loads(result.stdout)

        self.assertEqual(
            out["wasteColor"], "FALLBACK",
            "supplyColor colored a waste-toner marker at 1%% instead of "
            "returning the fallback color: got %r" % (out["wasteColor"],),
        )
        # Control: without this, a supplyColor that always returns the
        # fallback regardless of input would pass the assertion above for
        # the wrong reason.
        self.assertNotEqual(
            out["tonerColor"], "FALLBACK",
            "control failed: a non-waste supply at 1%% also got the "
            "fallback color, so the assertion above doesn't actually prove "
            "waste-toner is special-cased",
        )

        self.assertEqual(
            out["wasteEvents"], 0,
            "diffSnapshots emitted a supply-low event for a waste-toner "
            "marker crossing the threshold",
        )
        # Control: without this, a diffSnapshots that never emits supply-low
        # events at all would pass the assertion above for the wrong reason.
        self.assertGreaterEqual(
            out["tonerEvents"], 1,
            "control failed: diffSnapshots emitted no supply-low event for "
            "a non-waste marker crossing the threshold under the same "
            "conditions, so the assertion above doesn't actually prove "
            "waste-toner is special-cased",
        )



        # galley#9, executable: "other" is deliberately not excluded. A Belt
        # Unit arrives as marker-type "other" and still follows
        # percent-remaining, so it must colour and notify like a toner. Deciding
        # later that "other" is too vague to alert on would pass every
        # assertion above while silently changing behaviour -- these two are
        # what make that a visible change rather than an invisible one.
        self.assertNotEqual(
            out["otherColor"], "FALLBACK",
            'supplyColor did not colour an "other"-typed marker at 1%%; '
            "galley#9 confirmed only waste-toner is excluded",
        )
        self.assertEqual(
            out["otherEvents"], 1,
            'diffSnapshots raised %r supply-low events for an "other"-typed '
            "marker crossing the threshold, expected 1" % (out["otherEvents"],),
        )
class ColorPaletteTest(unittest.TestCase):
    """No *.qml file may contain a hex colour literal at all.

    Model.js owns the palette -- COLOR_OK/WARN/ERROR/BUSY -- and the QML
    consumes it as Model.COLOR_*. This is the inverse, and strictly stronger
    form of the guard that used to live here: rather than checking that every
    inlined hex matched the palette, it asserts there is nothing to match,
    because the duplication is gone.

    That earlier version existed only because Panel.qml hardcoded the same hex
    values inline, which also left COLOR_OK dead inside Model.js -- unused there
    *because* the QML had its own copy. Both are fixed (galley#6), so freezing
    the duplication is no longer the job; preventing its return is.

    A drift this guard cannot see: qmllint does not resolve Model.* lookups, so
    a typo'd Model.COLOR_EROR renders as a default colour and passes silently.
    That was verified by hand under a standalone qml runtime when the palette
    was first consumed. It is the reason the palette is read through one import
    rather than restated per call site -- one lookup to get wrong, not eight.
    """

    def test_no_qml_file_contains_a_hex_colour_literal(self):
        offenders = {}
        for name, source in qml_sources():
            found = re.findall(r"#[0-9a-fA-F]{6}", source)
            if found:
                offenders[name] = sorted(set(found))
        self.assertEqual(
            offenders, {},
            "hex colour literals found in QML: %r. Model.js owns the palette; "
            "use Model.COLOR_OK/WARN/ERROR/BUSY instead of inlining a value, "
            "so the two cannot drift apart (galley#6)." % (offenders,),
        )

    def test_every_model_reference_from_qml_exists(self):
        """Every Model.<name> a QML file calls must be declared in Model.js.

        qmllint parses QML but resolves nothing: it cannot see inside an
        imported JavaScript namespace, so `Model.reasonTxt(printer)` is
        syntactically perfect and evaluates to undefined at runtime. A Text
        bound to it renders empty and the panel simply loses that line -- no
        warning, no error, and the same silent-omission failure this palette
        guard exists to catch one directory over.
        """
        source = read("Model.js")
        # QML imports the whole script as a namespace, so every top-level
        # declaration is reachable -- not only what module.exports lists.
        declared = set(re.findall(r"^(?:function|var)\s+(\w+)", source, re.M))

        missing = {}
        for name, qml in qml_sources():
            # The filename itself reads as a namespace access: `import
            # "Model.js" as Model` and every comment mentioning Model.js would
            # otherwise be scraped as a reference to a member called `js`.
            refs = set(re.findall(r"Model\.(\w+)", qml.replace("Model.js", "")))
            unknown = sorted(r for r in refs if r not in declared)
            if unknown:
                missing[name] = unknown
        self.assertEqual(
            missing, {},
            "QML references names that Model.js does not declare: %r. These "
            "evaluate to undefined at runtime and render as nothing."
            % (missing,),
        )

    def test_the_qml_actually_consumes_the_palette(self):
        # Control for the assertion above, which a QML file with no colours at
        # all would satisfy vacuously -- including one where every Model.COLOR_*
        # reference had been deleted rather than the literals replaced.
        consumers = {}
        for name, source in qml_sources():
            refs = set(re.findall(r"Model\.(COLOR_\w+)", source))
            if refs:
                consumers[name] = sorted(refs)
        self.assertTrue(
            consumers,
            "no *.qml file references Model.COLOR_* -- the palette is exported "
            "but nothing consumes it, so the guard above passes vacuously",
        )

        palette = set(re.findall(r'var (COLOR_\w+) = "#[0-9a-fA-F]{6}"',
                                 read("Model.js")))
        self.assertTrue(palette, "no COLOR_* constants found in Model.js")
        for name, refs in consumers.items():
            for ref in refs:
                self.assertIn(
                    ref, palette,
                    "%s references Model.%s, which Model.js does not define -- "
                    "qmllint cannot catch this and it renders as a default "
                    "colour at runtime" % (name, ref),
                )


if __name__ == "__main__":
    unittest.main()
