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


if __name__ == "__main__":
    unittest.main()
