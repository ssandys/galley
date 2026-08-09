# tests/test_action.py
import os
import subprocess
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


if __name__ == "__main__":
    unittest.main()
