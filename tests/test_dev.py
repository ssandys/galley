# tests/test_dev.py
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEV = os.path.join(ROOT, "bin", "dev")


def run(args, env=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(["bash", DEV] + args, capture_output=True,
                          timeout=30, env=merged, cwd=ROOT)


def lines(proc):
    """Non-blank stdout lines. In a dry run these are the commands, in order."""
    return [line for line in proc.stdout.decode().splitlines() if line.strip()]


class DispatchTest(unittest.TestCase):
    def test_unknown_verb_exits_2(self):
        proc = run(["obliterate"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown verb", proc.stderr.decode())

    def test_no_verb_exits_2(self):
        proc = run([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr.decode().lower())


class DeployTest(unittest.TestCase):
    def test_dry_run_emits_rsync_and_sed(self):
        out = "\n".join(lines(run(["deploy", "--dry-run"])))
        self.assertIn("rsync", out)
        self.assertIn("sed", out)

    def test_deploy_never_touches_the_running_shell(self):
        # deploy is what bin/dev-watch calls on every save. If it could restart
        # or enable anything, the edit loop would flicker the whole bar on each
        # keystroke-to-disk. Checked on the leading token: $DEST legitimately
        # contains "omarchy" in its path.
        for line in lines(run(["deploy", "--dry-run"])):
            first = line.split()[0]
            self.assertNotIn(first, ("omarchy", "omarchy-shell"),
                             f"deploy emitted a shell command: {line}")

    def test_dry_run_deploys_nothing(self):
        proc = run(["deploy", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        # mkdir routes through run() like everything else, so a dry run cannot
        # create the destination as a side effect.
        self.assertTrue(any("mkdir" in line for line in lines(proc)))


class UpTest(unittest.TestCase):
    def setUp(self):
        self.out = lines(run(["up", "--dry-run"]))

    def index_of(self, needle):
        for i, line in enumerate(self.out):
            if needle in line:
                return i
        self.fail(f"`up --dry-run` never emitted {needle!r}; got {self.out}")

    def test_rescans_before_enabling(self):
        # `omarchy plugin enable` exits 1 on an id the registry has never seen,
        # which is every first deploy of a fresh clone. The official install
        # sequence rescans first; bin/install skipped it and only worked on a
        # machine where the dev id already existed.
        self.assertLess(self.index_of("rescanPlugins"),
                        self.index_of("plugin enable"))

    def test_deploys_before_rescanning(self):
        self.assertLess(self.index_of("rsync"), self.index_of("rescanPlugins"))

    def test_restarts_the_shell_last(self):
        self.assertEqual(self.index_of("restart shell"), len(self.out) - 1)

    def test_passes_no_placement_to_enable(self):
        # manifest.json's barWidget.defaultSection already declares placement.
        # `up` runs repeatedly, so stamping one here would overwrite a position
        # the user has since moved by hand.
        enable = self.out[self.index_of("plugin enable")]
        self.assertRegex(enable, r"^omarchy plugin enable \S+$")


class DownTest(unittest.TestCase):
    def out(self, state):
        return lines(run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": state}))

    def test_absent_is_a_noop_and_does_not_restart(self):
        # `omarchy plugin disable` exits 1 on an unregistered id, which under
        # `set -e` would abort before the restart with an omarchy error rather
        # than a useful one.
        proc = run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": "absent"})
        self.assertEqual(proc.returncode, 0)
        joined = "\n".join(lines(proc))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("not registered", joined)

    def test_already_disabled_is_a_noop_and_does_not_restart(self):
        # A shell restart flickers the whole bar and closes open panels, which
        # is too rude for a no-op.
        joined = "\n".join(self.out("disabled"))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("already disabled", joined)

    def test_enabled_disables_then_restarts(self):
        out = self.out("enabled")
        self.assertTrue(any("plugin disable" in line for line in out), out)
        self.assertTrue(any("restart shell" in line for line in out), out)
        disable_at = next(i for i, l in enumerate(out) if "plugin disable" in l)
        restart_at = next(i for i, l in enumerate(out) if "restart shell" in l)
        self.assertLess(disable_at, restart_at)

    def test_down_does_not_remove_the_deployed_directory(self):
        # Retaining $DEST preserves the dev copy's shell.json settings, and
        # rsync --delete already makes `up` idempotent over a stale directory.
        joined = "\n".join(self.out("enabled"))
        self.assertNotIn("rm ", joined)


if __name__ == "__main__":
    unittest.main()
