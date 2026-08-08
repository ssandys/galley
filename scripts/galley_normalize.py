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
    if pages is None:
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
