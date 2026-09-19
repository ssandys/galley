"""bin/test must actually check every script it claims to check.

The shell-syntax stage ran `bash -n bin/* scripts/*.sh`, which parses only the
first argument and hands the rest to it as positional parameters. The stage
printed "ok" for eleven scripts while reading one (galley#32).

Nothing in this repo could see that: every script happened to be valid, so the
one file that was checked passed and the stage was green. A guard that reports
success for work it did not do is worse than no guard, which is the same
lesson the cross-language suite records about the waste-toner check.

These tests build a throwaway tree with its own copy of bin/test and run it
there. The real source tree is never modified and no printer action runs.
"""
import os
import shutil
import tempfile
import stat
import subprocess
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REAL_RUNNER = os.path.join(ROOT, "bin", "test")

VALID = "#!/usr/bin/env bash\necho fine\n"
# `if then` is a syntax error: `if` needs a condition before `then`.
BROKEN = "#!/usr/bin/env bash\nif then\n"


class ShellSyntaxStageTest(unittest.TestCase):
    def _tree(self, tmp, scripts):
        """A minimal plugin tree bin/test can run against end to end."""
        os.makedirs(os.path.join(tmp, "bin"))
        # An empty but importable tests/ makes unittest discover exit 5
        # ("nothing collected"), which bin/test treats as success -- so the run
        # reaches its own exit code rather than dying, and the control below can
        # assert a clean 0. The __init__.py is required: discover refuses a
        # start directory it cannot import.
        os.makedirs(os.path.join(tmp, "tests"))
        open(os.path.join(tmp, "tests", "__init__.py"), "w").close()
        with open(os.path.join(tmp, "manifest.json"), "w") as handle:
            handle.write('{"schemaVersion": 1}\n')
        shutil.copy(REAL_RUNNER, os.path.join(tmp, "bin", "test"))
        for name, body in scripts.items():
            path = os.path.join(tmp, "bin", name)
            with open(path, "w") as handle:
                handle.write(body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return subprocess.run(["bash", os.path.join(tmp, "bin", "test")],
                              capture_output=True, text=True, timeout=120)

    def test_a_broken_script_after_the_first_is_caught(self):
        # The regression itself. "aaa" sorts before "test", so the broken file
        # is never the first glob result -- which is exactly the position the
        # old invocation could not see.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._tree(tmp, {"aaa_first.sh": VALID,
                                    "zzz_broken.sh": BROKEN})
        self.assertNotEqual(
            proc.returncode, 0,
            "a syntax error in a non-first script was not detected:\n%s%s"
            % (proc.stdout, proc.stderr))
        self.assertIn(
            "zzz_broken.sh", proc.stdout + proc.stderr,
            "the failure must name the offending file")

    def test_a_broken_first_script_is_still_caught(self):
        # The case the old code did catch. Kept so a fix that somehow inverted
        # the ordering would not pass.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._tree(tmp, {"aaa_broken.sh": BROKEN,
                                    "zzz_fine.sh": VALID})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("aaa_broken.sh", proc.stdout + proc.stderr)

    def test_a_tree_of_valid_scripts_passes(self):
        # Control. Without it, a stage that failed unconditionally would
        # satisfy both assertions above.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._tree(tmp, {"aaa_first.sh": VALID,
                                    "zzz_second.sh": VALID})
        self.assertEqual(
            proc.returncode, 0,
            "valid scripts must pass:\n%s%s" % (proc.stdout, proc.stderr))
        self.assertIn("== bash syntax ==", proc.stdout)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
