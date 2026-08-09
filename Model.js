// Model.js — pure presentation transforms shared by the QML panel and the
// node test suite. No I/O, no QML imports, no timers.

var COLOR_OK = "#22c55e"
var COLOR_WARN = "#eab308"
var COLOR_ERROR = "#ef4444"
var COLOR_BUSY = "#3b82f6"

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
    if (!parsed || typeof parsed !== "object") {
      return emptySnapshot("collector output was not an object")
    }
    if (!parsed.printers) parsed.printers = []
    if (!parsed.jobs) parsed.jobs = []
    if (!parsed.summary) parsed.summary = EMPTY_SNAPSHOT.summary
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

function printerHasError(printer) {
  if (!printer) return false
  if (printer.state === "stopped") return true
  // Not accepting jobs is a deliberate admin state (cupsreject), not a
  // fault. Kept out so this agrees with galley_normalize.has_error.
  var reasons = printer.stateReasons || []
  for (var i = 0; i < reasons.length; i++) {
    if (reasons[i] && reasons[i] !== "none") return true
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

function plural(count, word) {
  return count + " " + word + (count === 1 ? "" : "s")
}

function tooltipText(snapshot) {
  if (!snapshot) return "Galley"
  if (snapshot.cupsd === "asleep") return "Galley — CUPS idle, nothing queued"
  if (snapshot.cupsd === "error") return "Galley — " + (snapshot.error || "collector failed")

  var summary = snapshot.summary || {}
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
  return "Galley — " + parts.join(" · ")
}

if (typeof module !== "undefined") {
  module.exports = {
    EMPTY_SNAPSHOT: EMPTY_SNAPSHOT,
    parseSnapshot: parseSnapshot,
    printerGlyph: printerGlyph,
    printerHasError: printerHasError,
    printerColor: printerColor,
    jobGlyph: jobGlyph,
    formatSize: formatSize,
    supplyLabel: supplyLabel,
    supplyColor: supplyColor,
    filterJobs: filterJobs,
    barSeverity: barSeverity,
    tooltipText: tooltipText
  }
}
