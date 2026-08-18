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

test("hasCancellableJobs is true when a job on that printer is mine", () => {
  // Both SNAPSHOT jobs are mine: 53 on Canon@OLP, 55 on Brother@Home.
  assert.equal(Model.hasCancellableJobs(SNAPSHOT.jobs, "Canon@OLP"), true)
  assert.equal(Model.hasCancellableJobs(SNAPSHOT.jobs, "Brother@Home"), true)
})

test("hasCancellableJobs is false when every job on that printer is someone else's", () => {
  // The whole point of the gate: cupsd runs with _user_cancel_any=0, so
  // `cancel -a` silently cancels only your own jobs. A queue full of other
  // people's work must not offer a button that appears to clear it.
  const foreign = SNAPSHOT.jobs.map(job => ({ ...job, mine: false }))
  assert.equal(Model.hasCancellableJobs(foreign, "Canon@OLP"), false)
})

test("hasCancellableJobs sees only the named printer's jobs", () => {
  // A job I own on ANOTHER printer must not enable this printer's button.
  const mixed = [
    { id: 1, printer: "Canon@OLP", mine: false },
    { id: 2, printer: "Brother@Home", mine: true }
  ]
  assert.equal(Model.hasCancellableJobs(mixed, "Canon@OLP"), false)
  assert.equal(Model.hasCancellableJobs(mixed, "Brother@Home"), true)
})

test("hasCancellableJobs survives an empty or absent queue", () => {
  assert.equal(Model.hasCancellableJobs([], "Canon@OLP"), false)
  assert.equal(Model.hasCancellableJobs(null, "Canon@OLP"), false)
  assert.equal(Model.hasCancellableJobs(undefined, "Canon@OLP"), false)
})

test("hasCancellableJobs requires a printer name rather than matching everything", () => {
  // filterJobs treats an empty selection as "no filter" and returns every job,
  // which is right for the queue view and wrong here: an unnamed printer must
  // not inherit another printer's ownership.
  assert.equal(Model.hasCancellableJobs(SNAPSHOT.jobs, ""), false)
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
  assert.match(text, /nothing queued/i)
  assert.doesNotMatch(text, /Galley/)
})

test("tooltipText describes retained content while cupsd sleeps", () => {
  // The tooltip is fed statusSnapshot() (Panel.qml), which merges the live
  // cupsd state onto retained content -- so an asleep snapshot still carries
  // the printers and job count that badgeText is drawing and the panel body
  // is listing under "CUPS idle - showing last known state". Claiming an
  // empty queue here contradicts both surfaces at once.
  const retained = { ...SNAPSHOT, cupsd: "asleep" }
  const text = Model.tooltipText(retained)
  assert.match(text, /idle/i)
  assert.doesNotMatch(text, /nothing queued/i)
  assert.match(text, /2 jobs/)
})

test("tooltipText surfaces a retained error while cupsd sleeps", () => {
  // barSeverity keeps the bar glyph red off retained errorPrinters while the
  // daemon sleeps, so the tooltip has to explain the color it is sitting on.
  const retained = { ...SNAPSHOT, cupsd: "asleep",
    summary: { ...SNAPSHOT.summary, errorPrinters: 1 } }
  assert.match(Model.tooltipText(retained), /1 error/)
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

function suppliedPrinter(level) {
  return { ...IDLE_PRINTER,
    supplies: [{ name: "Black", type: "toner", level: level }] }
}

test("nextArmedSupplies arms a supply below the threshold", () => {
  assert.deepEqual(
    Model.nextArmedSupplies({}, snap([suppliedPrinter(9)], []), 15, true),
    { "P/Black": true })
})

test("nextArmedSupplies clears a supply that cleared the re-arm margin", () => {
  assert.deepEqual(
    Model.nextArmedSupplies({ "P/Black": true },
      snap([suppliedPrinter(26)], []), 15, true),
    {})
})

test("nextArmedSupplies holds a supply inside the hysteresis band", () => {
  // Between threshold and threshold+10 neither condition applies. The margin
  // is what stops a supply hovering at the boundary from re-notifying on
  // every poll, so an armed entry has to survive this band.
  assert.deepEqual(
    Model.nextArmedSupplies({ "P/Black": true },
      snap([suppliedPrinter(20)], []), 15, true),
    { "P/Black": true })
})

test("nextArmedSupplies does not arm while supply-low notifications are off", () => {
  // diffSnapshots skips the whole supply loop under the same condition, so
  // arming here would swallow the one edge that fires the notification:
  // turning the toggle back on would stay silent until the supply refilled
  // past the re-arm margin.
  const low = snap([suppliedPrinter(9)], [])
  assert.deepEqual(Model.nextArmedSupplies({}, low, 15, false), {})

  // With the toggle back on, that same unchanged snapshot still notifies.
  const events = Model.diffSnapshots(low, low, ALL_ON)
  assert.equal(events.length, 1)
  assert.equal(events[0].type, "supply-low")
})

test("nextArmedSupplies returns a fresh map rather than mutating its input", () => {
  // armedSupplies is a QML `property var`: an in-place mutation would not
  // change the property's identity, and nothing bound to it would re-evaluate.
  const before = {}
  Model.nextArmedSupplies(before, snap([suppliedPrinter(9)], []), 15, true)
  assert.deepEqual(before, {})
})

test("a stranded armed entry stays silent until the map is cleared", () => {
  // This is the behaviour that clearing armedSupplies on a threshold change
  // buys. Armed under an old threshold of 40, "P/Black" is above the new arm
  // line and below the new re-arm line (15+10), so it is never cleared by
  // level alone -- and it suppresses the notification the new threshold of 15
  // exists to raise.
  const crossed = snap([suppliedPrinter(12)], [])
  assert.deepEqual(Model.diffSnapshots(crossed, crossed,
    Object.assign({}, ALL_ON, { armedSupplies: { "P/Black": true } })), [])
  assert.equal(Model.diffSnapshots(crossed, crossed, ALL_ON).length, 1)
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

// --- Explaining faults, not just flagging them -------------------------------
// A printer that ran out of paper showed a coloured glyph and the word
// "stopped", because the card's fallback chain skipped stateReasons while the
// notification path did not. The reason was in the snapshot the whole time.

test("reasonText names the fault when the backend leaves stateMessage empty", () => {
  const printer = { name: "p", state: "stopped", stateMessage: "",
                    stateReasons: ["media-empty-error"] }
  const text = Model.reasonText(printer)
  assert.match(text, /out of paper/i)
  assert.notEqual(text, "stopped")
})

test("reasonText prefers the backend's own message when there is one", () => {
  const printer = { name: "p", state: "stopped",
                    stateMessage: "Load paper into Tray 1",
                    stateReasons: ["media-empty-error"] }
  assert.equal(Model.reasonText(printer), "Load paper into Tray 1")
})

test("reasonText joins multiple reasons", () => {
  const printer = { name: "p", state: "stopped", stateMessage: "",
                    stateReasons: ["cover-open", "media-empty"] }
  const text = Model.reasonText(printer)
  assert.match(text, /cover open/i)
  assert.match(text, /out of paper/i)
})

test("reasonText falls back to the state when there is nothing to explain", () => {
  const printer = { name: "p", state: "idle", stateMessage: "",
                    stateReasons: ["none"] }
  assert.equal(Model.reasonText(printer), "idle")
})

test("reasonText makes an unmapped reason readable rather than dropping it", () => {
  // Vendors ship reasons outside the IPP registry. An unknown keyword must
  // still reach the user -- badly worded beats invisible, which is the whole
  // bug this feature exists to fix.
  const printer = { name: "p", state: "stopped", stateMessage: "",
                    stateReasons: ["brother-drum-shifted-warning"] }
  const text = Model.reasonText(printer)
  assert.match(text, /brother drum shifted/i)
  assert.doesNotMatch(text, /-warning/)
})

test("isWarnReason spans severity suffixes and excludes errors", () => {
  for (const reason of ["media-low", "media-low-warning", "media-low-report",
                        "marker-waste-almost-full", "output-area-almost-full"]) {
    assert.equal(Model.isWarnReason(reason), true, reason)
  }
  for (const reason of ["none", "", "media-empty", "media-jam"]) {
    assert.equal(Model.isWarnReason(reason), false, reason)
  }
})

test("printerHasWarning yields to a real error on the same printer", () => {
  const both = { state: "idle", stateReasons: ["media-low", "media-jam"] }
  assert.equal(Model.printerHasError(both), true)
  assert.equal(Model.printerHasWarning(both), false)
})

test("printerColor paints a warning amber and an error red", () => {
  const warn = { state: "idle", stateReasons: ["media-low"] }
  const error = { state: "idle", stateReasons: ["media-empty"] }
  assert.equal(Model.printerColor(warn, "#ffffff"), Model.COLOR_WARN)
  assert.equal(Model.printerColor(error, "#ffffff"), Model.COLOR_ERROR)
})

test("barSeverity warns when a printer reports a warning reason", () => {
  const snapshot = {
    cupsd: "running", printers: [], jobs: [],
    summary: { printers: 1, activeJobs: 0, errorPrinters: 0,
               warnPrinters: 1, lowSupplies: 0 }
  }
  assert.equal(Model.barSeverity(snapshot), "warn")
})

test("tooltipText names the worst fault instead of only counting it", () => {
  const snapshot = {
    cupsd: "running",
    printers: [{ name: "Brother@Home", state: "stopped", stateMessage: "",
                 stateReasons: ["media-empty-error"], supplies: [] }],
    jobs: [],
    summary: { printers: 1, activeJobs: 0, errorPrinters: 1,
               warnPrinters: 0, lowSupplies: 0 }
  }
  const text = Model.tooltipText(snapshot)
  assert.match(text, /Brother@Home/)
  assert.match(text, /out of paper/i)
})

test("jobReasonText explains a job that is not moving", () => {
  const job = { id: 7, state: "pending", stateReasons: ["printer-stopped"] }
  assert.match(Model.jobReasonText(job), /printer stopped/i)
})

test("jobReasonText stays quiet while a job is progressing normally", () => {
  for (const reason of ["none", "job-printing", "job-queued", "job-incoming"]) {
    const job = { id: 7, state: "processing", stateReasons: [reason] }
    assert.equal(Model.jobReasonText(job), "", reason)
  }
})

test("jobReasonText handles a job with no reasons at all", () => {
  assert.equal(Model.jobReasonText({ id: 7, state: "pending" }), "")
  assert.equal(Model.jobReasonText(null), "")
})
