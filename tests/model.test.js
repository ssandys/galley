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

test("tooltipText summarizes printers and jobs", () => {
  const text = Model.tooltipText(SNAPSHOT)
  assert.match(text, /2 printers/)
  assert.match(text, /2 jobs/)
})

test("tooltipText reports a sleeping daemon plainly", () => {
  const text = Model.tooltipText({ cupsd: "asleep", printers: [], jobs: [],
    summary: { printers: 0, activeJobs: 0, errorPrinters: 0, lowSupplies: 0 } })
  assert.match(text, /idle/i)
})
