# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(The dashboard is HTML/CSS/JS rendered inside a PySide6 Qt WebEngine window on the Linux desktop, default 920×640, minimum 720×520. There is no browser chrome and no network guarantee: fonts, icons and assets must ship with the app.)

## Users

- **Today:** the author, a developer running Jarvis daily on their own Linux desktop (Bazzite/Fedora, GNOME or KDE, X11 or Wayland).
- **Later:** other Linux users who install and set it up themselves. The dashboard may assume the owner's context today, but should not depend on private knowledge: settings, errors and labels need to make sense to someone who did not write the code.

## Product Purpose

Jarvis is a voice-first desktop assistant. The user holds a key combination anywhere on the desktop, speaks, and releases; Jarvis transcribes the speech, decides what to do, acts on the desktop, and answers out loud.

The dashboard window is opened, not watched. It is used for three jobs:
1. **Checking what it heard:** after a voice command, glance at what Jarvis understood, what it did, and why something failed.
2. **Setup and tweaking:** models, voices, the talk shortcut, custom commands, macros.
3. **Reviewing what it learned:** the memory profile and the shortcuts learned from repeated phrases.

Success: the owner trusts what the window says, can fix a failure from the window itself, and can change how Jarvis thinks or sounds in a few seconds.

## Positioning

- **Instant hold-to-talk:** one shortcut from any window, read at the kernel input level; no wake word.
- **Controls the Linux desktop:** real actions (launch apps, media, volume, timers, focus profiles via `locked-in`, power, screenshots, multi-step macros), not just answers.
- **Learns your shortcuts:** phrases you repeat become fast-path rules that skip the language model.
- **Local by default, cloud when you want it:** Faster-Whisper, Kokoro and Ollama run on the user's machine; Anthropic, Gemini and ElevenLabs are optional, and switching between local and cloud must be easy.

## Operating Context

- The loop: hold shortcut → listening → release → transcribe → think → act → speak. A bottom-of-screen HUD pill shows the live loop; the dashboard is where the user goes afterwards.
- Configuration lives in `~/.config/jarvis/settings.json`, API keys in `.env`, transcripts in `~/.local/share/jarvis/transcripts/` (optional S3 backup), custom commands in `~/.config/jarvis/tools/`, macros in `~/.config/jarvis/macros/`, the memory profile in `~/.config/jarvis/user_profile.md`.
- The dashboard talks to the daemon over a QWebChannel bridge; the same actions are exposed on `/tmp/jarvis.sock` for scripts.

## Capabilities and Constraints

- Pluggable providers: speech-to-text (Faster-Whisper local, Gemini), language model (Ollama local, Anthropic, Gemini), text-to-speech (Kokoro local, ElevenLabs).
- Custom commands are shell command templates registered with spoken examples and a risk level (Safe, Medium, High).
- Macros are named lists of shell steps compiled to scripts.
- Fast-path rules are either built in or learned from transcripts by a background agent.
- The memory profile is generated from transcripts by a language model; it is currently read-only in the UI.
- Terminology to use with users: "talk shortcut", "command", "macro", "shortcut phrase" / "learned shortcut", "memory profile", "conversation". Internal terms (tool manifest, few-shot, orchestrator, fast-path, IPC) stay out of user-facing copy except where a developer needs them.

## Evidence on Hand

- Real transcripts, learned rules, macros and a memory profile exist on the owner's machine and are what the dashboard renders. No screenshots, testimonials, or usage numbers exist; do not fabricate any.

## Product Principles

1. **Never show a state that isn't real.** Unknown is better than a confident guess.
2. **Every failure carries its fix.** If Jarvis couldn't do something, the window says why and what to do next.
3. **The conversation is the content.** What you said and what Jarvis said back come before the plumbing.
4. **Local first, switching is one step.** Changing model or voice should never require hunting.
5. **Destructive actions are reversible.** Deleting a learned shortcut, macro or command offers undo.

## Accessibility & Inclusion

- Fully usable by keyboard: it is a keyboard-triggered product.
- WCAG 2.1 AA contrast; status never conveyed by color alone; respects reduced motion.
