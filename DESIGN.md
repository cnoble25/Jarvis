---
name: Jarvis
description: A dark river-delta dashboard for a voice-first Linux desktop assistant, its chrome turned to water; where your words went, and how to fix what failed.
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
  control-edge: "#517f8f"
  pool-water: "color-mix(in oklab, #122c3c 60%, #0e2433)"
  row-water: "color-mix(in oklab, #122c3c 78%, #0e2433)"
  silt: "#7fd1d9"
  silt-deep: "#4fa9b8"
  silt-hover: "#9adde3"
  on-silt: "#062029"
  silt-pool: "color-mix(in oklab, #7fd1d9 13%, #122c3c)"
  silt-pool-strong: "color-mix(in oklab, #7fd1d9 22%, #122c3c)"
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
    fontFamily: "Atkinson Hyperlegible, Noto Sans, DejaVu Sans, system-ui, sans-serif"
    fontSize: "0.94em"
    fontWeight: 400
rounded:
  tail: "8px"
  small: "10px"
  default: "14px"
  pool: "22px"
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
    rounded: "{rounded.pill}"
    padding: "8px 24px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.silt-hover}"
  button-secondary:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pill}"
    padding: "8px 24px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.ramp-5}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ramp-9}"
    rounded: "{rounded.pill}"
    padding: "8px 24px"
  button-quiet-hover:
    backgroundColor: "{colors.ramp-3}"
    textColor: "{colors.coral-text}"
  button-small:
    typography: "{typography.label}"
    padding: "4px 16px"
    height: "32px"
  input:
    backgroundColor: "{colors.ramp-1}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.default}"
    padding: "8px 16px"
    height: "42px"
  ask-capsule:
    backgroundColor: "{colors.ramp-1}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pill}"
    padding: "4px 4px 4px 24px"
    height: "52px"
  topbar:
    backgroundColor: "{colors.ramp-1}"
    rounded: "{rounded.pill}"
    padding: "8px 8px 8px 16px"
  nav-pill:
    backgroundColor: "{colors.ramp-0}"
    rounded: "{rounded.pill}"
    padding: "4px"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ramp-9}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "36px"
  nav-item-active:
    backgroundColor: "{colors.silt-pool-strong}"
    textColor: "{colors.ramp-10}"
  pool:
    backgroundColor: "{colors.pool-water}"
    rounded: "{rounded.pool}"
    padding: "24px"
  capsule-row:
    backgroundColor: "{colors.row-water}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pool}"
    padding: "16px 24px"
  capsule-row-hover:
    backgroundColor: "{colors.ramp-4}"
  bubble-you:
    backgroundColor: "{colors.silt-pool}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pool}"
    padding: "16px 24px"
  bubble-jarvis:
    backgroundColor: "{colors.ramp-3}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pool}"
    padding: "16px 24px"
  task:
    backgroundColor: "{colors.ramp-3}"
    rounded: "{rounded.pool}"
    padding: "16px 24px"
  task-waiting:
    backgroundColor: "{colors.amber-ground}"
    textColor: "{colors.amber-text}"
  keycap:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    typography: "{typography.label}"
    rounded: "{rounded.small}"
    padding: "2px 12px"
  code-pool:
    backgroundColor: "{colors.ramp-1}"
    textColor: "{colors.ramp-10}"
    typography: "{typography.code}"
    rounded: "{rounded.tail}"
    padding: "1px 7px"
  tag:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "1px 12px"
  tag-high:
    backgroundColor: "{colors.coral-ground}"
    textColor: "{colors.coral-text}"
  tag-medium:
    backgroundColor: "{colors.amber-ground}"
    textColor: "{colors.amber-text}"
  chip:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pill}"
    padding: "3px 4px 3px 16px"
  switch:
    backgroundColor: "{colors.ramp-1}"
    rounded: "{rounded.pill}"
    width: "44px"
    height: "26px"
  switch-checked:
    backgroundColor: "{colors.silt-deep}"
  banner-error:
    backgroundColor: "{colors.coral-ground}"
    textColor: "{colors.coral-text}"
    rounded: "{rounded.pool}"
    padding: "12px 24px"
  banner-warn:
    backgroundColor: "{colors.amber-ground}"
    textColor: "{colors.amber-text}"
    rounded: "{rounded.pool}"
    padding: "12px 24px"
  toast:
    backgroundColor: "{colors.ramp-4}"
    textColor: "{colors.ramp-10}"
    rounded: "{rounded.pill}"
    padding: "8px 8px 8px 24px"
    height: "48px"
---

# Design System: Jarvis

## Overview

**Creative North Star: "The River Delta"**

The dashboard is a Landsat false-colour delta seen from orbit, and its chrome is water too. Deep slate water is the ground, silt-cyan and sage are the channels and banks that carry meaning, ice-white is the type, and coral is the one warm thing on screen: it appears only where something failed or needs the owner. Your voice is the river; the Overview shows where your words went as a delta of real outcomes, with waves rolling down its channels, not as a grid of metric cards.

Every piece of chrome is a body of water that pools, swells and flows on real events. A floating top capsule replaces the old sidebar; its six destinations sit in one pill whose liquid indicator flows to the chosen tab. Content sits in capsules and pools with large soft radii, lifted off the ground by tone plus a soft shadow cast below. A faint, slow current of lit water drifts under the page. The window is opened, not watched: 920×640 in Qt WebEngine (720×520 minimum), offline, dark only.

One humanist face on a strict five-step ladder carries all hierarchy, code included: there is no monospace. Motion is how water settles: arrivals rise out of a blur, the tab indicator springs, states ripple and breathe; reduced motion keeps every colour and opacity change and removes travel.

**Key Characteristics:**
- One eleven-step cold tonal ramp supplies every neutral: grounds, pools, controls, edges and all three text tiers.
- Each outcome owns one colour everywhere it appears: delta channel, row mark, conversation entry.
- Coral means failure or "needs you", and nothing else is warm except the amber caution tier.
- Capsules for what you press or type into, pools for what holds content; no hairline dividers.
- Depth is tone plus a soft cast shadow below; rings exist only where contrast is owed.
- Atkinson Hyperlegible at 13 / 15 / 19 / 24 / 30, weights 400 and 700 only, code in the same face.
- Arrivals flow in, the indicator springs, ambient loops pause when hidden; reduced motion keeps colour, drops travel.

## Colors

A cold, low-chroma water ramp with two cool channel hues (silt-cyan, sage), silt-lit pools for what belongs to you or a live state, a single reserved warm signal (coral), and amber for caution.

### Primary
- **Silt Cyan** (silt): the active channel. Primary buttons (with On Silt text), focus outlines, the active nav icon, listening and speaking state, link buttons, disclosure summaries, the chip's Clear, selection and caret, the "learned" tag, the "replies" outcome and the delta source. Silt Deep is the checked switch and the second thinking droplet; Silt Hover is the rising fill inside a primary button.
- **Silt Pool / Silt Pool Strong** (silt mixed 13% / 22% into ramp-3): water lit by the channel. Your bubble, the flowing nav indicator, a running task's gradient, the recorder while it listens.

### Secondary
- **Sage Bank** (sage): settled, healthy, safe. The Ready droplet, Safe-risk tags, done tasks, memory-profile markers, the "timers & focus" outcome, the third thinking droplet. Sage Deep is a finished task step and the "power" outcome.

### Tertiary
- **Delta Coral** (coral): failure and anything that needs the owner. The failed delta ribbon, disconnected or blocked state droplet, failed step droplets, the "needs you" pill, error banners and toasts (coral-ground, coral-edge, coral-text), failed rows and turns, fix hints, High and Critical risk tags, quiet-button hover.
- **Caution Amber** (amber-text / amber-ground / amber-edge): warnings that are not failures, and anything waiting for your OK. Medium-risk tags, the warn banner, a task waiting for approval (the whole pool turns amber), the voice pill when it asks for an OK, an unsure route.

### Neutral
- **Deep Water** (ramp-0): the nav pill's well, the voice pill's chip, the keycap lip.
- **Rail Water** (ramp-1): the top capsule, fields, the ask capsule, switch track, code pools, command wells, trigger-phrase pills, the delta pool's floor, overlay surfaces.
- **Ground Water** (ramp-2): the page background, task pools in the overlay panel.
- **Raised Water** (ramp-3): Jarvis's bubble, the model capsule, task pools, an open disclosure.
- **Pool Water** (pool-water, ramp-3 60% into ramp-2): settings sections, a closed disclosure, the memory profile, the system pools.
- **Row Water** (row-water, ramp-3 78% into ramp-2): resting capsule rows, turns, commands, macros, rules.
- **Control Water** (ramp-4): secondary buttons, tags, chips, toast, hovered rows and legend mouths.
- **Swell** (ramp-5): the rising fill in secondary buttons, chip-clear hover, scrollbar thumb, overlay surface edge.
- **Edge** (ramp-6): hovered scrollbar, the deep stop of the thinking swirl.
- **Control Edge** (control-edge, off-ramp by design): the 1px ring on fields, the switch and the recorder, tuned to 3.95:1 on the field and 3.3:1 on ramp-3 pools for WCAG 1.4.11.
- **Mist** (ramp-7): field hover ring, "other commands" outcome.
- **Text tiers**: ramp-10 primary text; ramp-9 secondary text, which carries nearly every label, time and meta line; ramp-8 only for placeholders, the select chevron and explicitly muted text.

### Outcome palette
Outcomes run silt into sage, one hue per outcome, sorted by volume with failures always last: replies = silt, volume & media = outcome-media, timers & focus = sage, apps & macros = outcome-apps, power = sage-deep, other commands = ramp-7, failed = coral.

### Named Rules
**The One Ramp Rule.** Every neutral comes from ramp-0..10 or a mix of two ramp steps (pool-water, row-water). The only off-ramp neutral is control-edge, which exists for a contrast floor. Do not introduce greys.

**The Reserved Coral Rule.** Coral and its text/ground/edge family appear only for failure or "needs you". A screen where nothing is wrong has no coral on it.

**The One Outcome, One Colour Rule.** An outcome's colour is the same in the delta channel, the legend mouth, the row mark and the conversation entry. Colour never carries an outcome alone: every mark sits beside its text label.

## Typography

**Display Font:** Atkinson Hyperlegible (with Noto Sans, DejaVu Sans, system-ui), bundled at 400 and 700
**Body Font:** Atkinson Hyperlegible
**Label/Mono Font:** none; code, paths, IDs and command templates are Atkinson Hyperlegible at 0.94em in a Rail Water pool

**Character:** One humanist, legibility-first face does every job; hierarchy is size and weight only. This is not a console, so nothing is set in monospace.

### Hierarchy
- **Display** (700, 30px, 1.15, -0.015em): the live status word ("Ready", "Listening", "Can't think") and the latest thing you said (1.2 line-height, curly-quoted, stepping down to 24px then 19px for longer sentences, three lines at most).
- **Headline** (700, 24px, 1.25, -0.01em): page titles.
- **Title** (700, 19px, 1.25): section titles, the wordmark, earlier-turn queries, task titles, macro names; at 400 for the latest reply (62ch) and a task's result.
- **Body** (400, 15px, 1.55, 0.005em): everything else; prose capped at 62–70ch, `text-wrap: pretty`, headings balanced. Section titles that sit over a run of capsules drop to body size in secondary text.
- **Label** (400 or 700, 13px): times, counts, help, field labels (700, secondary text), tags, keycaps (700), fix hints, the "needs you" pill. Sentence case, never uppercase-tracked.

### Named Rules
**The One Face, One Ladder Rule.** Only 13 / 15 / 19 / 24 / 30 (ratio about 1.25), only weights 400 and 700, only Atkinson Hyperlegible. Code is the same face in a small pool of deeper water. A new size is a new step that must earn its place.

**The Numbers Align Rule.** Counts at delta mouths and task times use tabular numerals; delta counts are right-aligned.

## Layout

The window is a column: a floating top capsule (12px from the top, 16px from the sides), then one scrolling main area, which is the only scroller. Main padding is 24px top, 32px sides, 48px bottom (24px sides under 860px). Each page is a single centred flex column, max 880px, with 32px between sections (Overview tightens to 24px).

Spacing is a 4-unit scale: 4, 8, 12, 16, 24, 32, 48. Capsule lists stack with 8px gaps; task pools with 12px. Conversation rows use fixed meta columns: 104px time, flexible query and reply, 128px outcome; under 860px the time column is 96px, the outcome column goes and its droplet moves beside the time. Task pools use a 112px status column (96px under 860px). Forms use two equal columns with 16px gaps; settings fields cap at 620px. The system facts sit in a two-column grid of small pools.

Responsive steps: under 1000px only the chosen destination shows its label (the others collapse to icons); under 860px the model capsule spans the row under the status; under 780px the state text beside the wordmark hides and the droplet alone carries it.

## Elevation & Depth

Water on water: depth is a tone step up the ramp plus a soft shadow cast below, never a border. Resting content pools carry the pool shadow; the two things that float over everything (the top capsule and the toast) carry the float shadow. Wells you type into or that hold the nav are pressed in with an inset shadow. Capsule rows rest flat on Row Water and swell on hover or focus: tone to ramp-4 and the pool shadow, with no travel.

### Shadow Vocabulary
- **Pool** (`--shadow-pool: 0 10px 28px -14px rgba(2, 10, 16, 0.75), 0 2px 6px -3px rgba(2, 10, 16, 0.5)`): model capsule, delta pool, bubbles, task pools, open disclosure, error banner, hovered rows.
- **Float** (`--shadow-float: 0 18px 40px -16px rgba(2, 10, 16, 0.85), 0 4px 12px -6px rgba(2, 10, 16, 0.6)`): the top capsule and the toast only.
- **Well** (`inset 0 2px 5px rgba(2, 10, 16, 0.5)` plus the field ring): fields, recorder, switch track; the ask capsule uses a 6px / 0.55 inset; the nav pill `inset 0 1px 3px rgba(2, 10, 16, 0.6)`.
- **Surface light** (`inset 0 1px 0` ramp-10 at 4–5%): the top lip of the top capsule and the delta pool.
- **Channel glow** (`0 8px 18px -10px` silt at 70%; `0 6px 16px -10px` silt at 60% on the nav indicator): a primary button and the flowing indicator.
- **Keycap** (`0 2px 0 #071722, 0 6px 12px -8px rgba(2, 10, 16, 0.8)`): a physical lip under each key.

### Named Rules
**The Water On Water Rule.** Depth is tone plus a soft shadow below. Hover swells a capsule's water (tone and shadow); the capsule stays under the pointer.

**The Ring Is Owed Rule.** A 1px ring appears only where contrast is owed or something is wrong: control-edge on fields, the switch and the recorder (WCAG 1.4.11), silt at 2px on focus, coral-edge or amber-edge on error and waiting states. Secondary buttons, pools, rows and tags have no ring.

## Shapes

Capsules and pools. Anything you press or type a line into is a capsule (999px): buttons, nav items, the nav pill, the top capsule, tags, chips, the toast, the ask capsule, the recorder, the switch, legend mouths, link buttons, the compact select. Multi-line fields and command wells are 14px. Anything that holds content is a pool (22px): rows, turns, commands, macros, rules, bubbles, tasks, banners, settings sections, the disclosure, the delta. Keys are 10px; inline code pools 8px. Bubbles keep one 8px corner, pointing toward each other (yours bottom-right, Jarvis's top-left). Dots are droplets: state, outcome marks, task steps, route marks.

Curves are no longer reserved for data. The delta is one body of water: filled ribbons that share a rounded source and peel away to round-capped mouths; the voice pill is an amorphous droplet whose whole outline moves.

### Named Rules
**The Capsule Or Pool Rule.** Controls are capsules, containers are pools at 22px. No square corners and no hairline dividers; space and tone separate things.

## Components

### Buttons
Capsules that fill like water. All pills, 40px tall, 8px/24px padding, 700 weight, no border; disabled at 55% opacity; busy buttons swap their label and set `aria-busy`.
- **Hover:** lighter water rises from the bottom of the capsule, a curved surface (45% top radii) leading, 420ms ease-out. Press scales to 0.97.
- **Primary:** silt with On Silt text and a silt glow below; Silt Hover rises in. One per form, also the send droplet in the ask capsule (44px).
- **Secondary:** Control Water, primary text, no ring; ramp-5 rises in. Inside an error banner it goes transparent on a coral-edge ring.
- **Quiet:** no fill, secondary text; Raised Water rises in and the text turns coral-text. Delete and Retry.
- **Small:** 32px, 4px/16px, label size. Banners, section heads, row actions.
- **Link button:** silt label-size text in a pill that tints silt 14% on hover.

### Keycaps
The talk shortcut is always shown as keycaps: each key a soft ramp-5 to ramp-4 gradient at 10px, label size bold, min 28px wide, with the keycap lip, joined by secondary "+" glyphs.

### Chips and Tags
- **Tags:** filled pills, no ring, label size, ramp-4 by default. Error and High risk on coral-ground, Medium on amber-ground, Safe on sage mixed 16% into ramp-2 with sage text, learned on silt mixed 18% into ramp-2 with silt text. Critical adds a 1px coral ring and bold text so it reads above High without colour alone.
- **Filter chip:** a Control Water pill ("Only volume & media") with a silt Clear; it appears when a delta mouth filters Conversations.

### Cards / Containers
Pools, not cards. Resting capsule rows on Row Water; settings sections, the profile and system facts on Pool Water at 24px or 16px padding; task pools, bubbles and the model capsule on Raised Water with the pool shadow.
- **Disclosure:** a Pool Water capsule whose silt summary carries a plus that turns to a minus; opening it pours to its natural height (460ms) and raises it to Raised Water with the pool shadow. The "Check before saving" preview lives inside the open capsule with no second container.
- **Bubbles (the latest exchange):** your words in a silt-lit pool aligned right, Jarvis's reply in Raised Water aligned left, joined by 8px gap; a failed reply turns Jarvis's bubble coral-ground with a coral-edge ring. While Jarvis thinks, three droplets (silt, silt-deep, sage) bob in its bubble.
- **Capsule rows:** rows, turns, commands, macros and rules share one capsule; failed rows and turns sit on coral-ground mixed 80% into ramp-2. Outcome marks are 8px droplets of the channel colour beside the label.

### Inputs / Fields
- **Style:** Rail Water well, 14px radius, 42px min height, 8px/16px padding, inset shadow plus a 1px control-edge ring; labels above at label size 700 in secondary text.
- **Hover / Focus:** ring to ramp-7 on hover; on focus a 2px silt ring, no outline.
- **Ask capsule:** a long Rail Water pill with a pressed-in well, a ramp-4 ring and the primary send button inside; focus turns the ring 2px silt.
- **Select:** native appearance removed, chevron in ramp-8. Compact variant is a 38px pill.
- **Switch:** a droplet sliding along its channel: 44×26 pill well with the control-edge ring; checked turns silt-deep with a silt ring, the 18px knob springs 18px across (420ms ease-flow) and stretches to 24px while pressed.
- **Shortcut recorder:** a 56px pill well that floods with a flowing silt-pool gradient and a 2px silt ring while it listens.

### Navigation
A floating top capsule on Rail Water with the float shadow: the 19px bold wordmark, the 12px state droplet and its state text on the left; on the right a Deep Water pill of six destinations (Overview, Conversations, Commands, Macros, What it knows, Settings; Alt+1..6). Items are 36px pills with an 18px stroke icon (1.6, round caps) in secondary text; hover brightens the text and lifts the icon 1px; the active item is primary, bold, with a silt icon. Behind it a silt-pool indicator flows to the chosen tab: on a change it stretches across the old and new tabs, then settles on the new one (560ms). Under 1000px only the chosen tab shows its label. A coral "needs you" pill appears in the capsule when something does.

### Banners
Pools tinted by what they say, 22px, max 76ch, an icon, a message and their own actions. Error (coral-ground, coral-edge ring, pool shadow) and warn (amber-ground, amber-edge ring) only. The inline variant carries small secondary and quiet buttons (Switch model, Retry), so every failure offers its fix in place.

### Toasts
A floating Control Water capsule bottom-right with the float shadow, 48px tall; it floats up from 14px and 0.92 scale and settles on the spring (520ms). Error tone uses coral-ground with a coral-edge ring. Deletes are reversible: the item hides immediately and the toast offers a silt "Undo" pill for 6 seconds.

### Tasks
Background tasks are pools on Raised Water: a 112px status column (state word in silt, sage when done, coral-text when failed, secondary when cancelled, amber when waiting; tabular time), the title at 19px bold, then steps. A running task is lit by a silt-pool gradient. Waiting for your OK, the whole pool turns amber (amber gradient, amber-edge ring), with the command in full in a Rail Water well and two answers. Steps are 8px droplets: sage-deep when done, silt and rippling when running, coral when failed, struck through when skipped.

### State vocabulary
The status word is the largest text on Overview and always true, paired with the state droplet: **Ready** (sage droplet that breathes slowly), **Listening** and **Speaking** (silt droplet, silt label, ripple ring), **Thinking** (a swirling silt conic droplet), **Can't think** (coral droplet, still, coral text) when the model is unreachable, in which case the shortcut keycaps hide and the detail says how to fix it. Beside it, the model capsule names the model and where it runs. Failed turns show coral reply text plus a label-size coral fix hint with inline code in primary text.

### The Delta (signature)
The Overview's centrepiece, in its own pool (Rail Water gradient, surface light, pool shadow): up to the last 50 requests as one stream branching into outcome channels.
- One body of water, never strokes butted together: every channel is a filled ribbon that starts as its own slice of the source stream (sized by its share) and peels away on a smoothstep to its mouth, so the source is simply where the ribbons still overlap. There is no seam or straight cut anywhere; ribbons overlap their neighbours by 0.3px and end in a rounded cap at the mouth.
- The source enters from the left with a round head about 55% of the full width, widening to full width (which grows with volume) before the split. Each ribbon is source-coloured (the replies silt) at the head and takes its own outcome colour as it leaves. Channels are sorted by volume; failures always last, as a thin coral ribbon.
- The drawing is 1:1 vertically with the legend: its height is max(108px, 24px per channel) so each mouth sits exactly on its label.
- Waves, not particles: each ribbon's edges ripple gently downstream (about 1px of sway, 8% width breathing, starting after the split), and a soft ice-white crest (a repeating gradient, 170 units apart, 38 units/s) rolls from the source through every channel. A newly logged request brightens its own channel's crest for 1.8s. On first appearance the water pours in from the source (a 1.1s clip reveal). Animation runs only while the Overview is on screen, the window is shown and motion is allowed; with reduced motion the ribbons are drawn once and stay still.
- Mouths are a legend of pill buttons (tabular count + label); hovering or focusing one dims every other channel to 28%; clicking filters Conversations to that outcome with a clearable chip.
- Empty state: no figure, one sentence saying each request will become a channel.

### The Voice Pill (overlay)
One amorphous droplet of water drawn on a 2D canvas in a 560×100 always-on-top window, centred on its content.
- **Outline:** a capsule (32px half-height) pushed in and out all the way round by periodic waves: k=1 and 2 for slow, uneven mass, k=3, 5 and 7 for lobes. The lobes grow with the state: idle 2, asking 3.5, thinking 4, speaking a breathing 4.5–7, listening 2.5 plus up to 11 with the microphone level. The swell is clamped (at most 15px out, a third of the half-height in) so the edge never leaves the window, and the outline is smoothed through midpoints so it has no corners.
- **Size follows content:** a ResizeObserver sets the half-width to half the content width plus 30px, clamped to 92–250px: a small bead for "Listening…", a long drop for a sentence. It stretches out fast (30% per frame) so new words are never outside it, and settles back slowly (10%).
- **Fill:** opaque Rail Water (XWayland lightens partial alpha) with a Raised Water depth gradient from the top at 70%, plus a lit current sweeping through in the state colour: silt for listening and speaking, sage for thinking, amber when Jarvis asks for an OK. A 1.25px skin in the same colour brightens as you speak louder.
- **Ripples:** a voice onset (the level jumping above its slow average) drops an elliptical ring at a random point inside the droplet and splashes the outline briefly at k=9; while Jarvis speaks it drops one ring about every 0.95s near the left end. Rings spread over 1.6s on a cubic ease-out, fade quadratically, cap at six, and are clipped inside the blob.
- **Content:** a 12px orb (scaling with the mic) and the text, with a Deep Water chip naming the state.
- **Reduced motion:** a still, frozen droplet at the content's width with no rings and no splash.

### The Task Panel (overlay)
An always-on-top 344px panel on the shared overlay tokens (`ui/css/overlay.css`): task pools on Ground Water with the same silt-lit running gradient, amber waiting pool, droplet steps and capsule buttons as the dashboard. Collapsed, it tucks into a 48×56 tab on the screen edge with a steady silt (or amber) dot and the count. Overlay surfaces are fully opaque (XWayland renders partial alpha too light) and use a dark outer ring instead of a cast shadow, which the window bounds would clip.

### Motion
- **Curves:** `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) for arrivals and state; `--ease-flow`, a spring with about 2.6% overshoot, for things that settle (switch knob, toast, nav indicator, icon nudges, row press).
- **Durations:** `--t-quick` 160ms for colour and hover; `--t-state` 260ms for state changes and droplet colour; `--t-arrive` 460ms for arrivals, label opening and the disclosure pour; 420ms for button fill and switch; 520–560ms for the toast and nav indicator.
- **Arrivals flow in:** new page content, the latest exchange and pending replies rise 10px out of a 6px blur and 0.985 scale over 460ms, staggered 40ms (140–160ms for the bubbles) and capped at 240ms.
- **Ambient:** the current, two drifting radial layers of lit water (70s and 95s alternating loops), the breathing state droplet, the delta waves; all pause while the window is hidden.
- **Reduced motion:** colour, opacity and shadow changes keep their short fades; nothing travels. flowIn becomes a 200ms fade; the current, droplets, ripples, swirl, delta draw, toast float and button fill are removed (buttons brighten instead); the voice pill holds still.

**The Simulation Stays Off The Dashboard Rule.** The per-frame outline deformation and ripple-ring technique of the voice pill is only for surfaces where performance does not matter, such as the glanceable voice overlay. It must not go on interactive dashboard surfaces: their liquid language comes from CSS shapes, tone, shadows and short transitions.

## Do's and Don'ts

### Do:
- **Do** take every neutral from ramp-0..10 (or pool-water / row-water) and use the role it is assigned.
- **Do** give each outcome its one colour in the delta, its droplets, row marks and conversation entries, always beside its text label.
- **Do** keep coral for failure and "needs you", and pair every failure with its fix (a banner action, a fix hint, or a Switch model button).
- **Do** make controls capsules and containers 22px pools, separated by space and tone rather than lines.
- **Do** lift with tone plus the pool or float shadow, and keep the 1px ring for fields, the switch and alarm states.
- **Do** keep type on the 13 / 15 / 19 / 24 / 30 ladder in Atkinson Hyperlegible 400/700, code included, with secondary text in ramp-9.
- **Do** show shortcuts as keycaps and destructive actions as quiet buttons that hide immediately and offer Undo.
- **Do** let arrivals flow in on the ease-out curve with capped staggers, pause ambient loops when hidden, and keep colour while removing travel under reduced motion.
- **Do** keep overlay surfaces opaque and on the shared overlay tokens.
- **Do** let the voice droplet follow its content and the microphone, and freeze it still under reduced motion.

### Don't:
- **Don't** build a metric-card telemetry grid; outcomes are shown as the delta and as conversation rows.
- **Don't** bring back a sidebar rail, hairline dividers, nested scroll wells or square corners.
- **Don't** set anything in monospace.
- **Don't** put a ring on secondary buttons, pools, rows or tags.
- **Don't** introduce greys, warm neutrals, or a second warm accent outside coral and amber.
- **Don't** show a state the daemon has not confirmed; prefer an honest unknown.
- **Don't** convey state or outcome by colour alone.
- **Don't** use partial alpha on an overlay surface.
- **Don't** put the voice pill's blob simulation or ripple rings on interactive dashboard surfaces.
