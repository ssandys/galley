# Bar badge — the queue count as an overlay, not inline text

**Date:** 2026-08-09
**Status:** Approved, ready for planning
**Touches:** `Model.js`, `Panel.qml`, `tests/model.test.js`
**Precedent:** `~/.local/share/omarchy/shell/plugins/panels/tailscale/TailscaleIcon.qml:46-64`

## Purpose

Galley's bar entry currently renders as glyph-plus-inline-number —
`Panel.qml:270`, `text: count > 0 ? barIcon + " " + count : barIcon`. This
replaces that with a notification-style badge: a small filled circle overlaid on
the glyph's top-right corner, carrying the same number.

The motivation is legibility at bar scale. An inline `" 3"` competes with the
glyph for the same horizontal run and fights the widget's `fixedWidth`; an
overlay badge consumes no horizontal space and reads at a glance as a count.

This is a presentation change. What the number *means* does not change.

## Scope

**In scope:** the visual form of the bar count, and a pure function in `Model.js`
that decides the badge's text.

**Out of scope, deliberately:**

- The meaning of the count. It stays `summary.activeJobs`.
- Severity signalling. `Model.barSeverity` keeps tinting the glyph red/amber and
  the badge never carries severity, so the two signals stay independent — a red
  glyph with a purple badge reads as "three jobs queued, and something is wrong".
- The slot width. `fixedWidth: Style.space(27)` was sized for `"󰐪 3"` and the
  glyph alone would fit in less, but shrinking it shifts every widget to
  galley's right. That is a bar-layout change nobody asked for. Keeping 27 also
  leaves the badge room inside its own slot.
- The panel body. Only the bar entry changes.

## Behaviour

| Snapshot state | Badge |
|---|---|
| No jobs | Absent |
| 1–9 jobs | Circle showing the exact count |
| 10+ jobs | Circle showing `9+` |
| Missing `summary`, or a null snapshot | Absent |

The badge is always a circle — the count never widens it into a pill. Clamping
at `9+` keeps the geometry constant, so the badge can never overhang the slot
and crowd the neighbouring widget. The exact figure is not lost: `tooltipText`
already renders `2 printers · 12 jobs` on hover.

Severity, meanwhile, continues to reach the bar only as the glyph's colour.

## Design

### Logic in `Model.js`, presentation in `Panel.qml`

Both badge rules — hidden at zero, clamped at `9+` — are pure functions of the
snapshot, so they live in `Model.js`, where `tests/model.test.js` can reach them
without a QML harness. `Panel.qml` gets no branching logic.

```js
var BADGE_MAX = 9

// "" means no badge. Zero jobs is the common case, so the empty string doubles
// as the visibility flag rather than a second exported predicate.
function badgeText(snapshot) {
  var summary = (snapshot && snapshot.summary) || {}
  var count = summary.activeJobs || 0
  if (count <= 0) return ""
  return count > BADGE_MAX ? BADGE_MAX + "+" : String(count)
}
```

Exported alongside `barSeverity` and `tooltipText`.

### Which snapshot it reads

Called as `Model.badgeText(root.statusSnapshot())`, matching the two neighbouring
call sites (`foreground` and `tooltipText`) rather than the raw `root.snapshot`
that the inline count reads today.

This is not a behaviour change. `statusSnapshot()` overrides only `cupsd` and
`error`; every content field — including `summary` — still comes from
`root.snapshot`, and `badgeText` reads neither overridden field. The two
expressions are identical today. Consistency at the call site is the whole
reason, plus room for the badge to react to collector state later without
switching sources.

**Known, preserved discrepancy:** the badge will keep showing retained job
counts while cupsd is asleep, at which point `tooltipText` returns
"CUPS idle, nothing queued". That disagreement already exists between the inline
count and the tooltip and is logged in `docs/FOLLOWUPS.md` under known
behavioural choices. Moving the count into a badge makes it marginally more
visible but does not create it. Fixing it is a separate decision about
`tooltipText`, and is not part of this work.

### The badge item

A child declared after `WidgetButton` in `Panel.qml`, so it stacks above the
button's internal label. Plain `Rectangle`/`Text` accept no mouse events, so the
button's click-to-open, middle-click-to-refresh, and tooltip all keep working
through it — no `MouseArea` may be added to the badge.

Anchoring uses `WidgetButton.labelWidth`, which exists for precisely this; its
own comment reads *"for bar chrome that wants to line up with the text rather
than with the slot it sits in."* The label is `anchors.centerIn: parent`, so the
glyph's right edge sits at `width / 2 + labelWidth / 2`, and the badge straddles
that edge at the glyph's top.

```qml
BorderSurface {
  visible: badgeLabel.text !== ""
  // x / y omitted here on purpose — anchored to the glyph's top-right via
  // button.labelWidth, offsets tuned during implementation. See below.
  width: Math.max(9, button.height * 0.42)
  height: width
  radius: width / 2
  color: Color.accent
  borderSpec: Border.flat(Color.bar.background, 1)

  Text {
    id: badgeLabel
    anchors.centerIn: parent
    text: Model.badgeText(root.statusSnapshot())
    color: Color.background
    font.family: root.fontFamily
    font.bold: true
    font.pixelSize: Math.max(6, parent.height * 0.66)
  }
}
```

Positioning is expressed against `button`'s geometry and `labelWidth`; exact
offsets are tuned by eye during implementation, since the target is "matches the
reference screenshot", not a numeric spec.

No import changes are needed. `Panel.qml` already imports `qs.Ui`
(`BorderSurface`) and `qs.Commons` (`Color`, `Border`, `Style`).

`BorderSurface` with `Border.flat(...)` is lifted from `TailscaleIcon.qml:46-64`
— the same 1px ring in a background colour, which is what separates the badge
from the glyph underneath it instead of letting the two shapes smear together.
Two differences from that precedent:

- **Top-right, not bottom-right.** Tailscale anchors its `!` bottom-right. The
  newer convention in the reference screenshot is top-right, and it reads better
  above a wide glyph.
- **`pixelSize` at 0.66 of the height, not 0.72.** Tailscale's ratio was tuned
  for a single `!`; `9+` is two characters and needs the smaller ratio to stay
  inside the circle.

**Vertical bars:** the y-anchor must key off the glyph's height rather than
`labelWidth`. `Panel.qml` already branches on `root.bar.vertical` for
`fixedWidth`/`fixedHeight`; this follows that existing shape.

### Colour

Fill is `Color.accent` — the omarchy theme's accent token, which is what renders
the badge purple on the current theme and what makes it track a theme switch
with no code change. Text is `Color.background` for contrast against it.

`Color.accent` was chosen over the two alternatives:

- **`Color.bar.active`** is semantically apt for a live count, but falls back to
  `Color.urgent` (`#a55555`, a red) on themes that do not set it — a plain
  three-job queue would read as an alarm.
- **`COLOR_BUSY` from `Model.js`** (`#3b82f6`) would match the panel's
  "printing" dot, but is hardcoded, ignores the theme, and would add a fifth
  Python/JavaScript colour crossing of the kind `docs/FOLLOWUPS.md` already
  flags.

Using a theme token adds no cross-language crossing: `Color.accent` is resolved
by the shell, and `BADGE_MAX` never leaves JavaScript.

## Testing

`tests/model.test.js` gains cases for `badgeText`:

| Input | Expected |
|---|---|
| `summary.activeJobs = 0` | `""` |
| `summary.activeJobs = 1` | `"1"` |
| `summary.activeJobs = 9` | `"9"` |
| `summary.activeJobs = 10` | `"9+"` |
| Snapshot with no `summary` | `""` |
| `null` | `""` |

That is the complete behavioural surface, and all of it is reachable without QML.

The QML side gets no automated test. Galley has no QML harness, and standing one
up to assert the position of a rectangle is not worth its cost. Verification
there is `bin/install` followed by looking at the bar — which is in any case the
only way to confirm the badge lands where the reference screenshot's does.

The existing `bin/test` suite must keep passing unchanged; this work adds no new
cross-language invariant for `tests/test_cross_language.py` to guard.

## Acceptance

- An empty queue shows the bare glyph, no badge.
- A queue with jobs shows a round accent-filled badge on the glyph's top-right,
  ringed so it stays distinct from the glyph.
- A queue over nine jobs shows `9+` in a badge the same size as `1` produces.
- A stopped printer still tints the glyph red, independently of the badge.
- Clicking the widget still opens the panel; middle-click still refreshes; the
  tooltip still appears on hover and still reports the exact job count.
- Neighbouring bar widgets do not shift position relative to before the change.
