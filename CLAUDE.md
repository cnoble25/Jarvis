# CLAUDE.md

Jarvis is a voice-first desktop assistant for **Linux and macOS**. You hold the talk shortcut, Faster-Whisper transcribes what you say, an LLM picks a tool, the tool runs, and the reply is spoken (Kokoro, or ElevenLabs). A PySide6/WebEngine voice pill and task panel float over every app, and a dashboard (`ui/index.html`, wired up through QWebChannel) holds the settings. `PRODUCT.md` covers who it's for and its voice; `DESIGN.md` covers the UI.

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.txt     # pyobjc on macOS, CUDA wheels on Linux (env markers)
python main.py                      # --background: start with the dashboard closed; --quit: stop the running one
python -m pytest -q                 # whole suite runs in ~20s; no mic, GPU or network needed
bin/install-app                     # start at login: systemd user service (Linux) / launchd agent local.jarvis (macOS)
```

Only one Jarvis runs at a time. A second launch asks the running one (over `/tmp/jarvis.sock`) to show its dashboard and then exits. Restart the running one to pick up code changes.

## Layout

- `main.py`: Qt app, the dashboard, the overlay windows, the voice loop, and the IPC command handler.
- `daemon/os_interface/`: **everything OS-specific lives here.** `base.py` defines `OSInterface`; `linux.py` and `macos.py` implement it; `keyboard_linux.py` (evdev) and `keyboard_macos.py` (Quartz event tap) read the keyboard; `audio.py` plays speech. Call `get_os()`. Tests swap in a fake with `set_os()`.
- `daemon/ipc/hotkey_interceptor.py`: what "holding the shortcut" means (held keys add up, a 200ms release buffer, live rebinding). It's the same on every OS; it gets key events from `get_os().keyboard(...)`.
- `daemon/agent/`: the orchestrator (system prompt, tool routing), fast-path rules, approval of risky commands (`approval.py`), and background tasks.
- `daemon/agent/pattern_miner.py`: learned shortcuts. After each turn it re-mines the whole transcript log for requests the model always answers the same way (templates like `open {app_name}`). A rule only skips the model after 4 agreeing decisions and zero conflicts; until then it's in "shadow" (its prediction is logged next to the model's). Noise rules ignore repeated low-confidence speech. `python -m daemon.agent.pattern_miner` prints a read-only report.
- `daemon/agent/pattern_learner.py`: background learning, with no user involvement. After the model handles a request nothing cached, a pre-filter and then one grader call (the memory model) decide whether it's worth caching. If it is, a locked-down Claude Code session writes an "authored" rule (templates with number, app or enum slots, mapped to an existing tool). That session can only read and use `test_pattern` / `save_pattern`. Saving is refused if the rule contradicts the log or doesn't reproduce its own request. The miner keeps re-verifying these rules: one more agreeing model decision makes them active, and any disagreement drops them. Capped at 20 Claude Code runs a day; set `"background_learning": false` in settings.json to turn it off.
- `daemon/agent/context_runtime.py`: context rules ("close that", "skip this song", "do that again"). An authored rule can carry `needs` (helpers to read) and a Python `resolver(slots, ctx)` that only computes the arguments. Built-in read-only helpers (front app, running apps, now playing, volume, last action, clipboard, recent files, time) come from the OS interface. The resolver code is checked (stdlib-only imports, no files, eval or dunder access) and runs in an isolated subprocess with a 3-second limit; returning None hands the request to the model. Claude Code can `propose_helper` for missing context; proposed helpers are code, so they wait for approval on the Commands page, and rules that need them wait too. Context rules are active once saved (their worked examples must pass). A correction within 20 seconds ("no", "undo", a rephrase the model answers differently) sends any learned rule back to watching, and a second one drops it.
- `daemon/providers/`: the STT/LLM/TTS provider registry (Anthropic, Claude Code, Ollama, Gemini, ElevenLabs, Kokoro, Faster-Whisper).
- `daemon/tools/`: `execution_engine.py` (built-in tools), `registry.py` (JSON tool manifests), `daily_commands.json`, and `app_scanner.py`.
- `daemon/tools/skills.py`: skills Jarvis writes for itself. Claude Code saves one through the `save_skill` Jarvis tool into `~/.config/jarvis/skills/<id>/` (`skill.json` plus `run.py` or `run.sh`). A skill only loads as a tool once the user approves it on the dashboard's Commands page. Approval stores a hash of the manifest and code, so any later change needs approval again. HIGH-risk skills ask before every run. Scripts read their arguments as JSON on stdin, and their last printed line is what Jarvis says.
- User state lives in `~/.config/jarvis/` (settings, tools, macros, memory profile, fast-path rules). Logs and transcripts are in `~/.local/share/jarvis/`.

## Rules

1. **Don't break either OS.** No `sys.platform` checks or OS commands (`wpctl`, `osascript`, `gtk-launch`, …) outside `daemon/os_interface/`. Add a method to `OSInterface`, implement it in `linux.py` and `macos.py`, and return `self.unsupported(...)` where an OS can't do it yet.
2. Built-in tools in `daily_commands.json` use `builtin_*` templates handled in `ExecutionEngine`. Shell templates are for tools users add themselves.
3. Keep the GUI thread free: audio, STT, LLM calls and tools run on worker threads and reach Qt through signals.
4. The system prompt's stable part is cached. Anything that changes per request (time, focus mode, memory profile) goes after `VOLATILE_CONTEXT_TAG` (`daemon/providers/base.py`), or it invalidates the cache.

## Gotchas

- Each turn's transcript records `served_by` (`fast_path`, `learned`, `noise`, `llm`, `claude_code`, `route`) and, for model turns, `llm_decision`, the model's own first choice. The miner learns only from `llm_decision`, never from what a shortcut did. Transcripts are kept for 90 days.
- On every start, `ToolRegistry` copies `daemon/tools/daily_commands.json` over `~/.config/jarvis/tools/daily_commands.json`. Running an older checkout downgrades the tools.
- macOS permissions are granted to the app Jarvis runs from: your terminal when you start it by hand, Python itself when it starts at login. The talk shortcut needs Accessibility (or Input Monitoring); the Microphone, Automation and Screen Recording prompts come up the first time each is used. The default shortcut on macOS is Option+Space, because Cmd+Space opens Spotlight.
- `locked_in_mode` needs the separate `locked-in` CLI (found on PATH, next to the venv's Python, or via `$JARVIS_LOCKED_IN`). It isn't installed on the Mac.
- Started at login, Jarvis gets a bare PATH. Binary lookups (`claude`, `ollama`) also check Homebrew's own folders, and the macOS launchd agent sets PATH itself.
