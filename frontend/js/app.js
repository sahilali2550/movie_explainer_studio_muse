// AutoExplainer AI SaaS - Frontend Studio Logic

const $ = id => document.getElementById(id);

// SECURITY: attach the server-injected API token to every /api/* call.
// window.__API_TOKEN__ is set by the backend when it serves index.html.
(function () {
  const _fetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    opts = opts || {};
    if (typeof url === "string" && url.indexOf("/api/") === 0 && window.__API_TOKEN__) {
      const headers = new Headers(opts.headers || {});
      headers.set("X-API-Token", window.__API_TOKEN__);
      opts.headers = headers;
    }
    return _fetch(url, opts);
  };
})();

function apiUrlWithToken(url) {
  if (window.__API_TOKEN__ && url.indexOf("/api/") === 0) {
    const sep = url.indexOf("?") === -1 ? "?" : "&";
    return url + sep + "token=" + encodeURIComponent(window.__API_TOKEN__);
  }
  return url;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

let currentLangMode = 'single'; // 'single' or 'multi'
let currentVoiceMode = 'ai'; // 'ai', 'custom_audio', 'clone'
let batchResults = null;
let activeBatchLang = 'en';

// Multi-Script & Multi-Voice State for Global Multiplier Studio
let multiScripts = {};          // maps lang -> script text
let multiVoices = {};           // maps lang -> voice id
let activeScriptTabLang = 'en'; // currently active script tab

// Language Metadata with Flag & Name
const LANG_META = {
  "en": { name: "English", flag: "🇺🇸" },
  "es": { name: "Spanish", flag: "🇪🇸" },
  "ur": { name: "Urdu", flag: "🇵🇰" },
  "hi": { name: "Hindi", flag: "🇮🇳" },
  "id": { name: "Indonesian", flag: "🇮🇩" },
  "ar": { name: "Arabic", flag: "🇸🇦" },
  "pt": { name: "Portuguese", flag: "🇧🇷" },
  "fr": { name: "French", flag: "🇫🇷" },
  "de": { name: "German", flag: "🇩🇪" },
  "ru": { name: "Russian", flag: "🇷🇺" },
  "vi": { name: "Vietnamese", flag: "🇻🇳" },
  "th": { name: "Thai", flag: "🇹🇭" },
  "ja": { name: "Japanese", flag: "🇯🇵" },
  "ko": { name: "Korean", flag: "🇰🇷" }
};

// Voice Map by Language
const VOICES_MAP = {
  "ur": [
    { id: "ur-PK-AsadNeural", name: "Asad (Deep Cinema Male)" },
    { id: "ur-PK-UzmaNeural", name: "Uzma (Warm Storyteller Female)" },
    { id: "ur-IN-SalmanNeural", name: "Salman (Expressive Male)" }
  ],
  "hi": [
    { id: "hi-IN-MadhurNeural", name: "Madhur (Cinematic Recapper Male)" },
    { id: "hi-IN-SwaraNeural", name: "Swara (Engaging Female)" }
  ],
  "es": [
    { id: "es-MX-DaliaNeural", name: "Dalia (Mexico - Resumen Narrator)" },
    { id: "es-ES-AlvaroNeural", name: "Alvaro (Spain - Deep Dramatic Male)" }
  ],
  "id": [
    { id: "id-ID-ArdiNeural", name: "Ardi (Alur Cerita Film Specialist Male)" },
    { id: "id-ID-GadisNeural", name: "Gadis (Female Storyteller)" }
  ],
  "en": [
    { id: "en-US-ChristopherNeural", name: "Christopher (Deep Hollywood Trailer Male)" },
    { id: "en-US-JennyNeural", name: "Jenny (Expressive Female)" },
    { id: "en-GB-RyanNeural", name: "Ryan (British Documentary Male)" }
  ],
  "ar": [
    { id: "ar-SA-HamedNeural", name: "Hamed (Saudi - Deep Documentary Male)" },
    { id: "ar-EG-ShakirNeural", name: "Shakir (Egyptian - Expressive Male)" }
  ],
  "pt": [
    { id: "pt-BR-AntonioNeural", name: "Antonio (Brazil - Rapid Recap Male)" },
    { id: "pt-BR-FranciscaNeural", name: "Francisca (Female)" }
  ],
  "fr": [
    { id: "fr-FR-HenriNeural", name: "Henri (French Narrator Male)" },
    { id: "fr-FR-DeniseNeural", name: "Denise (Female)" }
  ],
  "de": [
    { id: "de-DE-ConradNeural", name: "Conrad (German Cinematic Male)" },
    { id: "de-DE-KatjaNeural", name: "Katja (Female)" }
  ],
  "ru": [
    { id: "ru-RU-DmitryNeural", name: "Dmitry (Russian Thriller Male)" },
    { id: "ru-RU-SvetlanaNeural", name: "Svetlana (Female)" }
  ],
  "vi": [
    { id: "vi-VN-NamMinhNeural", name: "Nam Minh (Vietnamese Male)" }
  ],
  "th": [
    { id: "th-TH-NiwatNeural", name: "Niwat (Thai Recap Male)" }
  ],
  "ja": [
    { id: "ja-JP-KeitaNeural", name: "Keita (Japanese Movie Explainer Male)" }
  ],
  "ko": [
    { id: "ko-KR-InJoonNeural", name: "InJoon (Korean Recap Male)" }
  ]
};

// Initialize
window.addEventListener('DOMContentLoaded', () => {
  onLanguageChange();
  updateEstimatedWordCount();
  $('script-area').addEventListener('input', onScriptAreaInput);
  const fileInput = $('input-file');
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) {
        const rawName = fileInput.files[0].name;
        const cleanName = rawName.replace(/\.[^/.]+$/, "").replace(/[-_]+/g, " ").trim();
        const titleInput = $('input-title');
        if (titleInput && (!titleInput.value.trim() || titleInput.value === 'Movie Story Recap' || titleInput.value === 'Movie Story Explanation')) {
          titleInput.value = cleanName;
        }
      }
    });
  }
  const urlInput = $('input-url');
  if (urlInput) {
    urlInput.addEventListener('input', onSourceInputPastedOrChanged);
    urlInput.addEventListener('paste', () => setTimeout(() => triggerContextAutoDetect(true), 250));
  }
  const transcriptInput = $('input-transcript');
  if (transcriptInput) {
    transcriptInput.addEventListener('input', onSourceInputPastedOrChanged);
    transcriptInput.addEventListener('paste', () => setTimeout(() => triggerContextAutoDetect(true), 250));
  }

  startLogPolling();
  checkAiStatus();
  checkYouTubeStatus();
  onGenreChange();
  onAudioModeChange();
});

function switchSourceTab(type) {
  if (type === 'url') {
    $('tab-url').classList.add('active');
    $('tab-file').classList.remove('active');
    $('group-url').style.display = 'block';
    $('group-file').style.display = 'none';
  } else {
    $('tab-file').classList.add('active');
    $('tab-url').classList.remove('active');
    $('group-url').style.display = 'none';
    $('group-file').style.display = 'block';
  }
}

function onScriptAreaInput() {
  updateScriptStats();
  if (currentLangMode === 'multi') {
    multiScripts[activeScriptTabLang] = $('script-area').value;
    const tabBtn = document.querySelector(`.script-tab-btn[data-lang="${activeScriptTabLang}"]`);
    if (tabBtn) {
      const meta = LANG_META[activeScriptTabLang] || { name: activeScriptTabLang.toUpperCase(), flag: '🌐' };
      const hasScript = $('script-area').value.trim().length > 0;
      tabBtn.innerHTML = `${meta.flag} ${meta.name} ${hasScript ? '✓' : ''}`;
    }
  }
}

function onGenreChange() {
  const genre = $('select-genre') ? $('select-genre').value : 'movie_recap';
  const badge = $('genre-badge');
  const titleInput = $('input-title');
  const labelTitle = $('label-title-text');
  const personaSelect = $('select-persona');

  const configs = {
    'movie_recap': {
      badge: '🎬 Movie/Series',
      placeholder: 'e.g. Inception (2010) or Crime Thriller Story',
      label: 'Movie / Story Title',
      persona: 'hollywood_trailer'
    },
    'biography': {
      badge: '👤 Biography',
      placeholder: 'e.g. Steve Jobs, Nikola Tesla, or Babur Azam',
      label: 'Person / Icon Name',
      persona: 'documentary'
    },
    'documentary': {
      badge: '🔍 Documentary',
      placeholder: 'e.g. Mystery of Bermuda Triangle or Apollo 11',
      label: 'Investigation / Event Title',
      persona: 'documentary'
    },
    'true_crime': {
      badge: '🕵️ True Crime',
      placeholder: 'e.g. The Zodiac Mystery or Flight 370 Disappearance',
      label: 'Crime / Mystery Case Title',
      persona: 'documentary'
    },
    'tech_science': {
      badge: '💡 Tech / Business',
      placeholder: 'e.g. How NVIDIA Conquered AI or The Fall of Nokia',
      label: 'Company / Tech Subject',
      persona: 'viral_fast'
    },
    'video_essay': {
      badge: '💡 Video Essay',
      placeholder: 'e.g. How Apple Secretly Won AI, or Kodak Collapse',
      label: 'Case Study / Essay Title',
      persona: 'viral_fast'
    }
  };

  const cfg = configs[genre] || configs['movie_recap'];
  if (badge) badge.textContent = cfg.badge;
  if (labelTitle) labelTitle.textContent = cfg.label;
  if (titleInput && (!titleInput.value.trim() || titleInput.value.startsWith('e.g.'))) {
    titleInput.placeholder = cfg.placeholder;
  }
  if (personaSelect && personaSelect.value !== 'auto') {
    personaSelect.value = cfg.persona;
  }
}

function onAudioModeChange() {
  const mode = $('select-audio-mode') ? $('select-audio-mode').value : 'hybrid';
  const bgmSelect = $('select-bgm');
  const bgmHint = $('bgm-status-hint');

  if (mode === 'sfx_only') {
    if (bgmSelect) bgmSelect.disabled = true;
    if (bgmHint) {
      bgmHint.textContent = 'Muted (Pure SFX Mode active • 0% Music)';
      bgmHint.style.color = '#38bdf8';
    }
  } else {
    if (bgmSelect) bgmSelect.disabled = false;
    if (bgmHint) {
      bgmHint.textContent = 'Ducked under voiceover';
      bgmHint.style.color = 'var(--text-muted)';
    }
  }
}

const LANGUAGE_WPM = {
  ur: 200, hi: 160, es: 165, pt: 160, id: 155, vi: 160,
  en: 150, fr: 150, it: 155, tr: 155, de: 140, ar: 145,
  ru: 135, th: 155, ja: 280, ko: 200
};

function updateEstimatedWordCount() {
  const durVal = parseInt($('select-duration') ? $('select-duration').value : 3) || 3;
  const speedVal = $('select-speed') ? $('select-speed').value : 'fast';
  const lang = currentLangMode === 'multi' ? (activeScriptTabLang || 'en') : ($('select-lang') ? $('select-lang').value : 'en');
  
  const baseWpm = LANGUAGE_WPM[lang] || 150;
  const speedMult = speedVal === 'ultra_fast' ? 1.25 : (speedVal === 'fast' ? 1.15 : 1.0);
  const targetWords = Math.round(durVal * baseWpm * speedMult);
  const badge = $('target-words-badge');
  if (badge) {
    const rateLabel = speedVal === 'ultra_fast' ? '+20% Speed' : (speedVal === 'fast' ? '+15% Speed' : 'Normal');
    badge.textContent = `~${targetWords} Words (${rateLabel} • ${lang.toUpperCase()})`;
  }
}

// Top Studio Mode Switcher
function switchStudioMode(mode) {
  currentLangMode = mode;
  const singleBtn = $('btn-studio-single');
  const multiBtn = $('btn-studio-multi');
  const autoBtn = $('btn-studio-autopilot');
  const descEl = $('studio-mode-desc');
  const singleGrp = $('group-single-lang');
  const multiGrp = $('group-multi-lang');
  const scriptControls = $('multi-script-controls');
  const boxVoiceAi = $('box-voice-ai');
  const voiceCastingSection = $('multi-voice-casting-section');
  const renderBtnText = $('btn-render-text');
  const scriptAreaLabel = $('script-area-label');
  const swarmBar = $('agent-swarm-bar');
  const btnRunAutopilot = $('btn-run-autopilot');
  const btnGenScript = $('btn-gen-script');

  if (mode === 'autopilot') {
    if (autoBtn) autoBtn.classList.add('active');
    if (singleBtn) singleBtn.classList.remove('active');
    if (multiBtn) multiBtn.classList.remove('active');
    if (descEl) descEl.textContent = "⚡ 1-Click Autopilot Mode: 5-Agent Swarm auto-detects context, writes viral script with dynamic SFX, and renders video in 1 click. You retain full manual control of Voice & Speed!";
    if (swarmBar) swarmBar.style.display = 'block';
    if (singleGrp) singleGrp.style.display = 'block';
    if (multiGrp) multiGrp.style.display = 'none';
    if (scriptControls) scriptControls.style.display = 'none';
    if (boxVoiceAi) boxVoiceAi.style.display = 'block';
    if (voiceCastingSection) voiceCastingSection.style.display = 'none';
    const exportControls = $('export-mode-controls');
    if (exportControls) exportControls.style.display = 'none';
    if (btnRunAutopilot) btnRunAutopilot.style.display = 'block';
    if (btnGenScript) btnGenScript.style.display = 'none';
  } else if (mode === 'single') {
    if (singleBtn) singleBtn.classList.add('active');
    if (multiBtn) multiBtn.classList.remove('active');
    if (autoBtn) autoBtn.classList.remove('active');
    if (descEl) descEl.textContent = "Standard Mode: Focus on a single high-impact story recap with full manual control and live voice audition.";
    if (swarmBar) swarmBar.style.display = 'none';
    if (singleGrp) singleGrp.style.display = 'block';
    if (multiGrp) multiGrp.style.display = 'none';
    if (scriptControls) scriptControls.style.display = 'none';
    if (boxVoiceAi) boxVoiceAi.style.display = 'block';
    if (voiceCastingSection) voiceCastingSection.style.display = 'none';
    const exportControls = $('export-mode-controls');
    if (exportControls) exportControls.style.display = 'none';
    if (btnRunAutopilot) btnRunAutopilot.style.display = 'none';
    if (btnGenScript) btnGenScript.style.display = 'block';
    if (renderBtnText) renderBtnText.textContent = "🚀 2. Render Explainer & Thumbnails";
    if (scriptAreaLabel) scriptAreaLabel.textContent = "Story Narration & Scene Timestamps";

    const singleLang = $('select-lang') ? $('select-lang').value : 'ur';
    if (multiScripts[singleLang]) {
      $('script-area').value = multiScripts[singleLang];
    }
    updateScriptStats();
  } else {
    if (multiBtn) multiBtn.classList.add('active');
    if (singleBtn) singleBtn.classList.remove('active');
    if (autoBtn) autoBtn.classList.remove('active');
    if (descEl) descEl.textContent = "Global Multiplier: Generate localized videos, multi-script translations, custom voices, and 3 thumbnails across multiple languages simultaneously.";
    if (swarmBar) swarmBar.style.display = 'none';
    if (singleGrp) singleGrp.style.display = 'none';
    if (multiGrp) multiGrp.style.display = 'block';
    if (scriptControls) scriptControls.style.display = 'block';
    if (boxVoiceAi) boxVoiceAi.style.display = 'none';
    if (voiceCastingSection) voiceCastingSection.style.display = 'block';
    const exportControls = $('export-mode-controls');
    if (exportControls) exportControls.style.display = 'block';
    if (btnRunAutopilot) btnRunAutopilot.style.display = 'none';
    if (btnGenScript) btnGenScript.style.display = 'block';

    const currentText = $('script-area').value;
    if (currentText.trim() && !multiScripts[activeScriptTabLang]) {
      multiScripts[activeScriptTabLang] = currentText;
    }

    refreshMultiplierDeck();
  }
}

// Auto-Detect Story Context via Agent 1 (Detective)
let autoDetectDebounceTimer = null;

async function triggerContextAutoDetect(isAuto = false) {
  const url = $('input-url') ? $('input-url').value.trim() : '';
  const transcript = $('input-transcript') ? $('input-transcript').value.trim() : '';
  const titleHint = $('input-title') ? $('input-title').value.trim() : '';

  if (!url && !transcript) {
    if (!isAuto) {
      alert("Please enter a YouTube URL or paste a transcript first to auto-detect context!");
    }
    return;
  }

  const detectiveStatus = $('agent-status-detective');
  if (detectiveStatus) {
    detectiveStatus.textContent = "Analyzing...";
    detectiveStatus.style.color = "#38bdf8";
  }

  try {
    const formData = new FormData();
    if (transcript) formData.append("transcript_text", transcript);
    if (url) formData.append("url", url);
    if (titleHint) formData.append("title_hint", titleHint);

    const res = await fetch("/api/v1/explainer/auto-detect-context", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data && data.success) {
      if (data.title && $('input-title') && (!$('input-title').value || $('input-title').value.startsWith('e.g.'))) {
        $('input-title').value = data.title;
      }
      if (data.genre && $('select-genre')) {
        $('select-genre').value = data.genre;
        onGenreChange();
      }
      if (data.persona && $('select-persona')) {
        $('select-persona').value = data.persona;
      }
      if (data.mood && $('select-bgm')) {
        $('select-bgm').value = data.mood;
      }
      if (detectiveStatus) {
        detectiveStatus.textContent = `Done ✓ (${data.genre || 'Detected'})`;
        detectiveStatus.style.color = "#34d399";
      }
    }
  } catch (err) {
    console.warn("Auto-detect context notice:", err);
    if (detectiveStatus) {
      detectiveStatus.textContent = "Ready";
      detectiveStatus.style.color = "#94a3b8";
    }
  }
}

function onSourceInputPastedOrChanged() {
  clearTimeout(autoDetectDebounceTimer);
  autoDetectDebounceTimer = setTimeout(() => {
    triggerContextAutoDetect(true);
  }, 900);
}

// Multi-Agent Swarm Status Helper
function updateSwarmAgentStatus(agentId, statusText, color = "#38bdf8") {
  const el = $(`agent-status-${agentId}`);
  if (el) {
    el.textContent = statusText;
    el.style.color = color;
  }
}

// 1-Click Master Autopilot Workflow
let autopilotCountdownTimer = null;
let autopilotCountdownSeconds = 5;

async function runAutopilotWorkflow() {
  const url = $('input-url') ? $('input-url').value.trim() : '';
  const transcript = $('input-transcript') ? $('input-transcript').value.trim() : '';
  const fileInput = $('input-file');
  const hasFile = fileInput && fileInput.files && fileInput.files[0];

  if (!url && !transcript && !hasFile) {
    alert("Please provide a YouTube Link, paste a Transcript, or select a local video file.");
    return;
  }

  const btn = $('btn-run-autopilot');
  const btnText = $('btn-run-autopilot-text');
  if (btn) btn.disabled = true;
  if (btnText) btnText.textContent = "⚡ Swarm Active (Processing...)";

  const swarmBar = $('agent-swarm-bar');
  if (swarmBar) swarmBar.style.display = 'block';

  updateSwarmAgentStatus('detective', 'Analyzing Context...', '#38bdf8');
  updateSwarmAgentStatus('screenwriter', 'Writing Narration...', '#38bdf8');
  updateSwarmAgentStatus('hook', 'Testing Virality...', '#f59e0b');
  updateSwarmAgentStatus('art', 'Finding Climax...', '#38bdf8');
  updateSwarmAgentStatus('seo', 'Building Tags...', '#38bdf8');

  const formData = new FormData();
  if (url) formData.append("url", url);
  if (transcript) formData.append("transcript_text", transcript);
  if (hasFile) formData.append("local_file", fileInput.files[0]);

  const targetLang = $('select-lang') ? $('select-lang').value : 'ur';
  const voice = $('select-voice') ? $('select-voice').value : 'ur-PK-AsadNeural';
  const speed = $('select-speed') ? $('select-speed').value : 'fast';
  const duration = $('select-duration') ? $('select-duration').value : '3';
  const resolution = $('select-resolution') ? $('select-resolution').value : '720p';
  const aspect = $('select-aspect') ? $('select-aspect').value : 'vertical';
  const watermark = $('input-watermark') ? $('input-watermark').value.trim() : '';
  const audioMode = $('select-audio-mode') ? $('select-audio-mode').value : 'hybrid';
  const notes = $('input-notes') ? $('input-notes').value.trim() : '';

  formData.append("target_lang", targetLang);
  formData.append("narrator_voice", voice);
  formData.append("speech_velocity", speed);
  formData.append("duration_mins", duration);
  formData.append("resolution", resolution);
  formData.append("aspect_ratio", aspect);
  formData.append("watermark", watermark);
  formData.append("audio_mode", audioMode);
  formData.append("notes", notes);

  const progressCard = $('render-progress-card');
  const progressText = $('progress-step-text');
  const progressPct = $('progress-pct');
  const progressFill = $('progress-bar-fill');

  let autopilotProgressInterval = null;
  const autopilotSteps = [
    { pct: 35, text: "🤖 5-Agent Swarm crafting viral screenplay & beats..." },
    { pct: 55, text: "⚡ Downloading highlight scene cuts from video stream..." },
    { pct: 70, text: "🎙️ Synthesizing Neural AI voiceover narration..." },
    { pct: 82, text: "🔊 Composing soundtrack & dynamic SFX audio master..." },
    { pct: 90, text: "🛡️ Rendering final explainer video with anti-copyright armor..." },
    { pct: 95, text: "🖼️ Generating 3 viral climax thumbnails & SEO package..." }
  ];
  let autoStepIdx = 0;
  if (progressCard) progressCard.style.display = 'block';
  if (progressText) progressText.textContent = autopilotSteps[0].text;
  if (progressPct) progressPct.textContent = `${autopilotSteps[0].pct}%`;
  if (progressFill) progressFill.style.width = `${autopilotSteps[0].pct}%`;

  autopilotProgressInterval = setInterval(() => {
    if (autoStepIdx < autopilotSteps.length) {
      const step = autopilotSteps[autoStepIdx];
      if (progressFill) progressFill.style.width = `${step.pct}%`;
      if (progressPct) progressPct.textContent = `${step.pct}%`;
      if (progressText) progressText.textContent = step.text;
      autoStepIdx++;
    } else {
      let cur = parseInt(progressPct ? progressPct.textContent : '95', 10) || 95;
      if (cur < 98) {
        cur += 1;
        if (progressFill) progressFill.style.width = `${cur}%`;
        if (progressPct) progressPct.textContent = `${cur}%`;
      }
      const waitTexts = [
        "⚡ Finalizing video stream encoding...",
        "🎬 Burning high-definition styled subtitles...",
        "🎨 Finalizing high-CTR thumbnail composite...",
        "✨ Polishing final audio master..."
      ];
      const waitIdx = Math.floor((Date.now() / 4000) % waitTexts.length);
      if (progressText) progressText.textContent = waitTexts[waitIdx];
    }
  }, 3500);

  try {
    const res = await fetch("/api/v1/explainer/run-autopilot", {
      method: "POST",
      body: formData
    });

    const resText = await res.text();
    let data;
    try {
      data = JSON.parse(resText);
    } catch (parseErr) {
      throw new Error(`Server returned error (HTTP ${res.status}): ${resText.slice(0, 150)}`);
    }
    if (!res.ok || !data.success) {
      throw new Error(data.detail || data.error || "Autopilot pipeline encountered an error.");
    }
    if (autopilotProgressInterval) clearInterval(autopilotProgressInterval);

    updateSwarmAgentStatus('detective', 'Done ✓', '#34d399');
    updateSwarmAgentStatus('screenwriter', 'Done ✓', '#34d399');
    updateSwarmAgentStatus('hook', 'Viral Platinum ✓', '#34d399');
    updateSwarmAgentStatus('art', 'Done ✓', '#34d399');
    updateSwarmAgentStatus('seo', 'Done ✓', '#34d399');

    if (data.script && $('script-area')) {
      $('script-area').value = data.script;
      updateScriptStats();
    }
    if (data.hook_score && $('hook-score-badge')) {
      $('hook-score-badge').textContent = `${data.hook_score.final_score || data.hook_score.score || 92}/100 🔥 Viral Grade`;
      $('hook-score-badge').className = 'hook-badge high';
    }

    if (data.seo_pack) {
      if (data.seo_pack.viral_titles && data.seo_pack.viral_titles[0] && $('meta-title-1')) {
        $('meta-title-1').value = data.seo_pack.viral_titles[0];
      }
      if (data.seo_pack.description && $('meta-desc')) {
        $('meta-desc').value = data.seo_pack.description;
      }
      if (data.seo_pack.tags && $('meta-tags')) {
        $('meta-tags').value = Array.isArray(data.seo_pack.tags) ? data.seo_pack.tags.join(', ') : data.seo_pack.tags;
      }
      if (data.seo_pack.pinned_comment && $('meta-comment')) {
        $('meta-comment').value = data.seo_pack.pinned_comment;
      }
      ['meta-title-1', 'meta-desc', 'meta-tags', 'meta-comment'].forEach(id => {
        const el = $(id);
        if (el) el.setAttribute('dir', 'auto');
      });
    }

    if (progressPct) progressPct.textContent = "100%";
    if (progressFill) progressFill.style.width = "100%";
    if (progressText) progressText.textContent = "🎉 Explainer video & thumbnail pack ready!";

    setTimeout(() => {
      if (progressCard) progressCard.style.display = 'none';
      renderAutopilotResults(data);
    }, 600);

  } catch (err) {
    if (autopilotProgressInterval) clearInterval(autopilotProgressInterval);
    alert("Autopilot error: " + err.message);
    if (progressCard) progressCard.style.display = 'none';
  } finally {
    if (btn) btn.disabled = false;
    if (btnText) btnText.textContent = "🚀 Run 1-Click Autopilot Explainer";
  }
}

function renderAutopilotResults(data) {
  const hub = $('results-hub');
  if (!hub) return;
  hub.style.display = 'block';

  const player = $('result-player');
  const dlBtn = $('btn-download-video');
  if (player && data.video_url) {
    player.src = data.video_url;
    if (data.thumbnails && data.thumbnails[0]) {
      player.poster = data.thumbnails[0].url;
    }
    player.load();
  }
  if (dlBtn && data.video_url) {
    dlBtn.href = data.video_url;
  }

  const thumbsContainer = $('thumbnails-container');
  if (thumbsContainer && data.thumbnails) {
    thumbsContainer.innerHTML = '';
    data.thumbnails.forEach((t, i) => {
      const card = document.createElement('div');
      card.className = 'thumbnail-card';
      card.innerHTML = `
        <img src="${t.url}" style="width:100%; border-radius:8px; display:block;" alt="Thumbnail ${i+1}">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
          <span style="font-size:0.75rem; color:#cbd5e1;">Option ${i+1}</span>
          <a href="${t.url}" download class="btn-secondary" style="padding:2px 8px; font-size:0.70rem; text-decoration:none;">⬇️ Save</a>
        </div>
      `;
      thumbsContainer.appendChild(card);
    });
  }

  hub.scrollIntoView({ behavior: 'smooth' });
}

function proceedAutopilotRenderNow() {
  const countdownCard = $('autopilot-countdown-card');
  if (countdownCard) countdownCard.style.display = 'none';
  if (autopilotCountdownTimer) clearInterval(autopilotCountdownTimer);
}

function pauseAutopilotRender() {
  const countdownCard = $('autopilot-countdown-card');
  if (countdownCard) countdownCard.style.display = 'none';
  if (autopilotCountdownTimer) clearInterval(autopilotCountdownTimer);
  alert("Auto-render paused. You can now review or edit the generated script and click '2. Render Explainer' whenever you're ready!");
}

// Backward compatibility alias
function switchLangMode(mode) {
  switchStudioMode(mode);
}

// 1-Click Viral Presets
function applyLangPreset(preset) {
  const presetMap = {
    'viral_big3': ['en', 'es', 'ur'],
    'high_cpm': ['en', 'de', 'fr', 'ar'],
    'asian_growth': ['id', 'hi', 'vi', 'th'],
    'all': ['en', 'es', 'ur', 'id', 'hi', 'ar', 'pt', 'fr', 'de', 'ru', 'vi', 'th'],
    'clear': ['en']
  };

  const selected = presetMap[preset] || ['en', 'es', 'ur'];
  document.querySelectorAll('.batch-lang-cb').forEach(cb => {
    cb.checked = selected.includes(cb.value);
  });

  ['big3', 'cpm', 'asia'].forEach(p => {
    const chip = $(`chip-preset-${p}`);
    if (chip) chip.classList.remove('active');
  });
  if (preset === 'viral_big3' && $('chip-preset-big3')) $('chip-preset-big3').classList.add('active');
  if (preset === 'high_cpm' && $('chip-preset-cpm')) $('chip-preset-cpm').classList.add('active');
  if (preset === 'asian_growth' && $('chip-preset-asia')) $('chip-preset-asia').classList.add('active');

  onBatchLangChange();
}

function onBatchLangChange() {
  const cbs = document.querySelectorAll('.batch-lang-cb:checked');
  const count = cbs.length;
  const badge = $('batch-count-badge');
  if (badge) badge.textContent = `${count} Selected`;

  const renderBtnText = $('btn-render-text');
  if (renderBtnText && currentLangMode === 'multi') {
    renderBtnText.textContent = `🌐 2. Launch Global Multiplier (${count} Languages)`;
  }

  if (currentLangMode === 'multi') {
    refreshMultiplierDeck();
  }
}

// Refresh Multi-Script Deck tabs and Multi-Voice Casting Cards
function refreshMultiplierDeck() {
  const cbs = document.querySelectorAll('.batch-lang-cb:checked');
  let checkedLangs = Array.from(cbs).map(cb => cb.value);
  if (checkedLangs.length === 0) checkedLangs = ['en'];

  if (!checkedLangs.includes(activeScriptTabLang)) {
    activeScriptTabLang = checkedLangs[0];
  }

  // 1. Render Script Tabs
  const tabsBar = $('multi-script-tabs-bar');
  if (tabsBar) {
    tabsBar.innerHTML = '';
    checkedLangs.forEach(lang => {
      const meta = LANG_META[lang] || { name: lang.toUpperCase(), flag: '🌐' };
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `script-tab-btn ${lang === activeScriptTabLang ? 'active' : ''}`;
      btn.setAttribute('data-lang', lang);
      const hasScript = multiScripts[lang] && multiScripts[lang].trim().length > 0;
      btn.innerHTML = `${meta.flag} ${meta.name} ${hasScript ? '✓' : ''}`;
      btn.onclick = () => switchScriptTab(lang);
      tabsBar.appendChild(btn);
    });
  }

  // 2. Load active script
  const scriptArea = $('script-area');
  if (scriptArea) {
    scriptArea.value = multiScripts[activeScriptTabLang] || '';
    updateScriptStats();
  }
  const metaActive = LANG_META[activeScriptTabLang] || { name: activeScriptTabLang.toUpperCase(), flag: '🌐' };
  const label = $('script-area-label');
  if (label) {
    label.textContent = `Story Script [${metaActive.flag} ${metaActive.name}] (Live Editable)`;
  }

  // 3. Render Multi-Voice Casting Cards
  const voiceContainer = $('multi-voice-casting-container');
  if (voiceContainer) {
    voiceContainer.innerHTML = '';
    checkedLangs.forEach(lang => {
      const meta = LANG_META[lang] || { name: lang.toUpperCase(), flag: '🌐' };
      const voicesList = VOICES_MAP[lang] || VOICES_MAP['en'] || [];
      const currentVoice = multiVoices[lang] || (voicesList[0] ? voicesList[0].id : '');
      if (!multiVoices[lang] && currentVoice) {
        multiVoices[lang] = currentVoice;
      }

      const card = document.createElement('div');
      card.className = 'multi-voice-card';
      card.innerHTML = `
        <div class="multi-voice-header">
          <span>${meta.flag} ${meta.name} Voice</span>
          <span style="font-size:0.70rem; color:var(--text-muted); font-family:monospace;">${(currentVoice.split('-')[0] || '').toUpperCase()}</span>
        </div>
        <div class="multi-voice-row">
          <select id="voice-select-${lang}" onchange="multiVoices['${lang}'] = this.value">
            ${voicesList.map(v => `<option value="${v.id}" ${v.id === currentVoice ? 'selected' : ''}>${v.name}</option>`).join('')}
          </select>
          <button type="button" class="btn-secondary" style="padding:4px 8px; font-size:0.72rem; white-space:nowrap;" onclick="auditionSpecificVoice('${lang}')">
            🔊 Audition
          </button>
        </div>
      `;
      voiceContainer.appendChild(card);
    });
  }

  const renderBtnText = $('btn-render-text');
  if (renderBtnText && currentLangMode === 'multi') {
    renderBtnText.textContent = `🌐 2. Launch Global Multiplier (${checkedLangs.length} Languages)`;
  }
}

function switchScriptTab(lang) {
  if ($('script-area')) {
    multiScripts[activeScriptTabLang] = $('script-area').value;
  }
  activeScriptTabLang = lang;
  refreshMultiplierDeck();
}

// 1-Click Translation for All Active Languages
async function translateAllLanguageScripts() {
  const currentText = $('script-area').value.trim();
  if (!currentText) {
    alert('Please write or generate a base script first!');
    return;
  }

  multiScripts[activeScriptTabLang] = currentText;

  const cbs = document.querySelectorAll('.batch-lang-cb:checked');
  const checkedLangs = Array.from(cbs).map(cb => cb.value);
  if (checkedLangs.length === 0) {
    alert('Please select at least one language in Column 1!');
    return;
  }

  const btn = $('btn-translate-all');
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span>🌐 Translating across languages…</span>';

  try {
    const fd = new FormData();
    fd.append('base_script', currentText);
    fd.append('base_language', activeScriptTabLang);
    fd.append('target_languages', checkedLangs.join(','));

    const res = await fetch('/api/v1/explainer/translate-scripts', { method: 'POST', body: fd });
    const data = await res.json();

    if (data.success && data.translated_scripts) {
      Object.keys(data.translated_scripts).forEach(l => {
        multiScripts[l] = data.translated_scripts[l];
      });
      refreshMultiplierDeck();
      alert(`✅ Successfully localized script into ${Object.keys(data.translated_scripts).length} languages! You can now click any language tab to inspect and edit before rendering.`);
    } else {
      alert('Translation failed: ' + (data.error || 'Server error'));
    }
  } catch (err) {
    alert('Translation request failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

// Audition specific voice for a given language card
async function auditionSpecificVoice(lang) {
  const selectEl = $(`voice-select-${lang}`);
  const voice = selectEl ? selectEl.value : (multiVoices[lang] || '');
  if (!voice) return;

  const btn = event.target;
  const original = btn.textContent;
  btn.textContent = '🔊 …';
  btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('voice', voice);
    fd.append('language', lang);

    const res = await fetch('/api/v1/explainer/preview-voice', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success && data.preview_url) {
      const audio = new Audio(data.preview_url);
      audio.play();
      audio.onended = () => { btn.textContent = original; btn.disabled = false; };
    } else {
      alert('Could not preview voice sample.');
      btn.textContent = original; btn.disabled = false;
    }
  } catch (err) {
    alert('Voice preview error: ' + err.message);
    btn.textContent = original; btn.disabled = false;
  }
}

function switchVoiceMode(mode) {
  currentVoiceMode = mode;
  ['ai', 'custom', 'clone'].forEach(m => {
    const tab = $(`tab-voice-${m}`);
    if (tab) tab.classList.remove('active');
  });

  $('box-voice-ai').style.display = 'none';
  $('box-voice-custom').style.display = 'none';
  $('box-voice-clone').style.display = 'none';

  if (mode === 'ai') {
    $('tab-voice-ai').classList.add('active');
    $('box-voice-ai').style.display = 'block';
  } else if (mode === 'custom_audio') {
    $('tab-voice-custom').classList.add('active');
    $('box-voice-custom').style.display = 'block';
  } else if (mode === 'clone') {
    $('tab-voice-clone').classList.add('active');
    $('box-voice-clone').style.display = 'block';
  }
}

function onCustomAudioSelected(input) {
  const file = input.files[0];
  if (!file) return;

  const url = URL.createObjectURL(file);
  const audio = new Audio(url);
  audio.onloadedmetadata = () => {
    const sec = Math.round(audio.duration);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    const durStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
    $('custom-audio-dur-text').textContent = durStr;
    $('custom-audio-info').style.display = 'block';
  };
}

function onCloneSampleSelected(input) {
  const file = input.files[0];
  if (!file) return;
  $('clone-status-text').textContent = `Ready: ${file.name.slice(0, 20)}...`;
  $('clone-status-text').style.color = '#38bdf8';
}

function onLanguageChange() {
  const lang = $('select-lang').value;
  const voiceSelect = $('select-voice');
  voiceSelect.innerHTML = '';

  const list = VOICES_MAP[lang] || VOICES_MAP['en'];
  list.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.name;
    voiceSelect.appendChild(opt);
  });

  updateEstimatedWordCount();
  updateScriptStats();
}

function updateScriptStats() {
  const rawText = $('script-area').value.trim();
  const cleanSpoken = rawText
    .replace(/\[SCENE:[^\]]*\]/gi, '')
    .replace(/\[VOICEOVER\]/gi, '')
    .replace(/\[SFX:[^\]]*\]/gi, '')
    .replace(/\[[^\]]*\]/g, '')
    .replace(/^#+.*$/gm, '')
    .trim();
  const spokenWords = cleanSpoken ? cleanSpoken.split(/\s+/).filter(Boolean).length : 0;
  const rawWords = rawText ? rawText.split(/\s+/).filter(Boolean).length : 0;
  const lang = currentLangMode === 'multi' ? (activeScriptTabLang || 'en') : ($('select-lang') ? $('select-lang').value : 'en');
  const speedVal = $('select-speed') ? $('select-speed').value : 'fast';

  const baseWpm = LANGUAGE_WPM[lang] || 150;
  const speedMult = speedVal === 'ultra_fast' ? 1.25 : (speedVal === 'fast' ? 1.15 : 1.0);
  const effectiveWpm = baseWpm * speedMult;

  const estSec = Math.round((spokenWords / effectiveWpm) * 60);
  const min = Math.floor(estSec / 60);
  const sec = estSec % 60;
  const timeStr = min > 0 ? `${min}m ${sec}s` : `${sec}s`;
  $('script-stats').textContent = `${spokenWords} Spoken Words (${rawWords} Total) • ~${timeStr} Voiceover (${lang.toUpperCase()})`;
}

function clearScript() {
  $('script-area').value = '';
  $('hook-score-badge').textContent = 'Awaiting Analysis...';
  updateScriptStats();
}

async function recalculateHook() {
  const text = $('script-area').value.trim();
  if (!text) return;
  const lang = $('select-lang').value;
  
  // Client-side quick hook score
  const firstP = text.split(/\s+/).slice(0, 45).join(' ').toLowerCase();
  let score = 65;
  const triggers = ["secret", "killed", "mystery", "shock", "trap", "died", "lie", "راز", "قتل", "دھوکہ", "خوفناک", "ہوش", "حیران", "خطرناک", "سازش", "انجام", "सच", "मौत", "धोखा", "रहस्य", "secreto", "muerte", "peligro", "rahasia", "terjebak"];
  const matches = triggers.filter(k => firstP.includes(k));
  score += Math.min(25, matches.length * 8);
  const finalScore = Math.min(98, Math.max(55, score));
  const rating = finalScore >= 85 ? "Viral Platinum 🔥" : "High Retention ⚡";
  $('hook-score-badge').textContent = `${finalScore}/100 (${rating})`;
}

async function auditionVoice() {
  const voice = $('select-voice').value;
  const lang = $('select-lang').value;
  if (!voice) return;

  const btn = event.target;
  const original = btn.textContent;
  btn.textContent = '🔊 Auditioning…';
  btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('voice', voice);
    fd.append('language', lang);

    const res = await fetch('/api/v1/explainer/preview-voice', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success && data.preview_url) {
      const audio = new Audio(data.preview_url);
      audio.play();
      audio.onended = () => { btn.textContent = original; btn.disabled = false; };
    } else {
      alert('Could not preview voice sample.');
      btn.textContent = original; btn.disabled = false;
    }
  } catch (err) {
    alert('Voice preview error: ' + err.message);
    btn.textContent = original; btn.disabled = false;
  }
}

async function generateStoryScript() {
  const isUrlMode = $('tab-url').classList.contains('active');
  const url = $('input-url').value.trim();
  const localFile = $('input-file').files[0];
  const customTranscript = $('input-transcript') ? $('input-transcript').value.trim() : '';

  if (!customTranscript && isUrlMode && !url) {
    alert('Please enter a YouTube video URL or paste a transcript.');
    return;
  }
  if (!customTranscript && !isUrlMode && !localFile) {
    alert('Please select a local video file or paste a transcript.');
    return;
  }

  const btn = $('btn-gen-script');
  btn.disabled = true;
  btn.innerHTML = '<span>🧠 Analyzing Story Arc & Writing Script…</span>';

  try {
    const fd = new FormData();
    if (customTranscript) fd.append('custom_transcript', customTranscript);
    if (isUrlMode) {
      if (url) fd.append('url', url);
    } else {
      if (localFile) fd.append('local_file', localFile);
    }

    const titleVal = ($('input-title') ? $('input-title').value.trim() : '') || 'Movie Story Explanation';
    fd.append('title', titleVal);
    const targetLang = currentLangMode === 'multi' ? activeScriptTabLang : $('select-lang').value;
    fd.append('language', targetLang);
    fd.append('voice_speed', $('select-speed').value);
    fd.append('persona', $('select-persona').value);
    fd.append('mood', $('select-bgm').value);
    fd.append('duration_mins', $('select-duration').value);
    fd.append('spoiler_mode', $('select-spoiler').value);
    fd.append('plot_summary', $('input-notes').value.trim());
    fd.append('genre', $('select-genre') ? $('select-genre').value : 'movie_recap');

    const res = await fetch('/api/v1/explainer/generate-script', { method: 'POST', body: fd });
    const data = await res.json();

    if (data.success && data.script) {
      $('script-area').value = data.script;
      if (currentLangMode === 'multi') {
        multiScripts[activeScriptTabLang] = data.script;
        refreshMultiplierDeck();
      }
      updateScriptStats();

      if (data.title && $('input-title') && (!$('input-title').value.trim() || $('input-title').value === 'Movie Story Explanation')) {
        $('input-title').value = data.title;
      }

      if (data.hook_score) {
        $('hook-score-badge').textContent = `${data.hook_score.score}/100 (${data.hook_score.rating})`;
      }
    } else {
      alert('Script generation failed: ' + (data.error || 'Check server logs'));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>🧠 1. Generate Storyboard Script</span>';
  }
}

// Animated Progress Bar Helper
let progressInterval = null;
function startProgressAnimation() {
  const card = $('render-progress-card');
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth' });

  const steps = [
    { pct: 15, text: '⚡ Slicing required scene clips & synthesizing voiceover…' },
    { pct: 38, text: '🎙️ Synthesizing Neural AI voiceover narration…' },
    { pct: 65, text: '🛡️ Assembling scene cuts & applying anti-copyright armor…' },
    { pct: 85, text: '🖼️ 9Router AI generating 3 High-CTR thumbnails…' },
    { pct: 95, text: '📦 Packaging YouTube & TikTok viral metadata…' },
  ];

  let currentStep = 0;
  $('progress-bar-fill').style.width = '12%';
  $('progress-bar-fill').style.background = 'linear-gradient(90deg, #06b6d4, #a855f7)';
  $('progress-pct').textContent = '12%';
  $('progress-step-text').style.color = '#e2e8f0';
  $('progress-step-text').textContent = steps[0].text;

  progressInterval = setInterval(() => {
    if (currentStep < steps.length) {
      const s = steps[currentStep];
      $('progress-bar-fill').style.width = `${s.pct}%`;
      $('progress-pct').textContent = `${s.pct}%`;
      $('progress-step-text').textContent = s.text;
      currentStep++;
    } else {
      let currentPct = parseInt($('progress-pct').textContent, 10) || 95;
      if (currentPct < 98) {
        currentPct += 1;
        $('progress-bar-fill').style.width = `${currentPct}%`;
        $('progress-pct').textContent = `${currentPct}%`;
      }
      const waitTexts = [
        '⚡ Finalizing video stream encoding...',
        '🎬 Burning high-definition styled subtitles...',
        '🎨 Finalizing high-CTR thumbnail composite...',
        '✨ Polishing final audio master...'
      ];
      const waitIdx = Math.floor((Date.now() / 4000) % waitTexts.length);
      $('progress-step-text').textContent = waitTexts[waitIdx];
    }
  }, 4000);
}

function stopProgressAnimation(isSuccess = true, errorMsg = '') {
  if (progressInterval) clearInterval(progressInterval);
  const fill = $('progress-bar-fill');
  const pct = $('progress-pct');
  const text = $('progress-step-text');
  if (isSuccess) {
    if (fill) {
      fill.style.width = '100%';
      fill.style.background = 'linear-gradient(90deg, #10b981, #06b6d4)';
    }
    if (pct) pct.textContent = '100%';
    if (text) {
      text.textContent = '✅ Explainer Generated Successfully!';
      text.style.color = '#34d399';
    }
  } else {
    if (fill) {
      fill.style.width = '100%';
      fill.style.background = '#ef4444';
    }
    if (pct) pct.textContent = 'Error';
    if (text) {
      text.textContent = '❌ Generation Failed: ' + (errorMsg || 'Server error occurred');
      text.style.color = '#f87171';
    }
  }
}

async function renderExplainerVideo() {
  const scriptText = $('script-area').value.trim();
  if (!scriptText) {
    alert('Please generate or paste a story script first!');
    return;
  }

  const isUrlMode = $('tab-url').classList.contains('active');
  const url = $('input-url').value.trim();
  const localFile = $('input-file').files[0];

  const btn = $('btn-render-video');
  const btnScript = $('btn-gen-script');
  btn.disabled = true;
  if (btnScript) btnScript.disabled = true;
  btn.innerHTML = '<span>🚀 Rendering Explainer & Thumbnails…</span>';
  startProgressAnimation();

  try {
    const fd = new FormData();
    fd.append('script_text', scriptText);
    const titleVal = ($('input-title') ? $('input-title').value.trim() : '') || 'Movie Story Recap';
    fd.append('title', titleVal);
    const customTranscript = $('input-transcript') ? $('input-transcript').value.trim() : '';
    if (customTranscript) fd.append('transcript_text', customTranscript);
    if (isUrlMode) fd.append('url', url);
    else if (localFile) fd.append('local_file', localFile);

    fd.append('voice_mode', currentVoiceMode);
    if (currentVoiceMode === 'custom_audio') {
      const audioFile = $('input-custom-audio').files[0];
      if (audioFile) fd.append('custom_audio_file', audioFile);
    } else if (currentVoiceMode === 'clone') {
      const cloneFile = $('input-clone-sample').files[0];
      if (cloneFile) fd.append('clone_sample_file', cloneFile);
    }

    fd.append('voice_speed', $('select-speed').value);
    fd.append('aspect_ratio', $('select-aspect').value);
    fd.append('mood_theme', $('select-bgm').value);
    fd.append('genre', $('select-genre') ? $('select-genre').value : 'movie_recap');
    fd.append('audio_mode', $('select-audio-mode') ? $('select-audio-mode').value : 'hybrid');
    fd.append('watermark', $('input-watermark').value.trim());
    fd.append('burn_subtitles', $('check-subs').checked);
    fd.append('resolution', $('select-resolution') ? $('select-resolution').value : '720p');

    if (currentLangMode === 'multi') {
      // Check export architecture mode
      const selectedModeRadio = document.querySelector('input[name="export-mode"]:checked');
      const exportMode = selectedModeRadio ? selectedModeRadio.value : 'youtube_audio_pack';
      fd.append('export_mode', exportMode);

      // Collect selected batch languages
      const cbs = document.querySelectorAll('.batch-lang-cb:checked');
      const selectedLangs = Array.from(cbs).map(cb => cb.value);
      if (selectedLangs.length === 0) {
        alert('Please select at least one language for batch generation.');
        stopProgressAnimation(false, 'No languages selected');
        btn.disabled = false;
        if (btnScript) btnScript.disabled = false;
        btn.innerHTML = '<span>🚀 2. Render Explainer & Thumbnails</span>';
        return;
      }
      fd.append('languages', selectedLangs.join(','));

      // Ensure active script text is saved
      multiScripts[activeScriptTabLang] = scriptText;
      fd.append('scripts_json', JSON.stringify(multiScripts));
      fd.append('voices_json', JSON.stringify(multiVoices));

      const res = await fetch('/api/v1/explainer/render-batch', { method: 'POST', body: fd });
      const resText = await res.text();
      let data;
      try {
        data = JSON.parse(resText);
      } catch (parseErr) {
        throw new Error(`Server error (HTTP ${res.status}): ${resText.slice(0, 150)}`);
      }
      const isOk = Boolean(data && data.success === true);
      const errMsg = data ? (data.error || data.detail || 'Batch rendering error') : 'Server error';
      stopProgressAnimation(isOk, errMsg);

      if (isOk && data.results) {
        batchResults = data.results;
        showBatchResultsHub(batchResults, data.zip_url || `/api/v1/explainer/download-bundle-zip?job_id=${data.job_id}`);
      } else {
        alert('Batch rendering failed: ' + errMsg);
      }
    } else {
      // Single Language Mode
      const lang = $('select-lang').value;
      fd.append('language', lang);
      fd.append('voice', $('select-voice').value);

      const res = await fetch('/api/v1/explainer/render-video', { method: 'POST', body: fd });
      const resText = await res.text();
      let data;
      try {
        data = JSON.parse(resText);
      } catch (parseErr) {
        throw new Error(`Server error (HTTP ${res.status}): ${resText.slice(0, 150)}`);
      }
      const isOk = Boolean(data && data.success === true);
      const errMsg = data ? (data.error || data.detail || 'Video rendering error') : 'Server error';
      stopProgressAnimation(isOk, errMsg);

      if (isOk) {
        batchResults = null;
        showResultsHub(data, lang);
      } else {
        alert('Video rendering failed: ' + errMsg);
      }
    }
  } catch (err) {
    stopProgressAnimation(false, err.message);
    alert('Render request failed: ' + err.message);
  } finally {
    btn.disabled = false;
    if (btnScript) btnScript.disabled = false;
    const renderBtnText = $('btn-render-text');
    if (renderBtnText && currentLangMode === 'multi') {
      const cbs = document.querySelectorAll('.batch-lang-cb:checked');
      renderBtnText.textContent = `🌐 2. Launch Global Multiplier (${cbs.length} Languages)`;
    } else if (renderBtnText) {
      renderBtnText.textContent = '🚀 2. Render Explainer & Thumbnails';
    }
  }
}

function showBatchResultsHub(results, zipUrl) {
  const tabsBar = $('batch-tabs-bar');
  tabsBar.style.display = 'flex';
  tabsBar.innerHTML = '';

  const zipBtn = $('btn-download-bundle-zip');
  if (zipBtn && zipUrl) {
    zipBtn.href = apiUrlWithToken(zipUrl);
    zipBtn.style.display = 'inline-flex';
  }

  const langKeys = Object.keys(results);
  if (langKeys.length === 0) return;

  langKeys.forEach((lang, idx) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `tab-btn ${idx === 0 ? 'active' : ''}`;
    const meta = LANG_META[lang] || { name: results[lang].language_name || lang.toUpperCase(), flag: '🌐' };
    btn.textContent = `${meta.flag} ${meta.name}`;
    btn.onclick = () => {
      document.querySelectorAll('#batch-tabs-bar .tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      displayLanguageResult(results[lang], lang);
    };
    tabsBar.appendChild(btn);
  });

  // Show first language by default
  displayLanguageResult(results[langKeys[0]], langKeys[0]);
}

function showResultsHub(data, lang = 'en') {
  $('batch-tabs-bar').style.display = 'none';
  const zipBtn = $('btn-download-bundle-zip');
  if (zipBtn) zipBtn.style.display = 'none';
  displayLanguageResult(data, lang);
}

function displayLanguageResult(data, lang) {
  currentActiveResult = { ...data, lang };
  const hub = $('results-hub');
  hub.style.display = 'block';
  hub.scrollIntoView({ behavior: 'smooth' });

  // Pre-select matching YouTube channel if available
  const chSelect = $('yt-sched-channel');
  if (chSelect && connectedYouTubeChannels && connectedYouTubeChannels.length > 0) {
    const match = connectedYouTubeChannels.find(c => (c.language || '').toLowerCase() === lang.toLowerCase());
    if (match) chSelect.value = match.channel_id;
  }

  // 1. Video Player
  const player = $('result-player');
  player.src = data.video_url;
  if (data.thumbnails && data.thumbnails.length > 0 && data.thumbnails[0].url) {
    player.poster = data.thumbnails[0].url;
  }
  player.load();
  $('btn-download-video').href = data.video_url;
  $('btn-download-video').download = data.video_filename;

  // YouTube Audio Track & SRT Downloads
  let extraDownloads = $('extra-audio-downloads');
  if (!extraDownloads) {
    extraDownloads = document.createElement('div');
    extraDownloads.id = 'extra-audio-downloads';
    extraDownloads.style.cssText = 'display:flex; flex-direction:column; gap:6px; margin-top:8px;';
    $('btn-download-video').parentNode.appendChild(extraDownloads);
  }
  extraDownloads.innerHTML = '';

  if (data.audio_url) {
    const audioBtn = document.createElement('a');
    audioBtn.href = data.audio_url;
    audioBtn.download = data.audio_filename || `Audio_Track_${lang.toUpperCase()}.mp3`;
    audioBtn.className = 'btn-secondary';
    audioBtn.style.cssText = 'text-decoration:none; font-size:0.8rem; padding:8px 12px; background:rgba(56, 189, 248, 0.15); border-color:#38bdf8; color:#38bdf8;';
    audioBtn.innerHTML = `<span>🎙️ Download ${escapeHtml(data.language_name || lang.toUpperCase())} Audio Track (.mp3)</span>`;
    extraDownloads.appendChild(audioBtn);
  }

  if (data.srt_url) {
    const srtBtn = document.createElement('a');
    srtBtn.href = data.srt_url;
    srtBtn.download = data.srt_filename || `Subtitles_${lang.toUpperCase()}.srt`;
    srtBtn.className = 'btn-secondary';
    srtBtn.style.cssText = 'text-decoration:none; font-size:0.8rem; padding:8px 12px; background:rgba(168, 85, 247, 0.15); border-color:#c084fc; color:#c084fc;';
    srtBtn.innerHTML = `<span>📄 Download ${escapeHtml(data.language_name || lang.toUpperCase())} Subtitles (.srt)</span>`;
    extraDownloads.appendChild(srtBtn);
  }

  // 2. Thumbnails Gallery with Live Interactive Text Editor
  const thumbContainer = $('thumbnails-container');
  thumbContainer.innerHTML = '';

  if (data.thumbnails && data.thumbnails.length > 0) {
    data.thumbnails.forEach((t, idx) => {
      const card = document.createElement('div');
      card.className = 'thumb-card';
      card.id = `thumb-card-${idx}`;
      card.innerHTML = `
        <img id="thumb-img-${idx}" src="${escapeHtml(t.url)}" alt="${escapeHtml(t.hook_text)}">
        <div class="thumb-card-body">
          <span class="thumb-badge">${escapeHtml(t.badge)}</span>
          <div style="display:flex; gap:4px;">
            <input type="text" id="thumb-input-${idx}" dir="auto" value="${escapeHtml(t.hook_text)}" style="font-size:0.75rem; padding:4px 6px; text-align:start;">
            <button type="button" class="btn-secondary btn-update-thumb" style="padding:4px 8px; font-size:0.72rem; white-space:nowrap;">🎨 Update</button>
          </div>
          <a id="thumb-download-${idx}" href="${escapeHtml(t.url)}" download="${escapeHtml(t.filename)}" class="btn-secondary" style="font-size:0.75rem; padding:4px 8px;">⬇️ Download</a>
        </div>
      `;
      const updateBtn = card.querySelector('.btn-update-thumb');
      if (updateBtn) {
        updateBtn.addEventListener('click', (e) => {
          updateThumbnailLive(t.filename, idx, lang, t.badge, e.target);
        });
      }
      thumbContainer.appendChild(card);
    });
  }

  // 3. Metadata Suite
  if (data.metadata_pack) {
    const m = data.metadata_pack;
    $('meta-title-1').value = m.titles ? m.titles[0] : '';
    $('meta-desc').value = m.description || '';
    $('meta-tags').value = m.tags ? m.tags.join(', ') : '';
    $('meta-comment').value = m.pinned_comment || '';

    ['meta-title-1', 'meta-desc', 'meta-tags', 'meta-comment'].forEach(id => {
      const el = $(id);
      if (el) el.setAttribute('dir', 'auto');
    });
  }
}

async function updateThumbnailLive(filename, idx, lang, badge, btnEl = null) {
  const newText = $(`thumb-input-${idx}`).value.trim();
  if (!newText) return;

  const btn = btnEl || (typeof event !== 'undefined' ? event.target : null);
  const orig = btn ? btn.textContent : '🎨 Update';
  if (btn) {
    btn.textContent = '…';
    btn.disabled = true;
  }

  try {
    const fd = new FormData();
    fd.append('filename', filename);
    fd.append('hook_text', newText);
    fd.append('language', lang);
    fd.append('badge', badge);

    const res = await fetch('/api/v1/explainer/update-thumbnail', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success && data.updated_url) {
      $(`thumb-img-${idx}`).src = data.updated_url;
      $(`thumb-download-${idx}`).href = data.updated_url;
    } else {
      alert('Could not update thumbnail typography.');
    }
  } catch (err) {
    alert('Update error: ' + err.message);
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
}

function copyText(el) {
  el.select();
  document.execCommand('copy');
  const original = el.style.borderColor;
  el.style.borderColor = 'var(--accent-cyan)';
  setTimeout(() => { el.style.borderColor = original; }, 1200);
}

// ==========================================
// 🖼️ Column 2: Instant Thumbnails Studio
// ==========================================
async function generateInstantThumbnails() {
  const isUrlMode = $('tab-url').classList.contains('active');
  const url = $('input-url').value.trim();
  const localFile = $('input-file').files[0];
  const lang = $('select-lang').value;
  const titleInput = $('input-title');
  const title = (titleInput ? titleInput.value.trim() : '') || "Movie Story Recap";

  if (isUrlMode && !url) {
    alert('Please provide a YouTube video URL first.');
    return;
  }
  if (!isUrlMode && !localFile) {
    alert('Please select a local video file first.');
    return;
  }

  const btn = $('btn-gen-instant-thumbs');
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span>⚡ Extracting 3 Frames…</span>';

  const container = $('col2-thumbnails-box');
  container.style.display = 'grid';
  container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:15px; color:#94a3b8; font-size:0.8rem;">Analyzing timeline sharpness & rendering 3 localized thumbnails...</div>';

  try {
    const fd = new FormData();
    if (isUrlMode) fd.append('url', url);
    else fd.append('local_file', localFile);
    fd.append('language', lang);
    fd.append('title', title);
    const scriptVal = ($('script-area') ? $('script-area').value.trim() : '') || ($('input-notes') ? $('input-notes').value.trim() : '');
    fd.append('plot_summary', scriptVal.slice(0, 400));

    const res = await fetch('/api/v1/explainer/instant-thumbnails', { method: 'POST', body: fd });
    const data = await res.json();

    if (data.success && data.thumbnails && data.thumbnails.length > 0) {
      container.innerHTML = '';
      data.thumbnails.forEach((t, idx) => {
        const item = document.createElement('div');
        item.style.background = 'rgba(15, 23, 42, 0.8)';
        item.style.border = '1px solid rgba(255,255,255,0.1)';
        item.style.borderRadius = '8px';
        item.style.overflow = 'hidden';
        item.style.display = 'flex';
        item.style.flexDirection = 'column';
        item.style.gap = '4px';
        item.style.padding = '6px';

        item.innerHTML = `
          <img id="instant-img-${idx}" src="${t.url}" style="width:100%; border-radius:4px; aspect-ratio:16/9; object-fit:cover; display:block;" alt="${t.hook_text}">
          <div style="font-size:0.68rem; font-weight:700; color:#e2e8f0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${t.badge}</div>
          <div style="display:flex; gap:3px;">
            <input type="text" id="instant-input-${idx}" value="${t.hook_text}" style="font-size:0.7rem; padding:2px 4px; flex:1; height:24px;">
            <button type="button" class="btn-secondary" style="padding:2px 6px; font-size:0.68rem; height:24px;" onclick="updateInstantThumbLive('${t.filename}', ${idx}, '${lang}', '${t.badge}')">🎨</button>
          </div>
          <a id="instant-dl-${idx}" href="${t.url}" download="${t.filename}" class="btn-secondary" style="font-size:0.68rem; padding:2px 4px; text-align:center; text-decoration:none; margin-top:2px;">⬇️ Download</a>
        `;
        container.appendChild(item);
      });
    } else {
      container.innerHTML = '<div style="grid-column:1/-1; color:#ef4444; font-size:0.8rem; text-align:center;">Failed to generate instant thumbnails. Check video source or logs below.</div>';
    }
  } catch (err) {
    container.innerHTML = `<div style="grid-column:1/-1; color:#ef4444; font-size:0.8rem; text-align:center;">Error: ${err.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function updateInstantThumbLive(filename, idx, lang, badge) {
  const newText = $(`instant-input-${idx}`).value.trim();
  if (!newText) return;

  const btn = event.target;
  const orig = btn.textContent;
  btn.textContent = '…';
  btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('filename', filename);
    fd.append('hook_text', newText);
    fd.append('language', lang);
    fd.append('badge', badge);

    const res = await fetch('/api/v1/explainer/update-thumbnail', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success && data.updated_url) {
      $(`instant-img-${idx}`).src = data.updated_url;
      $(`instant-dl-${idx}`).href = data.updated_url;
    } else {
      alert('Could not update thumbnail typography.');
    }
  } catch (err) {
    alert('Update error: ' + err.message);
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
}

// ==========================================
// 🖥️ Live Diagnostics & Engine Logs Terminal
// ==========================================
let logPollTimer = null;
let lastLogCount = 0;

function startLogPolling() {
  if (logPollTimer) clearInterval(logPollTimer);
  fetchLogs();
  logPollTimer = setInterval(fetchLogs, 1500);
}

async function fetchLogs() {
  try {
    const res = await fetch('/api/v1/explainer/logs');
    if (!res.ok) return;
    const data = await res.json();
    if (data.success && Array.isArray(data.logs)) {
      if (data.logs.length !== lastLogCount) {
        lastLogCount = data.logs.length;
        renderLogs(data.logs);
      }
    }
  } catch (err) {
    // Silent fail on transient poll errors
  }
}

function renderLogs(logs) {
  const terminal = $('live-logs-terminal');
  if (!terminal) return;

  if (logs.length === 0) {
    terminal.innerHTML = '<div style="color:#64748b;">[System Ready] Engine initialized. Awaiting user commands...</div>';
    return;
  }

  const colorMap = {
    'INFO': '#94a3b8',
    'SUCCESS': '#10b981',
    'WARNING': '#f59e0b',
    'ERROR': '#ef4444'
  };

  const html = logs.map(entry => {
    const col = colorMap[entry.level] || '#94a3b8';
    return `<div style="margin-bottom:2px;"><span style="color:#64748b;">[${entry.time}]</span> <span style="font-weight:bold; color:${col};">[${entry.level}]</span> <span style="color:#e2e8f0;">${escapeHtml(entry.message)}</span></div>`;
  }).join('');

  const isAtBottom = (terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight) < 60;
  terminal.innerHTML = html;
  if (isAtBottom) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

async function clearLiveLogs() {
  try {
    await fetch('/api/v1/explainer/clear-logs', { method: 'POST' });
    lastLogCount = 0;
    const terminal = $('live-logs-terminal');
    if (terminal) {
      terminal.innerHTML = '<div style="color:#64748b;">[Logs Cleared] Terminal buffer cleared. Ready for new operations.</div>';
    }
  } catch (err) {
    console.error('Clear logs error:', err);
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================
// ⚙️ 9Router AI Settings & Health Monitor
// ==========================================
async function checkAiStatus() {
  try {
    const res = await fetch('/api/v1/explainer/ai-status');
    const data = await res.json();
    const badge = $('ai-status-badge');
    const text = $('ai-status-text');

    if (data.online) {
      badge.style.background = 'rgba(16, 185, 129, 0.15)';
      badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      badge.style.color = '#34d399';
      text.textContent = `Online (${data.latency_ms}ms)`;
    } else {
      badge.style.background = 'rgba(239, 68, 68, 0.15)';
      badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
      badge.style.color = '#f87171';
      text.textContent = 'Offline';
    }
  } catch (err) {
    const text = $('ai-status-text');
    if (text) text.textContent = 'Offline';
  }
}

function openAiSettingsModal() {
  $('modal-ai-settings').style.display = 'flex';
  checkAiStatus();
}

function closeAiSettingsModal() {
  $('modal-ai-settings').style.display = 'none';
}

async function testAiConnectionModal() {
  const fb = $('ai-modal-feedback');
  fb.textContent = 'Testing connection to 9Router...';
  fb.style.color = '#38bdf8';

  try {
    const res = await fetch('/api/v1/explainer/ai-status');
    const data = await res.json();
    if (data.online) {
      fb.textContent = `🟢 Connected! Latency: ${data.latency_ms}ms | Active Model: ${data.active_combo}`;
      fb.style.color = '#34d399';
    } else {
      fb.textContent = `🔴 Offline: ${data.message || 'Could not connect to 9Router port.'}`;
      fb.style.color = '#f87171';
    }
  } catch (err) {
    fb.textContent = `🔴 Error: ${err.message}`;
    fb.style.color = '#f87171';
  }
}

async function saveAiSettingsModal() {
  const url = $('ai-modal-url').value.trim();
  const combo = $('ai-modal-combo').value.trim();
  const key = $('ai-modal-key').value.trim();

  const fb = $('ai-modal-feedback');
  fb.textContent = 'Saving configuration...';

  try {
    const fd = new FormData();
    fd.append('url', url);
    fd.append('combo_model', combo);
    if (key) fd.append('key', key);

    const res = await fetch('/api/v1/explainer/ai-config', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success) {
      fb.textContent = '✅ Settings saved successfully!';
      fb.style.color = '#34d399';
      checkAiStatus();
      setTimeout(closeAiSettingsModal, 900);
    } else {
      fb.textContent = '❌ Failed to save settings.';
      fb.style.color = '#f87171';
    }
  } catch (err) {
    fb.textContent = `❌ Error: ${err.message}`;
    fb.style.color = '#f87171';
  }
}

// ==========================================
// ⚡ 30-Second Voice Clone Audition Preview
// ==========================================
async function previewClonedVoice() {
  const file = $('input-clone-sample').files[0];
  if (!file) {
    alert('Please select a 20-60 second voice clip first!');
    return;
  }

  const lang = $('select-lang').value;
  const btn = $('btn-preview-clone');
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⚡ Cloning…';

  try {
    const fd = new FormData();
    fd.append('clone_sample_file', file);
    fd.append('language', lang);

    const res = await fetch('/api/v1/explainer/preview-clone', { method: 'POST', body: fd });
    const data = await res.json();

    if (data.success && data.preview_url) {
      const audio = new Audio(data.preview_url);
      audio.play();
      audio.onended = () => {
        btn.textContent = origText;
        btn.disabled = false;
      };
    } else {
      alert('Failed to synthesize cloned voice audition.');
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert('Voice clone audition error: ' + err.message);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

// ==========================================
// 📺 YouTube Channel Hub & Auto-Scheduler
// ==========================================
let currentActiveResult = null;
let connectedYouTubeChannels = [];
let ytPollingInterval = null;

async function checkYouTubeStatus() {
  try {
    const res = await fetch('/api/v1/youtube/status');
    const data = await res.json();
    const countBadge = $('yt-channels-count');
    const credsBadge = $('yt-creds-badge');
    const credsMsg = $('yt-creds-msg');
    const chList = $('yt-connected-channels-list');
    const chSelect = $('yt-sched-channel');
    const modalChCount = $('yt-modal-ch-count');

    connectedYouTubeChannels = data.channels || [];

    if (countBadge) {
      countBadge.textContent = `${data.channels_count} Connected`;
    }
    if (modalChCount) {
      modalChCount.textContent = data.channels_count;
    }

    if (credsBadge) {
      if (data.configured) {
        credsBadge.textContent = 'Configured (' + data.client_id + ')';
        credsBadge.style.background = 'rgba(16, 185, 129, 0.2)';
        credsBadge.style.color = '#34d399';
      } else {
        credsBadge.textContent = 'Not Configured';
        credsBadge.style.background = 'rgba(239, 68, 68, 0.2)';
        credsBadge.style.color = '#fca5a5';
      }
    }

    // Populate Modal Channel List
    if (chList) {
      if (connectedYouTubeChannels.length === 0) {
        chList.innerHTML = '<div style="color:#64748b; font-size:0.80rem; text-align:center; padding:10px;">No channels linked yet. Add one above!</div>';
      } else {
        chList.innerHTML = connectedYouTubeChannels.map(ch => `
          <div style="display:flex; align-items:center; justify-content:space-between; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:10px 12px;">
            <div style="display:flex; align-items:center; gap:10px;">
              <img src="${escapeHtml(ch.thumbnail_url || 'https://www.youtube.com/s/desktop/9963c639/img/favicon_144x144.png')}" alt="Avatar" style="width:36px; height:36px; border-radius:50%; object-fit:cover;">
              <div>
                <div style="font-weight:600; font-size:0.85rem; color:#f8fafc;">${escapeHtml(ch.title)}</div>
                <div style="font-size:0.75rem; color:#94a3b8;">${escapeHtml(ch.custom_url || ch.channel_id)} • <span style="text-transform:uppercase; color:#38bdf8;">${escapeHtml(ch.language || 'Global')}</span></div>
              </div>
            </div>
            <button type="button" class="btn-secondary" style="font-size:0.75rem; padding:4px 8px; color:#f87171; border-color:rgba(239,68,68,0.3);" onclick="disconnectYouTubeChannel('${escapeHtml(ch.channel_id)}')">Disconnect</button>
          </div>
        `).join('');
      }
    }

    // Populate Dropdown in Results Hub
    if (chSelect) {
      if (connectedYouTubeChannels.length === 0) {
        chSelect.innerHTML = '<option value="">(No channel connected - Click 📺 YouTube in header)</option>';
      } else {
        chSelect.innerHTML = connectedYouTubeChannels.map(ch => `
          <option value="${escapeHtml(ch.channel_id)}">${escapeHtml(ch.title)} (${escapeHtml((ch.language || '').toUpperCase())} • ${escapeHtml(ch.custom_url || ch.channel_id)})</option>
        `).join('');

        // Auto-select channel matching current active result language if possible
        if (currentActiveResult && currentActiveResult.lang) {
          const match = connectedYouTubeChannels.find(c => (c.language || '').toLowerCase() === currentActiveResult.lang.toLowerCase());
          if (match) chSelect.value = match.channel_id;
        }
      }
    }
  } catch (err) {
    console.error('Error fetching YouTube status:', err);
  }
}

function openYouTubeModal() {
  $('modal-youtube').style.display = 'flex';
  checkYouTubeStatus();
}

function closeYouTubeModal() {
  $('modal-youtube').style.display = 'none';
}

async function saveYouTubeCredentials() {
  const clientId = $('yt-modal-client-id').value.trim();
  const clientSecret = $('yt-modal-client-secret').value.trim();
  const msg = $('yt-creds-msg');

  if (!clientId || !clientSecret) {
    alert('Please enter both Google Client ID and Client Secret.');
    return;
  }

  try {
    msg.textContent = 'Saving keys…';
    msg.style.color = '#38bdf8';
    const res = await fetch('/api/v1/youtube/setup-client', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
    });
    const data = await res.json();
    if (data.status === 'success') {
      msg.textContent = '✅ API Keys Saved!';
      msg.style.color = '#34d399';
      checkYouTubeStatus();
    } else {
      msg.textContent = '❌ Failed to save keys.';
      msg.style.color = '#f87171';
    }
  } catch (err) {
    msg.textContent = `❌ Error: ${err.message}`;
    msg.style.color = '#f87171';
  }
}

async function connectYouTubeChannel() {
  try {
    const res = await fetch('/api/v1/youtube/connect-url');
    const data = await res.json();
    if (data.auth_url) {
      window.open(data.auth_url, 'youtube_oauth', 'width=620,height=750,menubar=no,toolbar=no');
    } else {
      alert(data.detail || 'Failed to generate Google OAuth consent URL. Please configure Client ID and Secret first.');
    }
  } catch (err) {
    alert('OAuth error: ' + err.message);
  }
}

async function disconnectYouTubeChannel(channelId) {
  if (!confirm('Are you sure you want to disconnect this YouTube channel?')) return;
  try {
    const res = await fetch(`/api/v1/youtube/channels/${channelId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.deleted) {
      checkYouTubeStatus();
    } else {
      alert('Failed to disconnect channel.');
    }
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

// Window listener for popup message on OAuth complete
window.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'YOUTUBE_AUTH_SUCCESS') {
    checkYouTubeStatus();
  }
});

function setSchedulePreset(presetType) {
  const dtInput = $('yt-sched-datetime');
  if (!dtInput) return;

  const now = new Date();
  let target = new Date();

  if (presetType === 'today_peak') {
    target.setHours(19, 0, 0, 0); // 7:00 PM today
    if (target <= now) {
      // If already past 7 PM today, schedule for tomorrow 7 PM
      target.setDate(target.getDate() + 1);
    }
  } else if (presetType === 'tomorrow_peak') {
    target.setDate(target.getDate() + 1);
    target.setHours(19, 0, 0, 0); // 7:00 PM tomorrow
  } else if (presetType === 'weekend') {
    // Coming Saturday 11:00 AM
    const day = target.getDay();
    const daysUntilSaturday = (6 - day + 7) % 7 || 7;
    target.setDate(target.getDate() + daysUntilSaturday);
    target.setHours(11, 0, 0, 0);
  }

  // Format YYYY-MM-DDTHH:MM for datetime-local input
  const pad = n => String(n).padStart(2, '0');
  const formatted = `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}T${pad(target.getHours())}:${pad(target.getMinutes())}`;
  dtInput.value = formatted;
}

async function scheduleCurrentVideoToYouTube() {
  const channelId = $('yt-sched-channel').value;
  if (!channelId) {
    alert('Please select or connect a YouTube channel first.');
    openYouTubeModal();
    return;
  }

  const dtVal = $('yt-sched-datetime').value;
  if (!dtVal) {
    alert('Please pick a schedule date & time or select a Peak Preset (e.g., Today Peak).');
    return;
  }

  if (!currentActiveResult || !currentActiveResult.video_url) {
    alert('No rendered video found to schedule. Please render an explainer video first!');
    return;
  }

  // Determine file paths on server
  let videoPath = currentActiveResult.video_url.replace('/outputs/', '');
  let srtPath = currentActiveResult.srt_url ? currentActiveResult.srt_url.replace('/outputs/', '') : null;
  let thumbPath = null;
  if (currentActiveResult.thumbnails && currentActiveResult.thumbnails.length > 0) {
    // Use option 3 (index 2) or first thumbnail
    const thumbObj = currentActiveResult.thumbnails[2] || currentActiveResult.thumbnails[0];
    thumbPath = thumbObj.url.replace('/outputs/thumbnails/', 'thumbnails/').replace('/outputs/', '');
  }

  const title = ($('meta-title-1') ? $('meta-title-1').value : '') || 'AI Movie Explainer Recap';
  const desc = ($('meta-desc') ? $('meta-desc').value : '') || 'Full movie explainer recap.';
  const tagsText = ($('meta-tags') ? $('meta-tags').value : '') || '';
  const tags = tagsText.split(',').map(t => t.trim()).filter(Boolean);

  const tzOffsetHours = (new Date()).getTimezoneOffset() / -60.0;

  const btn = $('btn-yt-schedule');
  const statusBar = $('yt-sched-status');
  const statusMsg = $('yt-sched-status-msg');
  const pBar = $('yt-sched-progress-bar');

  btn.disabled = true;
  statusBar.style.display = 'block';
  pBar.style.width = '10%';
  statusMsg.textContent = '🚀 Initializing upload to YouTube...';

  try {
    const payload = {
      channel_id: channelId,
      video_path: videoPath,
      title: title,
      description: desc,
      tags: tags,
      publish_at: dtVal.replace('T', ' ') + ':00',
      tz_offset_hours: tzOffsetHours,
      thumbnail_path: thumbPath,
      srt_path: srtPath,
      language: currentActiveResult.lang || 'en'
    };

    const res = await fetch('/api/v1/youtube/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Scheduling failed');
    }

    const taskId = data.task_id;
    statusMsg.textContent = `Queued (${data.channel_title || 'YouTube'}). Uploading in background…`;
    pBar.style.width = '25%';

    // Poll task status
    if (ytPollingInterval) clearInterval(ytPollingInterval);
    ytPollingInterval = setInterval(async () => {
      try {
        const pollRes = await fetch(`/api/v1/youtube/tasks/${taskId}`);
        const pollData = await pollRes.json();

        if (pollData.progress) {
          pBar.style.width = `${pollData.progress}%`;
        }
        if (pollData.message) {
          statusMsg.textContent = pollData.message;
        }

        if (pollData.status === 'completed') {
          clearInterval(ytPollingInterval);
          btn.disabled = false;
          pBar.style.width = '100%';
          pBar.style.background = '#10b981';
          statusMsg.innerHTML = `✅ <strong>Video Scheduled!</strong> Will go public on <em>${pollData.publish_at || data.publish_at_iso}</em>. <a href="${pollData.video_url}" target="_blank" style="color:#38bdf8; text-decoration:underline;">View on YouTube</a>`;
        } else if (pollData.status === 'failed') {
          clearInterval(ytPollingInterval);
          btn.disabled = false;
          pBar.style.background = '#ef4444';
          statusMsg.textContent = `❌ Upload Failed: ${pollData.error || pollData.message}`;
        }
      } catch (pollErr) {
        console.warn('Poll error:', pollErr);
      }
    }, 1500);

  } catch (err) {
    btn.disabled = false;
    statusMsg.textContent = `❌ Error: ${err.message}`;
    pBar.style.background = '#ef4444';
  }
}

// 🔄 Reset Studio / New Project
function resetStudio() {
  if (confirm("Reset studio for a new project? Your connected YouTube channels and saved API credentials will remain safely stored.")) {
    // Clear inputs
    if ($('input-url')) $('input-url').value = '';
    if ($('input-file')) $('input-file').value = '';
    if ($('input-title')) $('input-title').value = '';
    if ($('input-notes')) $('input-notes').value = '';
    if ($('script-area')) $('script-area').value = '';
    if ($('input-custom-audio')) $('input-custom-audio').value = '';
    if ($('input-clone-sample')) $('input-clone-sample').value = '';

    // Clear stats & badges
    if ($('script-stats')) $('script-stats').textContent = '0 Words';
    if ($('hook-score-badge')) $('hook-score-badge').textContent = 'Awaiting Analysis...';

    // Hide results hub & progress
    if ($('results-hub')) $('results-hub').style.display = 'none';
    if ($('render-progress-card')) $('render-progress-card').style.display = 'none';
    if ($('col2-thumbnails-box')) {
      $('col2-thumbnails-box').style.display = 'none';
      $('col2-thumbnails-box').innerHTML = '';
    }

    // Reset video player
    const player = $('result-player');
    if (player) {
      player.pause();
      player.removeAttribute('src');
      player.load();
    }

    // Clear batch data
    batchResults = {};
    multiScripts = {};

    // Reset buttons
    const btnScript = $('btn-gen-script');
    if (btnScript) {
      btnScript.disabled = false;
      btnScript.innerHTML = '<span>🧠 1. Generate Storyboard Script</span>';
    }
    const btnRender = $('btn-render-video');
    if (btnRender) {
      btnRender.disabled = false;
      btnRender.innerHTML = '<span id="btn-render-text">🚀 2. Render Explainer & Thumbnails</span>';
    }

    updateEstimatedWordCount();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// ⚡ 1-Click Expand Script
async function expandScript() {
  const currentScript = $('script-area').value.trim();
  if (!currentScript) {
    alert('Please generate or enter a story script first before expanding.');
    return;
  }

  const durVal = parseInt($('select-duration') ? $('select-duration').value : 10) || 10;
  const lang = currentLangMode === 'multi' ? (activeScriptTabLang || 'en') : ($('select-lang') ? $('select-lang').value : 'en');
  const speedVal = $('select-speed') ? $('select-speed').value : 'fast';
  const genre = $('select-genre') ? $('select-genre').value : 'movie_recap';

  const btn = $('btn-expand-script');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⚡ Expanding Script...';
  }

  try {
    const fd = new FormData();
    fd.append('script', currentScript);
    fd.append('language', lang);
    fd.append('duration_mins', durVal);
    fd.append('voice_speed', speedVal);
    fd.append('genre', genre);

    const res = await fetch('/api/v1/explainer/expand-script', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success && data.script) {
      $('script-area').value = data.script;
      if (currentLangMode === 'multi') {
        multiScripts[activeScriptTabLang] = data.script;
      }
      updateScriptStats();
      recalculateHook();
    } else {
      alert('Script expansion note: ' + (data.error || 'Could not expand script. Check server logs.'));
    }
  } catch (err) {
    alert('Error expanding script: ' + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Expand to Full Length';
    }
  }
}

// Concept 3 ("Creator Split Hub") Studio Helpers
function addSceneBlockTemplate() {
  const area = $('script-area');
  if (!area) return;
  const current = area.value.trim();
  const template = `\n\n[SCENE: 00:00 - 00:05]\n[VOICEOVER] Enter compelling narration and dialogue for this scene here...`;
  area.value = current ? current + template : template.trim();
  area.focus();
  area.scrollTop = area.scrollHeight;
  if (typeof updateScriptStats === 'function') updateScriptStats();
  if (typeof recalculateHook === 'function') recalculateHook();
}

function setPreviewAspect(aspect) {
  const wrapper = $('video-preview-wrapper');
  const btn169 = $('btn-aspect-16-9');
  const btn916 = $('btn-aspect-9-16');
  const selectAspect = $('select-aspect');

  if (aspect === '9-16' || aspect === 'vertical') {
    if (wrapper) wrapper.classList.add('aspect-vertical');
    if (btn916) btn916.classList.add('active');
    if (btn169) btn169.classList.remove('active');
    if (selectAspect && selectAspect.value !== 'vertical') selectAspect.value = 'vertical';
  } else {
    if (wrapper) wrapper.classList.remove('aspect-vertical');
    if (btn169) btn169.classList.add('active');
    if (btn916) btn916.classList.remove('active');
    if (selectAspect && selectAspect.value !== 'horizontal') selectAspect.value = 'horizontal';
  }
}

// Sync aspect ratio dropdown with preview container
document.addEventListener('DOMContentLoaded', () => {
  const selectAspect = $('select-aspect');
  if (selectAspect) {
    selectAspect.addEventListener('change', () => {
      setPreviewAspect(selectAspect.value);
    });
  }
});
