// tests/model.test.js
const test = require("node:test")
const assert = require("node:assert/strict")

const Model = require("../Model.js")

const SNAPSHOT = {
  schema: 1, cupsd: "running", error: null, defaultPrinter: "Canon@OLP",
  printers: [
    { name: "Brother@Home", state: "idle", stateReasons: ["none"],
      accepting: true, queuedJobCount: 1, supplies: [
        { name: "Drum Unit", type: "opc", level: 76, color: "#000000" }] },
    { name: "Canon@OLP", state: "printing", stateReasons: ["none"],
      accepting: true, queuedJobCount: 2, supplies: [
        { name: "Black", type: "toner", level: 8, color: "#000000" }] }
  ],
  jobs: [
    { id: 53, name: "report.pdf", printer: "Canon@OLP", user: "sean",
      state: "processing", pages: null, sizeKb: 1024, mine: true },
    { id: 55, name: "slides.pdf", printer: "Brother@Home", user: "sean",
      state: "held", pages: null, sizeKb: 1, mine: true }
  ],
  summary: { printers: 2, activeJobs: 2, errorPrinters: 0, lowSupplies: 1 }
}

test("parseSnapshot returns the parsed object", () => {
  const parsed = Model.parseSnapshot(JSON.stringify(SNAPSHOT))
  assert.equal(parsed.cupsd, "running")
  assert.equal(parsed.printers.length, 2)
})

test("parseSnapshot survives garbage without throwing", () => {
  const parsed = Model.parseSnapshot("not json at all")
  assert.equal(parsed.cupsd, "error")
  assert.ok(parsed.error)
  assert.deepEqual(parsed.printers, [])
})

test("parseSnapshot survives empty input", () => {
  assert.equal(Model.parseSnapshot("").cupsd, "error")
})

test("printerColor flags a stopped printer", () => {
  const stopped = { state: "stopped", stateReasons: ["media-jam"] }
  assert.notEqual(Model.printerColor(stopped, "#ffffff"), "#ffffff")
})

test("printerColor leaves an idle printer on the theme foreground", () => {
  const idle = { state: "idle", stateReasons: ["none"] }
  assert.equal(Model.printerColor(idle, "#ffffff"), "#ffffff")
})

test("error reasons match the Python whitelist, across severity suffixes", () => {
  for (const reason of ["media-jam", "media-empty-warning", "cover-open-report",
                        "offline", "offline-report", "offline-warning"]) {
    assert.equal(Model.isErrorReason(reason), true, reason)
  }
})

test("benign reasons are not errors", () => {
  for (const reason of ["none", "", "connecting-to-device", "paused", "other",
                        "cups-waiting-for-job-completed", "toner-low-warning"]) {
    assert.equal(Model.isErrorReason(reason), false, reason)
  }
})

test("formatSize switches units at a megabyte", () => {
  assert.equal(Model.formatSize(1), "1 KB")
  assert.equal(Model.formatSize(999), "999 KB")
  assert.equal(Model.formatSize(1024), "1.0 MB")
  assert.equal(Model.formatSize(0), "—")
  assert.equal(Model.formatSize(null), "—")
})

test("supplyLabel abbreviates the standard process colors", () => {
  assert.equal(Model.supplyLabel({ name: "Black Toner", type: "toner", level: 41 }), "K41")
  assert.equal(Model.supplyLabel({ name: "Cyan Toner", type: "toner", level: 38 }), "C38")
  assert.equal(Model.supplyLabel({ name: "Drum Unit", type: "opc", level: 76 }), "drum 76")
  assert.equal(Model.supplyLabel({ name: "Waste Toner Box", type: "waste-toner", level: 83 }), "waste 83")
})

test("supplyColor never warns on waste toner", () => {
  const waste = { name: "Waste", type: "waste-toner", level: 2 }
  assert.equal(Model.supplyColor(waste, 15, "#ffffff"), "#ffffff")
})

test("supplyColor warns below the threshold", () => {
  const low = { name: "Black", type: "toner", level: 8 }
  assert.notEqual(Model.supplyColor(low, 15, "#ffffff"), "#ffffff")
})

test("filterJobs with no selection returns everything", () => {
  assert.equal(Model.filterJobs(SNAPSHOT.jobs, "").length, 2)
})

test("filterJobs narrows to the selected printer", () => {
  const filtered = Model.filterJobs(SNAPSHOT.jobs, "Brother@Home")
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].id, 55)
})

test("filterJobs on an unknown printer returns nothing", () => {
  assert.equal(Model.filterJobs(SNAPSHOT.jobs, "Nope").length, 0)
})

test("barSeverity is normal when all is well", () => {
  // Job 55 is held, which is itself a warn condition. Keep only the
  // processing job so this exercises "actively printing, nothing wrong"
  // rather than "nothing happening at all".
  const calm = {
    ...SNAPSHOT,
    jobs: [SNAPSHOT.jobs[0]],
    summary: { ...SNAPSHOT.summary, lowSupplies: 0 }
  }
  assert.equal(Model.barSeverity(calm), "normal")
})

test("barSeverity warns on a held job", () => {
  assert.equal(Model.barSeverity(SNAPSHOT), "warn")
})

test("barSeverity escalates to error on a stopped printer", () => {
  const broken = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, errorPrinters: 1 } }
  assert.equal(Model.barSeverity(broken), "error")
})

test("barSeverity is normal while cupsd sleeps", () => {
  assert.equal(Model.barSeverity({ cupsd: "asleep", printers: [], jobs: [],
    summary: { printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0 } }), "normal")
})

test("badgeText is empty when nothing is queued", () => {
  const idle = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, activeJobs: 0 } }
  assert.equal(Model.badgeText(idle), "")
})

test("badgeText shows the exact count up to nine", () => {
  const one = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, activeJobs: 1 } }
  const nine = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, activeJobs: 9 } }
  assert.equal(Model.badgeText(one), "1")
  assert.equal(Model.badgeText(nine), "9")
})

test("badgeText clamps a queue past nine so the badge stays a circle", () => {
  const ten = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, activeJobs: 10 } }
  const many = { ...SNAPSHOT, summary: { ...SNAPSHOT.summary, activeJobs: 348 } }
  assert.equal(Model.badgeText(ten), "9+")
  assert.equal(Model.badgeText(many), "9+")
})

test("badgeText survives a snapshot with no summary", () => {
  assert.equal(Model.badgeText({ cupsd: "running", printers: [], jobs: [] }), "")
})

test("badgeText survives a null snapshot", () => {
  assert.equal(Model.badgeText(null), "")
  assert.equal(Model.badgeText(undefined), "")
})

test("tooltipText summarizes printers and jobs without a name prefix", () => {
  const text = Model.tooltipText(SNAPSHOT)
  assert.match(text, /2 printers/)
  assert.match(text, /2 jobs/)
  assert.doesNotMatch(text, /Galley/)
})

test("tooltipText reports a sleeping daemon plainly", () => {
  const text = Model.tooltipText({ cupsd: "asleep", printers: [], jobs: [],
    summary: { printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0 } })
  assert.match(text, /idle/i)
  assert.doesNotMatch(text, /Galley/)
})

const ALL_ON = {
  threshold: 15, notifyJobFailed: true, notifyPrinterError: true,
  notifyJobCompleted: true, notifySupplyLow: true,
  completedIds: [], armedSupplies: {}
}

function snap(printers, jobs) {
  return {
    schema: 1, cupsd: "running", error: null, defaultPrinter: "",
    printers: printers, jobs: jobs,
    summary: { printers: printers.length, activeJobs: jobs.length,
      errorPrinters: 0, lowSupplies: 0 }
  }
}

const IDLE_PRINTER = { name: "P", state: "idle", stateReasons: ["none"],
  accepting: true, queuedJobCount: 0, supplies: [] }

test("no notifications on first load", () => {
  assert.deepEqual(Model.diffSnapshots(null, snap([IDLE_PRINTER], []), ALL_ON), [])
})

test("job that vanished and appears completed notifies completion", () => {
  const before = snap([IDLE_PRINTER], [{ id: 9, name: "a.pdf", printer: "P", state: "processing" }])
  const after = snap([IDLE_PRINTER], [])
  const events = Model.diffSnapshots(before, after,
    Object.assign({}, ALL_ON, { completedIds: [9] }))
  assert.equal(events.length, 1)
  assert.equal(events[0].type, "job-completed")
  assert.match(events[0].message, /a\.pdf/)
})

test("job that vanished without completing is silent", () => {
  // A cancelled job also disappears; without confirmation we say nothing.
  const before = snap([IDLE_PRINTER], [{ id: 9, name: "a.pdf", printer: "P", state: "processing" }])
  const after = snap([IDLE_PRINTER], [])
  assert.deepEqual(Model.diffSnapshots(before, after, ALL_ON), [])
})

test("job entering the stopped state notifies failure", () => {
  const before = snap([IDLE_PRINTER], [{ id: 9, name: "a.pdf", printer: "P", state: "processing" }])
  const after = snap([IDLE_PRINTER], [{ id: 9, name: "a.pdf", printer: "P", state: "stopped" }])
  const events = Model.diffSnapshots(before, after, ALL_ON)
  assert.equal(events.length, 1)
  assert.equal(events[0].type, "job-failed")
  assert.equal(events[0].urgency, "critical")
})

test("printer entering the stopped state notifies once, not repeatedly", () => {
  const ok = snap([IDLE_PRINTER], [])
  const broken = snap([{ ...IDLE_PRINTER, state: "stopped",
    stateReasons: ["media-jam"], stateMessage: "Paper jam" }], [])

  const first = Model.diffSnapshots(ok, broken, ALL_ON)
  assert.equal(first.length, 1)
  assert.equal(first[0].type, "printer-error")
  assert.match(first[0].message, /Paper jam/)

  assert.deepEqual(Model.diffSnapshots(broken, broken, ALL_ON), [])
})

test("printer recovering is silent", () => {
  const broken = snap([{ ...IDLE_PRINTER, state: "stopped", stateReasons: ["media-jam"] }], [])
  const ok = snap([IDLE_PRINTER], [])
  assert.deepEqual(Model.diffSnapshots(broken, ok, ALL_ON), [])
})

test("supply crossing below the threshold notifies once", () => {
  const high = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: 40 }] }], [])
  const low = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: 9 }] }], [])

  const events = Model.diffSnapshots(high, low, ALL_ON)
  assert.equal(events.length, 1)
  assert.equal(events[0].type, "supply-low")
  assert.equal(events[0].key, "P/Black")
})

test("supply already armed low does not re-notify", () => {
  const low = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: 9 }] }], [])
  const options = Object.assign({}, ALL_ON, { armedSupplies: { "P/Black": true } })
  assert.deepEqual(Model.diffSnapshots(low, low, options), [])
})

test("waste toner never raises a supply alert", () => {
  const high = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Waste", type: "waste-toner", level: 40 }] }], [])
  const low = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Waste", type: "waste-toner", level: 2 }] }], [])
  assert.deepEqual(Model.diffSnapshots(high, low, ALL_ON), [])
})

test("supplyRearmed requires clearing the threshold by ten points", () => {
  assert.equal(Model.supplyRearmed(20, 15), false)
  assert.equal(Model.supplyRearmed(26, 15), true)
})

test("each notification type respects its toggle", () => {
  // Every gate is checked in both directions: off must suppress, on must
  // still fire. A one-directional check would pass against a gate that is
  // simply broken and never fires at all.

  const failBefore = snap([IDLE_PRINTER],
    [{ id: 9, name: "a.pdf", printer: "P", state: "processing" }])
  const failAfter = snap([IDLE_PRINTER],
    [{ id: 9, name: "a.pdf", printer: "P", state: "stopped" }])
  assert.equal(Model.diffSnapshots(failBefore, failAfter, ALL_ON).length, 1)
  assert.deepEqual(Model.diffSnapshots(failBefore, failAfter,
    Object.assign({}, ALL_ON, { notifyJobFailed: false })), [])

  const ok = snap([IDLE_PRINTER], [])
  const broken = snap([{ ...IDLE_PRINTER, state: "stopped",
    stateReasons: ["media-jam"] }], [])
  assert.equal(Model.diffSnapshots(ok, broken, ALL_ON).length, 1)
  assert.deepEqual(Model.diffSnapshots(ok, broken,
    Object.assign({}, ALL_ON, { notifyPrinterError: false })), [])

  const had = snap([IDLE_PRINTER],
    [{ id: 9, name: "a.pdf", printer: "P", state: "processing" }])
  const gone = snap([IDLE_PRINTER], [])
  const completed = Object.assign({}, ALL_ON, { completedIds: [9] })
  assert.equal(Model.diffSnapshots(had, gone, completed).length, 1)
  assert.deepEqual(Model.diffSnapshots(had, gone,
    Object.assign({}, completed, { notifyJobCompleted: false })), [])

  const high = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: 40 }] }], [])
  const low = snap([{ ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: 9 }] }], [])
  assert.equal(Model.diffSnapshots(high, low, ALL_ON).length, 1)
  assert.deepEqual(Model.diffSnapshots(high, low,
    Object.assign({}, ALL_ON, { notifySupplyLow: false })), [])
})

test("a snapshot in the error state produces no notifications", () => {
  const before = snap([IDLE_PRINTER], [])
  const after = Model.parseSnapshot("garbage")
  assert.deepEqual(Model.diffSnapshots(before, after, ALL_ON), [])
})
