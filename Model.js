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

function printerGlyph(state) {
  if (state === "printing") return "󰐪"
  if (state === "stopped") return "󰐮"
  return "󰐪"
}

// Mirrors ERROR_REASONS in scripts/galley_normalize.py — the two MUST agree.
// Python drives summary.errorPrinters; this drives the bar and card colors.
// A divergence shows up as a red printer next to a "0 errors" summary.
var ERROR_REASONS = [
  "media-jam", "media-empty", "media-needed", "toner-empty",
  "marker-supply-empty", "offline", "offline-report", "door-open", "cover-open",
  "input-tray-missing", "output-area-full", "shutdown"
]

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

function printerColor(printer, fallback) {
  if (printerHasError(printer)) return COLOR_ERROR
  if (printer && printer.state === "printing") return COLOR_BUSY
  return fallback
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
  // shown but never warned on.
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

function barSeverity(snapshot) {
  if (!snapshot) return "normal"
  if (snapshot.cupsd === "error") return "error"
  var summary = snapshot.summary || {}
  if (summary.errorPrinters > 0) return "error"
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
  if (summary.errorPrinters > 0) parts.push(plural(summary.errorPrinters, "error"))
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
        message: printer.name + ": " +
          (printer.stateMessage || (printer.stateReasons || []).join(", ") || "stopped"),
        key: "printer/" + printer.name
      })
    }

    if (!opts.notifySupplyLow) continue

    var supplies = printer.supplies || []
    for (var s = 0; s < supplies.length; s++) {
      var supply = supplies[s]
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
    EMPTY_SNAPSHOT: EMPTY_SNAPSHOT,
    parseSnapshot: parseSnapshot,
    printerGlyph: printerGlyph,
    printerHasError: printerHasError,
    isErrorReason: isErrorReason,
    printerColor: printerColor,
    jobGlyph: jobGlyph,
    formatSize: formatSize,
    supplyLabel: supplyLabel,
    supplyColor: supplyColor,
    filterJobs: filterJobs,
    barSeverity: barSeverity,
    badgeText: badgeText,
    tooltipText: tooltipText,
    diffSnapshots: diffSnapshots,
    supplyRearmed: supplyRearmed,
    nextArmedSupplies: nextArmedSupplies
  }
}
