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


if __name__ == "__main__":
    unittest.main()
