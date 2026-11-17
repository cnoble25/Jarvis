---
name: Jarvis
description: A dark river-delta dashboard for a voice-first Linux desktop assistant; where your words went, and how to fix what failed.
colors:
  ramp-0: "#071722"
  ramp-1: "#0a1c28"
  ramp-2: "#0e2433"
  ramp-3: "#122c3c"
  ramp-4: "#16384a"
  ramp-5: "#1f4558"
  ramp-6: "#2d5a70"
  ramp-7: "#5f8796"
  ramp-8: "#93b4bd"
  ramp-9: "#b9d0d6"
  ramp-10: "#e8f2f4"
  control-edge: "#4a7686"
  silt: "#7fd1d9"
  silt-deep: "#4fa9b8"
  silt-hover: "#9adde3"
  on-silt: "#062029"
  sage: "#9fbfb1"
  sage-deep: "#6f9585"
  outcome-media: "#5fbac6"
  outcome-apps: "#86ab9b"
  coral: "#e0786a"
  coral-text: "#f4a99d"
  coral-ground: "#2a2531"
  coral-edge: "#7a423f"
  amber-text: "#f1cf8a"
  amber-ground: "#2c2a26"
  amber-edge: "#6e5c34"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 700
    lineHeight: 1.25
  body:
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "0.005em"
  label:
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.55
  code:
    fontFamily: "JetBrains Mono, DejaVu Sans Mono, ui-monospace, monospace"
    fontSize: "0.92em"
    fontWeight: 400
rounded:
  small: "5px"
  default: "8px"
  pill: "999px"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-5: "24px"
  s-6: "32px"
  s-7: "48px"
components:
  button-primary:
    backgroundColor: "{colors.silt}"
    textColor: "{colors.on-silt}"
    typography: "{typography.body}"
    rounded: "{rounded.default}"
    padding: "8px 16px"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.silt-hover}"
  button-secondary:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.default}"
    padding: "8px 16px"
    height: "38px"
  button-secondary-hover:
    backgroundColor: "{colors.ramp-5}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ramp-9}"
    rounded: "{rounded.default}"
    padding: "8px 16px"
  button-quiet-hover:
    backgroundColor: "{colors.ramp-3}"
    textColor: "{colors.coral-text}"
  button-small:
    typography: "{typography.label}"
    padding: "4px 12px"
    height: "30px"
  input:
    backgroundColor: "{colors.ramp-1}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.default}"
    padding: "8px 12px"
    height: "38px"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ramp-9}"
    rounded: "{rounded.default}"
    padding: "8px 8px 8px 12px"
    height: "36px"
  nav-item-active:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
  keycap:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    typography: "{typography.label}"
    rounded: "{rounded.small}"
    padding: "1px 8px"
  tag:
    backgroundColor: "transparent"
    textColor: "{colors.ramp-9}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 8px"
  chip:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pill}"
    padding: "3px 4px 3px 12px"
  banner-error:
    backgroundColor: "{colors.coral-ground}"
    textColor: "{colors.coral-text}"
    rounded: "{rounded.default}"
    padding: "12px 16px"
  banner-warn:
    backgroundColor: "{colors.amber-ground}"
    textColor: "{colors.amber-text}"
    rounded: "{rounded.default}"
    padding: "12px 16px"
  toast:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.default}"
    padding: "12px 12px 12px 16px"
---

# Design System: Jarvis

## Overview

**Creative North Star: "The River Delta"**

The dashboard is a Landsat false-colour delta seen from orbit. Deep slate water is the ground, silt-cyan and sage are the channels and banks that carry meaning, ice-white is the type, and coral is the one warm thing on screen: it appears only where something failed or needs the owner. Your voice is the river; the Overview shows where your words went as a delta of real outcomes, not as a grid of metric cards.

The window is opened, not watched, inside a 920×640 Qt WebEngine frame (720×520 minimum), offline, dark only. Density is calm and list-led: one sidebar, one column of content capped at 880px, hairline-divided rows that lift on hover. Organic curves exist only in data (the delta); everything else is rectilinear with soft 8px corners. One humanist face on a strict five-step ladder carries all hierarchy; weight and size do the work, never colour noise.

Depth is tonal, not cast. Surfaces step up the cold ramp (rail, ground, raised, control) and a single ambient shadow is reserved for the floating toast.

**Key Characteristics:**
- One eleven-step cold tonal ramp supplies every neutral: grounds, hairlines, edges and all three text tiers.
- Each outcome owns one colour everywhere it appears: delta channel, row mark, conversation entry.
- Coral means failure or "needs you", and nothing else is warm except the amber warning tier.
- 1px hairlines inset to the text column, hidden beside a lifted row.
- Atkinson Hyperlegible at 13 / 15 / 19 / 24 / 30, weights 400 and 700 only.
- Motion is short (160–220ms) ease-out-expo state feedback; the delta draws once on load; reduced motion removes it.

## Colors

A cold, low-chroma water ramp with two cool channel hues (silt-cyan, sage) and a single reserved warm signal (coral), plus amber for caution.

### Primary
- **Silt Cyan** (silt): the active channel. Primary buttons (with on-silt text, `#062029`), focus outlines, the active nav icon, listening/speaking state, link buttons, disclosure summaries, selection, the "learned" tag, the "replies" outcome and the delta trunk. Silt Deep is the checked switch fill and learned-tag edge; Silt Hover is the primary hover.

### Secondary
- **Sage Bank** (sage): settled, healthy, safe. The Ready state mark, Safe-risk tags, memory-profile list markers, the "timers & focus" outcome. Sage Deep is the Safe-tag edge and the "power" outcome.

### Tertiary
- **Delta Coral** (coral): failure and anything that needs the owner. The failed delta channel (dashed), disconnected/blocked state mark, error banners and toasts (coral-ground, coral-edge, coral-text), failed replies, fix hints, High-risk tags, quiet-button hover.
- **Caution Amber** (amber-text / amber-ground / amber-edge): warnings that are not failures, e.g. "a command with this ID already exists", Medium-risk tags.

### Neutral
- **Deep Water** (ramp-0): keycap underside and the darkest well.
- **Rail Water** (ramp-1): sidebar rail, input and select fields, command wells, trigger-phrase pills.
- **Ground Water** (ramp-2): the page background.
- **Raised Water** (ramp-3): row hover lift, preview panels, sidebar divider.
- **Control Water** (ramp-4): secondary buttons, active nav item, keycaps, chips, switch track, toast.
- **Hairline** (ramp-5): 1px row dividers, secondary-button hover, scrollbar thumb.
- **Edge** (ramp-6): button and tag borders, keycap borders, preview border.
- **Control Edge** (control-edge, off-ramp by design): input, select and switch borders, tuned to 3.3:1 on grounds for WCAG 1.4.11.
- **Mist** (ramp-7): input hover border, "other commands" outcome.
- **Text tiers**: ramp-10 primary text, ramp-9 secondary text, ramp-8 tertiary/meta text and placeholders.

### Outcome palette
Outcomes run silt into sage, one hue per outcome, sorted by volume with failures always last: replies = silt, volume & media = outcome-media, timers & focus = sage, apps & macros = outcome-apps, power = sage-deep, other commands = ramp-7, failed = coral.

### Named Rules
**The One Ramp Rule.** Every neutral comes from ramp-0..10. The only off-ramp neutral is control-edge, which exists for a contrast floor. Do not introduce greys.

**The Reserved Coral Rule.** Coral and its text/ground/edge family appear only for failure or "needs you". A screen where nothing is wrong has no coral on it.

**The One Outcome, One Colour Rule.** An outcome's colour is the same in the delta channel, the legend mouth, the row mark and the conversation entry. Colour never carries an outcome alone: every mark sits beside its text label.

## Typography

**Display Font:** Atkinson Hyperlegible (with Noto Sans, DejaVu Sans, system-ui), bundled at 400 and 700
**Body Font:** Atkinson Hyperlegible
**Label/Mono Font:** JetBrains Mono 400 (with DejaVu Sans Mono), for code, command templates and IDs only

**Character:** One humanist, legibility-first face does every job; hierarchy is size and weight only. Mono appears only where the content is literally code.

### Hierarchy
- **Display** (700, 30px, 1.15, -0.015em): the live status word ("Ready", "Listening", "Can't think") and the latest thing you said (1.2 line-height, curly-quoted).
- **Headline** (700, 24px, 1.25, -0.01em): page titles.
- **Title** (700, 19px): section titles, brand name, earlier-turn queries, macro names; at 400 for the latest reply (secondary text, 62ch).
- **Body** (400, 15px, 1.55, 0.005em): everything else; prose capped at 62–70ch, `text-wrap: pretty`, headings balanced.
- **Label** (400 or 700, 13px): timestamps, counts, help, field labels (700, secondary text), tags, keycaps (700), fix hints. Sentence case, never uppercase-tracked.

### Named Rules
**The One Face, One Ladder Rule.** Only 13 / 15 / 19 / 24 / 30 (ratio about 1.25), only weights 400 and 700. A new size is a new step that must earn its place; do not add an intermediate.

**The Numbers Align Rule.** Counts at delta mouths use tabular numerals, right-aligned.

## Layout

A fixed sidebar rail (200px; 176px under 860px) on Rail Water beside a scrolling main column on Ground Water. Main padding is 24px / 32px / 48px bottom (24px sides under 860px). Each page is a single flex column, max 880px, with 32px between sections (Overview tightens to 20px). There are no nested scroll wells: the main column is the only scroller.

Spacing is a 4-unit scale: 4, 8, 12, 16, 24, 32, 48. Rows bleed 8px past the column (negative margin) so their hover lift aligns text to the column edge. Row grids use fixed meta columns: 112px time (96px narrow), flexible query and reply, 128px outcome (dropped under 860px). Forms use two equal columns with 16px gaps, settings fields cap at 620px.

## Elevation & Depth

Flat and tonal. Depth is the ramp stepping up: rail (ramp-1) below ground (ramp-2), raised (ramp-3) for hover lifts and previews, control (ramp-4) for things you press. Borders are 1px and quiet; they mark controls and panels, not layout.

### Shadow Vocabulary
- **Floating toast** (`box-shadow: 0 8px 24px rgba(3, 12, 18, 0.5)`): the only cast shadow; the toast is the only element that floats over content.
- **Keycap underside** (`box-shadow: 0 1px 0 #071722`): a 1px ramp-0 lip that makes a keycap read as a physical key. Keycaps only.
- **Input focus** (`box-shadow: 0 0 0 1px #7fd1d9`): doubles the silt border on focus.

### Named Rules
**The Lift, Not Shadow Rule.** Hover and focus raise a row by tone (to ramp-3), never by a shadow. Hairlines beside a lifted row disappear.

## Shapes

Soft rectangles. 8px for buttons, inputs, banners, previews, nav items, toasts, the recorder; 5px for small inline things (keycaps, rows, legend buttons, command wells, trigger pills, toast action); full pills only for tags, chips and the switch. The only organic forms are data: the delta's bezier channels, butt-capped, leaving a soft-cornered (3px) trunk that enters square from the left edge.

### Named Rules
**The Inset Hairline Rule.** List dividers are 1px ramp-5 lines drawn as a pseudo-element inset 8px on each side, absent on the first item and on either side of a hovered item. Section dividers (settings, disclosure, system list) are full-width 1px ramp-5 borders.

**The Curves Are Data Rule.** Curves appear only where they encode something. Chrome stays rectilinear.

## Components

### Buttons
Confident, flat, three tiers. All 38px tall, 8px radius, 700 weight, 1px border, 160ms ease-out-expo colour transitions; disabled at 55% opacity; busy buttons swap their label and set `aria-busy`.
- **Primary:** silt fill, on-silt text; hover lightens to silt-hover. One per form (Review command, Save command, Save macro).
- **Secondary:** control-water fill, edge border, primary text; hover to ramp-5. Inside an error banner it goes transparent on a coral-edge border.
- **Quiet:** no fill, secondary text; hover lifts to raised with coral text. Used for Delete and for Retry inside the model banner.
- **Small:** 30px, 4px/12px padding, label size. Used in banners, section heads and row actions.
- **Link button:** silt label-size text, underline fades in on hover.

### Keycaps
The talk shortcut is always shown as keycaps, never as a string: each key a control-water cap with an edge border, 5px radius, 1px ramp-0 lip, label size bold, min 26px wide, joined by tertiary "+" glyphs.

### Chips and Tags
- **Tags:** outline pills, 1px edge border, label size. Variants by border/text: error and High risk (coral-edge / coral-text), Medium (amber), Safe (sage-deep / sage), learned (silt-deep / silt).
- **Filter chip:** control-water pill ("Only volume & media") with a silt "Clear" action; it appears when a delta mouth filters Conversations.

### Cards / Containers
There are no cards. Content is rows and sections on the ground. The one panel is the **preview** ("Check before saving"): raised fill, edge border, 8px radius, 16px padding.

### Inputs / Fields
- **Style:** rail-water fill, 1px control-edge border, 8px radius, 38px min height, 8px/12px padding; labels sit above at label size 700 in secondary text; optional marks in tertiary 400.
- **Hover / Focus:** border to ramp-7 on hover; on focus the border and a 1px ring turn silt, no outline.
- **Select:** native appearance removed, inline chevron in ramp-8. Compact variant 34px.
- **Switch:** 38×22 pill, control track, control-edge border; checked turns silt-deep with silt border, knob slides 16px in 180ms.
- **Shortcut recorder:** dashed edge field that goes solid silt on raised while recording.

### Navigation
Sidebar rail, items 36px tall with an 18px stroke icon (1.6 stroke, round caps) and secondary text. Hover lifts to raised with primary text; active is control-water, primary text, 700, silt icon. The rail foot carries the live state mark (8px dot) and label, plus a coral "needs you" line when something does.

### Banners
Full-row notices with an icon, a message and their own actions, 8px radius, 1px border, max 76ch. Error (coral) and warn (amber) only. The inline variant centres its content and carries small secondary + quiet buttons (e.g. Switch model / Retry), so every failure banner offers its fix in place.

### Toasts
Bottom-right, control water, edge border, the floating shadow, rising 8px in 220ms. Error tone uses the coral family. Deletes are reversible: the item hides immediately and the toast offers a silt-outlined "Undo" for 6 seconds before the delete commits; a failed commit restores the item and says so.

### State vocabulary
The status word is the largest text on Overview and always true: **Ready** (sage dot), **Listening** and **Speaking** (silt dot, silt label), **Thinking** (hollow silt ring), **Can't think** (coral dot, coral text) when the model is unreachable, in which case the shortcut keycaps hide and the detail says how to fix it. Failed turns show coral reply text plus a label-size coral **fix hint** with inline code in primary text.

### The Delta (signature)
The Overview's centrepiece: up to the last 50 requests as one stream branching into outcome channels.
- A soft-cornered trunk in silt enters square from the left edge; its thickness grows with volume (4–34 units).
- Each channel leaves its own slice of the trunk, its stroke width equal to its share, butt-capped, curving on a cubic bezier to its mouth. Channels are sorted by volume; failures always last.
- The failed channel is a coral 2/7 dash and never animates.
- Mouths are a legend of buttons (tabular count + label, outcome mark); hovering or focusing one dims every other channel to 28%; clicking filters Conversations to that outcome with a clearable chip.
- Empty state: no figure, one sentence saying each request will become a channel.
- Motion: channels draw once on render, 900ms ease-out-expo, staggered 70ms from a 120ms start; skipped entirely under reduced motion.

### Motion
One curve, `cubic-bezier(0.16, 1, 0.3, 1)`. 160ms for colour and background state changes, 180ms for the switch, 220ms for the toast entrance, 900ms for the one-time delta draw. Under `prefers-reduced-motion: reduce` all transitions drop to 0ms and the delta draw and toast entrance are removed.

## Do's and Don'ts

### Do:
- **Do** take every neutral from the ramp-0..10 tokens and use the role it is assigned (rail, ground, raised, control, hairline, edge, three text tiers).
- **Do** give each outcome its one colour in the delta, row marks and conversation entries, always beside its text label.
- **Do** keep coral for failure and "needs you", and pair every failure with its fix (a banner action, a fix hint, or a Switch model button).
- **Do** show shortcuts as keycaps and destructive actions as quiet buttons that hide immediately and offer Undo.
- **Do** separate list items with the 1px inset hairline and lift hovered rows to ramp-3.
- **Do** keep type on the 13 / 15 / 19 / 24 / 30 ladder in Atkinson Hyperlegible 400/700, mono only for literal code.
- **Do** keep transitions at 160–220ms on the ease-out-expo curve and honour reduced motion.

### Don't:
- **Don't** build a metric-card telemetry grid; outcomes are shown as the delta and as conversation rows.
- **Don't** add cards, nested scroll wells, or shadows on resting surfaces; the toast is the only floating element.
- **Don't** use curves in chrome; organic shapes belong to data.
- **Don't** introduce greys, warm neutrals, or a second warm accent outside coral and amber.
- **Don't** show a state the daemon has not confirmed; prefer an honest unknown.
- **Don't** convey state or outcome by colour alone.
