---
version: 1
name: PSY-residency-scheduler
description: An ElevenLabs-inspired planning workspace with off-white surfaces, warm ink, editorial headings and restrained pill controls. Adapted for a readable July-to-June timetable, not a marketing website.
colors:
  canvas: "#f5f5f5"
  surface: "#ffffff"
  surface-soft: "#fafafa"
  surface-strong: "#f0efed"
  ink: "#0c0a09"
  primary: "#292524"
  primary-hover: "#0c0a09"
  body: "#4e4e4e"
  muted: "#6e675e"
  hairline: "#e7e5e4"
  hairline-strong: "#d6d3d1"
  control-border: "#938c84"
  on-primary: "#ffffff"
  focus: "#695b82"
  core-bg: "#f0efed"
  core-text: "#49423c"
  elective-bg: "#f0ebf5"
  elective-text: "#6b527a"
  leave-bg: "#f9ecdf"
  leave-text: "#835630"
  success-bg: "#e8f2eb"
  success-text: "#276344"
  warning-bg: "#fff1dc"
  warning-text: "#815b24"
  error-bg: "#fff0ee"
  error-text: "#9f352e"
  info-bg: "#edf3f8"
  info-text: "#315c7f"
  pastel-mint: "#a7e5d3"
  pastel-peach: "#f4c5a8"
  pastel-lavender: "#c8b8e0"
  pastel-sky: "#a8c8e8"
typography:
  heading: {fontFamily: "Instrument Serif, Georgia, serif", fontSize: "36px", fontWeight: 400, lineHeight: 1.1}
  section: {fontFamily: "Inter, sans-serif", fontSize: "20px", fontWeight: 500, lineHeight: 1.4}
  body: {fontFamily: "Inter, sans-serif", fontSize: "14px", fontWeight: 400, lineHeight: 1.6}
  label: {fontFamily: "Inter, sans-serif", fontSize: "13px", fontWeight: 500, lineHeight: 1.5}
  caption: {fontFamily: "Inter, sans-serif", fontSize: "12px", fontWeight: 400, lineHeight: 1.5}
  metadata: {fontFamily: "Inter, sans-serif", fontSize: "11px", fontWeight: 400, lineHeight: 1.5}
spacing: {xs: "4px", sm: "8px", md: "12px", base: "16px", lg: "24px", xl: "32px", section: "48px"}
rounded: {small: "6px", input: "8px", panel: "16px", pill: "9999px"}
---

## Overview

Build a calm tool for programme staff planning PSY residency postings. Preserve
the ElevenLabs reference's off-white canvas, warm dark ink, light editorial
headings, understated borders, generous spacing and near-black pill buttons.
Adapt the composition to a working timetable. Avoid voice players, pricing
cards, testimonials, large promotional heroes and decorative dashboard metrics.

Use colour sparingly. A user should first notice the resident, posting and month.
Show history and editing controls on request instead of permanently filling the
screen with panels. The visual guide does not define scheduling policy.

## Colors

Use the frontmatter tokens and matching CSS custom properties in
`preview/styles.css`. Keep values consistent in both places when editing.

| Role | Treatment |
| --- | --- |
| Page and workspace | Off-white canvas, white panels, subtle warm-grey dividers |
| Primary action | Warm near-black fill with white text; one primary action per group |
| Core posting | Neutral fill and dark text |
| Elective posting | Pale lavender fill and dark lavender text |
| LOA | Pale peach fill, dark brown text and an explicit LOA label |
| Unallocated month | White or transparent fill, dashed outline, text label |
| Excluded resident | Neutral treatment and a full-year exclusion explanation |
| Feedback | Labelled success, warning, error and information messages |

Pastel mint, peach, lavender and sky remain optional brand accents. Use soft
atmosphere only in empty/upload states or the component showcase. Never put
decorative gradients behind timetable text or use them as primary button fills.

## Typography

Use Inter for controls, navigation, names, data and body text. The reference's
Waldenburg font is not bundled. This preview uses the openly licensed Instrument
Serif Regular for page headings to retain an editorial character. Both preview
fonts are self-hosted with their licence files in `preview/assets`.

| Role | Size / weight | Use |
| --- | --- | --- |
| Page heading | 36px / 400 Instrument Serif | One heading per screen; 30px on mobile |
| Section title | 20px / 500 Inter | Groups and detail headings |
| Body | 14px / 400 Inter | Instructions and resident information |
| Control label | 13px / 500 Inter | Buttons, filters and forms |
| Caption / table text | 12px / 400 Inter | Metadata and compact month cells |
| Compact secondary metadata | 11px / 400 Inter | Institution sublabels, reference IDs and year tags only |

Keep names and essential values readable. Use tabular numerals for aligned counts
and durations. Use monospace only for colour values and token measurements in
the design-system page. Never use tiny type to fit more columns.

## Layout

- A simple header contains the PSY identity and page navigation.
- The working screen leads with the planning year and timetable, not statistics.
- Use Timetable, Residents, Requests and Postings as separate views.
- Put resident search and year filters immediately above the relevant table.
- Keep the resident column visible during horizontal scrolling.
- At wide desktop sizes fit all twelve months where readable; at smaller sizes
  contain horizontal scrolling inside the table, not the whole page.
- Use 36px page padding on desktop, 20px below 800px, and 16px below 520px.
- Use 42px vertical padding for showcase sections, reducing to 32px below 520px.
  Do not inherit marketing's 96px band gaps.

## Components

### Buttons and navigation

Primary buttons are near-black pills, secondary buttons are outlined pills, and
quiet actions use text or subtle backgrounds. Standard height is 40px, increasing
to 44px for touch. Every icon-only button needs an accessible name. Provide hover,
focus, active, disabled and loading examples. Disabled buttons must not suggest a
feature is working; explain unavailable functionality nearby.

### Forms

Place visible labels above inputs. Use 8px input corners and native selects and
checkboxes where practical. Errors name the problem and how to correct it. Keep
invalid values visible until corrected; do not silently discard them on navigation.
Blank capacity means unknown, not zero. Demo capacities are illustrative only.

### Workbook chooser

Use a spacious upload area with a clear Choose workbook action, drag-and-drop
support, and concise file guidance. After selection, show the filename and size
with Replace and Remove actions. Validate one non-empty `.xlsx` file up to the
preview's 10 MB limit. Keep a valid selection visible if a replacement fails.
Use textContent for filenames, and announce selection or errors accessibly.
Selection is not proof that workbook contents have been read or validated.

### Skeleton loaders

Use the shared `skeletonMarkup` variants in `preview/components.mjs` for timetable,
resident detail and workbook sheet content. Match the loaded layout's dimensions
to minimise movement. Keep decorative shapes hidden from screen readers and
mark the owning region busy, with a meaningful loading label outside the shapes.
Clear the busy state when real content arrives. Use a subtle neutral pulse;
respect reduced motion and offer a pause control in the showcase. Do not delay
available content to display a skeleton. Long operations such as scheduling need
a progress status rather than an endless content placeholder.

### Timetable and resident detail

Month cells show posting category and institution with a full accessible label.
Selecting a cell opens a focused posting/range editor. Selecting a name reveals
recorded history and requests. On narrow screens the detail panel becomes a
modal region with contained keyboard focus. Restore focus to the initiating
control after closing or saving, falling back to resident search if that control
disappears. Do not describe planned assignments as completed
training or claim a draft is programme-validated.

### Surfaces and feedback

Panels use 16px corners and a 1px hairline without a permanent shadow. Reserve
an offset soft shadow for dialogs and overlays. Feedback uses restrained tonal
fills, an icon and clear text. Status must never depend on colour alone.

## Interaction and accessibility

- Make search, year filters, editing, dismissal and export understandable.
- Keep a visible 2px focus ring and adequate text contrast (4.5:1 for normal text).
- Support keyboard operation and labelled native controls.
- Freeze editing during a save/export request to avoid losing later changes.
- Respect reduced motion. Use short colour transitions, not looping decoration.
- Announce feedback with a live region; avoid interrupting ordinary exploration.
- Keep scheduling logic outside presentation code. Use confirmed rules separately.

## Preview scope

`preview/index.html` is an interactive interface demonstration with fictional
residents, editing and demo CSV export. It is not the PSY scheduling engine or
the workbook importer. `preview/design-system.html` shows the shared typography,
colour tokens, controls, timetable states, forms, feedback, spacing and radii.
Both use the same styles. No real resident records are included.

## Reference

Adapted from the independent ElevenLabs analysis installed using getdesign:
https://getdesign.md/elevenlabs/design-md. This is a PSY-specific visual guide,
not an official ElevenLabs product or a copy of its marketing website.
