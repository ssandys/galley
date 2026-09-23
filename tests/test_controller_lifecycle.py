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


if __name__ == "__main__":
    unittest.main()
