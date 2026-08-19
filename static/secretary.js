/* Bolla Segretaria — assistente AI dell'avvocato (agenda + voce).
   Self-contained: inietta la sua CSS, costruisce il widget, parla col
   backend /api/secretary. Il cervello è "Tetramorph" (mai rivelato). */
(function () {
  "use strict";
  if (window.__sekrLoaded) return;
  window.__sekrLoaded = true;

  var CSS = `
  .sekr-fab{position:fixed;right:18px;bottom:104px;top:auto;width:40px;height:40px;border:none;
    border-radius:50%;cursor:pointer;z-index:9998;padding:0;background:transparent;
    filter:drop-shadow(0 4px 12px rgba(201,162,77,.4));transition:transform .2s}
  .sekr-fab:hover{transform:scale(1.1)}
  .sekr-wave{position:absolute;inset:0;border-radius:50%;border:1.5px solid rgba(201,162,77,.5);
    pointer-events:none;opacity:0;animation:sekr-wave 3.6s cubic-bezier(.2,.6,.35,1) infinite}
  .sekr-wave.w2{animation-delay:1.8s}
  @keyframes sekr-wave{0%{transform:scale(.92);opacity:.45}70%{opacity:.08}100%{transform:scale(2.4);opacity:0}}
  .sekr-orb{display:block;width:100%;height:100%;border-radius:50%;position:relative;overflow:hidden;
    background:linear-gradient(145deg,#fdf8ee,#f1e3c6);
    box-shadow:inset 0 1px 2px rgba(255,255,255,.85),0 3px 10px rgba(20,24,40,.22),inset 0 0 0 1.5px rgba(201,162,77,.5)}
  .sekr-logo{position:absolute;top:50%;left:50%;width:66%;height:66%;
    transform:translate(-50%,-53%);object-fit:contain;pointer-events:none}
  .sekr-panel{position:fixed;right:20px;bottom:20px;width:380px;max-width:calc(100vw - 32px);
    height:min(560px,calc(100dvh - 130px));background:#fbf7ee;border:1px solid #e5d9bd;
    border-radius:18px;box-shadow:0 30px 70px rgba(15,20,40,.35);z-index:9999;display:none;
    flex-direction:column;overflow:hidden;font-family:Inter,system-ui,sans-serif}
  .sekr-panel.open{display:flex;animation:sekr-in .22s cubic-bezier(.2,.9,.3,1.2)}
  @keyframes sekr-in{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
  .sekr-head{background:linear-gradient(135deg,#0f1b33,#1c3057);color:#f7edcf;padding:13px 15px;
    display:flex;align-items:center;gap:10px}
  .sekr-head .mini{width:30px;height:30px;border-radius:50%;flex:0 0 auto;
    background:#fff url(/static/logo-aala-mark.png) center/72% no-repeat;
    box-shadow:inset 0 0 0 1px rgba(201,162,77,.4)}
  .sekr-head b{font-size:15px;font-weight:700;display:block;line-height:1.1}
  .sekr-head small{font-size:11px;opacity:.8}
  .sekr-x{margin-left:6px;background:transparent;border:none;color:#f7edcf;font-size:20px;
    cursor:pointer;opacity:.8;line-height:1}
  .sekr-tts{margin-left:auto;background:transparent;border:none;color:#f7edcf;font-size:17px;
    cursor:pointer;opacity:.85;line-height:1;padding:0 2px}
  .sekr-tts.on{opacity:1;text-shadow:0 0 9px rgba(201,162,77,.95)}
  .sekr-speak{display:inline-block;margin-left:7px;background:transparent;border:none;
    cursor:pointer;font-size:12px;opacity:.4;padding:0;vertical-align:middle}
  .sekr-speak:hover{opacity:1}
  .sekr-body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;
    background:#fbf7ee}
  .sekr-msg{max-width:85%;padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.45;
    white-space:pre-wrap;word-wrap:break-word}
  .sekr-msg.bot{align-self:flex-start;background:#fff;border:1px solid #ece0c4;color:#22314f;
    border-bottom-left-radius:4px}
  .sekr-msg.user{align-self:flex-end;background:linear-gradient(135deg,#c9a24d,#a9842f);color:#fff;
    border-bottom-right-radius:4px}
  .sekr-msg.bot b,.sekr-msg.bot strong{color:#0f1b33}
  .sekr-confirm{align-self:flex-start;max-width:92%;background:#fff8e8;border:1px solid #e6c877;
    border-radius:14px;padding:11px 12px;font-size:13.5px;color:#4a3a12}
  .sekr-confirm .row{display:flex;gap:8px;margin-top:9px}
  .sekr-confirm button{flex:1;border:none;border-radius:9px;padding:8px;font-weight:700;cursor:pointer;
    font-size:13px}
  .sekr-ok{background:#1c7a3e;color:#fff}
  .sekr-no{background:#eee;color:#555}
  .sekr-typing{align-self:flex-start;color:#9a8a63;font-size:13px;font-style:italic}
  .sekr-foot{display:flex;gap:8px;align-items:flex-end;padding:10px;border-top:1px solid #ece0c4;
    background:#fff}
  .sekr-foot textarea{flex:1;resize:none;border:1px solid #dcd0b4;border-radius:12px;padding:9px 11px;
    font-size:14px;font-family:inherit;max-height:96px;outline:none;background:#fdfaf2;color:#22314f}
  .sekr-foot textarea:focus{border-color:#c9a24d}
  .sekr-mic,.sekr-send{width:40px;height:40px;flex:0 0 auto;border:none;border-radius:50%;cursor:pointer;
    font-size:17px;display:flex;align-items:center;justify-content:center}
  .sekr-mic{background:#f0e8d2;color:#8a6a26}
  .sekr-mic.rec{background:#e41e26;color:#fff;animation:sekr-pulse2 1s infinite}
  @keyframes sekr-pulse2{0%,100%{box-shadow:0 0 0 0 rgba(228,30,38,.5)}50%{box-shadow:0 0 0 8px rgba(228,30,38,0)}}
  .sekr-send{background:linear-gradient(135deg,#c9a24d,#a9842f);color:#fff}
  .sekr-send:disabled{opacity:.5;cursor:default}
  @media (max-width:560px){
    .sekr-panel{right:8px;left:8px;width:auto;bottom:12px;height:min(72dvh,calc(100dvh - 90px))}
    .sekr-fab{right:10px;bottom:92px;top:auto;width:38px;height:38px}
  }`;

  var st = document.createElement("style");
  st.textContent = CSS;
  document.head.appendChild(st);

  var UI_LANG = (document.documentElement.lang || "sq").slice(0, 2);
  var T = {
    sq: { title: "Tetramorph", sub: "Sekretarja jote AI", ph: "Shkruaj ose fol…",
      hi: "Përshëndetje! Jam Tetramorph, sekretarja jote. Pyet për seancat, takimet ose afatet e tua — ose thuaj p.sh. «regjistro një seancë më 4 gusht ora 10».",
      confirm: "Konfirmo", cancel: "Anulo", err: "Ndodhi një gabim. Provo përsëri.",
      speak: "Dëgjo me zë", ttsOn: "Zëri: ndezur", ttsOff: "Zëri: fikur",
      micHint: "Në iPhone përdor mikrofonin e tastierës për të diktuar.",
      micErr: "Zëri nuk u kap. Provo përsëri ose shkruaj.",
      micDenied: "Leja e mikrofonit u refuzua. Aktivizoje te cilësimet." },
    it: { title: "Tetramorph", sub: "La tua segretaria AI", ph: "Scrivi o parla…",
      hi: "Ciao! Sono Tetramorph, la tua segretaria. Chiedimi delle tue udienze, appuntamenti o scadenze — o dì ad es. «registra un'udienza il 4 agosto alle 10».",
      confirm: "Conferma", cancel: "Annulla", err: "Si è verificato un errore. Riprova.",
      speak: "Ascolta", ttsOn: "Voce: attiva", ttsOff: "Voce: spenta",
      micHint: "Su iPhone usa il microfono della tastiera per dettare.",
      micErr: "Voce non rilevata. Riprova o scrivi.",
      micDenied: "Permesso microfono negato. Attivalo nelle impostazioni." },
    en: { title: "Tetramorph", sub: "Your AI secretary", ph: "Type or speak…",
      hi: "Hi! I'm Tetramorph, your secretary. Ask about your hearings, appointments or deadlines — or say e.g. \"add a hearing on August 4 at 10\".",
      confirm: "Confirm", cancel: "Cancel", err: "Something went wrong. Try again.",
      speak: "Listen", ttsOn: "Voice: on", ttsOff: "Voice: off",
      micHint: "On iPhone use the keyboard mic to dictate.",
      micErr: "No speech detected. Try again or type.",
      micDenied: "Microphone permission denied. Enable it in settings." }
  };
  var L = T[UI_LANG] || T.sq;
  var VOICE_LANG = { sq: "sq-AL", it: "it-IT", en: "en-US" }[UI_LANG] || "sq-AL";

  // ── text-to-speech (risposta a voce) ─────────────────────────────────────
  var SS = window.speechSynthesis || null;
  var autoSpeak = false;
  try { autoSpeak = localStorage.getItem("sekr_tts") === "1"; } catch (e) {}
  function _clean4speech(t) {
    var s = String(t || "").replace(/\*\*/g, "");
    try {
      s = s.replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE0F}]/gu, "");
    } catch (e) { /* old engine: leave emoji, TTS ignores them */ }
    return s.replace(/\s+/g, " ").trim();
  }
  function speak(text) {
    if (!SS) return;
    try {
      SS.cancel();
      var u = new SpeechSynthesisUtterance(_clean4speech(text));
      u.lang = VOICE_LANG; u.rate = 1.02; u.pitch = 1.0;
      SS.speak(u);
    } catch (e) {}
  }

  var history = [];
  var pendingAction = null;

  // ── build DOM ──────────────────────────────────────────────────────────
  var fab = document.createElement("button");
  fab.className = "sekr-fab";
  fab.setAttribute("aria-label", L.title);
  fab.innerHTML = '<span class="sekr-wave"></span><span class="sekr-wave w2"></span><span class="sekr-orb"><img class="sekr-logo" src="/static/logo-aala-mark.png" alt=""></span>';

  var panel = document.createElement("div");
  panel.className = "sekr-panel";
  panel.innerHTML =
    '<div class="sekr-head"><span class="mini"></span><span><b>' + L.title +
    '</b><small>' + L.sub + '</small></span>' +
    '<button class="sekr-tts" title="' + L.ttsOff + '" aria-label="voice">🔇</button>' +
    '<button class="sekr-x" aria-label="Close">×</button></div>' +
    '<div class="sekr-body"></div>' +
    '<div class="sekr-foot">' +
    '<button class="sekr-mic" title="Voice">🎤</button>' +
    '<textarea rows="1" placeholder="' + L.ph + '"></textarea>' +
    '<button class="sekr-send" title="Send">➤</button></div>';

  document.body.appendChild(fab);
  document.body.appendChild(panel);

  var body = panel.querySelector(".sekr-body");
  var ta = panel.querySelector("textarea");
  var sendBtn = panel.querySelector(".sekr-send");
  var micBtn = panel.querySelector(".sekr-mic");
  var ttsBtn = panel.querySelector(".sekr-tts");
  function _syncTts() {
    if (!ttsBtn) return;
    ttsBtn.textContent = autoSpeak ? "🔊" : "🔇";
    ttsBtn.title = autoSpeak ? L.ttsOn : L.ttsOff;
    ttsBtn.classList.toggle("on", autoSpeak);
  }
  if (!SS && ttsBtn) ttsBtn.style.display = "none";
  _syncTts();
  if (ttsBtn) ttsBtn.onclick = function () {
    autoSpeak = !autoSpeak;
    try { localStorage.setItem("sekr_tts", autoSpeak ? "1" : "0"); } catch (e) {}
    _syncTts();
    if (!autoSpeak && SS) SS.cancel();
  };
  var greeted = false;

  function esc(s) {
    return (s || "").replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }
  function fmt(s) { // minimal **bold** + line breaks
    return esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }
  function scroll() { body.scrollTop = body.scrollHeight; }

  function addMsg(role, text) {
    var d = document.createElement("div");
    d.className = "sekr-msg " + (role === "user" ? "user" : "bot");
    d.innerHTML = fmt(text);
    if (role !== "user" && SS) {
      var sp = document.createElement("button");
      sp.className = "sekr-speak"; sp.type = "button";
      sp.title = L.speak; sp.textContent = "🔊";
      sp.onclick = function () { speak(text); };
      d.appendChild(sp);
    }
    body.appendChild(d); scroll();
    if (role !== "user" && autoSpeak) speak(text);
    return d;
  }
  function typing(on) {
    var ex = body.querySelector(".sekr-typing");
    if (on && !ex) { var d = document.createElement("div"); d.className = "sekr-typing"; d.textContent = "…"; body.appendChild(d); scroll(); }
    else if (!on && ex) ex.remove();
  }

  function addConfirm(action) {
    pendingAction = action;
    var box = document.createElement("div");
    box.className = "sekr-confirm";
    box.innerHTML = "📌 " + esc(action.confirm || "") +
      '<div class="row"><button class="sekr-ok">✓ ' + L.confirm +
      '</button><button class="sekr-no">✕ ' + L.cancel + '</button></div>';
    body.appendChild(box); scroll();
    box.querySelector(".sekr-ok").onclick = function () { doExecute(box); };
    box.querySelector(".sekr-no").onclick = function () {
      pendingAction = null; box.querySelector(".row").remove();
      var p = document.createElement("div"); p.style.cssText = "margin-top:6px;color:#888;font-size:12px"; p.textContent = "✕ " + L.cancel; box.appendChild(p);
    };
  }

  async function doExecute(box) {
    if (!pendingAction) return;
    var act = pendingAction; pendingAction = null;
    box.querySelector(".row").remove();
    typing(true);
    try {
      var r = await fetch("/api/secretary/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: act })
      });
      var data = await r.json();
      typing(false);
      addMsg("bot", data.reply || L.err);
      history.push({ role: "assistant", content: data.reply || "" });
    } catch (e) { typing(false); addMsg("bot", L.err); }
  }

  async function send(text) {
    text = (text || ta.value || "").trim();
    if (!text) return;
    ta.value = ""; ta.style.height = "auto";
    addMsg("user", text);
    history.push({ role: "user", content: text });
    typing(true); sendBtn.disabled = true;
    try {
      var r = await fetch("/api/secretary/message", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.slice(-12) })
      });
      var data = await r.json();
      typing(false);
      if (!r.ok) { addMsg("bot", (data && data.error) ? data.error : L.err); return; }
      if (data.reply) { addMsg("bot", data.reply); history.push({ role: "assistant", content: data.reply }); }
      if (data.action) addConfirm(data.action);
    } catch (e) { typing(false); addMsg("bot", L.err); }
    finally { sendBtn.disabled = false; ta.focus(); }
  }

  // ── open / close ───────────────────────────────────────────────────────
  function open() {
    panel.classList.add("open"); fab.classList.remove("pulse");
    if (!greeted) { greeted = true; addMsg("bot", L.hi); }
    setTimeout(function () { ta.focus(); }, 100);
  }
  function close() { panel.classList.remove("open"); }
  fab.onclick = function () { panel.classList.contains("open") ? close() : open(); };
  panel.querySelector(".sekr-x").onclick = close;

  sendBtn.onclick = function () { send(); };
  ta.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  ta.addEventListener("input", function () {
    ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 96) + "px";
  });

  // ── voice (Web Speech API) ─────────────────────────────────────────────
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) ||
              (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (!SR || isIOS) {
    // iOS WebKit has no in-browser speech recognition. Instead of failing
    // silently, focus the field and tell the user to use the keyboard mic.
    micBtn.onclick = function () { ta.focus(); addMsg("bot", L.micHint); };
  } else {
    var rec = new SR(); rec.lang = VOICE_LANG; rec.interimResults = false; rec.maxAlternatives = 1;
    var recording = false;
    rec.onresult = function (ev) {
      var t = ev.results[0][0].transcript;
      ta.value = t; ta.dispatchEvent(new Event("input"));
      send(t); // auto-send dopo dettatura
    };
    rec.onend = function () { recording = false; micBtn.classList.remove("rec"); };
    rec.onerror = function (e) {
      recording = false; micBtn.classList.remove("rec");
      var err = e && e.error;
      if (err === "not-allowed" || err === "service-not-allowed") addMsg("bot", L.micDenied);
      else if (err === "no-speech" || err === "aborted") { /* silent */ }
      else addMsg("bot", L.micErr);
    };
    micBtn.onclick = function () {
      if (recording) { rec.stop(); return; }
      try { rec.lang = VOICE_LANG; rec.start(); recording = true; micBtn.classList.add("rec"); }
      catch (e) { addMsg("bot", L.micErr); }
    };
  }

  // gentle pulse to invite the first click
  setTimeout(function () { fab.classList.add("pulse"); }, 1500);
})();
