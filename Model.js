// Model.js — pure presentation transforms shared by the QML panel and the
// node test suite. No I/O, no QML imports, no timers.

var COLOR_OK = "#22c55e"
var COLOR_WARN = "#eab308"
var COLOR_ERROR = "#ef4444"
var COLOR_BUSY = "#3b82f6"

// Past this, the badge shows "9+" rather than the true figure. Keeping the
// badge a fixed-width circle is the point: a two-digit count would widen it
// into a pill that overhangs the bar slot and crowds the next widget. The
// exact figure stays available in the tooltip.
var BADGE_MAX = 9

var EMPTY_SNAPSHOT = {
  schema: 1, cupsd: "error", error: null, defaultPrinter: "",
  printers: [], jobs: [],
  summary: { printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0 }
}

function emptySnapshot(errorText) {
  return {
    schema: 1, cupsd: "error", error: errorText || null, defaultPrinter: "",
    printers: [], jobs: [],
    summary: { printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0 }
  }
}

function parseSnapshot(raw) {
  if (!raw) return emptySnapshot("collector produced no output")
  try {
    var parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return emptySnapshot("collector output was not an object")
    }
    if (!parsed.printers) parsed.printers = []
    if (!parsed.jobs) parsed.jobs = []
    if (!parsed.summary) {
      // A fresh object, never the shared EMPTY_SNAPSHOT.summary — aliasing it
      // lets any later mutation corrupt the exported fallback constant.
      parsed.summary = {
        printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0
      }
    }
    return parsed
  } catch (err) {
    return emptySnapshot("could not parse collector output: " + err)
  }
}

// Mirrors ERROR_REASONS in scripts/galley_normalize.py — the two MUST agree.
// Python drives summary.errorPrinters; this drives the bar and card colors.
// A divergence shows up as a red printer next to a "0 errors" summary.
var ERROR_REASONS = [
  "media-jam", "media-empty", "media-needed", "toner-empty",
  "marker-supply-empty", "offline", "offline-report", "door-open", "cover-open",
  "input-tray-missing", "output-area-full", "shutdown",
  "interlock-open", "output-tray-missing", "fuser-over-temp",
  "fuser-under-temp", "opc-life-over", "developer-empty", "marker-waste-full",
  "spool-area-full", "cups-missing-filter"
]

// Mirrors WARN_REASONS in scripts/galley_normalize.py — the two MUST agree.
// Conditions worth naming before they become errors. toner-low and its
// siblings are absent on purpose: low_supplies already reports those from
// marker-levels against a user-tunable threshold.
var WARN_REASONS = [
  "media-low", "output-area-almost-full", "marker-waste-almost-full",
  "opc-near-eol"
]

// Short human phrases for the reasons that actually occur. Anything missing
// falls through to humanizeReason(), so an unmapped or vendor-specific keyword
// is still readable -- never silently dropped, which was the original bug.
var REASON_TEXT = {
  "media-empty": "Out of paper",
  "media-needed": "Load paper",
  "media-low": "Paper low",
  "media-jam": "Paper jam",
  "cover-open": "Cover open",
  "door-open": "Door open",
  "interlock-open": "Interlock open",
  "input-tray-missing": "Paper tray missing",
  "output-tray-missing": "Output tray missing",
  "output-area-full": "Output tray full",
  "output-area-almost-full": "Output tray almost full",
  "toner-empty": "Out of toner",
  "toner-low": "Toner low",
  "marker-supply-empty": "Out of ink",
  "marker-supply-low": "Ink low",
  "marker-waste-full": "Waste container full",
  "marker-waste-almost-full": "Waste container almost full",
  "developer-empty": "Developer empty",
  "opc-life-over": "Drum worn out",
  "opc-near-eol": "Drum near end of life",
  "fuser-over-temp": "Fuser too hot",
  "fuser-under-temp": "Fuser too cold",
  "offline": "Offline",
  "shutdown": "Powered down",
  "spool-area-full": "Spool full",
  "connecting-to-device": "Connecting",
  "timed-out": "Timed out",
  "paused": "Paused",
  "moving-to-paused": "Pausing",
  "stopping": "Stopping",
  "stopped-partly": "Partly stopped",
  "cups-missing-filter": "Missing printer driver",
  "cups-insecure-filter": "Insecure printer driver"
}

// Job reasons that describe healthy progress. These must produce no text at
// all: a queue where every row carries an explanation teaches the user to stop
// reading them, and then the one row that matters gets skipped too.
var BENIGN_JOB_REASONS = [
  "none", "", "job-printing", "job-queued", "job-incoming", "job-outgoing",
  "job-queued-for-marker", "job-transforming", "job-interpreting",
  "job-completed-successfully", "job-restartable", "job-streaming"
]

var JOB_REASON_TEXT = {
  "printer-stopped": "Printer stopped",
  "printer-stopped-partly": "Printer partly stopped",
  "resources-are-not-ready": "Waiting for the printer",
  "job-hold-until-specified": "Held until a scheduled time",
  "cups-held-for-authentication": "Needs authentication",
  "job-password-wait": "Needs a password",
  "job-data-insufficient": "Waiting for data",
  "document-format-error": "Document format error",
  "unsupported-document-format": "Unsupported document format",
  "unsupported-compression": "Unsupported compression",
  "compression-error": "Compression error",
  "document-access-error": "Cannot read the document",
  "service-off-line": "Printer offline",
  "submission-interrupted": "Submission interrupted",
  "aborted-by-system": "Aborted by the system",
  "job-canceled-by-operator": "Cancelled by an operator",
  "job-canceled-at-device": "Cancelled at the printer",
  "job-completed-with-errors": "Finished with errors",
  "job-completed-with-warnings": "Finished with warnings",
  "job-suspended": "Suspended",
  "job-fetchable": "Waiting to be fetched"
}

var SEVERITY_SUFFIXES = ["-report", "-warning", "-error"]

function baseReason(reason) {
  var text = String(reason || "")
  for (var i = 0; i < SEVERITY_SUFFIXES.length; i++) {
    var suffix = SEVERITY_SUFFIXES[i]
    if (text.length > suffix.length &&
        text.lastIndexOf(suffix) === text.length - suffix.length) {
      return text.slice(0, text.length - suffix.length)
    }
  }
  return text
}

function isErrorReason(reason) {
  var text = String(reason || "")
  if (!text || text === "none") return false
  var base = baseReason(text)
  for (var i = 0; i < ERROR_REASONS.length; i++) {
    if (ERROR_REASONS[i] === base || ERROR_REASONS[i] === text) return true
  }
  return false
}

function isWarnReason(reason) {
  var text = String(reason || "")
  if (!text || text === "none") return false
  var base = baseReason(text)
  for (var i = 0; i < WARN_REASONS.length; i++) {
    if (WARN_REASONS[i] === base || WARN_REASONS[i] === text) return true
  }
  return false
}

function printerHasError(printer) {
  if (!printer) return false
  if (printer.state === "stopped") return true
  // Not accepting jobs is a deliberate admin state (cupsreject), not a
  // fault. Kept out so this agrees with galley_normalize.has_error.
  var reasons = printer.stateReasons || []
  for (var i = 0; i < reasons.length; i++) {
    if (isErrorReason(reasons[i])) return true
  }
  return false
}

// Warnings yield to errors, matching galley_normalize.has_warning: a printer
// reporting both must colour once, at the higher severity.
function printerHasWarning(printer) {
  if (!printer || printerHasError(printer)) return false
  var reasons = printer.stateReasons || []
  for (var i = 0; i < reasons.length; i++) {
    if (isWarnReason(reasons[i])) return true
  }
  return false
}

function printerColor(printer, fallback) {
  if (printerHasError(printer)) return COLOR_ERROR
  if (printerHasWarning(printer)) return COLOR_WARN
  if (printer && printer.state === "printing") return COLOR_BUSY
  return fallback
}

// A keyword nobody mapped, made readable: strip the severity suffix and let the
// dashes become spaces. "brother-drum-shifted-warning" -> "Brother drum shifted".
function humanizeReason(reason) {
  var base = baseReason(String(reason || "")).replace(/-/g, " ").trim()
  if (!base) return ""
  return base.charAt(0).toUpperCase() + base.slice(1)
}

function reasonPhrases(reasons, vocabulary) {
  var out = []
  var list = reasons || []
  for (var i = 0; i < list.length; i++) {
    var text = String(list[i] || "")
    if (!text || text === "none") continue
    var base = baseReason(text)
    var mapped = vocabulary[base] || vocabulary[text]
    var phrase = mapped || humanizeReason(text)
    if (phrase && out.indexOf(phrase) === -1) out.push(phrase)
  }
  return out
}

// What to show under a printer's name. The backend's own message wins when it
// exists -- it is written for humans and often names the specific tray -- then
// the reasons, then the bare state. The middle step is the one the panel used
// to skip, which is why an empty stateMessage left a stopped printer with no
// explanation anywhere the user was still looking.
function reasonText(printer) {
  if (!printer) return ""
  if (printer.stateMessage) return printer.stateMessage
  var phrases = reasonPhrases(printer.stateReasons, REASON_TEXT)
  if (phrases.length) return phrases.join(" · ")
  return printer.state || ""
}

// Why a job is not moving, or "" while it is moving fine.
function jobReasonText(job) {
  if (!job) return ""
  var list = job.stateReasons || []
  var interesting = []
  for (var i = 0; i < list.length; i++) {
    if (BENIGN_JOB_REASONS.indexOf(String(list[i] || "")) === -1) {
      interesting.push(list[i])
    }
  }
  return reasonPhrases(interesting, JOB_REASON_TEXT).join(" · ")
}

// The single most severe thing worth naming in one line, for the bar tooltip.
function worstFault(snapshot) {
  var printers = (snapshot && snapshot.printers) || []
  var i
  for (i = 0; i < printers.length; i++) {
    if (printerHasError(printers[i])) {
      return printers[i].name + ": " + reasonText(printers[i])
    }
  }
  for (i = 0; i < printers.length; i++) {
    if (printerHasWarning(printers[i])) {
      return printers[i].name + ": " + reasonText(printers[i])
    }
  }
  return ""
}

function jobGlyph(state) {
  if (state === "processing") return "⏵"
  if (state === "held") return "⏸"
  if (state === "stopped" || state === "aborted") return "⚠"
  return "⏸"
}

function formatSize(sizeKb) {
  if (!sizeKb || sizeKb <= 0) return "—"
  if (sizeKb < 1024) return sizeKb + " KB"
  return (sizeKb / 1024).toFixed(1) + " MB"
}

function supplyLabel(supply) {
  if (!supply) return ""
  var name = String(supply.name || "").toLowerCase()
  var level = supply.level

  if (supply.type === "toner" || supply.type === "ink") {
    if (name.indexOf("black") !== -1) return "K" + level
    if (name.indexOf("cyan") !== -1) return "C" + level
    if (name.indexOf("magenta") !== -1) return "M" + level
    if (name.indexOf("yellow") !== -1) return "Y" + level
  }
  if (supply.type === "opc") return "drum " + level
  if (supply.type === "waste-toner") return "waste " + level

  var short = String(supply.name || "").split(" ")[0].toLowerCase()
  return short + " " + level
}

function supplyColor(supply, threshold, fallback) {
  // waste-toner polarity is vendor-dependent and undefined by IPP, so it is
  // shown but never warned on. Only waste-toner: an "other"-typed marker (a
  // Belt Unit, on this hardware) still follows percent-remaining and warns
  // normally. The exclusion is about undefined polarity, not vague type names.
  if (!supply || supply.type === "waste-toner") return fallback
  if (typeof supply.level !== "number") return fallback
  if (supply.level < threshold) return COLOR_ERROR
  if (supply.level < threshold * 2) return COLOR_WARN
  return fallback
}

function filterJobs(jobs, selectedPrinter) {
  var list = jobs || []
  if (!selectedPrinter) return list.slice()
  var result = []
  for (var i = 0; i < list.length; i++) {
    if (list[i].printer === selectedPrinter) result.push(list[i])
  }
  return result
}

function hasCancellableJobs(jobs, printerName) {
  // Whether `cancel -a <printer>` would actually cancel anything. cupsd runs
  // with _user_cancel_any=0, so it silently cancels only the caller's own jobs
  // -- on a shared queue a "cancel all" button would appear to clear the queue,
  // cancel a subset, and surface the rest as stderr in the error strip.
  //
  // Deliberately not filterJobs(): that treats an empty selection as "no
  // filter" and returns every job, which is correct for the queue view and
  // wrong here, where an unnamed printer would inherit another printer's
  // ownership. A card without a name has nothing cancellable.
  if (!printerName) return false
  var list = jobs || []
  for (var i = 0; i < list.length; i++) {
    if (list[i].printer === printerName && list[i].mine) return true
  }
  return false
}

function barSeverity(snapshot) {
  if (!snapshot) return "normal"
  if (snapshot.cupsd === "error") return "error"
  var summary = snapshot.summary || {}
  if (summary.errorPrinters > 0) return "error"
  if (summary.warnPrinters > 0) return "warn"
  if (summary.lowSupplies > 0) return "warn"

  var jobs = snapshot.jobs || []
  for (var i = 0; i < jobs.length; i++) {
    if (jobs[i].state === "held" || jobs[i].state === "stopped") return "warn"
  }
  return "normal"
}

function badgeText(snapshot) {
  var summary = (snapshot && snapshot.summary) || {}
  var count = summary.activeJobs || 0
  // "" doubles as the visibility flag. An idle queue is the common case, and
  // this saves Panel.qml a second call to ask whether to draw at all.
  if (count <= 0) return ""
  return count > BADGE_MAX ? BADGE_MAX + "+" : String(count)
}

function plural(count, word) {
  return count + " " + word + (count === 1 ? "" : "s")
}

function tooltipText(snapshot) {
  if (!snapshot) return "Printers"

  var summary = snapshot.summary || {}

  // An asleep daemon keeps its content: Panel.qml's handleOutput() replaces
  // the snapshot only on a "running" response, so summary/printers here are
  // still exactly what badgeText is drawing in the bar and what the panel
  // body is listing. Split on retained content the same way the panel body
  // does, or the tooltip ends up denying the count sitting next to it.
  if (snapshot.cupsd === "asleep") {
    if ((snapshot.printers || []).length === 0) return "CUPS idle — nothing queued"
    // No "<name> printing" clause here: a sleeping daemon is printing
    // nothing, so a retained printing state must not be reported as current.
    var idle = [plural(summary.printers || 0, "printer"),
                plural(summary.activeJobs || 0, "job")]
    if (summary.errorPrinters > 0) idle.push(plural(summary.errorPrinters, "error"))
    return "CUPS idle — last known: " + idle.join(" · ")
  }
  if (snapshot.cupsd === "error") return snapshot.error || "Collector failed"

  var parts = [plural(summary.printers || 0, "printer")]

  var printers = snapshot.printers || []
  for (var i = 0; i < printers.length; i++) {
    if (printers[i].state === "printing") {
      parts.push(printers[i].name + " printing")
      break
    }
  }

  parts.push(plural(summary.activeJobs || 0, "job"))

  // Name the fault rather than counting it. "1 error" told the user something
  // was wrong without saying what, which sent them looking at the network while
  // the printer was out of paper. The count still appears when more than one
  // printer is affected, so nothing is hidden by naming only the worst.
  var fault = worstFault(snapshot)
  if (fault) {
    var affected = (summary.errorPrinters || 0) + (summary.warnPrinters || 0)
    parts.push(affected > 1 ? fault + " (+" + (affected - 1) + " more)" : fault)
  }
  return parts.join(" · ")
}

var SUPPLY_REARM_MARGIN = 10

function supplyRearmed(level, threshold) {
  return level > threshold + SUPPLY_REARM_MARGIN
}

// Advances the armed set that suppresses repeat supply-low notifications.
// Lives here rather than in Panel.qml so it can be tested against the same
// conditions diffSnapshots applies -- the two must agree on which supplies
// are in play, or one silently disarms what the other would have announced.
function nextArmedSupplies(armed, snapshot, threshold, notifySupplyLow) {
  // A fresh map, never the caller's: armedSupplies is a QML `property var`,
  // and mutating it in place would leave its identity unchanged.
  var next = {}
  for (var key in (armed || {})) next[key] = armed[key]

  // diffSnapshots skips its whole supply loop when this toggle is off, so
  // arming under it would swallow the falling edge that fires the
  // notification: turning the toggle back on would then stay silent until the
  // supply refilled past the re-arm margin.
  if (!notifySupplyLow) return next

  var printers = (snapshot && snapshot.printers) || []
  for (var p = 0; p < printers.length; p++) {
    var supplies = printers[p].supplies || []
    for (var s = 0; s < supplies.length; s++) {
      var supply = supplies[s]
      if (typeof supply.level !== "number") continue
      var supplyKey = printers[p].name + "/" + supply.name
      if (supply.level < threshold) next[supplyKey] = true
      else if (supplyRearmed(supply.level, threshold)) delete next[supplyKey]
    }
  }
  return next
}

function indexBy(list, key) {
  var map = {}
  for (var i = 0; i < (list || []).length; i++) map[list[i][key]] = list[i]
  return map
}

function diffSnapshots(prev, next, options) {
  var events = []
  // Silent on first load, and never diff against an unusable snapshot.
  if (!prev || !next) return events
  if (prev.cupsd !== "running" || next.cupsd !== "running") return events

  var opts = options || {}
  var threshold = opts.threshold || 15
  var completed = {}
  for (var c = 0; c < (opts.completedIds || []).length; c++) {
    completed[opts.completedIds[c]] = true
  }
  var armed = opts.armedSupplies || {}

  var prevJobs = indexBy(prev.jobs, "id")
  var nextJobs = indexBy(next.jobs, "id")

  for (var id in prevJobs) {
    var before = prevJobs[id]
    var after = nextJobs[id]

    if (!after) {
      // A completed job and a cancelled job both simply vanish. Only the
      // collector's completed-job confirmation tells them apart.
      if (opts.notifyJobCompleted && completed[before.id]) {
        events.push({
          type: "job-completed", urgency: "low", title: "Print complete",
          message: before.name + " finished on " + before.printer,
          key: "job/" + before.id
        })
      }
      continue
    }

    var failed = after.state === "stopped" || after.state === "aborted"
    var wasFailed = before.state === "stopped" || before.state === "aborted"
    if (opts.notifyJobFailed && failed && !wasFailed) {
      events.push({
        type: "job-failed", urgency: "critical", title: "Print failed",
        message: after.name + " stopped on " + after.printer,
        key: "job/" + after.id
      })
    }
  }

  var prevPrinters = indexBy(prev.printers, "name")
  for (var p = 0; p < (next.printers || []).length; p++) {
    var printer = next.printers[p]
    var previous = prevPrinters[printer.name]
    if (!previous) continue

    if (opts.notifyPrinterError &&
        printerHasError(printer) && !printerHasError(previous)) {
      events.push({
        type: "printer-error", urgency: "critical", title: "Printer error",
        // reasonText rather than a private fallback chain: this path was the
        // only one that explained a fault, and the card's divergence from it
        // is what left "stopped" as the only thing on screen.
        message: printer.name + ": " + (reasonText(printer) || "stopped"),
        key: "printer/" + printer.name
      })
    }

    if (!opts.notifySupplyLow) continue

    var supplies = printer.supplies || []
    for (var s = 0; s < supplies.length; s++) {
      var supply = supplies[s]
      // waste-toner only -- see supplyColor. An "other"-typed marker such as a
      // Belt Unit does raise a supply-low notification, deliberately.
      if (supply.type === "waste-toner") continue
      if (typeof supply.level !== "number") continue

      var key = printer.name + "/" + supply.name
      if (supply.level >= threshold) continue
      if (armed[key]) continue

      events.push({
        type: "supply-low", urgency: "normal", title: "Supply low",
        message: printer.name + ": " + supply.name + " at " + supply.level + "%",
        key: key
      })
    }
  }

  return events
}

if (typeof module !== "undefined") {
  module.exports = {
    // QML sees every top-level var through the namespace import, so Panel.qml
    // can reach these without help. Node only sees this object, and a test that
    // hardcodes "#eab308" would pass while the palette moved underneath it.
    COLOR_OK: COLOR_OK,
    COLOR_WARN: COLOR_WARN,
    COLOR_ERROR: COLOR_ERROR,
    COLOR_BUSY: COLOR_BUSY,
    EMPTY_SNAPSHOT: EMPTY_SNAPSHOT,
    parseSnapshot: parseSnapshot,
    printerHasError: printerHasError,
    isErrorReason: isErrorReason,
    isWarnReason: isWarnReason,
    printerHasWarning: printerHasWarning,
    reasonText: reasonText,
    jobReasonText: jobReasonText,
    worstFault: worstFault,
    humanizeReason: humanizeReason,
    printerColor: printerColor,
    jobGlyph: jobGlyph,
    formatSize: formatSize,
    supplyLabel: supplyLabel,
    supplyColor: supplyColor,
    filterJobs: filterJobs,
    hasCancellableJobs: hasCancellableJobs,
    barSeverity: barSeverity,
    badgeText: badgeText,
    tooltipText: tooltipText,
    diffSnapshots: diffSnapshots,
    supplyRearmed: supplyRearmed,
    nextArmedSupplies: nextArmedSupplies
  }
}
