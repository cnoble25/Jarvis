---
version: 1
slug: "ui-index-html"
primary_target: "ui/index.html"
related_targets: ["ui/css/style.css","ui/js/app.js"]
---

# Surface brief: Jarvis dashboard (ui/index.html)

Mode: Operate. Six pages behind one sidebar: Overview, Conversations, Commands, Macros, What it knows (memory profile + learned shortcuts), Settings. Qt WebEngine window, 920×640 default, 720×520 minimum; offline (bundle fonts and icons).

Audience and job: the owner opens the window after a voice command to check what was heard and fix failures, to tweak models/voice/shortcut, and to review what Jarvis learned. Constraints: PRODUCT.md principles (never show unreal state, every failure carries its fix, conversation first, one-step model switching, reversible deletes).

## Direction contract

THESIS: Your voice is the river; Overview shows where your words went, a delta of real outcomes, instead of the category's metric-card telemetry grid.

OWN-WORLD: Landsat false-colour delta. Deep slate water ground, silt-cyan channels, sage sediment banks, ice-white type; one eleven-step cold tonal ramp for every neutral; coral reserved for failures and what needs you. Organic channel curves only in data; hairline 1px dividers; soft 8px radii; one humanist face (Atkinson Hyperlegible) on a strict size ladder.

STORY: The visitor sees whether Jarvis is ready and what it heard last, understands where recent requests went and what failed and why, and fixes it or switches model in one step.

FIRST VIEWPORT: Sidebar left (pages, needs-you line). Main: status line (state, talk shortcut as keycaps, model + Switch); failure banner when the model is unreachable; the delta band (one stream branching into outcome channels, counts at the mouths); latest exchange large; three earlier turns.

FORM: own grounded list, position 7 (River delta from orbit), seed:c6e19e1056de6c36. Raises: one tonal ramp (darkroom record); no nested scroll wells (j-card); hairline discipline (centre rail); focus lifts the row (streaming wall).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
