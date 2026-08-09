import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import galley_collect as gc

FIXTURES = os.path.join(HERE, "fixtures")
COLLECTOR = os.path.join(HERE, "..", "scripts", "galley_collect.py")


def run_cli(env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, COLLECTOR],
        capture_output=True, env=env, timeout=30,
    )
    return proc, json.loads(proc.stdout.decode())


class FixtureReplayTest(unittest.TestCase):
    def test_replays_a_fixture_directory_without_calling_ipptool(self):
        proc, snapshot = run_cli({"GALLEY_FIXTURE": os.path.join(FIXTURES, "busy")})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(snapshot["cupsd"], "running")
        self.assertEqual(len(snapshot["printers"]), 2)
        self.assertEqual(len(snapshot["jobs"]), 3)
        self.assertEqual(snapshot["defaultPrinter"], "Canon@OLP")

    def test_replays_the_idle_fixture(self):
        proc, snapshot = run_cli({"GALLEY_FIXTURE": os.path.join(FIXTURES, "idle")})
        self.assertEqual(snapshot["summary"]["activeJobs"], 0)
        self.assertEqual(len(snapshot["printers"]), 2)


class ErrorEnvelopeTest(unittest.TestCase):
    def test_missing_fixture_dir_emits_error_snapshot_not_a_traceback(self):
        proc, snapshot = run_cli({"GALLEY_FIXTURE": "/nonexistent/galley"})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(snapshot["cupsd"], "error")
        self.assertIsNotNone(snapshot["error"])
        self.assertEqual(snapshot["printers"], [])

    def test_malformed_plist_emits_error_snapshot(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("printers.plist", "jobs.plist"):
                with open(os.path.join(tmp, name), "wb") as handle:
                    handle.write(b"this is not xml")
            proc, snapshot = run_cli({"GALLEY_FIXTURE": tmp})
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(snapshot["cupsd"], "error")
            self.assertIsNotNone(snapshot["error"])

    def test_always_emits_valid_json_on_stdout(self):
        proc, _ = run_cli({"GALLEY_FIXTURE": "/nonexistent/galley"})
        self.assertEqual(proc.stdout[:1], b"{")


class CupsdGateTest(unittest.TestCase):
    def test_asleep_snapshot_skips_ipptool(self):
        # IdleExitTimeout means cupsd sleeps when unused; polling must not
        # wake it. A stopped cupsd has no jobs by definition.
        original = gc.cupsd_running
        gc.cupsd_running = lambda: False
        try:
            snapshot = gc.collect(15)
        finally:
            gc.cupsd_running = original
        self.assertEqual(snapshot["cupsd"], "asleep")
        self.assertEqual(snapshot["jobs"], [])
        self.assertIsNone(snapshot["error"])


class SubprocessFailureTest(unittest.TestCase):
    """Exercise the real ipptool path with a fake binary on PATH."""

    def _fake_bin(self, tmp, ipptool_body):
        import stat
        for name, body in (("ipptool", ipptool_body),
                           ("systemctl", "#!/bin/sh\nexit 0\n")):
            path = os.path.join(tmp, name)
            with open(path, "w") as handle:
                handle.write(body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return tmp

    def _run_with_path(self, tmp):
        env = dict(os.environ)
        env["PATH"] = tmp + os.pathsep + env.get("PATH", "")
        env.pop("GALLEY_FIXTURE", None)
        proc = subprocess.run([sys.executable, COLLECTOR],
                              capture_output=True, env=env, timeout=30)
        return proc, json.loads(proc.stdout.decode())

    def test_failed_ipp_status_is_an_error_not_an_empty_printer_list(self):
        # ipptool emits a plist AND exits non-zero when a STATUS assertion
        # fails. That must not look like "no printers configured".
        failing_plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<plist version="1.0">\n<dict>\n<key>Tests</key>\n<array>\n<dict>\n'
            '<key>Name</key><string>Get printers</string>\n'
            '<key>StatusCode</key><string>server-error-service-unavailable</string>\n'
            '<key>Successful</key><false />\n'
            '<key>ResponseAttributes</key>\n<array>\n<dict>\n'
            '<key>attributes-charset</key><string>utf-8</string>\n'
            '</dict>\n</array>\n</dict>\n</array>\n</dict>\n</plist>\n'
        )
        body = "#!/bin/sh\ncat <<'PLIST'\n%s\nPLIST\nexit 1\n" % failing_plist
        with tempfile.TemporaryDirectory() as tmp:
            proc, snapshot = self._run_with_path(self._fake_bin(tmp, body))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(snapshot["cupsd"], "error")
        self.assertIsNotNone(snapshot["error"])

    def test_missing_ipptool_produces_an_error_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Only systemctl is faked; ipptool is absent from this dir, and we
            # blank PATH so the real one cannot be found either.
            import stat
            path = os.path.join(tmp, "systemctl")
            with open(path, "w") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["PATH"] = tmp
            env.pop("GALLEY_FIXTURE", None)
            proc = subprocess.run([sys.executable, COLLECTOR],
                                  capture_output=True, env=env, timeout=30)
        snapshot = json.loads(proc.stdout.decode())
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(snapshot["cupsd"], "error")
        self.assertIsNotNone(snapshot["error"])


if __name__ == "__main__":
    unittest.main()
