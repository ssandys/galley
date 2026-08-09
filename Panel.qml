import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "ssandys.galley"
  ipcTarget: "ssandys.galley"

  property var snapshot: Model.EMPTY_SNAPSHOT
  property int dataVersion: 0
  property bool loading: false
  property string selectedPrinter: ""

  readonly property string barIcon: "󰐪"
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"

  function settingValue(key, fallback) {
    var value = settings ? settings[key] : undefined
    return (value === undefined || value === null) ? fallback : value
  }

  readonly property int supplyThreshold: settingValue("supplyLowThreshold", 15)
  readonly property bool showSupplies: settingValue("showSupplies", true) === true

  property bool pendingRefresh: false

  property var previousSnapshot: null
  property var armedSupplies: ({})
  property bool jobWasActive: false

  readonly property int openInterval: settingValue("pollIntervalOpenSec", 3)
  readonly property int idleInterval: settingValue("pollIntervalIdleSec", 30)

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

  function updateArmedSupplies() {
    var next = {}
    for (var key in root.armedSupplies) next[key] = root.armedSupplies[key]

    var printers = root.snapshot.printers || []
    for (var p = 0; p < printers.length; p++) {
      var supplies = printers[p].supplies || []
      for (var s = 0; s < supplies.length; s++) {
        var key2 = printers[p].name + "/" + supplies[s].name
        if (supplies[s].level < root.supplyThreshold) next[key2] = true
        else if (Model.supplyRearmed(supplies[s].level, root.supplyThreshold))
          delete next[key2]
      }
    }
    root.armedSupplies = next
  }

  property var notifyQueue: []

  function dispatchNotifications() {
    var events = Model.diffSnapshots(
      root.previousSnapshot, root.snapshot, notifyOptions())
    if (events.length > 0) {
      var queued = root.notifyQueue.slice()
      for (var i = 0; i < events.length; i++) queued.push(events[i])
      root.notifyQueue = queued
      sendNextNotification()
    }
    updateArmedSupplies()
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
      if (root.opened) return root.openInterval * 1000
      var active = root.snapshot.summary
        ? root.snapshot.summary.activeJobs : 0
      return active > 0 ? root.openInterval * 1000 : root.idleInterval * 1000
    }
    onTriggered: root.refresh(true)
  }

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) return decodeURIComponent(value.substring(7))
    return value
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
    var args = ["python3",
      pathFromUrl(Qt.resolvedUrl("scripts/galley_collect.py")),
      "--threshold", String(root.supplyThreshold)]
    if (root.jobWasActive) args.push("--completed")
    collectProc.command = args
    collectProc.running = true
  }

  function handleOutput(raw) {
    var next = Model.parseSnapshot(raw)
    root.previousSnapshot = root.dataVersion > 0 ? root.snapshot : null
    root.snapshot = next
    root.dataVersion++
    root.loading = false
    root.jobWasActive = (next.summary ? next.summary.activeJobs : 0) > 0
    root.dispatchNotifications()
  }

  function selectPrinter(name) {
    root.selectedPrinter = (root.selectedPrinter === name) ? "" : name
  }

  function visibleJobs() {
    return Model.filterJobs(root.snapshot.jobs, root.selectedPrinter)
  }

  property string actionInProgress: ""
  property string actionError: ""
  property bool actionExited: false

  function runAction(verb, target) {
    if (actionInProgress !== "") return
    actionInProgress = verb + ":" + target
    actionError = ""
    actionExited = false
    actionProc.command = ["bash",
      pathFromUrl(Qt.resolvedUrl("scripts/galley_action.sh")), verb, target]
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
      // collectProc handler above guards against.
      if (!root.actionExited && root.actionInProgress !== "")
        root.actionError = "Could not run the action helper"
      root.actionInProgress = ""
      Qt.callLater(root.refresh)
    }
  }

  onOpenedChanged: {
    if (opened) {
      actionError = ""
      refresh()
    } else {
      selectedPrinter = ""
    }
  }

  Component.onCompleted: refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

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

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: {
      var count = root.snapshot.summary ? root.snapshot.summary.activeJobs : 0
      return count > 0 ? root.barIcon + " " + count : root.barIcon
    }
    foreground: {
      var severity = Model.barSeverity(root.snapshot)
      if (severity === "error") return "#ef4444"
      if (severity === "warn") return "#eab308"
      return root.fg
    }
    fixedWidth: root.bar && root.bar.vertical ? -1 : Style.space(27)
    fixedHeight: root.bar && root.bar.vertical ? Style.space(26) : -1
    tooltipText: Model.tooltipText(root.snapshot)
    onPressed: function (which) {
      if (which === Qt.MiddleButton) { root.refresh(); return }
      if (root.opened) root.close()
      // No explicit refresh here: onOpenedChanged covers it, and also covers
      // opens triggered via IPC or a keybind, which never reach onPressed.
      else root.open()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(460))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: {
        if (root.selectedPrinter !== "") root.selectedPrinter = ""
        else root.close()
      }
      onTextKey: function (t) {
        if (t === "r" || t === "R") {
          root.actionError = ""
          root.refresh()
        }
      }

      ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(10)

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Text {
            text: "󰐪  Galley"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }

          Text {
            text: {
              var s = root.snapshot.summary
              if (!s) return ""
              return s.printers + " printers · " + s.activeJobs + " jobs"
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Button {
            text: "Refresh"
            foreground: root.fg
            tooltipText: "Refresh printers and queue"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: root.refresh()
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        // ── Printer cards ──
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Repeater {
            model: root.dataVersion >= 0 ? (root.snapshot.printers || []) : []

            delegate: BorderSurface {
              required property var modelData
              Layout.fillWidth: true
              radius: Style.cornerRadius
              padding: Style.space(8)
              color: root.selectedPrinter === modelData.name
                ? Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.10)
                : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.055)
              borderSpec: root.selectedPrinter === modelData.name
                ? Border.flat(Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.35), 1)
                : Border.flat(Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.05), 1)
              implicitHeight: cardBody.implicitHeight + contentTopInset + contentBottomInset

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.selectPrinter(modelData.name)
              }

              ColumnLayout {
                id: cardBody
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: parent.contentTopInset
                anchors.leftMargin: parent.contentLeftInset
                anchors.rightMargin: parent.contentRightInset
                anchors.bottomMargin: parent.contentBottomInset
                spacing: Style.space(3)

                RowLayout {
                  Layout.fillWidth: true
                  spacing: Style.space(6)

                  Text {
                    text: "●"
                    color: Model.printerColor(modelData, root.fg)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                  }

                  Text {
                    text: modelData.name + (modelData.isDefault ? "  ★" : "")
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                  }

                  Text {
                    text: modelData.stateMessage || modelData.state
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Text {
                  visible: text !== ""
                  text: {
                    var parts = []
                    if (modelData.info) parts.push(modelData.info)
                    if (modelData.location) parts.push(modelData.location)
                    return parts.join(" · ")
                  }
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                }

                RowLayout {
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  spacing: Style.space(8)

                  Repeater {
                    model: root.showSupplies ? (modelData.supplies || []) : []
                    delegate: Text {
                      required property var modelData
                      text: Model.supplyLabel(modelData)
                      color: Model.supplyColor(modelData, root.supplyThreshold, root.dim)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Item { Layout.fillWidth: true }

                  Text {
                    text: modelData.queuedJobCount === 1
                      ? "1 job" : modelData.queuedJobCount + " jobs"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                RowLayout {
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  Layout.topMargin: Style.space(2)
                  spacing: Style.space(4)

                  Button {
                    text: modelData.state === "stopped" ? "resume" : "pause"
                    foreground: modelData.state === "stopped" ? "#22c55e" : root.fg
                    tooltipText: modelData.state === "stopped"
                      ? "Resume printing on this queue"
                      : "Stop this queue; jobs stay pending"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: root.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: root.runAction(
                      modelData.state === "stopped" ? "resume" : "pause",
                      modelData.name)
                  }

                  Button {
                    visible: modelData.queuedJobCount > 0
                    text: "cancel all"
                    foreground: "#ef4444"
                    tooltipText: "Cancel every job you own on this queue"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: root.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: root.runAction("cancel-all", modelData.name)
                  }

                  Item { Layout.fillWidth: true }
                }
              }
            }
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Text {
            text: root.selectedPrinter === ""
              ? "QUEUE" : "QUEUE · " + root.selectedPrinter
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            Layout.fillWidth: true
          }

          Button {
            visible: root.selectedPrinter !== ""
            text: "clear ✕"
            foreground: root.dim
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(2)
            onClicked: root.selectedPrinter = ""
          }
        }

        // ── Empty and error states ──
        Text {
          visible: root.snapshot.cupsd === "asleep"
          Layout.fillWidth: true
          text: "CUPS idle — nothing queued"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: root.snapshot.cupsd === "error"
          Layout.fillWidth: true
          text: root.snapshot.error || "Collector failed"
          color: "#ef4444"
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: root.snapshot.cupsd === "running"
                   && (root.snapshot.printers || []).length > 0
                   && root.visibleJobs().length === 0
          Layout.fillWidth: true
          text: "No active jobs"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: root.snapshot.cupsd === "running" && (root.snapshot.printers || []).length === 0
          Layout.fillWidth: true
          text: "No printers configured"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        // ── Queue ──
        Flickable {
          id: queueView
          visible: root.visibleJobs().length > 0
          Layout.fillWidth: true
          implicitHeight: Math.min(queueColumn.implicitHeight, Style.space(320))
          contentHeight: queueColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          ColumnLayout {
            id: queueColumn
            width: queueView.width
            spacing: Style.space(2)

            Repeater {
              model: root.dataVersion >= 0 ? root.visibleJobs() : []

              delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(6)

                Text {
                  text: String(modelData.id)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  Layout.preferredWidth: Style.space(30)
                }

                Text {
                  text: Model.jobGlyph(modelData.state)
                  color: modelData.state === "processing" ? "#3b82f6" : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  text: modelData.name
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }

                Text {
                  visible: root.selectedPrinter === ""
                  text: modelData.printer
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  text: modelData.pages
                    ? modelData.pages + "pg" : Model.formatSize(modelData.sizeKb)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Button {
                  text: "✕"
                  foreground: modelData.mine ? "#ef4444" : root.dim
                  // _user_cancel_any is 0, so only the owner may cancel.
                  enabled: modelData.mine && root.actionInProgress === ""
                  opacity: enabled ? 1.0 : 0.4
                  tooltipText: modelData.mine
                    ? "Cancel this job"
                    : "Owned by " + modelData.user + " — you cannot cancel it"
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(6)
                  verticalPadding: Style.space(2)
                  onClicked: root.runAction("cancel-job", String(modelData.id))
                }
              }
            }
          }
        }

        Text {
          visible: root.actionError !== ""
          Layout.fillWidth: true
          text: root.actionError
          color: "#ef4444"
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          Layout.fillWidth: true
          text: "r refreshes · esc clears filter, then closes"
          color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.3)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }
      }
    }
  }
}
