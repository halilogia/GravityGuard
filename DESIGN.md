---
name: GravityGuard Design System
version: 1.0.0
theme:
  mode: dark
  palette:
    canvas: "#0b1120"
    surface: "#111a2e"
    surfaceHover: "#18233b"
    borderSubtle: "#1f2a41"
    primaryAccent: "#38bdf8"
    textMain: "#f8fafc"
    textMuted: "#94a3b8"
    success: "#10b981"
    warning: "#f59e0b"
    danger: "#ef4444"
    info: "#c084fc"
typography:
  family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  mono: '"SF Mono", Consolas, "Courier New", monospace'
  sizes:
    micro: 8px
    caption: 9px
    body: 11px
    label: 10px
    title: 13px
    hero: 18px
  numbers: tabular-nums
spacing:
  unit: 4px
  scale: [4, 8, 12, 16, 24, 32]
radii:
  sm: 4px
  md: 8px
  lg: 12px
---

# Design Specification — GravityGuard

Single source of truth for the Live Monitor webview and every surface the extension owns.
When code and this file disagree, this file wins until it is amended.

## 1. Visual Atmosphere & Philosophy

**Calm instrument, not a dashboard.**

GravityGuard sits inside the editor sidebar for hours. It must read like a precision
instrument in a dim control room: dark slate canvas, thin borders, dense but breathable
type, and colour used only as signal — never decoration.

Principles:

1. **Silence by default.** Neutral surfaces carry the layout. Accent appears only on the
   one actionable element of the current view.
2. **Signal over ornament.** Every hue maps to a state: cyan = active/info, green = pass,
   amber = pending/risk, red = violation, purple = knowledge. No hue without meaning.
3. **Density with rhythm.** 11px body, 4px spacing scale, 8px section padding. Tight, but
   never touching — the sidebar is narrow, so vertical rhythm replaces horizontal air.
4. **Editor-native.** Colours resolve through `--vscode-*` variables first, with the
   palette above as fallback. The panel must never fight the user's theme.
5. **Numbers are data.** All counts, scores, durations and line references use
   `font-variant-numeric: tabular-nums` so columns never jitter while streaming.

Atmospheric reference: a heads-up display at low brightness — legible at a glance,
invisible when ignored.

## 2. Component Guidelines

### Surfaces

| Token | Value | Use |
| --- | --- | --- |
| `canvas` | `#0b1120` | Body background |
| `surface` | `#111a2e` | Cards, panels, expanded rows |
| `surfaceHover` | `#18233b` | Row and button hover |
| `borderSubtle` | `#1f2a41` | 1px separators, card outlines |

Cards: 1px `borderSubtle`, `radius.md`, 8px padding, no shadow. Elevation is expressed by
border contrast, not blur.

### Typography

- Titles: 13px / 600 / `textMain`.
- Body: 11px / 400 / 1.45 line-height.
- Labels and badges: 9–10px / 600 / uppercase tracking `0.04em` / `textMuted`.
- Rule IDs, diffs, paths: `mono`, 8.5–10px.
- Never more than three sizes in one card.

### Status language

- Badge = pill, 9px, `radius.sm`, background `color @ 20% alpha`, text `color`.
- Pass / fail / pending always pair colour with a word or icon — colour alone is not a label.
- Progress and score bars: 4px height, `radius.sm`, track `surface`, fill = state colour.

### Buttons & controls

- Height 24px, padding `0 10px`, `radius.sm`, 10px label.
- Default: transparent background, `borderSubtle` border, `textMuted` text.
- Hover: `surfaceHover` background, `textMain` text.
- Primary action: `primaryAccent` border and text at 15% background tint.
- Destructive action: `danger` only, never filled solid.
- Focus: 1px `primaryAccent` outline, offset 2px. Never remove focus rings.

### Tabs

- 10px labels, 6px vertical padding, bottom 2px underline in `primaryAccent` when active.
- Inactive tabs are `textMuted`; counts render as badges, not parenthetical text.

### Tables & lists

- Row height 26px minimum, 6px horizontal padding, separators `borderSubtle` only.
- Numeric columns right-aligned with tabular figures.
- Truncate long rule IDs and paths with ellipsis; expose full text via `title`.

### Motion

- 120ms `ease-out` for hover, tab and expand transitions.
- No entrance animations, no spinners longer than 400ms without text.
- Respect `prefers-reduced-motion`: collapse all transitions to 0ms.

## 3. Do's & Don'ts

**Do**

- Resolve colour through `--vscode-*` first, palette second.
- Keep one primary action per view.
- Pair every colour signal with text or an icon.
- Use the 4px scale for every margin, gap and padding.
- Verify contrast at `textMuted` on `surface` (≥ 4.5:1) before shipping new text.
- Reuse `styles/base.ts` tokens; add new sections under `src/webview/styles/`.

**Don't**

- Don't introduce a new hex value outside this palette without amending this file.
- Don't use gradients, glow, drop shadows, or rounded corners above `radius.lg`.
- Don't fill destructive buttons or use red for anything but a real violation.
- Don't animate layout properties (`width`, `height`, `top`) — transform and opacity only.
- Don't render raw JSON, stack traces or YAML in the default view; summarise and expand.
- Don't hardcode font sizes below 8px or above 18px in the sidebar.
- Don't add a second accent colour to a single card to create hierarchy — use weight and spacing.
