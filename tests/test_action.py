# tests/test_action.py
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(__file__)
ACTION = os.path.join(HERE, "..", "scripts", "galley_action.sh")


def run(args):
    return subprocess.run(["bash", ACTION] + args,
                          capture_output=True, timeout=15)


class DryRunTest(unittest.TestCase):
    def test_cancel_job_builds_cancel_command(self):
        proc = run(["cancel-job", "53", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode().strip(), "cancel 53")

    def test_cancel_all_targets_the_printer(self):
        proc = run(["cancel-all", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.stdout.decode().strip(), "cancel -a Canon@OLP")

    def test_pause_uses_cupsdisable(self):
        proc = run(["pause", "Brother@Home", "--dry-run"])
        self.assertEqual(proc.stdout.decode().strip(), "cupsdisable Brother@Home")

    def test_resume_uses_cupsenable(self):
        proc = run(["resume", "Brother@Home", "--dry-run"])
        self.assertEqual(proc.stdout.decode().strip(), "cupsenable Brother@Home")


class ValidationTest(unittest.TestCase):
    def test_unknown_verb_exits_2(self):
        proc = run(["obliterate", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown action", proc.stderr.decode())

    def test_missing_target_exits_3(self):
        proc = run(["pause", "--dry-run"])
        self.assertEqual(proc.returncode, 3)
        self.assertIn("missing target", proc.stderr.decode())

    def test_no_arguments_exits_2(self):
        self.assertEqual(run([]).returncode, 2)

    def test_printer_name_with_at_sign_is_not_split(self):
        proc = run(["pause", "Canon@OLP", "--dry-run"])
        self.assertIn("Canon@OLP", proc.stdout.decode())


class AdminActionTest(unittest.TestCase):
    def test_set_default_uses_lpoptions(self):
        proc = run(["set-default", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stdout.decode().strip(),
                         "lpoptions -d Canon@OLP")

    def test_set_default_still_requires_a_target(self):
        proc = run(["set-default", "--dry-run"])
        self.assertEqual(proc.returncode, 3)
        self.assertIn("missing target", proc.stderr.decode())

    def test_web_ui_opens_the_cups_interface(self):
        proc = run(["web-ui", "--dry-run"])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(proc.stdout.decode().strip(),
                         "xdg-open http://localhost:631")

    def test_web_ui_needs_no_target(self):
        # The blanket `[[ -z "$TARGET" ]]` check this replaces would have
        # exited 3 here. The per-verb rule is what makes a global action
        # expressible at all.
        proc = run(["web-ui", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing target", proc.stderr.decode())

    def test_web_ui_ignores_a_stray_target(self):
        # runAction always passes two arguments, so the QML side sends "".
        # A stray value must not change the command.
        proc = run(["web-ui", "Canon@OLP", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode().strip(),
                         "xdg-open http://localhost:631")


class WebUiDetachTest(unittest.TestCase):
    """web-ui must return before the browser does.

    Every other verb here is short-lived, so the script waits for it and reports
    what it said. `xdg-open` is not: on its generic path it runs the browser in
    the foreground with no `&`, and `output=$(...)` waits for the pipe to close
    rather than for the child to exit -- so even a browser that forks holds it
    open while it keeps inherited stdout. Either alone kept the action running
    for the whole browsing session, which left Controller.qml's actionInProgress
    set and every button in the panel disabled with no message. A warm start
    hides this completely, because the second Chrome process relays and exits.
    """

    def _launcher_that_outlives_us(self, directory, marker):
        # Stands in for a cold-start browser: records that it ran, then stays
        # alive far longer than the assertion window.
        path = os.path.join(directory, "xdg-open")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\ntouch %s\nsleep 5\n" % marker)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def test_web_ui_returns_before_the_browser_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "launched")
            self._launcher_that_outlives_us(tmp, marker)
            env = dict(os.environ)
            env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
            started = time.monotonic()
            proc = subprocess.run(["bash", ACTION, "web-ui"],
                                  capture_output=True, timeout=15, env=env)
            elapsed = time.monotonic() - started
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            self.assertLess(
                elapsed, 3.0,
                "web-ui waited %.1fs for the browser instead of detaching"
                % elapsed)
            deadline = time.monotonic() + 3.0
            while not os.path.exists(marker) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(os.path.exists(marker),
                            "detaching must still launch the browser")

    def test_a_missing_launcher_is_still_reported(self):
        # Detaching gives up the exit status of what we launched, so the one
        # failure worth catching -- xdg-utils not installed -- is checked before
        # the fork rather than inferred afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["PATH"] = tmp
            # bash by absolute path: PATH is emptied to hide xdg-open, and a
            # relative name would hide the interpreter from the test too.
            proc = subprocess.run([shutil.which("bash") or "/bin/bash",
                                   ACTION, "web-ui"],
                                  capture_output=True, timeout=15, env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("galley: ", proc.stderr.decode())


if __name__ == "__main__":
    unittest.main()
