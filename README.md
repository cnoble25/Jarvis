# 🎙️ Jarvis Desktop AI Assistant

A high-performance, voice-first desktop assistant for Linux and macOS featuring real-time speech recognition, Anthropic Claude 3.5 LLM with prompt caching, local neural speech synthesis, system-wide kernel hotkey interception, and a dynamic desktop tool execution engine.

---

## 🌟 Key Features

* **Instant Voice Activation**: Hold the talk shortcut anywhere on your system to talk to Jarvis (`Super + Space` on Linux, `Option + Space` on macOS; change it in the dashboard). Linux reads the kernel's `/dev/input/event*` devices, so it works across X11, Wayland, GNOME and KDE; macOS uses a Quartz event tap.
* **Glassmorphic Floating HUD**: Sleek PySide6 / HTML5 floating HUD pill that pops up at the bottom of your screen during voice sessions.
* **Anthropic Prompt Caching**: Utilizes Anthropic Claude 3.5 with 5-minute ephemeral prompt caching (`anthropic-beta: prompt-caching-2024-07-31`), reducing system prompt tokens by 90%+ and delivering sub-second response latency.
* **Privacy-First Local AI Core**:
  * **STT**: Local `Faster-Whisper` (`base.en`) for real-time speech transcription.
  * **TTS**: Local `Kokoro-ONNX` (`af_kore` voice) for natural 44.1kHz speech synthesis.
  * **Memory LLM**: Local `Ollama` (`qwen2.5:3b`) for offline profile synthesis and event-driven memory extraction.
* **Dynamic Tool Execution Engine**:
  * **Visual Timers**: Spawns standalone floating desktop timer widgets with hi-fi crystal bell chimes and tight vertical snapping.
  * **Focus Profiles**: Integrates with `locked-in` CLI for multi-profile app/website blocking (`movies`, `work`, `study`).
  * **Desktop Control**: Media playback, volume adjustments, application launcher, screenshot capture, and power management.
  * **Macros**: Multi-step desktop automation scripts (e.g. Movie Mode macro).

---

## 🏗️ Project Architecture

```
Jarvis/
├── main.py                    # Application Entry Point & PySide6 GUI Loop
├── requirements.txt           # Python Dependencies
├── .env.example               # Environment Variables Template
├── daemon/
│   ├── agent/                 # ReAct Agent Orchestrator & Fast-Path Engine
│   ├── ipc/                   # Talk-shortcut logic & Unix Socket Server
│   ├── os_interface/          # Everything OS-specific: linux.py, macos.py, keyboard readers, audio
│   ├── memory/                # Transcript Logger, S3 Backup Syncer & Memory Profiler
│   ├── providers/             # LLM (Anthropic), STT (Faster-Whisper), TTS (Kokoro-ONNX)
│   ├── tools/                 # Execution Engine, Tool Registry & App Scanner
│   └── utils/                 # Environment Manager & Audio Utilities
└── ui/                        # HTML5/CSS3 Glassmorphic HUD & Settings Interfaces
```

---

## 📋 System Prerequisites (Linux)

Before installing Jarvis, ensure your system has the required audio and GUI system packages installed.

### Fedora / RHEL / Bazzite
```bash
sudo dnf install -y portaudio-devel alsa-lib-devel pipewire-utils libnotify wmctrl xdotool
```

### Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y portaudio19-dev libasound2-dev pipewire-audio-client-libraries libnotify-bin wmctrl xdotool
```

### Arch Linux
```bash
sudo pacman -S --needed portaudio alsa-lib pipewire-alsa libnotify wmctrl xdotool
```

## 📋 System Prerequisites (macOS)

Nothing beyond Python 3 (e.g. `brew install python`): audio, AppleScript, `afplay`, `screencapture` and `pmset` are built in, and `pip install -r requirements.txt` pulls in the PyObjC bridges Jarvis needs.

The first time Jarvis runs, macOS asks for permissions (System Settings > Privacy & Security), granted to the app Jarvis runs from (your terminal, or Python when it starts at login):
- **Accessibility** (or at least **Input Monitoring**): the talk shortcut. With Accessibility the shortcut's key doesn't also type into the focused app.
- **Microphone**: hearing you.
- **Automation** (Spotify, Music, System Events), **Screen Recording** (screenshots): asked the first time you use them.

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/Jarvis.git
cd Jarvis
```

### 2. Set Up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Environment Configuration (`.env`)

1. Copy `.env.example` to create your active `.env` file:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` in your text editor and configure your credentials:
   ```env
   # Anthropic Claude API Key (Required for main LLM Engine)
   ANTHROPIC_API_KEY=sk-ant-api03-...

   # Optional Local Ollama Endpoint (For memory profiler)
   OLLAMA_BASE_URL=http://localhost:11434

   # Optional AWS S3 Memory Backup
   JARVIS_S3_SYNC_ENABLED=false
   JARVIS_S3_BUCKET_ARN=arn:aws:s3:::my-jarvis-transcripts-bucket
   AWS_ACCESS_KEY_ID=your_access_key_id
   AWS_SECRET_ACCESS_KEY=your_secret_access_key
   AWS_REGION=us-east-1

   # Developer Debug Telemetry (Set to 1 to enable prompt caching console logs)
   JARVIS_DEBUG_LLM=0
   ```

---

## 🎯 Running Jarvis

Run the main application:
```bash
source .venv/bin/activate
python3 main.py
```

### Install as an app (start at login)
```bash
bin/install-app
```
This sets Jarvis up for your user, no root needed:
- **Jarvis** in the app menu (with its icon) and `jarvis` on your PATH. Opening it while Jarvis is running brings the dashboard forward; only one Jarvis runs at a time.
- Linux: a systemd user service that starts Jarvis quietly at login (the dashboard stays closed until you open it) and restarts it if it crashes.
- Closing the dashboard only hides it; Jarvis keeps listening. Quit with `jarvis --quit` (or *Quit Jarvis* on the menu entry).

- macOS: a launchd agent (`~/Library/LaunchAgents/local.jarvis.plist`) that does the same; there's no app-menu entry, so run `jarvis` to open the dashboard. At login Jarvis runs as Python itself, so grant *that* Python Accessibility (the installer prints its path).

It runs from this folder and its `.venv`, so after a `git pull` restart it (`systemctl --user restart jarvis`, or on macOS `launchctl kickstart -k gui/$(id -u)/local.jarvis`). Logs go to `~/.local/share/jarvis/jarvis.log`. `bin/install-app --no-login` skips start at login; `bin/install-app --uninstall` removes it all.

### Voice Usage
1. Press and hold the talk shortcut (**`Super + Space`** on Linux, **`Option + Space`** on macOS) anywhere on your desktop.
2. Speak your command into your microphone.
3. Let go.

---

## 🛠️ Example Voice Commands

| Category | Example Command |
| :--- | :--- |
| **Visual Timers** | *"Set a timer for 10 minutes for Pizza"* |
| **Focus Profiles** | *"Create a focus profile named movies blocking Discord, Steam, and youtube.com"* |
| **Activate Focus** | *"Start locked in mode with movies profile for 3 hours"* |
| **Focus Status** | *"Status on movie mode"* |
| **Media Control** | *"Pause Spotify and resume video playback on Firefox"* |
| **Volume Control** | *"Set audio volume to 60%"* |
| **App Launching** | *"Open VS Code"* |
| **System Info** | *"Check system status"* |

---

## 🤝 External Ecosystem Addons

Jarvis interfaces with standalone external desktop tools:
* **[jarvis-timer](file:///home/carson/Documents/jarvis-timer)**: Standalone PySide6 desktop visual timer widget.
* **[locked-in](file:///home/carson/Documents/locked-in%20terminal%20commands)**: Multi-profile CLI focus and distraction blocker.

---

## 📄 License
Distributed under the MIT License.
