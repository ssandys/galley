import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import galley_collect as gc

FIXTURES = os.path.join(HERE, "fixtures")
COLLECTOR = os.path.join(HERE, "..", "scripts", "galley_collect.py")


def read_source(path):
    with open(path) as handle:
        return handle.read()


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
        # PATH is emptied so the "without calling ipptool" half of the name is
        # actually enforced: any attempt to shell out fails loudly instead of
        # quietly succeeding on a machine that happens to have a real ipptool
        # and a live cupsd. Without this the test asserted only on the parsed
        # snapshot, so a regression that ignored GALLEY_FIXTURE could pass
        # whenever the real output happened to match the fixture.
        #
        # Emptying PATH is safe here specifically: collect() also calls
        # `systemctl is-active`, but only when fixture_path() is falsy, so the
        # fixture short-circuit runs before anything needs a binary. If that
        # ordering ever changes this test catches it, which is the point.
        proc, snapshot = run_cli({
            "GALLEY_FIXTURE": os.path.join(FIXTURES, "busy"),
            "PATH": "",
        })
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
        # json.dump() writes incrementally, so an unserializable value would
        # yield truncated JSON plus a traceback instead of a clean failure.
        # Building the string with json.dumps() first means stdout is either
        # a complete document or (on a genuine bug) nothing at all.
        proc, _ = run_cli({"GALLEY_FIXTURE": "/nonexistent/galley"})
        self.assertEqual(proc.returncode, 0)
        parsed = json.loads(proc.stdout.decode())
        self.assertIsInstance(parsed, dict)
        self.assertEqual(proc.stdout, json.dumps(parsed).encode() + b"\n")


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


class CompletedIdsTest(unittest.TestCase):
    def test_snapshot_carries_a_completed_ids_list(self):
        proc, snapshot = run_cli({"GALLEY_FIXTURE": os.path.join(FIXTURES, "busy")})
        self.assertIn("completedIds", snapshot)
        self.assertIsInstance(snapshot["completedIds"], list)

    def test_completed_ids_empty_when_not_requested(self):
        proc, snapshot = run_cli({"GALLEY_FIXTURE": os.path.join(FIXTURES, "idle")})
        self.assertEqual(snapshot["completedIds"], [])


class ClientDefaultTest(unittest.TestCase):
    """The default printer comes from the client's lpoptions, then IPP.

    `lpoptions -d` writes a per-user default to ~/.cups/lpoptions that cupsd
    never sees, so a widget reading only CUPS-Get-Default would show a stale
    star after the user set a default from the panel. See the design spec.

    Paths are injected rather than patched via HOME, because the system file is
    an absolute path (/etc/cups/lpoptions) that a test cannot relocate. Passing
    them in keeps these tests off the real lpoptions locations, so they never
    depend on whether the developer has set a default.
    """

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def test_user_file_supplies_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent/system")),
                "Brother@Home")

    def test_user_file_wins_over_the_system_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            system = os.path.join(tmp, "system", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            self._write(system, "Default Canon@OLP\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, system)), "Brother@Home")

    def test_system_file_is_used_when_the_user_file_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            system = os.path.join(tmp, "system", "lpoptions")
            self._write(system, "Default Canon@OLP\n")
            self.assertEqual(
                gc.default_from_lpoptions(
                    (os.path.join(tmp, "absent"), system)), "Canon@OLP")

    def test_no_files_yields_empty_so_the_caller_falls_back_to_ipp(self):
        self.assertEqual(
            gc.default_from_lpoptions(("/nonexistent/a", "/nonexistent/b")), "")

    def test_option_lines_without_a_default_line_yield_empty(self):
        # A real lpoptions file usually carries per-destination option lines.
        # Only a line whose FIRST token is Default names the default.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Dest Canon@OLP copies=1 number-up=1\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")), "")

    def test_an_instance_suffix_is_stripped(self):
        # `lpoptions -d` accepts destination[/instance]; the printer names the
        # snapshot matches against never carry an instance.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home/duplex\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")),
                "Brother@Home")

    def test_a_bare_default_keyword_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default\n")
            self.assertEqual(
                gc.default_from_lpoptions((user, "/nonexistent")), "")

    def test_a_directory_in_place_of_a_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gc.default_from_lpoptions((tmp, "/nonexistent")), "")

    def test_lpdest_and_printer_env_vars_are_ignored(self):
        # Documented limitation, pinned so honouring them later is a deliberate
        # decision rather than an accident. CUPS consults these ABOVE both
        # lpoptions files; galley does not, because the collector inherits the
        # shell's environment rather than the user's terminal.
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user", "lpoptions")
            self._write(user, "Default Brother@Home\n")
            env = dict(os.environ)
            env["LPDEST"] = "Canon@OLP"
            env["PRINTER"] = "Canon@OLP"
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    gc.default_from_lpoptions((user, "/nonexistent")),
                    "Brother@Home")

    def test_lpoptions_paths_are_the_documented_two(self):
        user, system = gc.lpoptions_paths()
        self.assertTrue(user.endswith(os.path.join(".cups", "lpoptions")), user)
        self.assertEqual(system, "/etc/cups/lpoptions")

    def test_fixture_replay_never_reads_the_live_lpoptions(self):
        # The chain must be SKIPPED in fixture mode, not merely ordered after
        # the fixture's own default file. Both fixtures ship one, so ordering
        # alone would pass today and break the moment a fixture omitted it --
        # at which point replay would read the developer's real default and
        # these tests would differ per machine. Same class of defect as #4.
        source = read_source(COLLECTOR)
        body = source[source.index("def collect("):]
        self.assertIn("directory", body)
        marker = "default_from_lpoptions"
        self.assertIn(
            marker, body,
            "collect() never consults the lpoptions chain")
        call_line = next(line for line in body.splitlines() if marker in line)
        self.assertIn(
            "not directory", call_line,
            "the lpoptions chain is not gated on fixture mode: %r" % call_line)


if __name__ == "__main__":
    unittest.main()
