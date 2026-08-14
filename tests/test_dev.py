# tests/test_dev.py
import json
import os
import shutil
import subprocess
import tempfile
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


class RealDeployTest(unittest.TestCase):
    """Executes deploy() for real into a scratch HOME.

    Every other test here inspects --dry-run's printed strings, which means
    deploy() and verify() are never actually run. That left the rewrite itself
    untested: narrowing the sed target back to a named file, or gutting
    verify(), kept the suite green. $DEST derives from $HOME alone, so an
    overridden HOME makes a real deploy fully hermetic.

    The literals are read from this repo's own manifest.json, the same way
    PortabilityTest does, so this test ports unchanged.
    """

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.published_id = manifest["id"]
        self.published_name = manifest["name"]
        self.dev_id = f"{self.published_id}-dev"
        self.home = tempfile.mkdtemp(prefix="dev-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.dest = os.path.join(
            self.home, ".config", "omarchy", "plugins", self.dev_id)

    def deploy_into(self, home):
        return subprocess.run(["bash", DEV, "deploy"], capture_output=True,
                              timeout=60, cwd=ROOT, env={**os.environ, "HOME": home})

    def deployed_manifest(self):
        with open(os.path.join(self.dest, "manifest.json")) as handle:
            return json.load(handle)

    def deployed_qml_files(self):
        return [name for name in os.listdir(self.dest) if name.endswith(".qml")]

    def test_deploy_exits_zero(self):
        proc = self.deploy_into(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

    def test_deployed_manifest_carries_the_dev_identity(self):
        self.deploy_into(self.home)
        manifest = self.deployed_manifest()
        self.assertEqual(manifest["id"], self.dev_id)
        self.assertTrue(manifest["name"].endswith("(dev)"), manifest["name"])

    def test_every_deployed_qml_file_is_rewritten(self):
        self.deploy_into(self.home)
        qml_files = self.deployed_qml_files()
        self.assertTrue(qml_files, "deploy produced no *.qml files to check")
        published_id_quoted = f'"{self.published_id}"'
        published_name_quoted = f'{self.published_name}"'
        for name in qml_files:
            with open(os.path.join(self.dest, name)) as handle:
                text = handle.read()
            self.assertNotIn(
                published_id_quoted, text,
                f"{name} still claims the published id {published_id_quoted!r}")
            self.assertNotIn(
                published_name_quoted, text,
                f"{name} still carries the published name "
                f"{published_name_quoted!r}")

    def test_rewrite_reaches_every_top_level_qml_file_not_just_one(self):
        # Regression guard for the exact defect the old bin/install had and
        # this branch replaces: a rewrite scoped to a named file (there,
        # Panel.qml) silently misses a second top-level QML file introduced
        # later -- colophon's real Service.qml bug, described in the design
        # spec. Galley itself currently has only one top-level *.qml file, so
        # this can't be exercised against this repo's own tree: a mutation
        # that hardcodes the sed target back to "$DEST/Panel.qml" produces
        # byte-identical output to the glob today, and would slip past a test
        # that only looks at this repo's actual files. Reproduced instead in
        # a scratch mirror of the source tree carrying a second *.qml file.
        mirror = tempfile.mkdtemp(prefix="dev-test-mirror-")
        self.addCleanup(shutil.rmtree, mirror, ignore_errors=True)
        os.makedirs(os.path.join(mirror, "bin"))
        shutil.copy(DEV, os.path.join(mirror, "bin", "dev"))
        shutil.copy(os.path.join(ROOT, "manifest.json"), mirror)
        with open(os.path.join(mirror, "Extra.qml"), "w") as handle:
            handle.write(
                'Item {\n'
                f'  property string moduleName: "{self.published_id}"\n'
                f'  property string label: "  {self.published_name}"\n'
                '}\n')

        proc = subprocess.run(
            ["bash", os.path.join(mirror, "bin", "dev"), "deploy"],
            capture_output=True, timeout=60, cwd=mirror,
            env={**os.environ, "HOME": self.home})
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

        with open(os.path.join(self.dest, "Extra.qml")) as handle:
            text = handle.read()
        self.assertNotIn(f'"{self.published_id}"', text,
                         "a second top-level *.qml file still carries the "
                         "published id -- the rewrite is not reaching every "
                         "*.qml file")
        self.assertNotIn(f'{self.published_name}"', text,
                         "a second top-level *.qml file still carries the "
                         "published name -- the rewrite is not reaching "
                         "every *.qml file")

    def test_second_deploy_into_the_same_home_stays_idempotent(self):
        # `up` runs deploy repeatedly (rescan and enable are themselves
        # idempotent), so a second deploy over the first's output must not
        # compound the rewrite into -dev-dev or "(dev) (dev)".
        self.deploy_into(self.home)
        proc = self.deploy_into(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

        manifest = self.deployed_manifest()
        self.assertEqual(manifest["id"], self.dev_id)
        self.assertNotIn("-dev-dev", manifest["id"])
        self.assertNotIn("(dev) (dev)", manifest["name"])

        for name in self.deployed_qml_files():
            with open(os.path.join(self.dest, name)) as handle:
                text = handle.read()
            self.assertNotIn("-dev-dev", text)
            self.assertNotIn("(dev) (dev)", text)


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

    def test_unrecognised_state_does_not_act_and_exits_nonzero(self):
        # The case in down() must not default to "act": a typo, an
        # unexpected-case fixture, or a future fourth state falling through
        # the absent/disabled guard must not disable the plugin and restart
        # the shell for a state this script does not understand.
        proc = run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": "typo"})
        self.assertNotEqual(proc.returncode, 0)
        joined = "\n".join(lines(proc))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)


class PluginStateQueryTest(unittest.TestCase):
    """Drives a registry-query failure with an `omarchy` stub on PATH.

    DEV_STATE_FIXTURE bypasses the query entirely, so it can't exercise this
    path. Putting a failing `omarchy` first on PATH does.
    """

    def setUp(self):
        self.stub_dir = tempfile.mkdtemp(prefix="dev-test-path-stub-")
        self.addCleanup(shutil.rmtree, self.stub_dir, ignore_errors=True)
        stub = os.path.join(self.stub_dir, "omarchy")
        with open(stub, "w") as handle:
            handle.write("#!/usr/bin/env bash\nexit 1\n")
        os.chmod(stub, 0o755)

    def run_with_broken_omarchy(self, args):
        merged = dict(os.environ)
        merged["PATH"] = self.stub_dir + os.pathsep + merged["PATH"]
        return subprocess.run(["bash", DEV] + args, capture_output=True,
                              timeout=30, env=merged, cwd=ROOT)

    def test_down_fails_loudly_rather_than_reporting_absent(self):
        # Without the fix, `set -e` does not abort inside the command
        # substitution that assigns $json, so a failing `omarchy` leaves it
        # empty, `jq -e` reads that as "not present", and `down` would print
        # "is not registered; nothing to take down" and exit 0 -- the user
        # believes the dev copy is torn down while it is still enabled.
        proc = self.run_with_broken_omarchy(["down", "--dry-run"])
        self.assertNotEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertNotIn("not registered", out)
        self.assertNotIn("plugin disable", out)
        self.assertNotIn("restart", out)

    def test_status_fails_loudly_rather_than_reporting_absent(self):
        proc = self.run_with_broken_omarchy(["status"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("absent", proc.stdout.decode())


class StatusTest(unittest.TestCase):
    def test_reports_id_deployment_and_registry_state(self):
        proc = run(["status"], env={"DEV_STATE_FIXTURE": "enabled"})
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertIn("-dev", out)
        self.assertIn("deployed:", out)
        self.assertIn("enabled", out)


class PortabilityTest(unittest.TestCase):
    """The dev scripts must be byte-identical across plugin repos.

    Everything plugin-specific is derived at runtime from manifest.json, so a
    port is a copy with no edits. This asserts the invariant that makes that
    true: no script mentions this plugin's id, display name, or short name.

    The literals are read from manifest.json rather than hardcoded, so this
    test itself ports unchanged -- which is the whole point.

    Necessarily textual, unlike the behavioural tests above: absence of a
    literal is a textual property. Scoped to exactly that and nothing else.
    """

    SCRIPTS = ("bin/dev", "bin/dev-watch", "bin/test")

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        plugin_id = manifest["id"]
        self.literals = {
            "manifest id": plugin_id,
            "display name": manifest["name"],
            "short name": plugin_id.split(".")[-1],
        }

    def test_scripts_carry_no_plugin_specific_literal(self):
        for relative in self.SCRIPTS:
            path = os.path.join(ROOT, relative)
            with open(path) as handle:
                source = handle.read()
            for label, literal in self.literals.items():
                self.assertNotIn(
                    literal, source,
                    f"{relative} hardcodes the {label} '{literal}'. Derive it "
                    f"from manifest.json instead, so this script stays "
                    f"byte-identical across plugins and ports by copying.")

    def test_every_dev_script_is_covered(self):
        # A guard listing files by name is only as good as the list. If a new
        # bin/ script appears, it must be added above or explicitly excused.
        present = {
            os.path.join("bin", name)
            for name in os.listdir(os.path.join(ROOT, "bin"))
        }
        self.assertEqual(present, set(self.SCRIPTS),
                         "bin/ contents changed; update SCRIPTS or excuse the "
                         "new file explicitly")


if __name__ == "__main__":
    unittest.main()
