import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Non-visual: every mutable property, every Process, the poll Timer. Panel.qml
// binds to this and renders; it holds no collector or action state of its own.
//
// Extracted from Panel.qml, which had grown to 775 lines with this state
// machine buried in the first 263 — where it could not be read or reviewed
// without scrolling past layout. In-tree precedent: the sibling colophon
// plugin's Service.qml, split out from the start for this reason.
//
// The seam is narrow on purpose. Panel.qml reads seven properties from here
// (snapshot, dataVersion, cupsdState, collectorError, actionInProgress,
// actionError, supplyThreshold) plus showSupplies, and calls three functions
// (refresh, runAction, statusSnapshot). Everything else below is private
// machinery: `loading`, `previousSnapshot`, `armedSupplies`, `jobWasActive`,
// `pendingRefresh`, `notifyQueue` and `actionExited` have no reader outside
// this file, and that is the point of the split.
Item {
  id: root

  // Injected by Panel.qml. Ui/Panel.qml declares `settings`; this Item does
  // not, so the values must be passed in rather than read from here. The two
  // script paths likewise: Qt.resolvedUrl() resolves against the file it is
  // called from, so Panel.qml resolves them and hands them over.
  property var settings: ({})
  property string collectPath: ""
  property string actionPath: ""
  property bool panelOpen: false

  // Status is reported separately from content. `snapshot` is the
  // last-known-good content (printer cards, queue rows, counts) and is only
  // ever replaced by a "running" collector response — see handleOutput().
  // `cupsdState`/`collectorError` mirror the most recent response verbatim,
  // good or bad, so status-only surfaces (bar glyph color, tooltip, the
  // empty states) always reflect what just happened even while the content
  // underneath is stale.
  property var snapshot: Model.EMPTY_SNAPSHOT
  property int dataVersion: 0
  property string cupsdState: "running"
  property string collectorError: ""

  property string actionInProgress: ""
  property string actionError: ""

  // Private machinery. No reader in Panel.qml.
  property bool loading: false
  property bool actionExited: false
  property bool pendingRefresh: false
  property var previousSnapshot: null
  property var armedSupplies: ({})
  property bool jobWasActive: false
  property var notifyQueue: []

  function settingValue(key, fallback) {
    var value = settings ? settings[key] : undefined
    return (value === undefined || value === null) ? fallback : value
  }

  readonly property int supplyThreshold: settingValue("supplyLowThreshold", 15)
  readonly property bool showSupplies: settingValue("showSupplies", true) === true
  readonly property int openInterval: settingValue("pollIntervalOpenSec", 3)
  readonly property int idleInterval: settingValue("pollIntervalIdleSec", 30)

  // The armed set records no threshold of its own, and Model.supplyRearmed()
  // is relative to the current one -- so after a change, an entry armed under
  // the old threshold can sit above the new arm line and below the new re-arm
  // line at once. Stranded there it clears on neither condition, and it
  // suppresses the very notification a lowered threshold was set to raise.
  // Redefining "low" re-opens the question for every supply, so drop the
  // whole set and let the next poll arm it afresh.
  onSupplyThresholdChanged: root.armedSupplies = ({})

  function notifyOptions() {
    return {
      threshold: root.supplyThreshold,
      notifyJobFailed: settingValue("notifyJobFailed", true) === true,
      notifyPrinterError: settingValue("notifyPrinterError", true) === true,
      notifyJobCompleted: settingValue("notifyJobCompleted", true) === true,
      notifySupplyLow: settingValue("notifySupplyLow", true) === true,
      completedIds: root.snapshot.completedIds || [],
      armedSupplies: root.armedSupplies
    }
  }

  function dispatchNotifications() {
    // One options object for both calls below. The arming condition and the
    // notify condition have to read the same settings within a tick: read
    // separately, a toggle flipped between them could suppress the event and
    // arm the supply in the same pass, losing it until a refill.
    var opts = notifyOptions()
    var events = Model.diffSnapshots(
      root.previousSnapshot, root.snapshot, opts)
    if (events.length > 0) {
      var queued = root.notifyQueue.slice()
      for (var i = 0; i < events.length; i++) queued.push(events[i])
      root.notifyQueue = queued
      sendNextNotification()
    }
    root.armedSupplies = Model.nextArmedSupplies(
      root.armedSupplies, root.snapshot, opts.threshold, opts.notifySupplyLow)
  }

  function sendNextNotification() {
    // One notify-send at a time. Quickshell ignores a command assignment
    // while a Process is running, so firing these in a loop would silently
    // drop everything except the first and the last.
    if (notifyProc.running) return
    if (root.notifyQueue.length === 0) return

    var next = root.notifyQueue[0]
    root.notifyQueue = root.notifyQueue.slice(1)
    notifyProc.command = ["notify-send", "-a", "Galley",
      "-u", next.urgency, "--", next.title, next.message]
    notifyProc.running = true
  }

  Process {
    id: notifyProc
    onRunningChanged: {
      if (notifyProc.running) return
      Qt.callLater(root.sendNextNotification)
    }
  }

  Timer {
    id: pollTimer
    running: true
    repeat: true
    interval: {
      if (root.panelOpen) return root.openInterval * 1000
      var active = root.snapshot.summary
        ? root.snapshot.summary.activeJobs : 0
      return active > 0 ? root.openInterval * 1000 : root.idleInterval * 1000
    }
    onTriggered: root.refresh(true)
  }

  function refresh(fromTimer) {
    // A user-initiated refresh arriving mid-flight is coalesced rather than
    // dropped; the in-flight run re-triggers it on completion. A timer tick
    // is not coalesced: re-firing it immediately would decouple the poll
    // cadence from the configured interval whenever the collector runs
    // slower than it (degrading to back-to-back polling).
    if (collectProc.running) {
      if (fromTimer !== true) pendingRefresh = true
      return
    }
    pendingRefresh = false
    loading = true
    var args = ["python3", root.collectPath,
      "--threshold", String(root.supplyThreshold)]
    if (root.jobWasActive) args.push("--completed")
    collectProc.command = args
    collectProc.running = true
  }

  function statusSnapshot() {
    // Merge the authoritative status fields onto the retained content, for
    // the handful of call sites (bar glyph color, tooltip) that must react
    // to the live cupsd/collector state rather than the last-known-good
    // snapshot's own (possibly stale) `cupsd`/`error` fields. Content
    // fields (summary, jobs, printers) still come from root.snapshot, so a
    // retained error printer or low supply keeps coloring the glyph while
    // cupsd is merely asleep or the collector is erroring.
    var merged = {}
    for (var key in root.snapshot) merged[key] = root.snapshot[key]
    merged.cupsd = root.cupsdState
    merged.error = root.collectorError
    return merged
  }

  function handleOutput(raw) {
    var next = Model.parseSnapshot(raw)
    root.cupsdState = next.cupsd
    root.collectorError = next.error || ""
    root.loading = false
    // A collector error or an asleep cupsd must not destroy good content:
    // only a "running" response replaces the retained snapshot. This is
    // also why dispatchNotifications() lives inside this branch — calling
    // it against an unchanged (prev, snapshot) pair on every erroring poll
    // would replay the same diff and re-fire the same notifications.
    //
    // The two orderings here are load-bearing and must not be rearranged:
    // previousSnapshot is assigned BEFORE snapshot, and dispatchNotifications
    // runs only inside this branch. Swapping either replays or silences
    // notifications, and no test in this repo can see it.
    if (next.cupsd === "running") {
      root.previousSnapshot = root.dataVersion > 0 ? root.snapshot : null
      root.snapshot = next
      root.dataVersion++
      root.jobWasActive = (next.summary ? next.summary.activeJobs : 0) > 0
      root.dispatchNotifications()
    }
  }

  function runAction(verb, target) {
    if (actionInProgress !== "") return
    actionInProgress = verb + ":" + target
    actionError = ""
    actionExited = false
    actionProc.command = ["bash", root.actionPath, verb, target]
    actionProc.running = true
  }

  Process {
    id: actionProc
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: { if (text) root.actionError = text }
    }
    onExited: function (code, status) {
      root.actionExited = true
      if (code !== 0 && root.actionError === "")
        root.actionError = "Action failed with exit code " + code
    }
    onRunningChanged: {
      if (actionProc.running) return
      // Quickshell emits neither exited() nor streamEnded() when a process
      // fails to spawn, so onExited alone would leave actionInProgress set
      // forever and disable every button in the panel. Same failure mode the
      // collectProc handler below guards against.
      if (!root.actionExited && root.actionInProgress !== "")
        root.actionError = "Could not run the action helper"
      root.actionInProgress = ""
      Qt.callLater(root.refresh)
    }
  }

  Process {
    id: collectProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleOutput(text)
    }
    onRunningChanged: {
      if (collectProc.running) return
      // Quickshell does not call streamEnded() when a process fails to
      // spawn, so handleOutput never runs. Clearing here as well is what
      // keeps `loading` from sticking true forever.
      root.loading = false
      if (root.pendingRefresh) Qt.callLater(root.refresh)
    }
  }

  Component.onCompleted: refresh()
}
