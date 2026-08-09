"""Pure transforms from ipptool plist output to Galley's snapshot schema.

No I/O and no subprocesses live here so every parsing rule is testable
against a recorded fixture or a hand-built dict.
"""

import plistlib

PRINTER_STATES = {3: "idle", 4: "printing", 5: "stopped"}

JOB_STATES = {
    3: "pending", 4: "held", 5: "processing", 6: "stopped",
    7: "canceled", 8: "aborted", 9: "completed",
}


def parse_plist(raw):
    """Parse ipptool -X output.

    ipptool appends a plain-text "Summary:" footer after </plist> when a
    request file holds more than one operation, which makes the payload
    invalid XML. Truncate at the final closing tag before parsing.
    """
    close = b"</plist>"
    end = raw.rfind(close)
    if end != -1:
        raw = raw[:end + len(close)]
    return plistlib.loads(raw)


def test_succeeded(test_result):
    """Whether one ipptool test reported an IPP success status.

    ipptool emits a plist even when a STATUS assertion fails, so a parseable
    response is not the same as a successful one.
    """
    if test_result.get("Successful") is False:
        return False
    return str(test_result.get("StatusCode", "")).startswith("successful")


def response_groups(test_result):
    """Attribute groups of one ipptool test, minus the operation group.

    Group 0 is always operation attributes (charset, natural language);
    the object groups follow.
    """
    return list(test_result.get("ResponseAttributes", [])[1:])


def as_list(value):
    """Coerce an IPP attribute to a list.

    Single-valued attributes arrive as bare scalars: printer-state-reasons
    is the string 'none', not ['none'].
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def printer_state_name(code):
    return PRINTER_STATES.get(code, "unknown")


def job_state_name(code):
    return JOB_STATES.get(code, "unknown")


def normalize_supplies(attrs):
    """Build supply entries from the marker-* attribute family.

    Two real-hardware quirks: the arrays can disagree in length (one printer
    returns 4 names against 11 levels), and a level of -1 means unknown.
    """
    names = as_list(attrs.get("marker-names"))
    levels = as_list(attrs.get("marker-levels"))
    types = as_list(attrs.get("marker-types"))
    colors = as_list(attrs.get("marker-colors"))

    count = min(len(names), len(levels)) if names and levels else 0

    supplies = []
    for i in range(count):
        level = levels[i]
        if not isinstance(level, int) or level < 0:
            continue
        supplies.append({
            "name": names[i],
            "type": types[i] if i < len(types) else "unknown",
            "level": level,
            "color": colors[i] if i < len(colors) else "none",
        })
    return supplies


def normalize_printer(attrs, default_printer):
    name = attrs.get("printer-name", "")
    return {
        "name": name,
        "info": attrs.get("printer-info", ""),
        "location": attrs.get("printer-location", ""),
        "makeAndModel": attrs.get("printer-make-and-model", ""),
        "state": printer_state_name(attrs.get("printer-state")),
        "stateReasons": as_list(attrs.get("printer-state-reasons")),
        "stateMessage": attrs.get("printer-state-message", ""),
        "accepting": bool(attrs.get("printer-is-accepting-jobs", False)),
        "isDefault": name == default_printer,
        "queuedJobCount": attrs.get("queued-job-count", 0),
        "supplies": normalize_supplies(attrs),
    }


def printer_from_uri(uri):
    """Printer name from a job-printer-uri.

    Jobs carry no printer-name attribute, so the queue name comes from the
    last path segment. Names may contain '@', as in 'Canon@OLP'.
    """
    if not uri:
        return ""
    return str(uri).rstrip("/").rsplit("/", 1)[-1]


def normalize_job(attrs, current_user):
    job_id = attrs.get("job-id", 0)
    user = attrs.get("job-originating-user-name", "")

    pages = attrs.get("job-media-sheets")
    if not pages:
        impressions = attrs.get("job-impressions-completed")
        pages = impressions if impressions else None

    return {
        "id": job_id,
        "name": attrs.get("job-name") or "Job %s" % job_id,
        "printer": printer_from_uri(attrs.get("job-printer-uri")),
        "user": user,
        "state": job_state_name(attrs.get("job-state")),
        "stateReasons": as_list(attrs.get("job-state-reasons")),
        "pages": pages,
        "sizeKb": attrs.get("job-k-octets", 0),
        "createdAt": attrs.get("time-at-creation", 0),
        "mine": bool(user) and user == current_user,
    }


# Reasons that mean a human has to walk to the printer.
# Entries are base reasons; severity suffixes (-report, -warning, -error)
# are stripped before matching, so all severity variants match uniformly.
ERROR_REASONS = frozenset([
    "media-jam", "media-empty", "media-needed", "toner-empty",
    "marker-supply-empty", "offline", "offline-report", "door-open", "cover-open",
    "input-tray-missing", "output-area-full", "shutdown",
])


def has_error(printer):
    if printer.get("state") == "stopped":
        return True
    for reason in printer.get("stateReasons", []):
        # Reasons carry severity suffixes: 'media-empty-warning'.
        base = str(reason).rsplit("-", 1)[0] if str(reason).endswith(
            ("-report", "-warning", "-error")) else str(reason)
        if base in ERROR_REASONS or str(reason) in ERROR_REASONS:
            return True
    return False


def low_supplies(printer, threshold):
    """Supplies below the warning threshold.

    waste-toner is excluded: IPP does not define whether its level means
    percent full or percent remaining, and vendors disagree.
    """
    return [s for s in printer.get("supplies", [])
            if s.get("type") != "waste-toner" and s.get("level", 100) < threshold]


def summarize(printers, jobs, threshold):
    return {
        "printers": len(printers),
        "activeJobs": len(jobs),
        "errorPrinters": sum(1 for p in printers if has_error(p)),
        "lowSupplies": sum(len(low_supplies(p, threshold)) for p in printers),
    }


def build_snapshot(printers=None, jobs=None, default_printer="",
                   current_user="", cupsd="running", threshold=15, error=None):
    normalized_printers = [normalize_printer(p, default_printer)
                           for p in (printers or [])]
    # The default printer leads; the rest follow alphabetically so the order is
    # stable across polls rather than however CUPS happened to return them.
    normalized_printers.sort(key=lambda p: (not p["isDefault"], p["name"].lower()))
    normalized_jobs = [normalize_job(j, current_user) for j in (jobs or [])]

    return {
        "schema": 1,
        "cupsd": cupsd,
        "error": error,
        "defaultPrinter": default_printer,
        "printers": normalized_printers,
        "jobs": normalized_jobs,
        "summary": summarize(normalized_printers, normalized_jobs, threshold),
    }
