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


def collect(threshold=15):
    if not cupsd_running() and not fixture_path():
        return gn.build_snapshot(cupsd="asleep", threshold=threshold)

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

        if not default:
            default = _default_from_printers(parsed_printers)

        return gn.build_snapshot(
            printers=gn.response_groups(parsed_printers["Tests"][0]),
            jobs=gn.response_groups(parsed_jobs["Tests"][0]),
            default_printer=default,
            current_user=current_user(),
            cupsd="running",
            threshold=threshold,
        )
    except Exception as exc:
        return gn.build_snapshot(
            cupsd="error", error="%s: %s" % (type(exc).__name__, exc),
            threshold=threshold,
        )


def main(argv):
    threshold = 15
    if "--threshold" in argv:
        try:
            threshold = int(argv[argv.index("--threshold") + 1])
        except (IndexError, ValueError):
            pass

    json.dump(collect(threshold), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
