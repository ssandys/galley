import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "."
import "Model.js" as Model

Panel {
  id: root
  moduleName: "ssandys.galley"
  ipcTarget: "ssandys.galley"

  // Every mutable property, every Process and the poll Timer live in
  // Controller.qml. This file renders and holds view state only: which
  // printer the queue is filtered to, and the theme-derived colors below.
  // NOT instantiated: Controller.qml is a singleton, so this widget registers
  // interest in the one shared instance rather than owning its own. The bar
  // makes a widget per bar surface and a surface per monitor, so an instance
  // here meant a CUPS poll and a notify-send per monitor -- one printer event
  // raising two notifications on a two-monitor setup.
  //
  // wasOpen goes out with detach() because a surface destroyed while its panel
  // is open would otherwise leave openPanels counting a panel that is gone.
  Component.onCompleted: Controller.attach({
    collectPath: root.pathFromUrl(Qt.resolvedUrl("scripts/galley_collect.py")),
    actionPath: root.pathFromUrl(Qt.resolvedUrl("scripts/galley_action.sh"))
  })
  // NOT in onCompleted: the bar sets `settings` from its Loader's onLoaded,
  // after this item has completed, so at completion it is still the empty
  // default. This fires for that injection and for every later edit (#36).
  onSettingsChanged: Controller.configure(root.settings)
  Component.onDestruction: Controller.detach({ wasOpen: root.opened })

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
  readonly property color fg: root.bar ? root.bar.foreground : Commons.Color.foreground
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
    return Model.filterJobs(Controller.snapshot.jobs, root.selectedPrinter)
  }

  onOpenedChanged: {
    // FOLDED into the existing handler, not added beside it. QML rejects a
    // duplicate handler on one component and the component then fails to
    // instantiate with NOTHING in the journal -- measured on colophon, where
    // the widget silently did not exist, attach() never ran, and the poll this
    // change deduplicates simply never happened at all.
    Controller.setPanelOpen(!root.opened, root.opened)
    if (opened) {
      Controller.actionError = ""
      Controller.refresh()
    } else {
      selectedPrinter = ""
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // No openPanelIndicatorWidth hint on purpose. Bar.qml would accept one, and
  // panels/power sets it, but hinting the mark to the glyph's ink shortens it
  // from 15px to ~12px without moving it -- tried on a dev deploy and rejected
  // on looks. The mark's length is a separate question from its alignment.

  // BarIconButton, not WidgetButton: it paints the glyph through OpticalGlyph,
  // which centres on the painted ink instead of the monospace advance cell.
  // Every Nerd Font icon overflows that cell to the right (U+F042A: 11px of ink
  // in a 7.8px cell), so a raw WidgetButton label sits ~1.6px right of its slot
  // centre while Bar.qml centres the open-panel mark on the slot itself -- the
  // misalignment in #19, measured at 2.5px on a 1.6x display. WidgetButton is
  // for text labels; every other icon-only widget in the bar (audio, power,
  // network, tray, ...) already uses BarIconButton. It extends WidgetButton, so
  // bar/text/foreground/tooltipText/onPressed carry over unchanged.
  //
  // fixedWidth and fixedHeight are deliberately absent now: BarIconButton sets
  // them from Style.bar.iconSlot, whose default is the same 27 this hardcoded --
  // except it honours a theme's icon-slot, icon-canvas and icon-font tokens,
  // which the hardcoded value silently ignored.
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // The count is no longer inline — it renders as the badge child below.
    text: root.barIcon
    foreground: {
      var severity = Model.barSeverity(Controller.statusSnapshot())
      if (severity === "error") return Model.COLOR_ERROR
      if (severity === "warn") return Model.COLOR_WARN
      // Bar chrome convention (WidgetButton's own default, base Ui/Panel,
      // tailscale/Panel.qml): barForeground for the glyph, foreground for
      // panel content. Without this, a transparent bar recolors every
      // neighbouring widget for legibility except this one.
      return root.barForeground
    }
    tooltipText: Model.tooltipText(Controller.statusSnapshot())
    onPressed: function (which) {
      if (which === Qt.MiddleButton) { Controller.refresh(); return }
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
      color: Commons.Color.accent
      // The 1px ring separates the badge from the glyph underneath; without
      // it the two shapes smear together. Deliberately Commons.Color.background, not
      // Commons.Color.bar.background: the latter resolves through the theme's
      // bar.background-alpha, so on a translucent bar the ring itself would
      // go translucent and reintroduce the smear the ring exists to prevent.
      // Commons.Color.background is the foundational, always-opaque token — the same
      // one badgeLabel below uses for its text.
      borderSpec: Border.flat(Commons.Color.background, 1)

      // glyphPaintedWidth, not labelWidth: BarIconButton hides WidgetButton's
      // own label (labelVisible: false) and paints through OpticalGlyph, so
      // labelWidth is 0 here and the badge would collapse onto the glyph's
      // centre. glyphPaintedWidth is the ink width, which is what this wants
      // anyway -- half of it right of centre is the painted glyph's right edge;
      // half a font-size above centre is its top. The badge straddles that
      // corner.
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.horizontalCenterOffset: button.glyphPaintedWidth / 2
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: -button.fontSize * 0.5

      Text {
        textFormat: Text.PlainText
        id: badgeLabel
        anchors.centerIn: parent
        text: Model.badgeText(Controller.statusSnapshot())
        color: Commons.Color.background
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
          Controller.actionError = ""
          Controller.refresh()
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
            textFormat: Text.PlainText
            text: root.barIcon + "  Galley"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }

          Text {
            textFormat: Text.PlainText
            text: {
              var s = Controller.snapshot.summary
              if (!s) return ""
              return s.printers + " printers · " + s.activeJobs + " jobs"
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Button {
            // The header, not a printer card: this is a global action, and the
            // card rows are per-printer. Refresh, the only other global action,
            // already lives here.
            text: "Web UI"
            foreground: root.fg
            tooltipText: "Open the CUPS web interface at localhost:631"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            enabled: Controller.actionInProgress === ""
            opacity: enabled ? 1.0 : 0.4
            // web-ui takes no target, but runAction's signature is
            // (verb, target) and galley_action.sh ignores a stray one.
            onClicked: Controller.runAction("web-ui", "")
          }

          Button {
            text: "Refresh"
            foreground: root.fg
            tooltipText: "Refresh printers and queue"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: Controller.refresh()
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        // ── Printer cards ──
        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Repeater {
            model: Controller.snapshot.printers || []

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
                    textFormat: Text.PlainText
                    text: "●"
                    color: Model.printerColor(modelData, root.fg)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                  }

                  Text {
                    textFormat: Text.PlainText
                    text: modelData.name + (modelData.isDefault ? "  ★" : "")
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                  }

                  Text {
                    textFormat: Text.PlainText
                    // Model.reasonText, not stateMessage-or-state: many CUPS
                    // backends leave printer-state-message empty, and this line
                    // then showed the bare word "stopped" while the cause sat
                    // unread in stateReasons. Reporting a fault without naming
                    // it sends the user looking in the wrong place.
                    text: Model.reasonText(modelData)
                    color: Model.printerHasError(modelData) ? Model.COLOR_ERROR
                         : Model.printerHasWarning(modelData) ? Model.COLOR_WARN
                         : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                  }
                }

                Text {
                  textFormat: Text.PlainText
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
                    model: Controller.showSupplies ? (modelData.supplies || []) : []
                    delegate: Text {
                      textFormat: Text.PlainText
                      required property var modelData
                      text: Model.supplyLabel(modelData)
                      color: Model.supplyColor(modelData, Controller.supplyThreshold, root.dim)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Item { Layout.fillWidth: true }

                  Text {
                    textFormat: Text.PlainText
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
                    enabled: Controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: Controller.runAction(
                      modelData.state === "stopped" ? "resume" : "pause",
                      modelData.name)
                  }

                  Button {
                    // Hidden rather than disabled on the printer that already
                    // is the default: a disabled button invites a click and
                    // explains nothing, while an absent one reads correctly --
                    // the star beside the name already says which printer this
                    // is. `isDefault` comes from the snapshot, which now
                    // resolves the CLIENT default, so this button's effect is
                    // visible on the next poll. See the design spec.
                    visible: !modelData.isDefault
                    text: "set default"
                    foreground: root.fg
                    tooltipText: "Make this your default printer"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: Controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: Controller.runAction("set-default", modelData.name)
                  }

                  Button {
                    // Same rule as the per-job cancel below: cupsd runs with
                    // _user_cancel_any=0, so `cancel -a` clears only your own
                    // jobs. Ungated, this offered to empty a shared queue and
                    // then reported the rest as stderr. The card knows only
                    // queuedJobCount, so ownership comes from the snapshot.
                    readonly property bool mineHere:
                      Model.hasCancellableJobs(Controller.snapshot.jobs,
                                               modelData.name)
                    visible: modelData.queuedJobCount > 0
                    text: "cancel all"
                    foreground: mineHere ? Model.COLOR_ERROR : root.dim
                    // Two distinct reasons to be disabled, and they are not the
                    // same problem: nothing queued, versus a queue that is all
                    // someone else's.
                    tooltipText: mineHere
                      ? "Cancel every job you own on this queue"
                      : "No jobs of yours on this queue — you cannot cancel "
                        + "another user's"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: mineHere && Controller.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: Controller.runAction("cancel-all", modelData.name)
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
            textFormat: Text.PlainText
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
          textFormat: Text.PlainText
          visible: Controller.cupsdState === "asleep" && (Controller.snapshot.printers || []).length > 0
          Layout.fillWidth: true
          text: "CUPS idle — showing last known state"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          textFormat: Text.PlainText
          visible: Controller.cupsdState === "error" && (Controller.snapshot.printers || []).length > 0
          Layout.fillWidth: true
          text: "Showing last known data — " + (Controller.collectorError || "collector error")
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
          textFormat: Text.PlainText
          visible: Controller.cupsdState === "asleep" && (Controller.snapshot.printers || []).length === 0
          Layout.fillWidth: true
          text: "CUPS idle — nothing queued"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          textFormat: Text.PlainText
          visible: Controller.cupsdState === "error" && (Controller.snapshot.printers || []).length === 0
          Layout.fillWidth: true
          text: Controller.collectorError || "Collector failed"
          color: Model.COLOR_ERROR
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          textFormat: Text.PlainText
          visible: (Controller.snapshot.printers || []).length > 0
                   && root.visibleJobs().length === 0
          Layout.fillWidth: true
          text: "No active jobs"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          textFormat: Text.PlainText
          visible: Controller.cupsdState === "running" && (Controller.snapshot.printers || []).length === 0
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
                  textFormat: Text.PlainText
                  text: String(modelData.id)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  Layout.preferredWidth: Style.space(30)
                }

                Text {
                  textFormat: Text.PlainText
                  text: Model.jobGlyph(modelData.state)
                  // Accent, not a semantic error/warning colour: a printing job
                  // is normal activity, and this follows the user's theme.
                  color: modelData.state === "processing" ? Commons.Color.accent : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  // PlainText on every Text, this one first: a job name is
                  // whatever its submitter typed, and the default AutoText
                  // rendered <img src="https://..."> by fetching it, so opening
                  // the panel told a stranger your address. Elision is not
                  // sanitizing. Guarded by tests/test_plain_text.py.
                  textFormat: Text.PlainText
                  text: modelData.name
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                  Layout.fillWidth: true
                }

                Text {
                  textFormat: Text.PlainText
                  // Why this job is not moving. job-state-reasons was collected
                  // and normalized from the start and then read by nothing, so a
                  // stalled job looked exactly like a queued one. Present only
                  // when there is something to say: a queue where every row
                  // carries text teaches you to stop reading the column, and
                  // then the row that matters gets skipped with the rest.
                  //
                  // Amber for every reason, including the format errors: this is
                  // the job's problem, not the printer's, and red here would
                  // compete with the printer cards above for the same alarm.
                  readonly property string reason: Model.jobReasonText(modelData)
                  visible: reason !== ""
                  text: reason
                  color: Model.COLOR_WARN
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                  // Capped rather than fillWidth: the job name above already
                  // takes the slack, and a long vendor reason must not push the
                  // page count and cancel button off the row.
                  Layout.maximumWidth: Style.space(70)
                }

                Text {
                  textFormat: Text.PlainText
                  visible: root.selectedPrinter === ""
                  text: modelData.printer
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  textFormat: Text.PlainText
                  // How long this job has been waiting. time-at-creation was
                  // collected and normalized to createdAt from the start and
                  // then read by nothing, so a job pending forty seconds and a
                  // job pending forty minutes drew the same row -- and age is
                  // the cheapest answer there is to "is this stuck, or did I
                  // just hit print?".
                  //
                  // Blank under a minute and blank without a clock, same rule
                  // as the reason column above: a queue where every row carries
                  // text teaches you to stop reading the column, and then the
                  // row that matters gets skipped with the rest.
                  readonly property string age:
                    Model.formatAge(modelData.createdAt, Controller.nowSeconds)
                  visible: age !== ""
                  text: age
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  textFormat: Text.PlainText
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
                  enabled: modelData.mine && Controller.actionInProgress === ""
                  opacity: enabled ? 1.0 : 0.4
                  tooltipText: modelData.mine
                    ? "Cancel this job"
                    : "Owned by " + modelData.user + " — you cannot cancel it"
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(6)
                  verticalPadding: Style.space(2)
                  onClicked: Controller.runAction("cancel-job", String(modelData.id))
                }
              }
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          visible: Controller.actionError !== ""
          Layout.fillWidth: true
          text: Controller.actionError
          color: Model.COLOR_ERROR
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          horizontalAlignment: Text.AlignHCenter
        }

        Text {
          textFormat: Text.PlainText
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
