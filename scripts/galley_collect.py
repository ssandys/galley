#!/usr/bin/env python3
"""Emit one JSON snapshot of CUPS printers and the active queue.

Runs to completion and exits. Always prints a valid snapshot on stdout,
even on failure, so the panel never has to parse a traceback.
"""

import getpass
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import galley_normalize as gn

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRINTERS_REQUEST = os.path.join(SCRIPT_DIR, "get-printers.test")
JOBS_REQUEST = os.path.join(SCRIPT_DIR, "get-jobs.test")
COMPLETED_REQUEST = os.path.join(SCRIPT_DIR, "get-completed-jobs.test")
IPP_URI = "ipp://localhost/"
IPPTOOL_TIMEOUT = 10


def current_user():
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER", "")


def cupsd_running():
    """Whether cupsd is up.

    IdleExitTimeout lets cupsd shut down when unused. Polling it would keep
    it alive forever, so when it is asleep we report idle without waking it.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "cups.service"], timeout=5
        )
        return result.returncode == 0
    except Exception:
        # No systemd, or systemctl missing: assume running and let ipptool decide.
        return True


def run_ipptool(request_path, uri=IPP_URI):
    """Run one ipptool request and return raw plist bytes.

    -d user=... is mandatory: without requesting-user-name cupsd applies
    JobPrivateValues and redacts job-name and job-originating-user-name.
    """
    result = subprocess.run(
        ["ipptool", "-d", "user=%s" % current_user(), "-X", uri, request_path],
        capture_output=True, timeout=IPPTOOL_TIMEOUT,
    )
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(
            "ipptool failed (%s): %s"
            % (result.returncode, result.stderr.decode(errors="replace").strip())
        )
    return result.stdout


def fixture_path():
    path = os.environ.get("GALLEY_FIXTURE", "").strip()
    return path or None


def _read_fixture(directory):
    with open(os.path.join(directory, "printers.plist"), "rb") as handle:
        printers_raw = handle.read()
    with open(os.path.join(directory, "jobs.plist"), "rb") as handle:
        jobs_raw = handle.read()

    default = ""
    default_file = os.path.join(directory, "default")
    if os.path.exists(default_file):
        with open(default_file) as handle:
            default = handle.read().strip()
    return printers_raw, jobs_raw, default


def _default_from_printers(parsed):
    """Default printer from the second operation, when the file has one."""
    tests = parsed.get("Tests", [])
    if len(tests) < 2:
        return ""
    groups = gn.response_groups(tests[1])
    return groups[0].get("printer-name", "") if groups else ""


def lpoptions_paths():
    """The two client-side lpoptions files CUPS reads, in precedence order.

    Computed rather than module-level constants so a test can relocate HOME,
    and so the user path is resolved at call time rather than import time.
    """
    return (os.path.join(os.path.expanduser("~"), ".cups", "lpoptions"),
            "/etc/cups/lpoptions")


def default_from_lpoptions(paths):
    """The client-side default printer name, or "" if no file names one.

    `lpoptions -d` writes `Default <name>` here, and cupsd never sees it -- so
    this is the only way the panel's star can track a default the panel itself
    set. See docs/superpowers/specs/2026-08-16-printer-admin-actions-design.md.

    LPDEST and PRINTER are deliberately NOT consulted, though CUPS ranks them
    above both files: the collector inherits the environment of the shell that
    launched the Omarchy shell, not the user's terminal, so honouring them would
    be right only when those two happen to agree. Documented limitation, with a
    test pinning it.
    """
    for path in paths:
        try:
            # errors="replace" rather than a default strict read: a byte that is
            # not valid UTF-8 raises UnicodeDecodeError, which is a ValueError
            # and so escapes the OSError guard below, reaching collect()'s bare
            # `except Exception` and replacing the entire snapshot with an error
            # envelope. Substituting the byte keeps a mangled option value from
            # hiding an otherwise readable Default line.
            with open(path, errors="replace") as handle:
                for line in handle:
                    parts = line.split()
                    # Only a line whose first token is Default names the
                    # default; the rest are per-destination option lines.
                    if len(parts) >= 2 and parts[0] == "Default":
                        # destination[/instance] -- the snapshot's printer names
                        # never carry an instance.
                        return parts[1].split("/")[0]
        except OSError:
            # Missing, unreadable, or a directory: try the next one.
            continue
    return ""


def completed_job_ids():
    """IDs of the ten most recently completed jobs.

    Called only when a job has left the active queue, because a completed job
    and a cancelled job are indistinguishable from the active queue alone.
    """
    try:
        parsed = gn.parse_plist(run_ipptool(COMPLETED_REQUEST))
        groups = gn.response_groups(parsed["Tests"][0])
        return [g["job-id"] for g in groups
                if g.get("job-state") == 9 and "job-id" in g]
    except Exception:
        return []


def collect(threshold=15, want_completed=False):
    if not cupsd_running() and not fixture_path():
        snapshot = gn.build_snapshot(cupsd="asleep", threshold=threshold)
        snapshot["completedIds"] = []
        return snapshot

    try:
        directory = fixture_path()
        if directory:
            printers_raw, jobs_raw, default = _read_fixture(directory)
        else:
            printers_raw = run_ipptool(PRINTERS_REQUEST)
            jobs_raw = run_ipptool(JOBS_REQUEST)
            default = ""

        parsed_printers = gn.parse_plist(printers_raw)
        parsed_jobs = gn.parse_plist(jobs_raw)

        for label, parsed in (("printers", parsed_printers), ("jobs", parsed_jobs)):
            tests = parsed.get("Tests") or []
            if not tests:
                raise RuntimeError("ipptool returned no %s result" % label)
            if not gn.test_succeeded(tests[0]):
                # With no printers configured, cupsd answers CUPS-Get-Printers
                # with client-error-not-found and "No destinations added." —
                # a healthy empty state, not a fault. Any other failure
                # still surfaces as an error.
                if label == "printers" and gn.no_destinations(tests[0]):
                    continue
                raise RuntimeError("ipptool %s request failed: %s"
                                   % (label, tests[0].get("StatusCode", "unknown")))

        # Fixture mode is deliberately excluded: replaying a recorded snapshot
        # must not read the developer's live default, or these tests would
        # differ per machine. The fixture's own `default` file is the only
        # client-side source consulted there.
        if not default and not directory:
            default = default_from_lpoptions(lpoptions_paths())
        if not default:
            default = _default_from_printers(parsed_printers)

        snapshot = gn.build_snapshot(
            printers=gn.response_groups(parsed_printers["Tests"][0]),
            jobs=gn.response_groups(parsed_jobs["Tests"][0]),
            default_printer=default,
            current_user=current_user(),
            cupsd="running",
            threshold=threshold,
        )
        snapshot["completedIds"] = (
            completed_job_ids() if want_completed and not directory else []
        )
        return snapshot
    except Exception as exc:
        snapshot = gn.build_snapshot(
            cupsd="error", error="%s: %s" % (type(exc).__name__, exc),
            threshold=threshold,
        )
        snapshot["completedIds"] = []
        return snapshot


def main(argv):
    threshold = 15
    if "--threshold" in argv:
        try:
            threshold = int(argv[argv.index("--threshold") + 1])
        except (IndexError, ValueError):
            pass

    sys.stdout.write(json.dumps(collect(threshold, "--completed" in argv)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
