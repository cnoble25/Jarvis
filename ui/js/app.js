/* ==========================================================================
   Jarvis Desktop GUI Application Logic & IPC Client Bridge
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initKeybindRecorder();
  initFormHandlers();
  initMemoryProfileLoader();
  initTranscriptLogsLoader();
  initFastPathsLoader();
  loadSavedSettings();
});

/* Tab Switching Navigation */
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  const pages = document.querySelectorAll(".page-view");

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const targetPageId = item.getAttribute("data-page");
      
      navItems.forEach(nav => nav.classList.remove("active"));
      pages.forEach(page => page.classList.remove("active"));

      item.classList.add("active");
      const targetPage = document.getElementById(targetPageId);
      if (targetPage) {
        targetPage.classList.add("active");
      }
      if (targetPageId === "memory-page") {
        loadMemoryProfile();
      } else if (targetPageId === "transcripts-page" || targetPageId === "overview-page") {
        loadTranscriptLogs();
      }
    });
  });
}

/* Normalize physical hardware key codes (e.code) to prevent OS modifier masking */
function getNormalizedKeyName(e) {
  const code = e.code || "";

  if (code === "Space") return "Space";
  if (code.startsWith("Key")) return code.replace("Key", "");
  if (code.startsWith("Digit")) return code.replace("Digit", "");
  if (code.startsWith("Meta") || code.startsWith("OS") || e.key === "Meta") return "Super";
  if (code.startsWith("Alt") || e.key === "Alt") return "Alt";
  if (code.startsWith("Control") || e.key === "Control") return "Ctrl";
  if (code.startsWith("Shift") || e.key === "Shift") return "Shift";
  
  if (code === "Backspace") return "Backspace";
  if (code === "Tab") return "Tab";
  if (code === "Enter") return "Enter";

  return code ? code : (e.key ? e.key.toUpperCase() : null);
}

/* Sort keys so modifiers appear first (Super + Ctrl + Alt + Shift + MainKey) */
function sortKeyCombo(keySet) {
  const modOrder = ["Super", "Ctrl", "Alt", "Shift"];
  return Array.from(keySet).sort((a, b) => {
    let ia = modOrder.indexOf(a), ib = modOrder.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });
}

/* Interactive Hotkey & Keybinding Configurator (<KeybindRecorder />)
   Uses e.code physical hardware key tracking with 0.2 second (200ms) release buffer
*/
function initKeybindRecorder() {
  const recorderBox = document.getElementById("keybind-recorder");
  const displayBadge = document.getElementById("active-keybind-display");
  let isRecording = false;
  let activeKeys = new Set();
  let releaseTimer = null;

  if (!recorderBox) return;

  recorderBox.addEventListener("click", () => {
    isRecording = true;
    activeKeys.clear();
    if (releaseTimer) {
      clearTimeout(releaseTimer);
      releaseTimer = null;
    }
    displayBadge.textContent = "Press & Hold Shortcut Keys...";
    displayBadge.style.backgroundColor = "var(--accent-amber)";
  });

  window.addEventListener("keydown", (e) => {
    if (!isRecording) return;
    e.preventDefault();

    // Cancel pending release buffer timer while user is holding keys
    if (releaseTimer) {
      clearTimeout(releaseTimer);
      releaseTimer = null;
    }

    const keyName = getNormalizedKeyName(e);
    if (keyName) {
      activeKeys.add(keyName);
    }

    // Also check modifier flags explicitly
    if (e.metaKey) activeKeys.add("Super");
    if (e.ctrlKey) activeKeys.add("Ctrl");
    if (e.altKey) activeKeys.add("Alt");
    if (e.shiftKey) activeKeys.add("Shift");

    // Display live transient holding preview
    if (activeKeys.size > 0) {
      const sorted = sortKeyCombo(activeKeys);
      displayBadge.textContent = "Holding: " + sorted.join(" + ");
    }
  }, true);

  window.addEventListener("keyup", (e) => {
    if (!isRecording || activeKeys.size === 0) return;
    e.preventDefault();

    // 0.2 second (200ms) buffer timer upon key release before finalizing shortcut
    if (releaseTimer) clearTimeout(releaseTimer);

    releaseTimer = setTimeout(() => {
      if (activeKeys.size > 0) {
        const sorted = sortKeyCombo(activeKeys);
        const finalShortcut = sorted.join(" + ");
        displayBadge.textContent = finalShortcut;
        displayBadge.style.backgroundColor = "var(--accent-indigo)";
        isRecording = false;
        console.log("[KeybindRecorder] Finalized recorded shortcut after 0.2s release buffer:", finalShortcut);

        // Send update to Python daemon via IPC if pywebview API is available
        if (window.pywebview && window.pywebview.api) {
          window.pywebview.api.update_keybind(finalShortcut);
        }
      }
    }, 200); // 0.2 second buffer
  }, true);
}

/* QWebChannel IPC Client Bridge Initialization */
let jarvisBridge = null;

if (window.qt && window.qt.webChannelTransport) {
  new QWebChannel(window.qt.webChannelTransport, function(channel) {
    jarvisBridge = channel.objects.jarvisBridge;
    window.jarvisBridge = jarvisBridge;
    console.log("[IPC Bridge] QWebChannel connected to Python backend!");
    loadSavedSettings();
    loadMemoryProfile();
    loadTranscriptLogs();
  });
}

function sendIPCCommand(action, params = {}) {
  console.log(`[IPC Request] Action: '${action}'`, params);
  if (window.jarvisBridge && typeof window.jarvisBridge.call_ipc === "function") {
    window.jarvisBridge.call_ipc(action, JSON.stringify(params), function(responseJson) {
      console.log("[IPC Response]", responseJson);
    });
    return;
  }
  if (window.pywebview && window.pywebview.api) {
    if (action === "update_provider_config") window.pywebview.api.update_provider_config(params);
    else if (action === "update_keybind") window.pywebview.api.update_keybind(params.keybind);
  }
}

function updateTelemetryUI(settings) {
  if (!settings) return;
  
  // Update STT Engine Metric Card
  const sttEl = document.getElementById("metric-stt-provider");
  const sttSub = document.getElementById("metric-stt-subtext");
  if (sttEl) {
    if (settings.stt_provider === "gemini_stt") {
      sttEl.textContent = "Gemini Audio";
      if (sttSub) sttSub.textContent = "Cloud API";
    } else {
      sttEl.textContent = "Faster-Whisper";
      if (sttSub) sttSub.textContent = `Local (${settings.stt_model || 'base.en'})`;
    }
  }

  // Update LLM Router Metric Card
  const llmEl = document.getElementById("metric-llm-provider");
  const modelEl = document.getElementById("metric-model-name");
  if (llmEl) {
    if (settings.llm_provider === "gemini_llm") {
      llmEl.textContent = "Google Gemini";
      if (modelEl) modelEl.textContent = settings.llm_model || "gemini-3.6-flash";
    } else {
      const model = settings.llm_model || "qwen3.5:9b";
      llmEl.textContent = model.toLowerCase().includes("qwen") ? "Ollama (Qwen)" : "Ollama Local";
      if (modelEl) modelEl.textContent = model;
    }
  }
}

function loadSavedSettings() {
  if (window.jarvisBridge && typeof window.jarvisBridge.call_ipc === "function") {
    window.jarvisBridge.call_ipc("get_settings", "{}", function(resJson) {
      try {
        const res = JSON.parse(resJson);
        if (res.success && res.settings) {
          const s = res.settings;
          console.log("[Settings] Loaded saved settings from disk:", s);
          
          updateTelemetryUI(s);

          if (s.stt_provider && document.getElementById("setting-stt-provider")) {
            document.getElementById("setting-stt-provider").value = s.stt_provider;
          }
          if (s.llm_provider && document.getElementById("setting-llm-provider")) {
            const llmVal = s.llm_model ? `${s.llm_provider}:${s.llm_model}` : s.llm_provider;
            const selectEl = document.getElementById("setting-llm-provider");
            let matched = false;
            for (let opt of selectEl.options) {
              if (opt.value === llmVal) {
                selectEl.value = opt.value;
                matched = true;
                break;
              }
            }
            if (!matched) {
              for (let opt of selectEl.options) {
                if (opt.value.startsWith(s.llm_provider)) {
                  selectEl.value = opt.value;
                  break;
                }
              }
            }
          }
          if (s.memory_llm_provider && document.getElementById("setting-memory-llm-provider")) {
            const memSelect = document.getElementById("setting-memory-llm-provider");
            const targetVal = s.memory_llm_model ? `${s.memory_llm_provider}:${s.memory_llm_model}` : s.memory_llm_provider;
            let matched = false;
            for (let opt of memSelect.options) {
              if (opt.value === targetVal || opt.value === s.memory_llm_provider) {
                memSelect.value = opt.value;
                matched = true;
                break;
              }
            }
            if (!matched && s.memory_llm_provider === "inherit") {
              memSelect.value = "inherit";
            }
          }
          if (s.tts_voice && document.getElementById("setting-voice-select")) {
            document.getElementById("setting-voice-select").value = s.tts_voice;
          }
          if (s.gemini_api_key && document.getElementById("setting-gemini-key")) {
            document.getElementById("setting-gemini-key").value = s.gemini_api_key;
          }
          if (s.anthropic_api_key && document.getElementById("setting-anthropic-key")) {
            document.getElementById("setting-anthropic-key").value = s.anthropic_api_key;
          }
        }
      } catch (err) {
        console.error("[Settings Error] Failed to parse settings:", err);
      }
    });
  }
}

/* Custom Tool & Settings Form Handlers */
function initFormHandlers() {
  loadSavedSettings();

  const btnSaveSettings = document.getElementById("btn-save-settings");
  if (btnSaveSettings) {
    btnSaveSettings.addEventListener("click", () => {
      const stt = document.getElementById("setting-stt-provider")?.value || "faster_whisper";
      const llm = document.getElementById("setting-llm-provider")?.value || "ollama";
      const memLlm = document.getElementById("setting-memory-llm-provider")?.value || "inherit";
      const tts = document.getElementById("setting-tts-provider")?.value || "kokoro";
      const geminiKey = document.getElementById("setting-gemini-key")?.value.trim() || "";
      const anthropicKey = document.getElementById("setting-anthropic-key")?.value.trim() || "";
      const voice = document.getElementById("setting-voice-select")?.value || "af_kore";

      const payload = {
        stt_provider: stt,
        llm_provider: llm,
        memory_llm_provider: memLlm,
        tts_provider: tts,
        gemini_api_key: geminiKey,
        anthropic_api_key: anthropicKey,
        tts_voice: voice
      };

      console.log("[Settings] Saving provider config:", payload);
      sendIPCCommand("update_provider_config", payload);
      updateTelemetryUI(payload);

      alert("AI Provider Settings saved to ~/.config/jarvis/settings.json! Active engines updated live.");
    });
  }

  const addToolForm = document.getElementById("add-tool-form");
  if (addToolForm) {
    addToolForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const toolId = document.getElementById("tool-id-input").value.trim().toLowerCase().replace(/\s+/g, "_");
      const toolName = document.getElementById("tool-name-input").value.trim();
      const toolDesc = document.getElementById("tool-desc-input").value.trim();
      const toolCmd = document.getElementById("tool-cmd-input").value.trim();
      const toolExamples = document.getElementById("tool-examples-input").value.trim();
      const toolSpeak = document.getElementById("tool-speak-input").value.trim();

      const examplesList = [];
      if (toolExamples) {
        toolExamples.split("|").forEach(exStr => {
          const parts = exStr.split("->");
          const promptText = parts[0].replace(/User:\s*"?/, "").replace(/"?\s*$/, "").trim();
          examplesList.push({ user_prompt: promptText, expected_args: {} });
        });
      } else {
        examplesList.push({ user_prompt: toolName, expected_args: {} });
      }

      const manifestData = {
        id: toolId,
        name: toolName,
        version: "1.0.0",
        description: toolDesc,
        category: "custom",
        parameters: { type: "object", properties: {} },
        execution: { type: "command_template", template: toolCmd },
        examples: examplesList,
        risk_level: "SAFE",
        spoken_confirmation_template: toolSpeak
      };

      console.log("[ToolBuilder] Registering custom manifest:", manifestData);
      sendIPCCommand("register_custom_tool", manifestData);

      const tbody = document.getElementById("installed-tools-tbody");
      if (tbody) {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td><code>${toolId}</code></td>
          <td>
            <div style="font-weight: 600; color: #fff;">${toolName}</div>
            <div style="font-size: 12px; color: var(--text-secondary);">${toolDesc}</div>
          </td>
          <td><code>${toolCmd}</code></td>
          <td><div style="font-size: 12px; color: var(--accent-emerald);">${toolExamples || toolName}</div></td>
          <td><button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px;">Test Action</button></td>
        `;
        tbody.appendChild(row);
      }

      addToolForm.reset();
      alert(`Registered new custom tool manifest '${toolId}' and saved to ~/.config/jarvis/tools/${toolId}.json!`);
    });
  }

  const btnTestVoice = document.getElementById("btn-test-voice");
  if (btnTestVoice) {
    btnTestVoice.addEventListener("click", () => {
      alert("Testing Kokoro-ONNX voice output...");
    });
  }
}

function loadMemoryProfile() {
  if (window.jarvisBridge && typeof window.jarvisBridge.call_ipc === "function") {
    window.jarvisBridge.call_ipc("get_memory_profile", "{}", function(resJson) {
      try {
        const res = JSON.parse(resJson);
        if (res.success && res.content) {
          const container = document.getElementById("profile-md-container");
          if (container) {
            container.textContent = res.content;
            console.log("[MemoryProfile] Loaded user profile from disk!");
          }
        }
      } catch (err) {
        console.error("[MemoryProfile Error] Failed parsing profile:", err);
      }
    });
  }
}

/* Transcript Logs Loader & Live Auto-Refresh */
let cachedTranscripts = [];

function renderTranscriptLogs(transcripts) {
  cachedTranscripts = transcripts || [];

  // Update total turns metric on Overview page
  const totalTurnsEl = document.getElementById("metric-total-turns");
  if (totalTurnsEl) totalTurnsEl.textContent = cachedTranscripts.length;

  // Update Recent Voice Interaction Activity table on Overview page (latest 5 turns)
  const activityTbody = document.getElementById("activity-feed-tbody");
  if (activityTbody && cachedTranscripts.length > 0) {
    activityTbody.innerHTML = "";
    const recent = cachedTranscripts.slice(-5).reverse();
    recent.forEach(t => {
      const timeStr = t.timestamp ? t.timestamp.split("T")[1]?.slice(0, 8) || t.timestamp : "";
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${timeStr}</td>
        <td>${t.user_query || ""}</td>
        <td><span style="background: rgba(99,102,241,0.2); padding: 2px 8px; border-radius: 4px; color: #fff;">${t.tool_executed || "none"}</span></td>
        <td>${t.spoken_response || ""}</td>
      `;
      activityTbody.appendChild(row);
    });
  }

  // Update full Transcripts page list (#transcript-logs-list)
  const logsList = document.getElementById("transcript-logs-list");
  const searchInput = document.getElementById("transcript-search");
  const filterSelect = document.getElementById("transcript-filter");

  const query = searchInput?.value?.toLowerCase() || "";
  const filterVal = filterSelect?.value || "all";

  if (logsList) {
    logsList.innerHTML = "";

    if (cachedTranscripts.length === 0) {
      logsList.innerHTML = `<div class="card" style="padding: 16px; color: var(--text-secondary);">No transcript logs recorded yet. Hold Ctrl+Space to speak to Jarvis!</div>`;
      return;
    }

    const filtered = cachedTranscripts.slice().reverse().filter(t => {
      const q = (t.user_query || "").toLowerCase();
      const tool = (t.tool_executed || "").toLowerCase();
      const resp = (t.spoken_response || "").toLowerCase();
      const matchesQuery = !query || q.includes(query) || tool.includes(query) || resp.includes(query);
      const isSynced = Boolean(t.synced_to_s3 || t.s3_synced);

      if (!matchesQuery) return false;
      if (filterVal === "s3") return isSynced === true;
      return true;
    });

    filtered.forEach(t => {
      const card = document.createElement("div");
      card.className = "card";
      card.style.cssText = "padding: 14px; background: rgba(255,255,255,0.02); margin-bottom: 8px;";

      const timeStr = t.timestamp ? t.timestamp.replace("T", " ").slice(0, 19) : "";
      const isSynced = Boolean(t.synced_to_s3 || t.s3_synced);
      const syncedBadge = isSynced
        ? `<span style="background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); padding: 3px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3);">☁️ Synced to S3</span>`
        : `<span style="background: rgba(107, 114, 128, 0.15); color: #9ca3af; padding: 3px 10px; border-radius: 6px; font-size: 12px; border: 1px solid rgba(255,255,255,0.05);">💻 Local Only</span>`;

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span style="font-weight: 700; font-size: 14px; color: #fff;">"${t.user_query || ""}"</span>
          ${syncedBadge}
        </div>
        <div style="font-size: 12px; color: var(--text-secondary);">Tool: <code>${t.tool_executed || "none"}</code> | Time: ${timeStr} | Spoken: "${t.spoken_response || ""}"</div>
      `;
      logsList.appendChild(card);
    });
  }
}

function loadTranscriptLogs() {
  if (window.jarvisBridge && typeof window.jarvisBridge.call_ipc === "function") {
    window.jarvisBridge.call_ipc("get_transcripts", "{}", function(resJson) {
      try {
        const res = JSON.parse(resJson);
        if (res.transcripts) {
          renderTranscriptLogs(res.transcripts);
        }
      } catch (err) {}
    });
  }
}

function initTranscriptLogsLoader() {
  loadTranscriptLogs();

  const searchInput = document.getElementById("transcript-search");
  const filterSelect = document.getElementById("transcript-filter");

  if (searchInput) searchInput.addEventListener("input", () => renderTranscriptLogs(cachedTranscripts));
  if (filterSelect) filterSelect.addEventListener("change", () => renderTranscriptLogs(cachedTranscripts));

  // Auto-refresh transcript logs every 3 seconds after every conversation
  setInterval(() => {
    loadTranscriptLogs();
  }, 3000);
}

function loadFastPathRules() {
  if (window.jarvisBridge && typeof window.jarvisBridge.call_ipc === "function") {
    window.jarvisBridge.call_ipc("get_fast_path_rules", "{}", function(resJson) {
      try {
        const res = JSON.parse(resJson);
        const rulesListEl = document.getElementById("fast-path-rules-list");
        if (!rulesListEl) return;

        if (res.success && res.rules) {
          rulesListEl.innerHTML = "";
          if (res.rules.length === 0) {
            rulesListEl.innerHTML = `<div style="font-size: 13px; color: var(--text-secondary);">No fast-path rules registered yet.</div>`;
            return;
          }

          res.rules.forEach(rule => {
            const card = document.createElement("div");
            card.style.cssText = "padding: 12px; background: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;";

            const isSys = rule.is_system;
            const badge = isSys
              ? `<span style="background: rgba(99, 102, 241, 0.15); color: #818cf8; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">System Rule</span>`
              : `<span style="background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">🧠 Learned Shortcut</span>`;

            const escapeHtml = (str) => String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
            const triggersStr = (rule.triggers || []).map(t => `"${escapeHtml(t)}"`).join(", ");
            const actionStr = rule.tool && rule.tool !== "none" ? `Tool: <code>${escapeHtml(rule.tool)}</code>` : `Response: "${escapeHtml(rule.spoken_summary)}"`;

            let deleteBtn = "";
            if (!isSys) {
              deleteBtn = `<button class="btn btn-secondary btn-delete-fastpath" data-id="${escapeHtml(rule.id)}" style="padding: 4px 8px; font-size: 11px; color: #ef4444; border-color: rgba(239,68,68,0.3);">🗑️ Delete</button>`;
            }

            card.innerHTML = `
              <div>
                <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 4px;">
                  <span style="font-weight: 600; font-size: 13px; color: #fff;">${escapeHtml(rule.name || rule.id)}</span>
                  ${badge}
                </div>
                <div style="font-size: 12px; color: var(--text-secondary);">Triggers: <span style="color: #e2e8f0;">${triggersStr}</span></div>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Target: ${actionStr}</div>
              </div>
              <div>${deleteBtn}</div>
            `;
            rulesListEl.appendChild(card);
          });

          document.querySelectorAll(".btn-delete-fastpath").forEach(btn => {
            btn.addEventListener("click", (e) => {
              const ruleId = e.target.getAttribute("data-id");
              if (ruleId) {
                sendIPCCommand("delete_fast_path_rule", { rule_id: ruleId });
                setTimeout(loadFastPathRules, 300);
              }
            });
          });
        }
      } catch (err) {
        console.error("[FastPaths Error] Failed to parse rules:", err);
      }
    });
  }
}

function initFastPathsLoader() {
  loadFastPathRules();
  const btnRefresh = document.getElementById("btn-refresh-fastpaths");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", loadFastPathRules);
  }
  // Auto-refresh fast-paths every 5 seconds
  setInterval(() => {
    const activePage = document.querySelector(".page-view.active");
    if (activePage && activePage.id === "overview-page") {
      loadFastPathRules();
    }
  }, 5000);
}

/* Macro Modes Loader & Manager */
function loadMacroModes() {
  const container = document.getElementById("macros-container-grid");
  if (container && typeof sendIPCCommand === "function") {
    sendIPCCommand("get_macros", {}, (res) => {
      if (!res || !res.macros) return;
      container.innerHTML = "";
      const macros = res.macros;
      const keys = Object.keys(macros);

      if (keys.length === 0) {
        container.innerHTML = `<div style="color: var(--text-secondary); grid-column: 1 / -1;">No custom macro modes created yet. Use the form above or ask Jarvis: "Create gaming mode with Steam, Discord, and locked in mode".</div>`;
        return;
      }

      keys.forEach(k => {
        const m = macros[k];
        const steps = m.steps || m.apps || [];
        const card = document.createElement("div");
        card.className = "card";
        card.style.padding = "16px";
        card.style.display = "flex";
        card.style.flexDirection = "column";
        card.style.justify = "space-between";

        const escapeHtml = (str) => String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        const stepsBadges = steps.map(s => `<span style="background: rgba(99,102,241,0.15); border: 1px solid rgba(99,102,241,0.3); color: #a5b4fc; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-right: 4px; margin-bottom: 4px; display: inline-block;">${escapeHtml(s)}</span>`).join("");

        card.innerHTML = `
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <h3 style="font-size: 15px; font-weight: 700; color: #fff; margin: 0;">⚡ ${escapeHtml(m.name || m.id)}</h3>
              <span style="font-size: 11px; background: rgba(16,185,129,0.15); color: #34d399; padding: 2px 6px; border-radius: 4px;">&lt;1ms FastPath</span>
            </div>
            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 12px;">Steps: ${stepsBadges}</div>
            ${m.directory ? `<div style="font-size: 11px; color: var(--text-muted); margin-bottom: 12px;">📂 Working Dir: <code>${escapeHtml(m.directory)}</code></div>` : ''}
            <div style="font-size: 11px; color: var(--text-muted); font-family: monospace; word-break: break-all;">Script: ${escapeHtml(m.script_path || '')}</div>
          </div>
          <div style="display: flex; gap: 8px; margin-top: 16px;">
            <button class="btn btn-primary btn-run-macro" data-id="${escapeHtml(m.id)}" style="flex: 1; padding: 6px 12px; font-size: 12px;">▶ Run Macro</button>
            <button class="btn btn-secondary btn-delete-macro" data-id="${escapeHtml(m.id)}" style="padding: 6px 12px; font-size: 12px; color: var(--accent-rose);">🗑️</button>
          </div>
        `;
        container.appendChild(card);
      });

      document.querySelectorAll(".btn-run-macro").forEach(btn => {
        btn.addEventListener("click", (e) => {
          const id = e.target.getAttribute("data-id");
          if (id) {
            sendIPCCommand("run_macro", { name: id });
            alert(`Executed macro '${id}'!`);
          }
        });
      });

      document.querySelectorAll(".btn-delete-macro").forEach(btn => {
        btn.addEventListener("click", (e) => {
          const id = e.target.getAttribute("data-id");
          if (id && confirm(`Delete macro mode '${id}'?`)) {
            sendIPCCommand("delete_macro", { name: id });
            setTimeout(loadMacroModes, 300);
          }
        });
      });
    });
  }
}

function initMacrosLoader() {
  loadMacroModes();
  const createForm = document.getElementById("create-macro-form");
  if (createForm) {
    createForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = document.getElementById("macro-name-input").value.trim();
      const stepsRaw = document.getElementById("macro-steps-input").value.trim();
      const dir = document.getElementById("macro-dir-input").value.trim();

      const steps = stepsRaw.split(/[|,]/).map(s => s.trim()).filter(Boolean);

      sendIPCCommand("save_macro", { name, steps, directory: dir });
      createForm.reset();
      setTimeout(loadMacroModes, 400);
      alert(`Created and compiled macro mode '${name}' with ${steps.length} steps!`);
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initFormHandlers();
  initFastPathsLoader();
  initMacrosLoader();
});
