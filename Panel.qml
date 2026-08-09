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

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) return decodeURIComponent(value.substring(7))
    return value
  }

  function refresh() {
    // A request arriving mid-flight is coalesced rather than dropped; the
    // in-flight run re-triggers it on completion.
    if (collectProc.running) {
      pendingRefresh = true
      return
    }
    pendingRefresh = false
    loading = true
    collectProc.command = ["python3",
      pathFromUrl(Qt.resolvedUrl("scripts/galley_collect.py")),
      "--threshold", String(root.supplyThreshold)]
    collectProc.running = true
  }

  function handleOutput(raw) {
    root.snapshot = Model.parseSnapshot(raw)
    root.dataVersion++
    root.loading = false
  }

  function selectPrinter(name) {
    root.selectedPrinter = (root.selectedPrinter === name) ? "" : name
  }

  onOpenedChanged: {
    if (opened) refresh()
    else selectedPrinter = ""
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
        if (t === "r" || t === "R") root.refresh()
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
              }
            }
          }
        }
      }
    }
  }
}
