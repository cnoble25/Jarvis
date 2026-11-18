---
version: 1
slug: "ui-index-html"
primary_target: "ui/index.html"
related_targets: ["ui/css/style.css","ui/js/app.js","ui/hud.html","ui/panel.html","ui/css/overlay.css"]
---

# Surface brief: Jarvis dashboard (ui/index.html)

Mode: Operate. Six destinations: Overview, Conversations, Commands, Macros, What it knows (memory profile + learned shortcuts), Settings. Qt WebEngine window, 920×640 default, 720×520 minimum; offline (bundle fonts and icons). Shares its liquid language with the voice pill (ui/hud.html) and the task panel (ui/panel.html).

Audience and job: the owner opens the window after a voice command to check what was heard and fix failures, to tweak models/voice/shortcut, and to review what Jarvis learned. Constraints: PRODUCT.md principles (never show unreal state, every failure carries its fix, conversation first, one-step model switching, reversible deletes).

Owner direction (2026-11-17): fluid, "like fluids moving through systems"; capsules are fluid pieces; the page more dynamic with event motion plus a subtle passive flow; the pill ripples with the voice. Away from the console look: no monospace, no flat boxes and hairlines, no dense grey labels, no static snapping, no sidebar.

## Direction contract

THESIS: Your voice is the river and the window is the water it runs through: the Overview still shows where your words went as a delta of real outcomes, but every piece of chrome is a body of water that pools, swells and flows on real events, instead of a console's rail, boxes and grey rows.

OWN-WORLD: The Landsat delta palette kept whole: one eleven-step cold ramp, silt-cyan and sage channels, ice-white type, coral only for failure or "needs you". Chrome turns liquid: capsule surfaces with large soft radii, pill controls, depth from tone plus soft offset water-shadows, no hairlines, no monospace, no sidebar. A faint slow current moves under the page. Atkinson Hyperlegible only, fewer and larger labels.

STORY: The visitor sees whether Jarvis is ready and what it heard last, understands where recent requests went and what failed and why, and fixes it, types a request, or switches model in one step.

FIRST VIEWPORT: A floating top capsule: wordmark and a live state droplet left, the six destinations in one pill whose liquid indicator flows to the chosen one. Below: the status word large with its droplet, the model capsule, the type-to-Jarvis capsule; the delta band with droplets drifting down its channels (rate from real volume; each newly logged request runs one droplet into its outcome); the latest exchange as two joined bubbles (your words, Jarvis's reply); earlier turns as soft capsules.

FORM: own grounded list, position 7 (River delta from orbit), seed:c6e19e1056de6c36, evolved to liquid chrome at the owner's request. Signature interaction: the flowing tab indicator and the delta droplets; the voice pill's edge ripples with the microphone level. Motion grammar: arrivals flow (blur and rise to rest, ease-out-expo, staggers capped), states morph instead of swapping, exits faster than entrances, ambient loops pause when hidden; reduced motion keeps colour and opacity, drops movement and the current.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
