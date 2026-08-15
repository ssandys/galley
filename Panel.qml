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

  // Every mutable property, every Process and the poll Timer live in
  // Controller.qml. This file renders and holds view state only: which
  // printer the queue is filtered to, and the theme-derived colors below.
  Controller {
    id: controller
    settings: root.settings
    panelOpen: root.opened
    collectPath: root.pathFromUrl(Qt.resolvedUrl("scripts/galley_collect.py"))
    actionPath: root.pathFromUrl(Qt.resolvedUrl("scripts/galley_action.sh"))
  }

  // View state: the queue filter is a property of what you are looking at,
  // not of the collector, so it stays here.
  property string selectedPrinter: ""

  // Written as an escape rather than a pasted glyph, per c5f83a1 -- a literal
  // astral-plane character gets mangled by tooling that round-trips this file.
  // The ES6 \u{...} form is required here: \u consumes exactly four hex
  // digits, so "\uf042a" would be U+F042 followed by a literal 'a'.
  //
  // U+F042A (nf-md-printer) is the glyph the design spec specifies. c5f83a1
  // switched to U+F02F (nf-fa-print) on live-use feedback; this switches back
  // because F02F reads optically off-centre under the bar's open-panel mark,
  // which Bar.qml centres on the slot and gives no way to shift.
  readonly property string barIcon: "\u{F042A}"
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"

  // Qt.resolvedUrl() resolves against the file it is called from, so the
  // script paths are resolved here and injected into the controller above.
  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) return decodeURIComponent(value.substring(7))
    return value
  }

  function selectPrinter(name) {
    root.selectedPrinter = (root.selectedPrinter === name) ? "" : name
  }

  function visibleJobs() {
    return Model.filterJobs(controller.snapshot.jobs, root.selectedPrinter)
  }

  onOpenedChanged: {
    if (opened) {
      controller.actionError = ""
      controller.refresh()
    } else {
      selectedPrinter = ""
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // The count is no longer inline — it renders as the badge child below.
    text: root.barIcon
    foreground: {
      var severity = Model.barSeverity(controller.statusSnapshot())
      if (severity === "error") return Model.COLOR_ERROR
      if (severity === "warn") return Model.COLOR_WARN
      // Bar chrome convention (WidgetButton's own default, base Ui/Panel,
      // tailscale/Panel.qml): barForeground for the glyph, foreground for
      // panel content. Without this, a transparent bar recolors every
      // neighbouring widget for legibility except this one.
      return root.barForeground
    }
    fixedWidth: root.bar && root.bar.vertical ? -1 : Style.space(27)
    fixedHeight: root.bar && root.bar.vertical ? Style.space(26) : -1
    tooltipText: Model.tooltipText(controller.statusSnapshot())
    onPressed: function (which) {
      if (which === Qt.MiddleButton) { controller.refresh(); return }
      if (root.opened) root.close()
      // No explicit refresh here: onOpenedChanged covers it, and also covers
      // opens triggered via IPC or a keybind, which never reach onPressed.
      else root.open()
    }

    // Declared inside the button so it paints above the button's own label,
    // and so it can anchor to the painted glyph rather than to the slot.
    // No MouseArea here on purpose: a bare Rectangle/Text consumes no mouse
    // events, so click-to-open, middle-click-refresh, and the tooltip all
    // keep working straight through the badge.
    BorderSurface {
      visible: badgeLabel.text !== ""
      width: Math.max(9, button.fontSize * 0.85)
      height: width
      radius: width / 2
      color: Color.accent
      // The 1px ring separates the badge from the glyph underneath; without
      // it the two shapes smear together. Deliberately Color.background, not
      // Color.bar.background: the latter resolves through the theme's
      // bar.background-alpha, so on a translucent bar the ring itself would
      // go translucent and reintroduce the smear the ring exists to prevent.
      // Color.background is the foundational, always-opaque token — the same
      // one badgeLabel below uses for its text.
      borderSpec: Border.flat(Color.background, 1)

      // WidgetButton centers its label, and exposes labelWidth precisely so
      // bar chrome can line up with the painted text instead of the slot.
      // Half the label width right of center is the glyph's right edge; half
      // a font-size above center is its top. The badge straddles that corner.
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.horizontalCenterOffset: button.labelWidth / 2
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: -button.fontSize * 0.5

      Text {
        id: badgeLabel
        anchors.centerIn: parent
        text: Model.badgeText(controller.statusSnapshot())
        color: Color.background
        font.family: root.fontFamily
        font.bold: true
        // 0.66, not the 0.72 TailscaleIcon.qml uses — that was tuned for a
        // single "!", and "9+" is two characters.
        font.pixelSize: Math.max(6, parent.height * 0.66)
        // Matches WidgetButton's own label — this is the smallest text the
        // widget draws, where hinting matters most.
        renderType: Text.NativeRendering
      }
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
          controller.actionError = ""
          controller.refresh()
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
            text: root.barIcon + "  Galley"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }

          Text {
            text: {
              var s = controller.snapshot.summary
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
            onClicked: controller.refresh()
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        // ── Printer cards ──
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Repeater {
            model: controller.snapshot.printers || []

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
                    model: controller.showSupplies ? (modelData.supplies || []) : []
                    delegate: Text {
                      required property var modelData
                      text: Model.supplyLabel(modelData)
                      color: Model.supplyColor(modelData, controller.supplyThreshold, root.dim)
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
                    foreground: modelData.state === "stopped" ? Model.COLOR_OK : root.fg
                    tooltipText: modelData.state === "stopped"
                      ? "Resume printing on this queue"
                      : "Stop this queue; jobs stay pending"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: controller.runAction(
                      modelData.state === "stopped" ? "resume" : "pause",
                      modelData.name)
                  }

                  Button {
                    visible: modelData.queuedJobCount > 0
                    text: "cancel all"
                    foreground: Model.COLOR_ERROR
                    tooltipText: "Cancel every job you own on this queue"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: controller.runAction("cancel-all", modelData.name)
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

        // ── Stale indicators ──
        // Asleep and error both retain content instead of blanking the
        // panel, but they read differently on purpose: an idle cupsd
        // (IdleExitTimeout) is ordinary, expected behavior and must stay
        // calm — dim, no error styling, per the spec's "no error styling"
        // rule for asleep. A collector error is a real fault and keeps the
        // same red styling as the no-content error state below. Only ever
        // shown alongside retained content (printers.length > 0), so
        // neither competes with the four empty states below: those all
        // require printers.length === 0 except "No active jobs", which
        // carries no cupsdState requirement of its own.
        Text {
          visible: controller.cupsdState === "asleep" && (controller.snapshot.printers || []).length > 0
          Layout.fillWidth: true
          text: "CUPS idle — showing last known state"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: controller.cupsdState === "error" && (controller.snapshot.printers || []).length > 0
          Layout.fillWidth: true
          text: "Showing last known data — " + (controller.collectorError || "collector error")
          color: Model.COLOR_ERROR
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        // ── Empty and error states ──
        // Mutually exclusive: the first three are keyed on cupsdState, which
        // is always exactly one of "asleep"/"error"/"running", and all three
        // require an empty retained printer list; "No active jobs" is the
        // only one that can be visible when printers are present, so at most
        // one of the four is ever visible together.
        Text {
          visible: controller.cupsdState === "asleep" && (controller.snapshot.printers || []).length === 0
          Layout.fillWidth: true
          text: "CUPS idle — nothing queued"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: controller.cupsdState === "error" && (controller.snapshot.printers || []).length === 0
          Layout.fillWidth: true
          text: controller.collectorError || "Collector failed"
          color: Model.COLOR_ERROR
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: (controller.snapshot.printers || []).length > 0
                   && root.visibleJobs().length === 0
          Layout.fillWidth: true
          text: "No active jobs"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          visible: controller.cupsdState === "running" && (controller.snapshot.printers || []).length === 0
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
              model: root.visibleJobs()

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
                  // Accent, not a semantic error/warning colour: a printing job
                  // is normal activity, and this follows the user's theme.
                  color: modelData.state === "processing" ? Color.accent : root.dim
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
                  foreground: modelData.mine ? Model.COLOR_ERROR : root.dim
                  // _user_cancel_any is 0, so only the owner may cancel.
                  enabled: modelData.mine && controller.actionInProgress === ""
                  opacity: enabled ? 1.0 : 0.4
                  tooltipText: modelData.mine
                    ? "Cancel this job"
                    : "Owned by " + modelData.user + " — you cannot cancel it"
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(6)
                  verticalPadding: Style.space(2)
                  onClicked: controller.runAction("cancel-job", String(modelData.id))
                }
              }
            }
          }
        }

        Text {
          visible: controller.actionError !== ""
          Layout.fillWidth: true
          text: controller.actionError
          color: Model.COLOR_ERROR
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
