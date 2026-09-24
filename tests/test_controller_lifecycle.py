"""Executable coverage for Controller.qml's collector process lifecycle.

Everything else in this repo tests Python or plain JavaScript. The controller
is neither: it is QML driving Quickshell's Process, and `qmllint` only proves
the file parses. So the one failure mode that mattered here -- a collector that
never starts -- was invisible to the whole suite and was found by reading
(galley#34).

These run the real Controller.qml under the real Quickshell, with a harness
that reads the properties afterwards and reports through the exit code (Qt
logging is suppressed in this environment). Nothing touches the user's shell,
their printers, or their config.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FIXTURES = os.path.join(HERE, "fixtures")

HARNESS = """
import QtQuick
import Quickshell
import "."

// Exit 0 when the controller reached the expected state, 1 otherwise, 2 if it
// never settled. GALLEY_EXPECT picks which state is expected.
//
// Controller is a SINGLETON, so it is addressed by type rather than
// instantiated, and its configuration arrives through attach() -- a singleton
// has no caller to bind properties from. attach() also takes consumers above
// zero, which is what starts the poll: without it shouldRun stays false and
// the collector never spawns, so this harness would time out rather than fail.
ShellRoot {
  id: root

  Component.onCompleted: Controller.attach({
    settings: ({}),
    collectPath: Quickshell.env("GALLEY_COLLECT_PATH"),
    actionPath: "/nonexistent/action.sh"
  })

  Timer {
    running: true; interval: 3000
    onTriggered: {
      var expect = Quickshell.env("GALLEY_EXPECT")
      var ok
      if (expect === "error") {
        ok = Controller.cupsdState === "error" && Controller.collectorError !== ""
      } else {
        ok = Controller.cupsdState === "running" && Controller.collectorError === ""
      }
      Qt.exit(ok ? 0 : 1)
    }
  }
}
"""


def quickshell_missing():
    return shutil.which("quickshell") is None


@unittest.skipIf(quickshell_missing(), "quickshell is required to run Controller.qml")
class CollectorSpawnTest(unittest.TestCase):
    def _run(self, expect, collect_path, path_env=None, fixture=None):
        with tempfile.TemporaryDirectory() as tmp:
            # The controller and its JS import, copied rather than imported in
            # place: quickshell takes a config path and resolves QML imports
            # beside it, and the harness must sit in that same directory.
            # qmldir too: Controller.qml is a singleton, and the type only
            # resolves when its qmldir sits beside it in the import directory.
            for name in ("Controller.qml", "Model.js", "qmldir"):
                shutil.copy(os.path.join(ROOT, name), os.path.join(tmp, name))
            harness = os.path.join(tmp, "harness.qml")
            with open(harness, "w") as handle:
                handle.write(HARNESS)

            env = dict(os.environ)
            env["GALLEY_EXPECT"] = expect
            env["GALLEY_COLLECT_PATH"] = collect_path
            if path_env is not None:
                env["PATH"] = path_env
            if fixture is not None:
                env["GALLEY_FIXTURE"] = fixture
            else:
                env.pop("GALLEY_FIXTURE", None)
            # quickshell by absolute path: PATH is emptied below to hide
            # python3 from the controller, and a bare name would hide the
            # runtime from this test too. Same trick, same reason, as bash in
            # tests/test_action.py.
            return subprocess.run([shutil.which("quickshell"), "-p", harness],
                                  capture_output=True, text=True,
                                  timeout=60, env=env)

    def test_a_collector_that_cannot_start_reports_an_error(self):
        # The regression. With no python3 on PATH the spawn fails outright, and
        # Quickshell emits neither exited() nor streamFinished() -- so
        # handleOutput never runs and, before this fix, nothing set any error.
        # cupsdState kept its initial "running" and the panel said
        # "No printers configured" on a machine that had never been asked.
        with tempfile.TemporaryDirectory() as empty:
            proc = self._run("error", os.path.join(ROOT, "scripts",
                                                   "galley_collect.py"),
                             path_env=empty)
        self.assertEqual(
            proc.returncode, 0,
            "a collector that never started left no error on the controller\n"
            "%s%s" % (proc.stdout, proc.stderr))

    def test_a_successful_collection_is_not_mistaken_for_a_failed_spawn(self):
        # The control, and the reason the fix reads a flag rather than
        # deferring: under Quickshell 0.3.1 streamFinished arrives BEFORE
        # running goes false, so the flag is set by the time the handler looks.
        # If that ordering were ever reversed, every successful poll would
        # report a spawn failure -- and this test would catch it.
        proc = self._run("running",
                         os.path.join(ROOT, "scripts", "galley_collect.py"),
                         fixture=os.path.join(FIXTURES, "idle"))
        self.assertEqual(
            proc.returncode, 0,
            "a successful collection did not leave the controller running\n"
            "%s%s" % (proc.stdout, proc.stderr))


# A collector that records each spawn and then defers to the real one, so a
# test can count collections without giving up valid output for the controller
# to parse.
SPAWN_COUNTER = """import os, subprocess, sys
with open(os.environ["GALLEY_SPAWN_LOG"], "a") as handle:
    handle.write("run\\n")
sys.exit(subprocess.call([sys.executable, os.environ["GALLEY_REAL_COLLECT"]]
                         + sys.argv[1:]))
"""

# Runs a sequence of attach/detach calls, waits, and reports whether a check
# expression holds. Controller is a singleton, so these all address the one
# instance -- which is the whole point being tested.
LIFECYCLE_HARNESS = """
import QtQuick
import Quickshell
import "."

ShellRoot {
  function cfg() {
    return {
      settings: ({}),
      collectPath: Quickshell.env("GALLEY_COLLECT_PATH"),
      actionPath: "/nonexistent/action.sh"
    }
  }

  Component.onCompleted: {
    %(script)s
  }

  Timer {
    running: true; interval: %(wait)d
    onTriggered: Qt.exit((%(check)s) ? 0 : 1)
  }
}
"""


@unittest.skipIf(quickshell_missing(), "quickshell is required to run Controller.qml")
class SingletonSharingTest(unittest.TestCase):
    """The claim the singleton exists to make, asserted rather than measured
    by hand.

    The bar builds a widget per bar surface and a surface per monitor, so
    before Controller.qml was a singleton every surface polled CUPS and sent
    its own notify-send. Proving that stopped meant watching `pgrep` over a
    stopwatch window on a live desktop with a second output attached -- which
    is neither repeatable nor something CI can do.

    These drive the real Controller under real Quickshell with N attaches
    standing in for N surfaces.

    What they can and cannot show: N attaches reaching ONE object, the count
    pairing and clamping, and the collector still running at all. They cannot
    show two instances failing to share, because a singleton makes a second
    instance unrepresentable -- that is the guarantee, and the suite protects
    it by failing outright if `Controller.attach` ever stops existing.
    """

    def _run(self, script, check, wait=3000, count_spawns=False):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Controller.qml", "Model.js", "qmldir"):
                shutil.copy(os.path.join(ROOT, name), os.path.join(tmp, name))
            harness = os.path.join(tmp, "harness.qml")
            with open(harness, "w") as handle:
                handle.write(LIFECYCLE_HARNESS % {
                    "script": script, "check": check, "wait": wait})

            env = dict(os.environ)
            env["GALLEY_FIXTURE"] = os.path.join(FIXTURES, "idle")
            spawn_log = os.path.join(tmp, "spawns")
            if count_spawns:
                counter = os.path.join(tmp, "counting_collect.py")
                with open(counter, "w") as handle:
                    handle.write(SPAWN_COUNTER)
                env["GALLEY_SPAWN_LOG"] = spawn_log
                env["GALLEY_REAL_COLLECT"] = os.path.join(
                    ROOT, "scripts", "galley_collect.py")
                env["GALLEY_COLLECT_PATH"] = counter
            else:
                env["GALLEY_COLLECT_PATH"] = os.path.join(
                    ROOT, "scripts", "galley_collect.py")

            proc = subprocess.run([shutil.which("quickshell"), "-p", harness],
                                  capture_output=True, text=True,
                                  timeout=60, env=env)
            spawns = 0
            if count_spawns and os.path.exists(spawn_log):
                with open(spawn_log) as handle:
                    spawns = len([l for l in handle if l.strip()])
            return proc, spawns

    def test_two_surfaces_reach_one_controller_and_collect_once(self):
        # Two attaches stand in for two monitors. Before this change each
        # surface built its own Controller with its own collectProc and polled
        # independently; now both reach one object, which is what
        # `consumers === 2` on a single instance demonstrates.
        #
        # The spawn count is a liveness check, NOT proof of deduplication, and
        # the difference matters. Mutation-tested by making EVERY attach
        # refresh instead of only the first: the count stayed at 1 and this
        # test still passed, because refresh() coalesces while collectProc is
        # running and a singleton has only one collectProc. Nothing this
        # harness can do will make one instance spawn two collectors -- the
        # duplication being removed lived in there being two INSTANCES, which
        # a singleton makes unrepresentable rather than merely unlikely.
        proc, spawns = self._run(
            "Controller.attach(cfg()); Controller.attach(cfg())",
            "Controller.consumers === 2", count_spawns=True)
        self.assertEqual(proc.returncode, 0,
                         "both attaches did not reach one Controller\n"
                         "%s%s" % (proc.stdout, proc.stderr))
        self.assertEqual(
            spawns, 1,
            "two surfaces ran %d collectors; one shared Controller should "
            "produce exactly one" % spawns)

    def test_one_surface_still_collects(self):
        # The control. A test that only counts DOWN would pass just as well
        # against a widget that never ran at all -- which is exactly how the
        # first attempt at colophon's singleton looked: zero collections,
        # because a duplicate onOpenedChanged stopped the component
        # instantiating and nothing said so.
        proc, spawns = self._run(
            "Controller.attach(cfg())",
            "Controller.consumers === 1", count_spawns=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(spawns, 1, "one surface must still collect once")

    def test_the_consumer_count_returns_to_zero(self):
        # What stops the work when the last surface goes. If detach did not
        # pair with attach the count would drift up and the poll would run for
        # the life of the shell with no widget to show it.
        proc, _ = self._run(
            "Controller.attach(cfg()); Controller.attach(cfg());"
            " Controller.detach({}); Controller.detach({})",
            "Controller.consumers === 0 && Controller.shouldRun === false")
        self.assertEqual(proc.returncode, 0,
                         "consumers did not return to zero\n"
                         "%s%s" % (proc.stdout, proc.stderr))

    def test_detach_clamps_at_zero(self):
        # A reload can recreate widgets without destroying them, so the count
        # must never go negative and strand shouldRun false forever.
        proc, _ = self._run(
            "Controller.attach(cfg()); Controller.detach({});"
            " Controller.detach({}); Controller.detach({});"
            " Controller.attach(cfg())",
            "Controller.consumers === 1 && Controller.shouldRun === true")
        self.assertEqual(proc.returncode, 0,
                         "the count did not clamp at zero\n"
                         "%s%s" % (proc.stdout, proc.stderr))


@unittest.skipIf(quickshell_missing(), "quickshell is required to run Controller.qml")
class SettingsDeliveryTest(SingletonSharingTest):
    """Settings reaching the singleton at all (#36).

    The widget called Controller.attach({settings}) from Component.onCompleted,
    and attach() latched the first object it saw. The bar sets a widget's
    settings from its Loader's onLoaded, AFTER the item completes, so what got
    latched was Ui/Panel.qml's empty default -- every setting fell back to its
    hardcoded value for good, notification toggles included.

    Inherits SingletonSharingTest only for its harness. Its own tests are
    re-run here as a side effect, which is harmless.
    """

    def test_settings_that_arrive_after_attach_still_take_effect(self):
        # Exactly the order the host produces: attach holding the empty
        # default, then the real settings.
        proc, _ = self._run(
            "Controller.attach(cfg());"
            " Controller.configure({ pollIntervalIdleSec: 45,"
            " supplyLowThreshold: 7, showSupplies: false })",
            "Controller.idleInterval === 45 && Controller.supplyThreshold === 7"
            " && Controller.showSupplies === false")
        self.assertEqual(proc.returncode, 0,
                         "late settings were ignored\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_a_later_settings_change_replaces_the_earlier_one(self):
        # The settings UI assigns a new object on every edit; the latest wins.
        proc, _ = self._run(
            "Controller.attach(cfg());"
            " Controller.configure({ pollIntervalIdleSec: 45 });"
            " Controller.configure({ pollIntervalIdleSec: 120 })",
            "Controller.idleInterval === 120")
        self.assertEqual(proc.returncode, 0,
                         "the first settings object stuck\n%s%s"
                         % (proc.stdout, proc.stderr))

    def test_a_second_surface_attaching_does_not_clobber_settings(self):
        # Every surface attaches with whatever its widget held at completion,
        # which is the empty default. Settings must come from configure().
        proc, _ = self._run(
            "Controller.attach(cfg());"
            " Controller.configure({ pollIntervalIdleSec: 45 });"
            " Controller.attach(cfg())",
            "Controller.idleInterval === 45 && Controller.consumers === 2")
        self.assertEqual(proc.returncode, 0,
                         "a later attach wiped the settings\n%s%s"
                         % (proc.stdout, proc.stderr))


def read(name):
    with open(os.path.join(ROOT, name)) as handle:
        return handle.read()


def strip_comments(source):
    # Line comments only, and only where `//` starts the line or follows
    # whitespace: a URL's `//` follows a colon, so "http://..." survives. The
    # comments around this wiring NAME everything checked below, and a match
    # found only in prose must not satisfy -- or fail -- a guard.
    return re.sub(r"(^|\s)//.*", r"\1", source, flags=re.M)


class WidgetWiringTest(unittest.TestCase):
    """The widget's half of #36, which SettingsDeliveryTest cannot see.

    Those tests call Controller.configure() themselves, so they pass whether
    or not Panel.qml ever does. Loading Panel.qml for real needs the bar's own
    Ui components, so these read the source instead: crude, but they fail on
    exactly the edits that bring #36 back. Static, so unlike the tests above
    they run without quickshell.
    """

    def setUp(self):
        self.panel = strip_comments(read("Panel.qml"))
        self.controller = strip_comments(read("Controller.qml"))

    def test_the_widget_hands_over_every_settings_change(self):
        self.assertRegex(
            self.panel,
            r"onSettingsChanged:\s*Controller\.configure\(\s*root\.settings\s*\)",
            "Panel.qml must forward settings from onSettingsChanged: the bar "
            "injects them after Component.onCompleted, so attach() is too early")

    def test_the_widget_does_not_hand_settings_to_attach(self):
        start = self.panel.index("Controller.attach(")
        call = self.panel[start:self.panel.index("})", start) + 2]
        self.assertNotIn("settings", call,
                         "attach() runs before the bar injects settings; "
                         "whatever it is handed there is the empty default")

    def test_attach_does_not_take_settings(self):
        start = self.controller.index("function attach(options) {")
        body = self.controller[start:self.controller.index("\n  }\n", start)]
        self.assertNotIn("settings", body,
                         "attach() must not latch settings: the first surface "
                         "attaches holding the empty default (#36)")


if __name__ == "__main__":
    unittest.main()
