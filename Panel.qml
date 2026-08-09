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

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) return decodeURIComponent(value.substring(7))
    return value
  }

  function refresh() {
    if (collectProc.running) return
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

  Component.onCompleted: refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: collectProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleOutput(text)
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
      else { root.open(); root.refresh() }
    }
  }
}
