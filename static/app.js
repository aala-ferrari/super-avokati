(() => {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const messages = document.getElementById("messages");
  const sendBtn = document.getElementById("send-btn");
  const menuBtn = document.getElementById("menu-btn");
  const sidebar = document.getElementById("sidebar");
  const scrim = document.getElementById("sidebar-scrim");
  const sidebarClose = document.getElementById("sidebar-close");
  const caseList = document.getElementById("case-list");
  const newCaseBtn = document.getElementById("new-case-btn");
  const caseHeader = document.getElementById("case-header");
  const caseTitleText = document.getElementById("case-title-text");
  const renameBtn = document.getElementById("rename-case-btn");
  const exportMdBtn = document.getElementById("export-md-btn");
  const exportJsonBtn = document.getElementById("export-json-btn");
  const deleteCaseBtn = document.getElementById("delete-case-btn");
  const userBtn = document.getElementById("user-btn");
  const userDropdown = document.getElementById("user-dropdown");
  const logoutBtn = document.getElementById("logout-btn");
  const composerHint = document.getElementById("composer-hint");
  const welcomeMsg = document.getElementById("welcome-msg");
  const dossierBtn = document.getElementById("dossier-btn");
  const dossierPanel = document.getElementById("dossier-panel");
  const dossierClose = document.getElementById("dossier-close");
  const dossierCountBadge = document.getElementById("dossier-count-badge");
  const dossierDrop = document.getElementById("dossier-drop");
  const dossierInput = document.getElementById("dossier-input");
  const dossierList = document.getElementById("dossier-list");
  const composerAttach = document.getElementById("composer-attach");

  // State: the currently-selected case id. When null, the composer is
  // disabled and the welcome screen is shown.
  let activeCaseId = null;

  // V9.8 First-visit tour — auto-open the welcome-tour details on the first
  // page load; persist dismissal so it stays closed thereafter.
  const tourEl = document.getElementById("welcome-tour");
  if (tourEl) {
    if (!localStorage.getItem("sa.tour.seen")) {
      tourEl.open = true;
    }
    tourEl.addEventListener("toggle", () => {
      if (!tourEl.open) localStorage.setItem("sa.tour.seen", "1");
    });
  }

  // ─── sidebar drawer (mobile) ─────────────────────────────────────
  const openSidebar = () => {
    sidebar.classList.add("open");
    scrim.classList.add("open");
    document.body.style.overflow = "hidden";
  };
  const closeSidebar = () => {
    sidebar.classList.remove("open");
    scrim.classList.remove("open");
    document.body.style.overflow = "";
  };
  menuBtn?.addEventListener("click", openSidebar);
  sidebarClose?.addEventListener("click", closeSidebar);
  scrim?.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (sidebar.classList.contains("open")) closeSidebar();
      if (!userDropdown.hidden) userDropdown.hidden = true;
    }
  });

  // ─── user menu ───────────────────────────────────────────────────
  userBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    userDropdown.hidden = !userDropdown.hidden;
  });
  document.addEventListener("click", (e) => {
    if (!userDropdown.hidden && !userDropdown.contains(e.target) && e.target !== userBtn) {
      userDropdown.hidden = true;
    }
  });
  logoutBtn?.addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/";
  });

  // ─── textarea auto-grow ──────────────────────────────────────────
  const autoGrow = () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  };
  input.addEventListener("input", autoGrow);

  // ─── example chips → fill & focus ────────────────────────────────
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", async () => {
      if (!activeCaseId) {
        await createCase();
      }
      input.value = chip.textContent.trim();
      autoGrow();
      input.focus();
    });
  });

  // ─── cases API ───────────────────────────────────────────────────
  async function fetchCases() {
    const resp = await fetch("/api/cases");
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.cases || [];
  }

  async function createCase(title = "Rast i ri") {
    const resp = await fetch("/api/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!resp.ok) return null;
    const c = await resp.json();
    await renderCaseList();
    await selectCase(c.id);
    return c;
  }

  function _sideLabel(s) {
    return { client: "klient", opponent: "kundërshtar", third: "palë e tretë" }[s] || "palë";
  }
  async function checkCaseConflicts(id) {
    try {
      var old = document.getElementById("conflict-banner");
      if (old) old.remove();
      var r = await fetch("/api/cases/" + id + "/conflicts");
      if (!r.ok) return;
      var d = await r.json();
      if (!d.has_conflict || id !== activeCaseId) return;
      var lines = (d.conflicts || []).map(function (c) {
        return "<li><strong>" + escapeHtml(c.party) + "</strong> \u2014 te ju është <b>" +
          _sideLabel(c.here_side) + "</b>, por te «" + escapeHtml(c.other_case_title || "një rast tjetër") +
          "» figuron si <b>" + _sideLabel(c.other_side) + "</b></li>";
      }).join("");
      var b = document.createElement("div");
      b.id = "conflict-banner";
      b.className = "conflict-banner";
      b.innerHTML = '<div class="cb-head">\u26A0\uFE0F Konflikt i mundshëm interesi</div>' +
        '<ul class="cb-list">' + lines + "</ul>" +
        '<div class="cb-foot">Verifiko para se të vazhdosh \u2014 detyrim deontologjik i avokatit.</div>';
      messages.prepend(b);
    } catch (e) { /* silent */ }
  }

  async function selectCase(id) {
    activeCaseId = id;
    const resp = await fetch(`/api/cases/${id}`);
    if (!resp.ok) { activeCaseId = null; return; }
    const c = await resp.json();
    messages.innerHTML = "";
    welcomeMsg?.remove();
    caseHeader.hidden = false;
    caseTitleText.textContent = c.title;
    const stageSelect = document.getElementById("case-stage-select");
    if (stageSelect) {
      stageSelect.value = c.stage || "intake";
      stageSelect.dataset.caseId = id;
    }
    for (const m of c.messages) {
      if (m.role === "user") appendUser(m.content);
      else appendBot({
        kind: m.kind || "answer",
        text: m.content,
        articles: m.articles || [],
        precedents: m.precedents || [],
        timeline: m.timeline || null,
        comparison: m.comparison || null,
        missing_facts: m.missing_facts || null,
        premortem: m.premortem || null,
        distinguishing: m.distinguishing || null,
        evidence_map: m.evidence_map || null,
        nullity_radar: m.nullity_radar || null,
        urgency_radar: m.urgency_radar || null,
        action_plan: m.action_plan || null,
        contradictions: m.contradictions || null,
      });
    }
    renderDossier(c.documents || []);
    checkCaseConflicts(id);
    loadResearch(id);
    dossierPanel.hidden = true;  // reset to collapsed when switching cases
    if (typeof window.__refreshClientsCount === "function") {
      window.__refreshClientsCount();
    }
    sendBtn.disabled = false;
    composerHint.textContent = "Enter për të dërguar · Shift+Enter për rresht të ri";
    input.focus();
    // Mark selected in sidebar
    caseList.querySelectorAll(".case-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === id);
    });
    if (window.innerWidth < 900) closeSidebar();
    // V9.6: surface relevant lessons from past cases
    if (typeof window.surfaceRelevantLessons === "function") {
      window.surfaceRelevantLessons(id);
    }
    // V9.8: surface contextual Pro-tool suggestions based on stage/content
    surfaceCaseSuggestions(c);
  }

  // ── V9.8 contextual suggestions ──────────────────────────────────
  // Rule-based: from stage + title + last message, propose 1-2 Pro tools
  // the lawyer is most likely to need right now. Non-blocking banner;
  // dismissible per case via localStorage.
  function surfaceCaseSuggestions(c) {
    const banner = document.getElementById("suggest-banner");
    if (!banner) return;
    const dismissedKey = `sa.suggest.dismissed.${c.id}`;
    if (localStorage.getItem(dismissedKey)) { banner.hidden = true; return; }

    const stage = c.stage || "intake";
    const docCount = (c.documents || []).length;
    const msgCount = (c.messages || []).length;
    const lastUserMsg = [...(c.messages || [])].reverse().find(m => m.role === "user");
    const haystack = ((c.title || "") + " " + (lastUserMsg?.content || "")).toLowerCase();

    const picks = [];
    const seen = new Set();
    const add = (key, ico, label, why) => {
      if (seen.has(key)) return;
      seen.add(key);
      picks.push({ key, ico, label, why });
    };

    // Stage-driven
    if (stage === "intake" || msgCount <= 1) {
      add("genio", "🧠", "Genio Legale", "Rifrazo rastin nga 6 perspektiva para se të hapësh strategjinë");
    }
    if (stage === "preparation" || (msgCount >= 3 && docCount >= 2)) {
      add("bench", "⚖️", "Bench Memo", "Llogarit P(fitore) dhe identifiko upgrade-t e argumentit");
      add("precedent", "📚", "Pattern e precedentëve", "Cilat lëvizje fituan në raste të ngjashme");
    }
    if (stage === "hearing") {
      add("stress", "⚔️", "Red Team", "Stres-test i tezës para se gjyqtari ta bëjë");
    }
    if (stage === "decision" || stage === "execution") {
      add("coach", "📝", "Ratio Coach", "Bëj post-mortem dhe ruaj mësimet për rastet e ardhshme");
    }

    // Content keywords (additive, capped)
    if (/\bkontrat[ëe]\b|\bklauzol/i.test(haystack))
      add("contract", "📑", "Rishiko kontratë", "Semafor 🟢🟡🔴 për çdo klauzolë + flag GDPR-AL");
    if (/\bshoq[ëe]ri|sh\.p\.k|\bsha\b|visur[ëe]|statut|prokur/i.test(haystack))
      add("corporate", "🏢", "Corporate Intelligence", "Ekstrakto soci/CDA + checklist KYC/AML");
    if (/marr[ëe]veshj|akord|negoci|settlement/i.test(haystack))
      add("settlement", "🎯", "Settlement Monte Carlo", "10k simulime → percentile i ofertës");
    if (/\bpunes\b|pushim|punet[oë]r|kodi.*pun/i.test(haystack))
      add("stress", "⚔️", "Red Team", "Rastet e punës shpesh kanë levat procedurale të padukshme");

    const top = picks.slice(0, 2);
    if (!top.length) { banner.hidden = true; return; }

    banner.innerHTML = `
      <div class="suggest-head">
        <span class="suggest-icon">💡</span>
        <span class="suggest-title">Për këtë rast mund të të ndihmojnë:</span>
        <button type="button" class="suggest-dismiss" title="Mos shfaq më për këtë rast">×</button>
      </div>
      <div class="suggest-row">
        ${top.map(p => `
          <button type="button" class="suggest-chip" data-pro-key="${p.key}">
            <span class="suggest-chip-ico">${p.ico}</span>
            <span class="suggest-chip-body">
              <strong>${escapeHtml(p.label)}</strong>
              <em>${escapeHtml(p.why)}</em>
            </span>
          </button>`).join("")}
      </div>`;
    banner.hidden = false;

    banner.querySelector(".suggest-dismiss")?.addEventListener("click", () => {
      localStorage.setItem(dismissedKey, "1");
      banner.hidden = true;
    });
    banner.querySelectorAll("[data-pro-key]").forEach(b => {
      b.addEventListener("click", () => openProModal(b.dataset.proKey));
    });
  }

  async function renderCaseList() {
    const cases = await fetchCases();
    caseList.innerHTML = "";
    if (!cases.length) {
      const li = document.createElement("li");
      li.className = "case-empty";
      li.textContent = "Nuk ke ende asnjë rast të hapur. Kliko \"Rast i ri\" për të filluar.";
      caseList.appendChild(li);
      return;
    }
    const tpl = document.getElementById("case-item-tpl");
    for (const c of cases) {
      const node = tpl.content.cloneNode(true);
      const li = node.querySelector(".case-item");
      li.dataset.id = c.id;
      if (c.id === activeCaseId) li.classList.add("active");
      node.querySelector(".case-title").textContent = c.title;
      const meta = node.querySelector(".case-meta");
      const stageBadge = c.stage && c.stage !== "intake"
        ? `<span class="stage-badge stage-${c.stage}">${stageEmoji(c.stage)} ${escapeHtml(c.stage_label || c.stage)}</span> · `
        : "";
      meta.innerHTML = stageBadge + escapeHtml(formatWhen(c.updated_at));
      node.querySelector(".case-select").addEventListener("click", () => selectCase(c.id));
      caseList.appendChild(node);
    }
  }

  function stageEmoji(stage) {
    return ({intake:"📥", preparation:"📚", hearing:"⚖️",
             decision:"📜", execution:"🏁"})[stage] || "📁";
  }

  function formatWhen(iso) {
    try {
      const d = new Date(iso);
      const now = new Date();
      const diffMin = Math.round((now - d) / 60000);
      if (diffMin < 1) return "tani";
      if (diffMin < 60) return diffMin + " min më parë";
      const diffH = Math.round(diffMin / 60);
      if (diffH < 24) return diffH + " orë më parë";
      const diffD = Math.round(diffH / 24);
      if (diffD < 7) return diffD + " ditë më parë";
      return d.toLocaleDateString("sq-AL");
    } catch (_) { return ""; }
  }

  newCaseBtn.addEventListener("click", () => createCase());
  document.getElementById("clients-dir-btn")?.addEventListener("click", openClientsDir);
  initModeBar();

  renameBtn.addEventListener("click", async () => {
    if (!activeCaseId) return;
    const newTitle = prompt("Titulli i ri:", caseTitleText.textContent);
    if (!newTitle || !newTitle.trim()) return;
    const resp = await fetch(`/api/cases/${activeCaseId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    if (resp.ok) {
      caseTitleText.textContent = newTitle.trim();
      await renderCaseList();
    }
  });

  const stageSelect = document.getElementById("case-stage-select");
  stageSelect?.addEventListener("change", async () => {
    if (!activeCaseId) return;
    const newStage = stageSelect.value;
    const resp = await fetch(`/api/cases/${activeCaseId}/stage`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: newStage }),
    });
    if (resp.ok) {
      toast(`Faza: ${stageSelect.options[stageSelect.selectedIndex].text}`, "ok");
      await renderCaseList();
    } else {
      toast("Ndryshimi i fazës dështoi", "error");
    }
  });

  exportMdBtn.addEventListener("click", () => {
    if (!activeCaseId) return;
    window.location.href = `/api/cases/${activeCaseId}/export?format=md`;
  });
  exportJsonBtn.addEventListener("click", async () => {
    if (!activeCaseId) return;
    try {
      const cssResp = await fetch("/static/style.css");
      const css = cssResp.ok ? await cssResp.text() : "";
      const clone = messages.cloneNode(true);
      clone.querySelectorAll("button, input, textarea, select, .composer, #composer, .pro-menu, script, [contenteditable]").forEach((el) => el.remove());
      const te = document.getElementById("case-title-text");
      const title = ((te && te.textContent) || "Rasti").trim();
      const esc = (s) => String(s).replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
      const extra = 'body{background:#fff!important;margin:0;padding:22px;color:#1a1a1a}' +
        'main,.messages{display:block!important}' +
        '.topbar,.sidebar,.sidebar-scrim,#composer,.composer,.case-header,.case-header-actions,.icon-btn,.pro-menu-wrap,.user-menu,.logout-fab,.menu-btn{display:none!important}' +
        '.exp-head{font-family:Georgia,"Times New Roman",serif;color:#7a1f1f;border-bottom:2px solid #c9a24d;padding-bottom:10px;margin:0 0 4px;font-size:24px}' +
        '.exp-sub{color:#888;font-size:12px;margin:0 0 20px}' +
        '.messages{max-width:860px;margin:0 auto}' +
        '@media print{body{padding:0}}';
      const doc = '<!doctype html><html lang="sq"><head><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>' + esc(title) + ' — Super Avokati</title>' +
        '<style>' + css + '</style><style>' + extra + '</style></head><body>' +
        '<h1 class="exp-head">' + esc(title) + '</h1>' +
        '<p class="exp-sub">Super Avokati — Beteja fitohet para se të nisë · ' + new Date().toLocaleString("sq") + '</p>' +
        '<div class="messages">' + clone.innerHTML + '</div></body></html>';
      const blob = new Blob([doc], { type: "text/html;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (title.replace(/[^a-z0-9]+/gi, "_").slice(0, 50) || "rasti") + ".html";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    } catch (e) {
      window.location.href = `/api/cases/${activeCaseId}/export?format=md`;
    }
  });

  deleteCaseBtn.addEventListener("click", async () => {
    if (!activeCaseId) return;
    if (!confirm("Sigurt që do ta fshish këtë rast dhe të gjithë historikun e tij? Kjo nuk kthehet mbrapsht.")) return;
    const resp = await fetch(`/api/cases/${activeCaseId}`, { method: "DELETE" });
    if (resp.ok) {
      activeCaseId = null;
      caseHeader.hidden = true;
      dossierPanel.hidden = true;
      dossierList.innerHTML = "";
      updateDossierBadge(0);
      messages.innerHTML = "";
      sendBtn.disabled = true;
      composerHint.textContent = "Hap një rast për të filluar bisedën";
      await renderCaseList();
      // re-insert welcome if still exists in DOM elsewhere, else write static
      messages.innerHTML = `<div class="msg bot welcome"><p><strong>Rasti u fshi.</strong> Kliko "＋ Rast i ri" për të hapur një bisedë të re.</p></div>`;
    }
  });

  // ─── dossier (case documents) ────────────────────────────────────
  // Panel opens either from the paperclip in the composer or the 📎 in the
  // case header. Uploads are blocking + synchronous on the server (extraction
  // + AI analysis) so we show a pending row immediately, then replace it
  // with the analysed row when the server responds.

  function toggleDossier(force) {
    if (!activeCaseId) return;
    const want = force !== undefined ? force : dossierPanel.hidden;
    dossierPanel.hidden = !want;
    if (want) {
      dossierPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  dossierBtn?.addEventListener("click", () => toggleDossier());
  composerAttach?.addEventListener("click", () => {
    if (!activeCaseId) { createCase().then(() => toggleDossier(true)); return; }
    toggleDossier(true);
  });
  dossierClose?.addEventListener("click", () => toggleDossier(false));

  // File input: bubble up through the label click, then pick up the change.
  dossierInput?.addEventListener("change", () => {
    if (!dossierInput.files?.length) return;
    uploadFiles([...dossierInput.files]);
    dossierInput.value = "";  // allow re-selecting the same file
  });

  // Drag & drop anywhere on the drop zone.
  ["dragenter", "dragover"].forEach((ev) => {
    dossierDrop?.addEventListener(ev, (e) => {
      e.preventDefault(); e.stopPropagation();
      dossierDrop.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dossierDrop?.addEventListener(ev, (e) => {
      e.preventDefault(); e.stopPropagation();
      dossierDrop.classList.remove("dragover");
    });
  });
  dossierDrop?.addEventListener("drop", (e) => {
    if (!activeCaseId) return;
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) uploadFiles(files);
  });

  async function uploadFiles(files) {
    if (!activeCaseId) {
      const c = await createCase();
      if (!c) return;
    }
    toggleDossier(true);
    for (const f of files) {
      const pending = appendPendingDoc(f);
      try {
        const fd = new FormData();
        fd.append("file", f);
        const resp = await fetch(`/api/cases/${activeCaseId}/documents`, {
          method: "POST", body: fd,
        });
        const data = await resp.json();
        if (!resp.ok) {
          pending.remove();
          appendErrorDoc(f.name, data.error || `HTTP ${resp.status}`);
          continue;
        }
        pending.remove();
        appendDoc(data);
      } catch (err) {
        pending.remove();
        appendErrorDoc(f.name, err.message);
      }
    }
    await refreshDossier();
  }

  async function refreshDossier() {
    if (!activeCaseId) return;
    const resp = await fetch(`/api/cases/${activeCaseId}/documents`);
    if (!resp.ok) return;
    const { documents } = await resp.json();
    renderDossier(documents || []);
  }

  // ─── Vault: pyet dokumentet e dosjes (Harvey-style) ────────────────
  var vaultBox = document.getElementById("vault-box");
  var vaultQ = document.getElementById("vault-q");
  var vaultAsk = document.getElementById("vault-ask");
  var vaultAnswer = document.getElementById("vault-answer");
  function _vaultFmt(t) {
    return escapeHtml(t || "")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\[Dok (\d+)\]/g, '<span class="vault-cite">[Dok $1]</span>')
      .replace(/\n/g, "<br>");
  }
  async function askVault() {
    var q = ((vaultQ && vaultQ.value) || "").trim();
    if (!q || !activeCaseId) return;
    vaultAsk.disabled = true;
    vaultAnswer.hidden = false;
    vaultAnswer.innerHTML = "<em>Po lexoj dokumentet e dosjes\u2026 (~30s)</em>";
    try {
      var r = await fetch("/api/cases/" + activeCaseId + "/vault", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      var data = await r.json();
      if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
      var cites = (data.docs_used || []).map(function (d) {
        return "[Dok " + d.n + "] " + escapeHtml(d.filename);
      }).join(" \u00b7 ");
      vaultAnswer.innerHTML = '<div class="vault-ans-text">' + _vaultFmt(data.answer) + "</div>" +
        (cites ? '<div class="vault-cites">\ud83d\udcce ' + cites + "</div>" : "");
      _attachSecondOpinion(vaultAnswer, q, data.answer || "");
      _addSaveToCase(vaultAnswer, "vault", "Vault: " + q, data.answer || "");
      setTimeout(function () { try { vaultAnswer.scrollIntoView({ block: "nearest" }); } catch (e) {} }, 40);
    } catch (e) {
      vaultAnswer.innerHTML = '<span style="color:#c0392b">Gabim: ' + escapeHtml(e.message) + "</span>";
    } finally { vaultAsk.disabled = false; }
  }
  if (vaultAsk) vaultAsk.addEventListener("click", askVault);
  var needleBtn = document.getElementById("needle-btn");
  var needleAnswer = document.getElementById("needle-answer");
  if (needleBtn) needleBtn.addEventListener("click", async function () {
    if (!activeCaseId) return;
    needleBtn.disabled = true;
    needleAnswer.hidden = false;
    needleAnswer.innerHTML = "<em>Avokati i Djallit po kërkon gjilpërën në dosje\u2026 (~30s)</em>";
    try {
      var r = await fetch("/api/cases/" + activeCaseId + "/needle", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      var d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
      if (d.empty) { needleAnswer.innerHTML = "<em>Nuk ka dokumente të lexueshme në këtë dosje.</em>"; return; }
      needleAnswer.innerHTML = '<div class="fd-out"></div>';
      var out = needleAnswer.querySelector(".fd-out");
      out.innerHTML = renderMarkdown(d.markdown || "");
      if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
      if (d.citations && d.citations.stats && d.citations.stats.total > 0) needleAnswer.insertBefore(renderCitationsBadge(d.citations, null), out);
      _addSaveToCase(needleAnswer, "needle", "Gjilpëra në dosje", d.markdown || "");
      setTimeout(function () { try { needleAnswer.scrollIntoView({ block: "nearest" }); } catch (e) {} }, 40);
    } catch (e) { needleAnswer.innerHTML = '<span style="color:#c0392b">Gabim: ' + escapeHtml(e.message) + "</span>"; }
    finally { needleBtn.disabled = false; }
  });
  if (vaultQ) vaultQ.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); askVault(); }
  });

  function renderDossier(documents) {
    dossierList.innerHTML = "";
    updateDossierBadge(documents.length);
    if (vaultBox) vaultBox.hidden = !documents.length;
    if (!documents.length) return;
    for (const d of documents) appendDoc(d);
  }

  function updateDossierBadge(n) {
    if (!dossierCountBadge) return;
    if (n > 0) {
      dossierCountBadge.textContent = String(n);
      dossierCountBadge.hidden = false;
    } else {
      dossierCountBadge.hidden = true;
    }
  }

  function docIconFor(ext) {
    ext = (ext || "").toLowerCase();
    if (ext === ".pdf") return "📕";
    if (ext === ".svg") return "🧩";
    if ([".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"].includes(ext)) return "🖼️";
    return "📄";
  }

  function humanSize(n) {
    if (!n || n < 1024) return `${n || 0} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  function appendPendingDoc(file) {
    const li = document.createElement("li");
    li.className = "doc-item pending";
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    li.innerHTML = `
      <div class="doc-row">
        <span class="doc-icon">${docIconFor(ext)}</span>
        <div class="doc-main">
          <div class="doc-head">
            <span class="doc-name"></span>
          </div>
          <div class="doc-meta">
            <span class="doc-size">${humanSize(file.size)}</span>
            <span class="doc-status"><span class="spinner"></span> Po e analizojmë…</span>
          </div>
        </div>
      </div>`;
    li.querySelector(".doc-name").textContent = file.name;
    dossierList.appendChild(li);
    return li;
  }

  function appendErrorDoc(filename, error) {
    const li = document.createElement("li");
    li.className = "doc-item error";
    li.innerHTML = `
      <div class="doc-row">
        <span class="doc-icon">⚠️</span>
        <div class="doc-main">
          <div class="doc-head"><span class="doc-name"></span></div>
          <div class="doc-meta"><span class="doc-status"></span></div>
        </div>
        <div class="doc-actions">
          <button type="button" class="icon-btn danger doc-dismiss">🗑️</button>
        </div>
      </div>`;
    li.querySelector(".doc-name").textContent = filename;
    li.querySelector(".doc-status").textContent = "Ngarkimi dështoi: " + error;
    li.querySelector(".doc-dismiss").addEventListener("click", () => li.remove());
    dossierList.appendChild(li);
  }

  function appendDoc(d) {
    const tpl = document.getElementById("doc-item-tpl");
    const node = tpl.content.cloneNode(true);
    const li = node.querySelector(".doc-item");
    li.dataset.id = d.id;
    li.classList.toggle("error", d.status === "error");
    node.querySelector(".doc-icon").textContent = docIconFor(d.ext);
    node.querySelector(".doc-name").textContent = d.filename;
    if (d.doc_type) {
      node.querySelector(".doc-type").textContent = d.doc_type;
    } else {
      node.querySelector(".doc-type").remove();
    }
    node.querySelector(".doc-size").textContent = humanSize(d.size_bytes);
    const status = node.querySelector(".doc-status");
    if (d.status === "error") {
      status.textContent = "⚠ " + (d.error || "gabim");
    } else if (d.has_text || d.summary) {
      status.textContent = "✓ e analizuar";
      status.classList.add("ok");
    } else {
      status.textContent = "pa tekst";
    }
    const summaryEl = node.querySelector(".doc-summary");
    if (d.summary) summaryEl.textContent = d.summary;
    else summaryEl.remove();

    const viewBtn = node.querySelector(".doc-view");
    viewBtn.href = `/api/cases/${activeCaseId}/documents/${d.id}/raw`;
    viewBtn.hidden = false;

    const detailsEl = node.querySelector(".doc-details");
    const factsEl = node.querySelector(".doc-facts");
    const hasFacts = (d.key_facts && d.key_facts.length);
    if (hasFacts) {
      const ul = document.createElement("ul");
      for (const f of d.key_facts) {
        const fi = document.createElement("li");
        fi.textContent = f;
        ul.appendChild(fi);
      }
      factsEl.appendChild(ul);
    } else {
      factsEl.remove();
    }
    const expandBtn = node.querySelector(".doc-expand");
    if (hasFacts) {
      expandBtn.hidden = false;
      expandBtn.addEventListener("click", () => {
        detailsEl.hidden = !detailsEl.hidden;
        expandBtn.classList.toggle("active", !detailsEl.hidden);
      });
    } else {
      detailsEl.remove();
    }

    node.querySelector(".doc-delete").addEventListener("click", async () => {
      if (!confirm(`Fshi "${d.filename}" nga dosja?`)) return;
      const resp = await fetch(
        `/api/cases/${activeCaseId}/documents/${d.id}`,
        { method: "DELETE" },
      );
      if (resp.ok) {
        await refreshDossier();
      }
    });
    dossierList.appendChild(node);
  }

  // ── V9.8 slash commands (inline tools without leaving chat) ──────
  // Currently: /afatet — KPC/KPP deadline cascade. Format:
  //   /afatet                         → list event types
  //   /afatet <event_type> [YYYY-MM-DD]  → compute (date defaults to today)
  async function handleSlashCommand(text) {
    const m = /^\/(\w[\w-]*)(?:\s+(.*))?$/.exec(text);
    if (!m) return false;
    const cmd = m[1].toLowerCase();
    const argstr = (m[2] || "").trim();
    if (cmd === "afatet") {
      appendUser(text);
      if (!argstr) {
        try {
          const r = await fetch("/api/cascade/event-types");
          const { items } = await r.json();
          const lines = items.map(t => `• \`${t.key}\` — ${t.label}`).join("\n");
          appendInfoBot(`**Llojet e ngjarjeve procedurale**\n\n${lines}\n\nPërdor: \`/afatet <lloji> [data YYYY-MM-DD]\``);
        } catch { appendError("Gabim ngarkimi i llojeve."); }
        return true;
      }
      const parts = argstr.split(/\s+/);
      const eventType = parts[0];
      const eventDate = parts[1] || new Date().toISOString().slice(0, 10);
      appendTyping();
      try {
        const r = await fetch("/api/cascade/compute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event_type: eventType, event_date: eventDate }),
        });
        messages.querySelector(".msg.typing")?.remove();
        const data = await r.json();
        if (!r.ok) { appendError(data.error || "Gabim"); return true; }
        const head = `**⏳ Afatet procedurale** për *${escapeHtml(data.event_label || eventType)}* nga **${eventDate}**\n\n`;
        const rows = (data.deadlines || []).map(d =>
          `• **${d.label}** — afati: **${d.deadline_date}** (${d.days_from_event} ditë) · ${d.legal_basis || ""}`
        ).join("\n");
        appendInfoBot(head + (rows || "Asnjë afat."));
      } catch (err) {
        messages.querySelector(".msg.typing")?.remove();
        appendError("Gabim rrjeti: " + err.message);
      }
      return true;
    }
    return false;
  }

  function appendInfoBot(markdown) {
    const tpl = document.getElementById("bot-msg-tpl");
    const node = tpl.content.cloneNode(true);
    const msgEl = node.querySelector(".msg");
    const body = msgEl.querySelector(".bot-body");
    body.innerHTML = renderMarkdown(markdown);
    highlightNeni(body);
    msgEl.classList.add("slash-info");
    messages.appendChild(node);
    scroll();
  }

  // ─── submit ──────────────────────────────────────────────────────
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    // Slash commands handled inline — no LLM call, no case context required.
    if (text.startsWith("/")) {
      input.value = ""; autoGrow();
      const handled = await handleSlashCommand(text);
      if (handled) return;
      // Unknown slash command → fall through to normal chat send
    }
    if (!activeCaseId) {
      const c = await createCase();
      if (!c) return;
    }
    input.value = "";
    autoGrow();
    appendUser(text);
    const typing = appendTyping();
    sendBtn.disabled = true;
    let streamEl = null;
    let statusEl = null;
    const clearStatus = () => { if (statusEl) { statusEl.remove(); statusEl = null; } };
    let streamBuffer = "";
    const ensureStreamEl = () => {
      if (streamEl) return;
      typing.remove();
      clearStatus();
      const tpl = document.getElementById("bot-msg-tpl");
      const node = tpl.content.cloneNode(true);
      streamEl = node.querySelector(".msg");
      const body = streamEl.querySelector(".bot-body");
      body.innerHTML = "";
      streamEl.dataset.streaming = "1";
      messages.appendChild(node);
      scroll();
    };
    const appendStreamChunk = (chunk) => {
      ensureStreamEl();
      streamBuffer += chunk;
      const body = streamEl.querySelector(".bot-body");
      body.innerHTML = renderMarkdown(streamBuffer);
      highlightNeni(body);
      scroll();
    };
    try {
      const resp = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, case_id: activeCaseId }),
      });
      if (!resp.ok && resp.status === 401) {
        typing.remove();
        window.location.href = "/login";
        return;
      }
      if (!resp.ok || !resp.body) {
        typing.remove();
        appendError("Gabim serveri: " + resp.status);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let carry = "";
      let finalPayload = null;
      let sawError = null;
      outer: while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        carry += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = carry.indexOf("\n\n")) !== -1) {
          const rawEvt = carry.slice(0, idx);
          carry = carry.slice(idx + 2);
          if (!rawEvt.startsWith("data:")) continue;
          const jsonStr = rawEvt.slice(5).trim();
          if (!jsonStr) continue;
          let evt;
          try { evt = JSON.parse(jsonStr); } catch { continue; }
          if (evt.type === "delta" && typeof evt.text === "string") {
            appendStreamChunk(evt.text);
          } else if (evt.type === "status") {
            // Trego tekstin e progresit SI RRESHT i plotë poshtë flluskës (jo brenda saj)
            if (!streamEl && typing && typing.isConnected && typeof evt.text === "string" && evt.text.trim()) {
              if (!statusEl) {
                statusEl = document.createElement("div");
                statusEl.className = "typing-status";
                statusEl.style.cssText = "margin:6px 4px 2px 14px;font-size:13px;color:#6b7280;font-style:italic;line-height:1.5;max-width:80%;white-space:normal;overflow-wrap:anywhere";
                typing.after(statusEl);
              }
              statusEl.textContent = evt.text;
              scroll();
            }
          } else if (evt.type === "final") {
            finalPayload = evt.data || evt;
          } else if (evt.type === "error") {
            sawError = evt.message || "Gabim i panjohur";
          } else if (evt.type === "done") {
            break outer;
          }
        }
      }
      clearStatus();
      if (streamEl) {
        streamEl.remove();
        streamEl = null;
      } else {
        typing.remove();
      }
      if (sawError) {
        appendError(sawError);
      } else if (finalPayload) {
        appendBot(finalPayload);
      } else if (streamBuffer) {
        appendBot({ kind: "answer", text: streamBuffer, articles: [] });
      } else {
        appendError("Nuk u kthye përgjigje nga serveri.");
      }
      await renderCaseList();
      const resp2 = await fetch(`/api/cases/${activeCaseId}`);
      if (resp2.ok) {
        const c = await resp2.json();
        caseTitleText.textContent = c.title;
      }
    } catch (err) {
      clearStatus();
      if (streamEl) streamEl.remove();
      else typing.remove();
      appendError("Gabim rrjeti: " + err.message);
    } finally {
      sendBtn.disabled = false;
      if (window.innerWidth >= 900) input.focus();
    }
  });

  // Enter = send, Shift+Enter = newline
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && window.innerWidth >= 900) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // ─── message rendering ───────────────────────────────────────────
  var _lastQuestion = "";

  function _srcLabel(x) {
    return ({ answer: "\ud83d\udcac Përgjigje", devil: "\ud83d\ude08 Avokati i Djallit",
      adversary: "\u2694\ufe0f Kundërshtari", draft: "\u270d\ufe0f Draft",
      needle: "\ud83d\udd0d Gjilpëra", vault: "\ud83d\udd0e Vault",
      research: "\ud83d\udcdd Kërkim", expertise: "\ud83c\udfaf Ekspertizë", prosecutor: "\ud83c\udfdb\ufe0f Prokuror", notary: "\ud83d\udcdc Noter", deadlines: "\u23f0 Afatet" })[x] || "\ud83d\uddc2\ufe0f";
  }

  function _printAsPdf(title, md) {
    var w = window.open("", "_blank");
    if (!w) { if (typeof toast === "function") toast("Lejo dritaret pop-up për PDF", "warn"); return; }
    var safeTitle = String(title || "Dokument").replace(/[<>&]/g, "");
    var body = (typeof renderMarkdown === "function") ? renderMarkdown(md || "") : escapeHtml(md || "");
    w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>' + safeTitle +
      '</title><style>body{font-family:Georgia,\'Times New Roman\',serif;max-width:800px;margin:32px auto;padding:0 24px;color:#111;line-height:1.55}' +
      'h1,h2,h3{color:#0f2540;line-height:1.3}h1{font-size:22px;border-bottom:2px solid #c9a24b;padding-bottom:6px}h2{font-size:18px}h3{font-size:15px}' +
      'ul,ol{margin:8px 0 8px 22px}code{background:#f3f3f3;padding:1px 4px;border-radius:3px;font-size:.92em}' +
      'table{border-collapse:collapse;margin:10px 0}td,th{border:1px solid #ccc;padding:4px 8px}@media print{body{margin:0}}</style></head><body>' +
      '<h1>' + safeTitle + '</h1>' + body + '</body></html>');
    w.document.close();
    setTimeout(function () { try { w.focus(); w.print(); } catch (e) {} }, 350);
  }

  async function _addSaveToCase(container, source, titleHint, md) {
    if (!container || !md || md.length < 10) return;
    var b = document.createElement("button");
    b.type = "button"; b.className = "save-case-btn";
    b.innerHTML = t("\ud83d\udcbe Ruaj në fashikull");
    b.addEventListener("click", async function () {
      if (!activeCaseId) { if (typeof toast === "function") toast("Hap ose krijo një rast që ta ruash", "warn"); return; }
      b.disabled = true;
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/research", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source: source, title: (titleHint || "Kërkim").slice(0, 120), content: md }),
        });
        if (!r.ok) throw new Error();
        b.innerHTML = t("\u2713 U ruajt në fashikull");
        loadResearch(activeCaseId);
      } catch (e) { b.disabled = false; if (typeof toast === "function") toast("Ruajtja dështoi", "err"); }
    });
    container.appendChild(b);

    var v = document.createElement("button");
    v.type = "button"; v.className = "view-case-btn";
    v.innerHTML = t("\ud83d\uddc2\ufe0f Shiko të ruajturat");
    v.addEventListener("click", function () { openSavedResearch(); });
    container.appendChild(v);

    var dx = document.createElement("button");
    dx.type = "button"; dx.className = "dl-docx-btn"; dx.innerHTML = "⬇️ DOCX";
    dx.addEventListener("click", async function () {
      dx.disabled = true;
      try {
        var r = await fetch("/api/export/docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ markdown: md, title: titleHint || "Dokument" }) });
        if (!r.ok) throw new Error();
        var blob = await r.blob(); var url = URL.createObjectURL(blob);
        var a2 = document.createElement("a"); a2.href = url;
        a2.download = ((titleHint || "dokument").replace(/[^0-9A-Za-z _-]/g, "").slice(0, 60).trim() || "dokument") + ".docx";
        document.body.appendChild(a2); a2.click(); a2.remove(); URL.revokeObjectURL(url);
      } catch (e) { if (typeof toast === "function") toast("Shkarkimi dështoi", "err"); }
      finally { dx.disabled = false; }
    });
    container.appendChild(dx);

    var pf = document.createElement("button");
    pf.type = "button"; pf.className = "dl-pdf-btn"; pf.innerHTML = "⬇️ PDF";
    pf.addEventListener("click", function () { _printAsPdf(titleHint || "Dokument", md); });
    container.appendChild(pf);
  }

  (function () {
    var srch = document.getElementById("research-search");
    if (srch) srch.addEventListener("input", function () {
      var q = srch.value.trim().toLowerCase();
      var list = document.getElementById("research-list");
      if (!list) return;
      Array.prototype.forEach.call(list.querySelectorAll(".research-item"), function (li) {
        li.style.display = (!q || (li.dataset.search || "").indexOf(q) >= 0) ? "" : "none";
      });
    });
  })();

  async function loadResearch(id) {
    var box = document.getElementById("research-box");
    var list = document.getElementById("research-list");
    if (!box || !list || !id) return;
    try {
      var r = await fetch("/api/cases/" + id + "/research");
      if (!r.ok) { box.hidden = true; return; }
      var d = await r.json();
      var items = d.items || [];
      box.hidden = false;
      var _emp = document.getElementById("research-empty");
      if (_emp) _emp.hidden = items.length > 0;
      list.innerHTML = "";
      items.forEach(function (it) {
        var li = document.createElement("li");
        li.className = "research-item";
        li.dataset.search = ((it.title || "") + " " + (it.content || "") + " " + (it.client_name || "")).toLowerCase();
        var head = document.createElement("div");
        head.className = "research-head";
        head.innerHTML = '<span class="research-src">' + escapeHtml(_srcLabel(it.source)) + '</span>' +
          (it.client_name ? '<span class="research-cli">\ud83d\udc64 ' + escapeHtml(it.client_name) + '</span>' : "") +
          '<span class="research-ttl">' + escapeHtml(it.title || "") + '</span>' +
          '<button class="research-del" title="Fshij" type="button">\u00d7</button>';
        var body = document.createElement("div");
        body.className = "research-body"; body.hidden = true;
        head.addEventListener("click", function (e) {
          if (e.target.classList.contains("research-del")) return;
          if (body.hidden) { body.innerHTML = renderMarkdown(it.content || ""); body.hidden = false; }
          else body.hidden = true;
        });
        head.querySelector(".research-del").addEventListener("click", async function (e) {
          e.stopPropagation();
          if (!confirm("Fshij këtë kërkim nga fashikulli?")) return;
          await fetch("/api/cases/" + id + "/research/" + it.id, { method: "DELETE" });
          loadResearch(id);
        });
        li.appendChild(head); li.appendChild(body); list.appendChild(li);
      });
    } catch (e) { box.hidden = true; }
  }

  async function openSavedResearch() {
    if (!activeCaseId) { if (typeof toast === "function") toast("Hap një rast që të shohësh të ruajturat", "warn"); return; }
    var ov = document.getElementById("saved-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "saved-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>🗂️ Kërkime të ruajtura</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<input type="text" class="research-search sv-search" placeholder="🔍 Kërko në të ruajturat…" />' +
      '<div class="exp-body"><ul class="research-list sv-list"><li>Po ngarkoj…</li></ul></div>' +
      '</div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var list = ov.querySelector(".sv-list"), srch = ov.querySelector(".sv-search");
    async function render() {
      list.innerHTML = "<li>Po ngarkoj…</li>";
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/research");
        var d = await r.json(); var items = d.items || [];
        if (!items.length) { list.innerHTML = '<li class="research-empty">Ende asnjë kërkim i ruajtur. Kliko “💾 Ruaj në fashikull” te një rezultat.</li>'; return; }
        list.innerHTML = "";
        items.forEach(function (it) {
          var li = document.createElement("li"); li.className = "research-item";
          li.dataset.search = ((it.title || "") + " " + (it.content || "") + " " + (it.client_name || "")).toLowerCase();
          var head = document.createElement("div"); head.className = "research-head";
          head.innerHTML = '<span class="research-src">' + escapeHtml(_srcLabel(it.source)) + '</span>' +
            (it.client_name ? '<span class="research-cli">👤 ' + escapeHtml(it.client_name) + '</span>' : "") +
            '<span class="research-ttl">' + escapeHtml(it.title || "") + '</span>' +
            '<button class="research-del" title="Fshij" type="button">×</button>';
          var body = document.createElement("div"); body.className = "research-body"; body.hidden = true;
          head.addEventListener("click", function (e) {
            if (e.target.classList.contains("research-del")) return;
            if (body.hidden) { body.innerHTML = renderMarkdown(it.content || ""); body.hidden = false; }
            else body.hidden = true;
          });
          head.querySelector(".research-del").addEventListener("click", async function (e) {
            e.stopPropagation();
            if (!confirm("Fshij këtë kërkim nga fashikulli?")) return;
            try { await fetch("/api/cases/" + activeCaseId + "/research/" + it.id, { method: "DELETE" }); } catch (e2) {}
            render(); if (typeof loadResearch === "function") loadResearch(activeCaseId);
          });
          li.appendChild(head); li.appendChild(body); list.appendChild(li);
        });
      } catch (e) { list.innerHTML = "<li>Gabim gjatë ngarkimit.</li>"; }
    }
    if (srch) srch.addEventListener("input", function () {
      var q = srch.value.trim().toLowerCase();
      Array.prototype.forEach.call(list.querySelectorAll(".research-item"), function (li) {
        li.style.display = (!q || (li.dataset.search || "").indexOf(q) >= 0) ? "" : "none";
      });
    });
    render();
  }

  async function _runSecondOpinion(question, answer, panel, btn) {
    btn.disabled = true;
    panel.hidden = false;
    panel.innerHTML = '<div class="so-loading">\ud83d\udd2e Avokati i Djallit po mendon thell\u00eb\u2026</div>';
    try {
      const r = await fetch("/api/second-opinion", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question || "", answer: answer || "" }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
      panel.innerHTML =
        '<div class="so-head">\ud83d\udd2e Avokati i Djallit'
        + '<span class="so-tag">k\u00ebndv\u00ebshtrim i dyt\u00eb</span></div>'
        + '<div class="so-body">' + renderMarkdown(d.markdown || "") + '</div>';
      const bodyEl = panel.querySelector(".so-body");
      if (bodyEl && d.citations) highlightNeni(bodyEl, buildCitStatusMap(d.citations));
      if (bodyEl && d.citations && d.citations.stats && d.citations.stats.total > 0) {
        panel.insertBefore(renderCitationsBadge(d.citations, null), bodyEl);
      }
      _addSaveToCase(panel, "devil", "Avokati i Djallit", d.markdown || "");
    } catch (e) {
      panel.innerHTML = '<div class="so-err">Gabim: ' + escapeHtml(e.message) + '</div>';
      btn.disabled = false;
    }
  }

  function _attachSecondOpinion(msgEl, question, answer) {
    if (!msgEl || (answer || "").length < 40) return;
    const wrap = document.createElement("div");
    wrap.className = "so-wrap";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "so-btn";
    btn.innerHTML = '\ud83d\udd2e Avokati i Djallit <em>gjej gjilp\u00ebr\u00ebn n\u00eb kasht\u00eb</em>';
    const panel = document.createElement("div");
    panel.className = "so-panel"; panel.hidden = true;
    btn.addEventListener("click", function () { _runSecondOpinion(question, answer, panel, btn); });
    wrap.appendChild(btn); wrap.appendChild(panel);
    msgEl.appendChild(wrap);
  }

  function appendUser(text) {
    _lastQuestion = text;
    const tpl = document.getElementById("user-msg-tpl");
    const node = tpl.content.cloneNode(true);
    node.querySelector("p").textContent = text;
    messages.appendChild(node);
    scroll();
  }

  function appendTyping() {
    const tpl = document.getElementById("typing-tpl");
    const node = tpl.content.cloneNode(true);
    const el = node.querySelector(".msg");
    messages.appendChild(node);
    scroll();
    return el;
  }

  function appendBot(data) {
    const tpl = document.getElementById("bot-msg-tpl");
    const node = tpl.content.cloneNode(true);
    const msgEl = node.querySelector(".msg");
    const body = node.querySelector(".bot-body");

    body.innerHTML = renderMarkdown(data.text || "");
    const citStatusMap = buildCitStatusMap(data.citations);
    highlightNeni(body, citStatusMap);
    linkCaseMarkers(body, data.precedents || []);
    if (data.kind !== "error") _attachSecondOpinion(msgEl, _lastQuestion, data.text || "");
    if (data.kind !== "error") _addSaveToCase(msgEl, "answer", _lastQuestion || "Përgjigje", data.text || "");

    // Citation trust badge — provenance lock. Always at the very top of
    // the answer (before urgency/action-plan) so the lawyer's eye lands on
    // it first: "are these citations real or hallucinated?"
    if ((data.citations && data.citations.stats && data.citations.stats.total > 0) ||
        (data.decision_citations && data.decision_citations.stats && data.decision_citations.stats.total > 0)) {
      msgEl.insertBefore(renderCitationsBadge(data.citations || { stats: {}, items: [] }, data.decision_citations), body);
    }
    // V8.11 Citation Shield V2 — provenance panel beneath the badge.
    // Lawyer can inspect KB version, model, hash; export full pack.
    if (data.provenance && data.provenance.response_id) {
      msgEl.insertBefore(renderProvenancePanel(data.provenance), body);
    }

    // Urgency radar — ALWAYS AT THE TOP when level != none. An emergency
    // panel below the answer text defeats the purpose: the citizen needs
    // to see "you're in an emergency; here's what to do now" BEFORE the
    // five-section analysis. Empty radar contributes nothing (we keep
    // theoretical questions visually calm).
    const urgencyRadar = data.urgency_radar;
    if (urgencyRadar && urgencyRadar.level && urgencyRadar.level !== "none"
        && (urgencyRadar.signals || []).length) {
      msgEl.insertBefore(renderUrgencyRadar(urgencyRadar), body);
    }

    // Action plan — consolidated, time-bucketed checklist. Sits ABOVE
    // the body so the citizen sees "here's your plan for this week"
    // before reading the five-section prose. Null/empty on theoretical
    // questions so the UI stays clean.
    const actionPlan = data.action_plan;
    if (actionPlan && (actionPlan.items || []).length) {
      msgEl.insertBefore(renderActionPlan(actionPlan), body);
    }

    const retrieved = node.querySelector(".retrieved");
    const count = node.querySelector(".count");
    const list = node.querySelector(".articles");
    const articles = data.articles || [];
    const precedents = data.precedents || [];
    count.textContent = articles.length;

    if (!articles.length) {
      retrieved.remove();
    } else {
      for (const a of articles) {
        const li = document.createElement("li");
        li.innerHTML = `
          <span class="art-score">${a.score}</span>
          <div class="art-cite">${escapeHtml(a.citation)}${a.repealed ? ' <em>(shfuqizuar)</em>' : ''}</div>
          <div class="art-head">${escapeHtml(a.heading || "")}</div>
          <div class="art-body">${escapeHtml(a.body || "").replace(/\n/g, "<br>")}</div>
        `;
        li.querySelector(".art-body").addEventListener("click", (e) => {
          e.currentTarget.classList.toggle("expanded");
        });
        list.appendChild(li);
      }
    }

    // Precedent comparison (winners-vs-losers compass) — a single, glanceable
    // "are you on the winning side?" card. Only appears when both sides had
    // data to compare. Rendered above timeline so the strategic framing
    // precedes the deadline pressure.
    const comparison = data.comparison;
    if (comparison && !comparisonEmpty(comparison)) {
      msgEl.insertBefore(renderComparison(comparison), null);
    }

    // Pre-mortem — "5 reasons we could lose." Rendered right below the
    // comparison card so the citizen sees the honest risk frame before
    // the deadlines and precedents. Collapsed by default (heavy reading),
    // but the summary shows the risk count with a red dot when severe.
    const premortem = data.premortem;
    if (premortem && (premortem.risks || []).length) {
      msgEl.insertBefore(renderPremortem(premortem), null);
    }

    // Distinguishing — adverse precedents + lawyer's response for each.
    // Shown after the pre-mortem (so the user has the big-picture risk
    // frame first) and before the general precedent list.
    const distinguishing = data.distinguishing;
    if (distinguishing && (distinguishing.items || []).length) {
      msgEl.insertBefore(renderDistinguishing(distinguishing), null);
    }

    // Evidence map — who bears the burden of proof for each claim, with
    // burden-shift flags (labor / discrimination / consumer / domestic
    // violence). Rendered after distinguishing so the citizen has the
    // legal frame before hitting the "what proof do I need" board.
    const evidenceMap = data.evidence_map;
    if (evidenceMap && (evidenceMap.claims || []).length) {
      msgEl.insertBefore(renderEvidenceMap(evidenceMap), null);
    }

    // Contradictions — inter-document inconsistencies (dates, amounts,
    // parties, signatures, narrative). Rendered after evidence_map so
    // the citizen has the proof frame before seeing where the proofs
    // contradict each other. Only appears when ≥1 contradiction found;
    // a single-doc dossier never triggers the stage.
    const contradictions = data.contradictions;
    if (contradictions && (contradictions.items || []).length) {
      msgEl.insertBefore(renderContradictions(contradictions), null);
    }

    // Nullity + deadline radar — procedural levers: nullities,
    // forfeitures, prescription. Rendered last among the analytical
    // panels because it's the most technical; opens by default
    // whenever any "po"-applicable finding exists (these are case-
    // winning levers the citizen must not miss).
    const nullityRadar = data.nullity_radar;
    if (nullityRadar && (nullityRadar.findings || []).length) {
      msgEl.insertBefore(renderNullityRadar(nullityRadar), null);
    }

    // Timeline widget — past anchors + future deadlines with colour-coded
    // urgency badges. Rendered before the precedents block so citizens see
    // the "act by X" summary first.
    const timeline = data.timeline;
    if (timeline && (timeline.anchors?.length || timeline.deadlines?.length)) {
      msgEl.insertBefore(renderTimeline(timeline), null);
    }

    // Court precedents — shown in a second collapsible block when any exist.
    if (precedents.length) {
      const prec = document.createElement("details");
      prec.className = "precedents";
      const outcomeTag = (o) => o
        ? `<span class="prec-outcome prec-${o}">${escapeHtml(o)}</span>`
        : "";
      const articlesBadges = (arts) => (arts || [])
        .map((a) => `<span class="prec-article">${escapeHtml(a.code)} neni ${escapeHtml(a.article)}</span>`)
        .join("");
      const judgesLine = (js) => (js && js.length)
        ? `<div class="prec-judges">Trupi gjykues: ${escapeHtml(js.join(", "))}</div>`
        : "";
      const items = precedents.map((d) => `
        <li>
          <span class="art-score">${d.score}</span>
          <div class="prec-cite">
            <a class="prec-caseid" href="/case-precedent/${d.id}" target="_blank" rel="noopener" title="Hap fashikullin e plotë">${escapeHtml(d.citation)}</a>
            <span class="prec-date">${escapeHtml(d.date || "")}</span>
            ${outcomeTag(d.outcome)}
          </div>
          ${d.summary ? `<div class="prec-objekti">${escapeHtml(d.summary)}</div>` : ""}
          ${d.articles_cited && d.articles_cited.length ? `<div class="prec-articles">${articlesBadges(d.articles_cited)}</div>` : ""}
          ${judgesLine(d.judges)}
          ${d.source_url ? `<a class="prec-link" href="${encodeURI(d.source_url)}" target="_blank" rel="noopener">Lexo vendimin →</a>` : ""}
          ${d.download ? `<a class="prec-dl" href="/api/precedent-file?f=${encodeURIComponent(d.download)}" title="Shkarko dokumentin origjinal">📎 Shkarko vendimin</a>` : ""}
          <button type="button" class="prec-validity" data-vid="${d.id}">🔍 Statusi i vendimit</button><span class="prec-vresult" data-vid="${d.id}"></span>
        </li>
      `).join("");
      prec.innerHTML = `
        <summary>⚖️ Vendime relevante të gjykatave (${precedents.length})</summary>
        <ul class="precedents-list">${items}</ul>
      `;
      prec.addEventListener("click", onPrecValidity);
      msgEl.insertBefore(prec, null);
    }

    // Missing-facts — "3 pyetje që do ta ndryshonin përgjigjen." Appears
    // at the end so it feels like a natural next step: the answer's done,
    // here's where to drill deeper.
    const missing = data.missing_facts;
    if (missing && (missing.facts || []).length) {
      msgEl.insertBefore(renderMissingFacts(missing), null);
    }

    // kind classes
    if (data.kind === "error") msgEl.classList.add("error");
    if (data.kind === "answer" && articles.length > 0) {
      msgEl.classList.add("answer");
    }

    messages.appendChild(node);
    scroll();

    // celebrate a full, grounded answer with a burst of golden sparkles
    if (data.kind === "answer" && articles.length > 0) {
      requestAnimationFrame(() => sparkle(msgEl));
    }
  }

  function appendError(text) {
    appendBot({ kind: "error", text, articles: [] });
  }

  function scroll() {
    requestAnimationFrame(() =>
      messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" })
    );
  }

  // ─── sparkle particles ──────────────────────────────────────────
  function sparkle(target) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = target.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + Math.min(rect.height * 0.3, 80);
    const n = 16;
    for (let i = 0; i < n; i++) {
      const s = document.createElement("div");
      s.className = "sparkle";
      const angle = (i / n) * Math.PI * 2 + Math.random() * 0.5;
      const dist = 90 + Math.random() * 110;
      const dx = Math.cos(angle) * dist * (0.7 + Math.random() * 0.5);
      const dy = Math.sin(angle) * dist * 0.7 - 40;
      s.style.left = cx + "px";
      s.style.top = cy + "px";
      s.style.setProperty("--dx", dx + "px");
      s.style.setProperty("--dy", dy + "px");
      s.style.animationDelay = (Math.random() * 180) + "ms";
      const size = 6 + Math.random() * 8;
      s.style.width = size + "px";
      s.style.height = size + "px";
      document.body.appendChild(s);
      setTimeout(() => s.remove(), 2000);
    }
  }

  // ─── highlight "Neni X" citations after markdown render ─────────
  // Build a {articleNumber → worstStatus} map from the citation shield payload.
  // Worst-status wins so the lawyer never sees green over a fake citation
  // (same number can appear under multiple codes; we color defensively).
  function buildCitStatusMap(citations) {
    const map = new Map();
    if (!citations || !Array.isArray(citations.items)) return map;
    const rank = { fake: 4, repealed: 3, needs_code: 2, verified: 1 };
    const numRe = /Neni\s*(\d+(?:[\/-][a-zçëA-ZÇË0-9]+)?)/;
    for (const c of citations.items) {
      const m = numRe.exec(c.raw || "");
      if (!m) continue;
      const key = m[1].toLowerCase();
      const prev = map.get(key);
      if (!prev || (rank[c.status] || 0) > (rank[prev] || 0)) {
        map.set(key, c.status);
      }
    }
    return map;
  }

  function highlightNeni(root, citStatusMap) {
    const re = /\bNeni\s*(\d+(?:\s*[\/-]\s*[a-zçëA-ZÇË0-9]+)?)/g;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const toReplace = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && node.parentElement.closest(".neni-cite, code")) continue;
      if (re.test(node.nodeValue)) toReplace.push(node);
      re.lastIndex = 0;
    }
    const statusClass = {
      verified: "neni-cite-ok",
      fake: "neni-cite-fake",
      repealed: "neni-cite-warn",
      needs_code: "neni-cite-warn",
    };
    for (const n of toReplace) {
      const frag = document.createDocumentFragment();
      let last = 0;
      const text = n.nodeValue;
      let m;
      const rx = new RegExp(re.source, "g");
      while ((m = rx.exec(text)) !== null) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        const span = document.createElement("span");
        const num = (m[1] || "").replace(/\s+/g, "").toLowerCase();
        const status = citStatusMap ? citStatusMap.get(num) : null;
        span.className = "neni-cite" + (status ? " " + statusClass[status] : "");
        if (status === "verified") span.title = "Citim i verifikuar kundër korpusit";
        if (status === "fake") span.title = "⚠ Citim që nuk u gjet në korpus";
        if (status === "repealed") span.title = "⚠ Neni ekziston por është shfuqizuar";
        if (status === "needs_code") span.title = "ℹ Kod i pa-specifikuar — verifiko";
        span.textContent = m[0];
        frag.appendChild(span);
        last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      n.parentNode.replaceChild(frag, n);
    }
  }

  // ─── convert [[case:ID]] markers → clickable pin-to-row links ───
  async function onPrecValidity(e) {
    var btn = e.target.closest(".prec-validity");
    if (!btn) return;
    var vid = btn.getAttribute("data-vid");
    var res = btn.parentElement.querySelector('.prec-vresult[data-vid="' + vid + '"]');
    btn.disabled = true;
    if (res) res.innerHTML = ' <em style="color:#9a8a63">po kontrolloj vendimet e mëvonshme\u2026</em>';
    try {
      var r = await fetch("/api/decision-validity", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: parseInt(vid, 10) }),
      });
      var d = await r.json();
      if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
      var cls = { ne_fuqi: "v-ok", tejkaluar: "v-bad", kufizuar: "v-warn", e_paqarte: "v-unk" }[d.status] || "v-unk";
      var h = '<span class="prec-vbadge ' + cls + '">' + (d.icon || "") + " " + escapeHtml(d.label || d.status) + "</span>";
      if (d.superseded_by) h += ' <span class="prec-vnote">\u21b3 ' + escapeHtml(d.superseded_by) + "</span>";
      if (d.note) h += '<div class="prec-vnote">' + escapeHtml(d.note) + "</div>";
      if (res) res.innerHTML = h;
      btn.style.display = "none";
    } catch (err) {
      if (res) res.innerHTML = ' <span style="color:#c0392b">Gabim: ' + escapeHtml(err.message) + "</span>";
      btn.disabled = false;
    }
  }

  function linkCaseMarkers(root, precedents) {
    const byId = new Map((precedents || []).map((p) => [String(p.id), p]));
    const re = /\[\[case:(\d+)\]\]/g;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const toReplace = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && node.parentElement.closest(".case-cite, code")) continue;
      if (re.test(node.nodeValue)) toReplace.push(node);
      re.lastIndex = 0;
    }
    for (const n of toReplace) {
      const frag = document.createDocumentFragment();
      let last = 0;
      const text = n.nodeValue;
      let m;
      const rx = new RegExp(re.source, "g");
      while ((m = rx.exec(text)) !== null) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        const id = m[1];
        const p = byId.get(id);
        const a = document.createElement("a");
        a.className = "case-cite";
        a.href = `/case-precedent/${id}`;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = p ? `⚖ ${p.citation}` : `⚖ vendim #${id}`;
        if (p && p.outcome) a.title = p.outcome;
        frag.appendChild(a);
        last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      n.parentNode.replaceChild(frag, n);
    }
  }

  // ─── render distinguishing panel (adverse precedents + rebuttal) ──
  function renderDistinguishing(d) {
    const wrap = document.createElement("details");
    const items = d.items || [];
    const dangerous = items.filter((i) => i.still_dangerous);
    wrap.className = "distinguishing" + (dangerous.length ? " dist-has-danger" : "");
    wrap.open = dangerous.length > 0;

    const lis = items.map((item) => {
      const cls = item.still_dangerous ? "dist-danger" : "dist-safe";
      const tag = item.still_dangerous ? "⚠️ RREZIKSHËM" : "✂ DISTINGUISH";
      return `
        <li class="dist-item ${cls}">
          <div class="dist-head">
            <span class="dist-tag">${tag}</span>
            <a class="dist-cite" href="/case-precedent/${item.case_id}" target="_blank" rel="noopener">${escapeHtml(item.case_citation)}</a>
          </div>
          <div class="dist-reason">${escapeHtml(item.reason)}</div>
        </li>
      `;
    }).join("");

    const label = dangerous.length
      ? `🛡️ Precedentë sfavorizues (${items.length}, ${dangerous.length} ende të rrezikshëm)`
      : `🛡️ Precedentë sfavorizues (${items.length} — të gjithë distinguish)`;
    wrap.innerHTML = `
      <summary>${label}</summary>
      <div class="dist-intro">Çdo vendim më poshtë u gjet nga BM25 si i ngjashëm me rastin — dhe për secilin është bërë distinguishing: pse nuk aplikohet, ose si mbrohemi nëse aplikohet.</div>
      <ul class="dist-list">${lis}</ul>
    `;
    return wrap;
  }

  // ─── render evidence map panel (who proves what, burden-shifts) ──
  function renderEvidenceMap(em) {
    const wrap = document.createElement("details");
    const claims = em.claims || [];
    const missing = claims.filter((c) => c.status === "mungon" || c.status === "e dobët");
    const shifts = claims.filter((c) => c.burden_shift);
    wrap.className = "evidence-map"
      + (missing.length ? " em-has-missing" : "")
      + (shifts.length ? " em-has-shift" : "");
    // Open by default when there's something alarming to see: missing
    // proofs the citizen needs to gather, OR burden-shift rules where
    // the law puts the weight on the other side (huge strategic lever).
    wrap.open = missing.length > 0 || shifts.length > 0;

    const statusIcon = {
      "kemi": "✅",
      "mungon": "❌",
      "e dobët": "⚠️",
      "kontestuese": "❓",
    };
    const statusLabel = {
      "kemi": "e kemi",
      "mungon": "mungon",
      "e dobët": "e dobët",
      "kontestuese": "kontestuese",
    };
    const bearerLabel = {
      "klienti": "klienti yt",
      "qytetari": "klienti yt", // legacy alias (pre-V9.9)
      "kundërshtari": "pala tjetër",
      "shteti": "shteti / akuzuesi",
      "ndarë": "barrë e ndarë",
    };

    const items = claims.map((c, i) => {
      const icon = statusIcon[c.status] || "❓";
      const sLabel = statusLabel[c.status] || c.status;
      const bLabel = bearerLabel[c.who_bears_burden] || c.who_bears_burden;
      const shiftBadge = c.burden_shift
        ? `<span class="em-shift" title="Ligji e zhvendos barrën e provës mbi palën tjetër">🔄 BARRA E ZHVENDOSUR</span>`
        : "";
      const notes = c.notes
        ? `<div class="em-notes">${escapeHtml(c.notes)}</div>` : "";
      return `
        <li class="em-item em-status-${escapeHtml(c.status || "mungon")}">
          <div class="em-head">
            <span class="em-num">${i + 1}</span>
            <span class="em-status">${icon} ${escapeHtml(sLabel)}</span>
            ${shiftBadge}
          </div>
          <div class="em-claim">${escapeHtml(c.claim)}</div>
          <div class="em-proof"><strong>Provë e nevojshme:</strong> ${escapeHtml(c.needed_proof)}</div>
          <div class="em-bearer"><strong>Duhet ta provojë:</strong> ${escapeHtml(bLabel)}</div>
          ${notes}
        </li>
      `;
    }).join("");

    let label = `📋 Mapa e provës (${claims.length} pretendime)`;
    if (shifts.length && missing.length) {
      label = `📋 Mapa e provës — ${missing.length} provë që mungojnë, ${shifts.length} me barrë të zhvendosur`;
    } else if (shifts.length) {
      label = `📋 Mapa e provës — ${shifts.length} rregull me barrë të zhvendosur 🔄`;
    } else if (missing.length) {
      label = `📋 Mapa e provës — ${missing.length}/${claims.length} provë ende pa mbledhur`;
    }

    wrap.innerHTML = `
      <summary>${label}</summary>
      <div class="em-intro">Për çdo pretendim tregojmë ÇFARË duhet provuar dhe KUSH duhet ta provojë. Kur ligji e zhvendos barrën (punë, diskriminim, konsumator, dhunë në familje), pala tjetër është ajo që duhet të provojë të kundërtën.</div>
      <ul class="em-list">${items}</ul>
    `;
    return wrap;
  }

  // ─── render nullity + deadline radar (procedural levers) ────────
  function renderNullityRadar(nr) {
    const wrap = document.createElement("details");
    const findings = nr.findings || [];
    const applicable = findings.filter((f) => f.citizen_applicable === "po");
    const absolute = findings.filter((f) => f.kind === "nullity_absolute" && f.citizen_applicable === "po");
    const hasDeadlineAgainst = findings.some(
      (f) => (f.kind === "deadline" || f.kind === "prescription")
        && f.citizen_applicable === "po"
        && (f.applies_to === "kundërshtari" || f.applies_to === "të dyja") === false
        && f.applies_to === "qytetari"
    );
    wrap.className = "nullity-radar"
      + (applicable.length ? " nr-has-applicable" : "")
      + (absolute.length ? " nr-has-absolute" : "")
      + (hasDeadlineAgainst ? " nr-has-deadline-against" : "");
    // Open by default whenever there's at least one applicable finding:
    // these are the case-winning procedural levers, and missing an
    // applicable deadline is the most expensive mistake a citizen can make.
    wrap.open = applicable.length > 0;

    const kindIcon = {
      nullity_absolute: "🛑",
      nullity_relative: "⚠️",
      deadline: "⏰",
      prescription: "📅",
      procedural_defect: "⚙️",
    };
    const kindLabel = {
      nullity_absolute: "Pavlefshmëri absolute",
      nullity_relative: "Pavlefshmëri relative",
      deadline: "Afat dekadencial",
      prescription: "Parashkrim",
      procedural_defect: "Defekt procedural",
    };
    const applicableBadge = {
      po: "✅ PO APLIKOHET",
      ndoshta: "❓ NDOSHTA",
      jo: "— nuk aplikohet",
    };
    const appliesLabel = {
      qytetari: "në favor tonin",
      kundërshtari: "në favor të palës tjetër",
      "të dyja": "dypalësh",
    };

    const items = findings.map((f) => {
      const kind = f.kind || "procedural_defect";
      const icon = kindIcon[kind] || "•";
      const kLabel = kindLabel[kind] || kind;
      const app = f.citizen_applicable || "ndoshta";
      const appLabel = applicableBadge[app] || "—";
      const appliesFor = appliesLabel[f.applies_to] || "";
      const basis = f.legal_basis
        ? `<span class="nr-basis">${escapeHtml(f.legal_basis)}</span>` : "";
      const cond = f.condition
        ? `<div class="nr-row"><span class="nr-key">Kusht:</span> ${escapeHtml(f.condition)}</div>` : "";
      const dln = f.deadline_hint
        ? `<div class="nr-row nr-deadline"><span class="nr-key">⏰ Afati:</span> ${escapeHtml(f.deadline_hint)}</div>` : "";
      const cons = f.consequence
        ? `<div class="nr-row"><span class="nr-key">Pasoja:</span> ${escapeHtml(f.consequence)}</div>` : "";
      const act = f.action
        ? `<div class="nr-action"><strong>▶ Veprim:</strong> ${escapeHtml(f.action)}</div>` : "";
      return `
        <li class="nr-item nr-kind-${escapeHtml(kind)} nr-app-${escapeHtml(app)}">
          <div class="nr-head">
            <span class="nr-kind">${icon} ${escapeHtml(kLabel)}</span>
            <span class="nr-applicable">${appLabel}</span>
            ${appliesFor ? `<span class="nr-applies">${escapeHtml(appliesFor)}</span>` : ""}
          </div>
          <div class="nr-name">${escapeHtml(f.name)} ${basis}</div>
          ${cond}
          ${dln}
          ${cons}
          ${act}
        </li>
      `;
    }).join("");

    let label = `🛡️ Radari i pavlefshmërive dhe afateve (${findings.length})`;
    if (absolute.length) {
      label = `🛑 ${absolute.length} pavlefshmëri absolute që mund ta ngremë + ${findings.length - absolute.length} të tjera`;
    } else if (applicable.length) {
      label = `🛡️ ${applicable.length}/${findings.length} leva procedurale që aplikohen`;
    }

    wrap.innerHTML = `
      <summary>${label}</summary>
      <div class="nr-intro">Këto janë levat procedurale — pavlefshmëri, afate, parashkrim — që shpesh e fitojnë kauzën pa u prekur tema. Për çdo gjetje "PO APLIKOHET" ka një veprim konkret që duhet të bësh dhe, kur ka, afatin brenda të cilit duhet ngritur.</div>
      <ul class="nr-list">${items}</ul>
    `;
    return wrap;
  }

  // ─── render citations trust badge (provenance lock) ──────────────
  // Shows a single pill at the top of the bot answer summarising how many
  // legal citations were verified against the indexed corpus. Click to
  // expand the per-citation breakdown.
  function renderCitationsBadge(payload, decPayload) {
    const stats = payload.stats || {};
    const items = payload.items || [];
    const total = stats.total || 0;
    const verified = stats.verified || 0;
    const fake = stats.fake || 0;
    const needs = stats.needs_code || 0;
    const repealed = stats.repealed || 0;
    const stale = stats.stale || 0;
    const dStats = (decPayload && decPayload.stats) || {};
    const dItems = (decPayload && decPayload.items) || [];
    const dVer = dStats.verified || 0;
    const dUnv = dStats.unverified || 0;
    const dTotal = dStats.total || 0;

    let level, label, icon;
    const artStr = verified + "/" + total + " nene";
    const decStr = dTotal ? (dVer + "/" + dTotal + " vendime") : "";
    const base = artStr + (decStr ? " + " + decStr : "");
    if (fake > 0) {
      level = "danger"; icon = "⚠";
      label = base + " · " + fake + " nene fantazmë";
    } else if (repealed > 0 || needs > 0 || dUnv > 0) {
      level = "partial"; icon = "🛡";
      label = "Verifikuar: " + base +
        (repealed ? " · " + repealed + " nene të shfuqizuara" : "") +
        (dUnv ? " · " + dUnv + " vendime s’u konfirmuan" : "") +
        (needs ? " · " + needs + " pa kod" : "");
    } else {
      level = "ok"; icon = "🛡";
      label = "Verifikuar — " + base;
    }

    if (stale > 0 && level !== "danger") { label += " · ⏳ " + stale + " për t\u2019u rifreskuar"; }
    const decHtml = dItems.length ? ('<div class="cit-dechead">Vendime të cituara</div><ul class="cit-list">' +
      dItems.map(function (dc) {
        var ok = dc.status === "verified";
        return '<li class="cit-row ' + (ok ? "cit-row-ok" : "cit-row-warn") + '"><span class="cit-status">' +
          (ok ? "✓" : "?") + '</span><code>' + escapeHtml(dc.raw) + '</code><span class="cit-meta">' +
          (ok ? "e gjetur në bazën tonë" : "s’u konfirmua në bazë — kontrollo") + "</span></li>";
      }).join("") + "</ul>") : "";
    const wrap = document.createElement("details");
    wrap.className = `citations-badge cit-${level}`;
    wrap.innerHTML = `
      <summary>
        <span class="cit-icon">${icon}</span>
        <span class="cit-label">${escapeHtml(label)}</span>
        <span class="cit-hint">klik për detaje</span>
      </summary>
      <ul class="cit-list">
        ${items.map((c) => {
          if (c.status === "verified") {
            const head = c.article_heading ? ` — ${escapeHtml(c.article_heading.slice(0, 60))}` : "";
            const fresh = (c.volatility || "").toUpperCase() === "MEDIUM" ? ` <span class="cit-fresh" title="Kjo dispozitë ndryshon herë pas here — verifiko versionin aktual (Ligj i gjallë)">⏳</span>` : "";
            return `<li class="cit-row cit-row-ok">
              <span class="cit-status">✓</span>
              <code>${escapeHtml(c.raw)}</code>
              <span class="cit-meta">${escapeHtml(c.code_label || "")}${head}${fresh}</span>
            </li>`;
          }
          if (c.status === "fake") {
            return `<li class="cit-row cit-row-fake">
              <span class="cit-status">✗</span>
              <code>${escapeHtml(c.raw)}</code>
              <span class="cit-meta">nuk u gjet ${c.code_label ? `në ${escapeHtml(c.code_label)}` : "në asnjë kod"}</span>
            </li>`;
          }
          if (c.status === "repealed") {
            const rhead = c.article_heading ? ` — ${escapeHtml(c.article_heading.slice(0, 60))}` : "";
            return `<li class="cit-row cit-row-warn">
              <span class="cit-status">⚠</span>
              <code>${escapeHtml(c.raw)}</code>
              <span class="cit-meta">ekziston te ${escapeHtml(c.code_label || "")} por është SHFUQIZUAR${rhead}</span>
            </li>`;
          }
          // needs_code
          const cands = (c.candidates || []).map(x => escapeHtml(x.label)).join(", ");
          return `<li class="cit-row cit-row-warn">
            <span class="cit-status">?</span>
            <code>${escapeHtml(c.raw)}</code>
            <span class="cit-meta">kod i pa-specifikuar — ${cands ? `mund të jetë: ${cands}` : "asnjë përputhje"}</span>
          </li>`;
        }).join("")}
      </ul>
      ${decHtml}
    `;
    return wrap;
  }

  // V8.11 Citation Shield V2 — provenance panel.
  // Shows: confidence score, KB version, model, refusal flag, export links.
  // Compact by default; expandable for the lawyer who wants the full audit.
  function renderProvenancePanel(prov) {
    const score = typeof prov.confidence === "number" ? prov.confidence : 1.0;
    const label = prov.confidence_label || "—";
    const refused = !!prov.refused;
    const pct = Math.round(score * 100);
    let level = "ok";
    if (score < 0.5) level = "danger";
    else if (score < 0.85) level = "partial";

    const wrap = document.createElement("details");
    wrap.className = `provenance-panel prov-${level}`;
    const exportUrl = `/api/provenance/${encodeURIComponent(prov.response_id)}.json`;
    const docxUrl = `/api/provenance/${encodeURIComponent(prov.response_id)}.docx`;

    const refusalLine = refused
      ? `<div class="prov-refusal">⚠ Refusal: citimet u dështuan, përgjigjja shënohet si e pasigurt.</div>`
      : "";

    wrap.innerHTML = `
      <summary>
        <span class="prov-icon">🔒</span>
        <span class="prov-label">Provenance · besimi ${pct}% (${escapeHtml(label)})</span>
        <span class="prov-hint">klik për detajet</span>
      </summary>
      ${refusalLine}
      <dl class="prov-meta">
        <dt>ID përgjigjeje</dt><dd><code>${escapeHtml(prov.response_id || "")}</code></dd>
        <dt>Model</dt><dd><code>${escapeHtml(prov.model || "")}</code></dd>
        <dt>Versioni KB</dt><dd><code>${escapeHtml(prov.kb_version || "")}</code></dd>
        <dt>Versioni prompt</dt><dd><code>${escapeHtml(prov.system_prompt_version || "")}</code></dd>
        <dt>Hash kërkese</dt><dd><code>${escapeHtml(prov.prompt_hash || "")}</code></dd>
        <dt>Hash përgjigjeje</dt><dd><code>${escapeHtml(prov.response_hash || "")}</code></dd>
        <dt>Juridiksioni</dt><dd>${escapeHtml(prov.jurisdiction || "AL")}</dd>
        <dt>Koha</dt><dd>${escapeHtml(prov.timestamp_iso || "")}</dd>
      </dl>
      <div class="prov-actions">
        <a href="${exportUrl}" download class="prov-link">📄 Eksporto JSON</a>
        <a href="${docxUrl}" target="_blank" class="prov-link">📑 DOCX për fashikull</a>
      </div>
    `;
    return wrap;
  }

  // ─── render urgency radar (top-of-message emergency framing) ────
  function renderUrgencyRadar(ur) {
    const wrap = document.createElement("div");
    const level = ur.level || "elevated";
    const signals = ur.signals || [];
    wrap.className = `urgency-radar urgency-${level}`;
    wrap.setAttribute("role", "alert");

    const kindIcon = {
      arrest: "🚨",
      eviction: "🏠",
      dismissal: "💼",
      violence: "🛡️",
      custody: "👶",
      customs: "🛃",
      deadline: "⏰",
      enforcement: "⚖️",
      other: "❗",
    };
    const sevBadge = (s) => s === "critical"
      ? `<span class="ur-sev ur-sev-critical">KRITIK</span>`
      : `<span class="ur-sev ur-sev-elevated">ALARM</span>`;

    const items = signals.map((s) => {
      const icon = kindIcon[s.kind] || "❗";
      const reason = s.reason
        ? `<div class="ur-row"><span class="ur-key">Pse:</span> ${escapeHtml(s.reason)}</div>` : "";
      const deadline = s.deadline
        ? `<div class="ur-row ur-deadline"><span class="ur-key">⏰ Afati:</span> ${escapeHtml(s.deadline)}</div>` : "";
      const action = s.action
        ? `<div class="ur-action"><strong>▶ Veprim sot:</strong> ${escapeHtml(s.action)}</div>` : "";
      return `
        <li class="ur-item ur-kind-${escapeHtml(s.kind || "other")} ur-severity-${escapeHtml(s.severity || "elevated")}">
          <div class="ur-head">
            <span class="ur-icon">${icon}</span>
            ${sevBadge(s.severity)}
            <span class="ur-label">${escapeHtml(s.label || "")}</span>
          </div>
          ${reason}
          ${deadline}
          ${action}
        </li>
      `;
    }).join("");

    const header = level === "critical"
      ? `🚨 EMERGJENCË — VEPRO TANI`
      : `⚠️ ALARM I NGRITUR — AFATE KËSHTU JAVË`;

    wrap.innerHTML = `
      <div class="ur-header"><strong>${header}</strong></div>
      <ul class="ur-list">${items}</ul>
    `;
    return wrap;
  }

  // ─── render action plan (consolidated, time-bucketed checklist) ─
  function renderActionPlan(ap) {
    const wrap = document.createElement("details");
    const items = ap.items || [];
    wrap.className = "action-plan";
    // Open by default when there's at least one "sot" item — those are
    // the actions the citizen must do today and we don't want them hidden.
    const hasToday = items.some((it) => it.bucket === "sot");
    wrap.open = hasToday;

    const bucketLabel = {
      sot: "🔥 Sot / nesër",
      "kjo_javë": "📅 Kjo javë",
      "ky_muaj": "🗓️ Ky muaj",
      "më_vonë": "🕰️ Më vonë",
    };
    const bucketOrder = ["sot", "kjo_javë", "ky_muaj", "më_vonë"];
    const sourceBadge = {
      urgency:    { icon: "🚨", label: "emergjencë" },
      nullity:    { icon: "🛡️", label: "pavlefshmëri" },
      evidence:   { icon: "📎", label: "provë" },
      difference: { icon: "🎯", label: "gap vs fitoret" },
      premortem:  { icon: "⚠️", label: "mitigim rreziku" },
      other:      { icon: "•",  label: "" },
    };

    const byBucket = {};
    for (const it of items) {
      (byBucket[it.bucket] || (byBucket[it.bucket] = [])).push(it);
    }

    const sections = bucketOrder
      .filter((b) => byBucket[b] && byBucket[b].length)
      .map((b) => {
        const group = byBucket[b];
        const lis = group.map((it) => {
          const badge = sourceBadge[it.source] || sourceBadge.other;
          const basisTag = it.legal_basis
            ? `<span class="ap-basis">${escapeHtml(it.legal_basis)}</span>` : "";
          const reason = it.reason
            ? `<div class="ap-reason">${escapeHtml(it.reason)}</div>` : "";
          const srcLabel = badge.label
            ? `<span class="ap-source">${badge.icon} ${escapeHtml(badge.label)}</span>`
            : "";
          return `
            <li class="ap-item ap-source-${escapeHtml(it.source || "other")}">
              <div class="ap-row">
                <span class="ap-prio">${it.priority ?? ""}</span>
                <div class="ap-text">
                  <div class="ap-main">${escapeHtml(it.text)} ${basisTag}</div>
                  ${reason}
                  ${srcLabel}
                </div>
              </div>
            </li>
          `;
        }).join("");
        return `
          <div class="ap-bucket ap-bucket-${b}">
            <div class="ap-bucket-label">${bucketLabel[b] || b}</div>
            <ul class="ap-list">${lis}</ul>
          </div>
        `;
      })
      .join("");

    const summary = hasToday
      ? `✅ Plani i veprimit — ${items.length} hapa (${byBucket.sot?.length || 0} sot)`
      : `✅ Plani i veprimit — ${items.length} hapa`;

    wrap.innerHTML = `
      <summary>${summary}</summary>
      <div class="ap-intro">Ky është plani i konsoliduar — të gjitha veprimet nga analizat paraprake, të grupuara sipas kohës. Filloji nga lart.</div>
      ${sections}
    `;
    return wrap;
  }

  // ─── render contradictions (cross-document inconsistencies) ────
  function renderContradictions(cr) {
    const wrap = document.createElement("details");
    const items = cr.items || [];
    const hasHigh = items.some((c) => c.severity === "high");
    wrap.className = "contradictions" + (hasHigh ? " ct-has-high" : "");
    // Open by default when we have a high-severity contradiction —
    // those are the strategic levers the citizen can't afford to miss.
    wrap.open = hasHigh;

    const kindIcon = {
      date: "📅",
      amount: "💰",
      party: "👤",
      signature: "✍️",
      narrative: "📖",
      procedure: "⚙️",
      other: "❓",
    };
    const kindLabel = {
      date: "Datë",
      amount: "Shumë",
      party: "Palë",
      signature: "Nënshkrim",
      narrative: "Narrativë",
      procedure: "Procedurë",
      other: "Tjetër",
    };
    const sevIcon = { high: "🔴", medium: "🟡", low: "🟢" };
    const sevLabel = { high: "I LARTË", medium: "MESATAR", low: "I ULËT" };

    const liHtml = items.map((c, i) => {
      const kind = c.kind || "other";
      const kIcon = kindIcon[kind] || "❓";
      const kLab = kindLabel[kind] || kind;
      const sev = c.severity || "medium";
      const cv = c.conflicting_values || {};
      const cvRows = Object.entries(cv).map(([doc, val]) => `
        <div class="ct-cv-row">
          <span class="ct-cv-doc">${escapeHtml(doc)}</span>
          <span class="ct-cv-val">«${escapeHtml(val)}»</span>
        </div>
      `).join("");
      const refs = (c.doc_refs || []).map((d) =>
        `<span class="ct-doc-ref">${escapeHtml(d)}</span>`
      ).join("");
      const impl = c.implication
        ? `<div class="ct-impl"><strong>▶ Implikim:</strong> ${escapeHtml(c.implication)}</div>`
        : "";
      return `
        <li class="ct-item ct-kind-${escapeHtml(kind)} ct-sev-${escapeHtml(sev)}">
          <div class="ct-head">
            <span class="ct-num">${i + 1}</span>
            <span class="ct-kind-tag">${kIcon} ${escapeHtml(kLab)}</span>
            <span class="ct-sev-tag ct-sev-tag-${escapeHtml(sev)}">${sevIcon[sev] || "🟡"} ${sevLabel[sev] || "MESATAR"}</span>
          </div>
          <div class="ct-desc">${escapeHtml(c.description || "")}</div>
          ${refs ? `<div class="ct-refs">${refs}</div>` : ""}
          ${cvRows ? `<div class="ct-cv">${cvRows}</div>` : ""}
          ${impl}
        </li>
      `;
    }).join("");

    const label = hasHigh
      ? `⚖️ ${items.length} kontradikta në dosje — ${items.filter(c => c.severity === "high").length} e lartë`
      : `⚖️ ${items.length} kontradikta në dosje`;

    wrap.innerHTML = `
      <summary>${label}</summary>
      <div class="ct-intro">Këto janë mospërputhjet mes dokumenteve të dosjes. Një avokat i mirë i përdor si levë — dyshim për besueshmëri, shkak për pavlefshmëri, bazë për negocim.</div>
      <ul class="ct-list">${liHtml}</ul>
    `;
    return wrap;
  }

  // ─── render pre-mortem panel (red-team "why we could lose") ─────
  function renderPremortem(pm) {
    const wrap = document.createElement("details");
    const risks = pm.risks || [];
    const hasHigh = risks.some((r) => r.severity === "high");
    wrap.className = "premortem" + (hasHigh ? " pm-has-high" : "");
    // Open by default only when there's at least one high-severity risk —
    // otherwise the citizen has less to worry about and can drill down.
    wrap.open = hasHigh;

    const sevIcon = { high: "🔴", medium: "🟡", low: "🟢" };
    const sevLabel = { high: "I LARTË", medium: "MESATAR", low: "I ULËT" };
    const items = risks.map((r, i) => `
      <li class="pm-item pm-sev-${escapeHtml(r.severity || "medium")}">
        <div class="pm-head">
          <span class="pm-num">${i + 1}</span>
          <span class="pm-sev">${sevIcon[r.severity] || "🟡"} ${sevLabel[r.severity] || "MESATAR"}</span>
        </div>
        <div class="pm-risk">${escapeHtml(r.risk)}</div>
        ${r.mitigation ? `<div class="pm-mitig"><strong>Mitigim:</strong> ${escapeHtml(r.mitigation)}</div>` : ""}
      </li>
    `).join("");

    const label = hasHigh
      ? `⚠️ Pse kauza mund të humbet (${risks.length} rreziqe — ka rreziqe të larta)`
      : `🛡️ Pse kauza mund të humbet (${risks.length} rreziqe)`;
    wrap.innerHTML = `
      <summary>${label}</summary>
      <div class="pm-intro">Avokat i mirë nuk t'i fsheh pikat ku mund të bjerë kauza. I njeh që të të mbrojë.</div>
      <ul class="pm-list">${items}</ul>
    `;
    return wrap;
  }

  // ─── render missing-facts panel (the 3 questions a lawyer asks) ──
  function renderMissingFacts(mf) {
    const wrap = document.createElement("details");
    wrap.className = "missing-facts";
    wrap.open = true;

    const items = (mf.facts || []).map((f, i) => {
      const impact = [];
      if (f.impact_if_yes) impact.push(`<div class="mf-impact"><strong>Nëse PO:</strong> ${escapeHtml(f.impact_if_yes)}</div>`);
      if (f.impact_if_no)  impact.push(`<div class="mf-impact"><strong>Nëse JO:</strong> ${escapeHtml(f.impact_if_no)}</div>`);
      return `
        <li class="mf-item">
          <button class="mf-ask" type="button" data-question="${escapeHtml(f.question)}">
            <span class="mf-num">${i + 1}</span>
            <span class="mf-q">${escapeHtml(f.question)}</span>
          </button>
          <div class="mf-why">${escapeHtml(f.why_it_matters)}</div>
          ${impact.join("")}
        </li>
      `;
    }).join("");

    wrap.innerHTML = `
      <summary>❓ Pyetje që do ta sqaronin edhe më shumë rastin (${(mf.facts || []).length})</summary>
      <ul class="mf-list">${items}</ul>
    `;

    // Click-to-ask: pre-fill the composer with a leading sentence and the
    // question, so the citizen only needs to add their answer underneath.
    wrap.querySelectorAll(".mf-ask").forEach((btn) => {
      btn.addEventListener("click", () => {
        const q = btn.dataset.question || "";
        input.value = `Përgjigja për pyetjen "${q}" është: `;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        autoGrow();
        input.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
    return wrap;
  }

  // ─── render precedent-comparison card (winners vs losers) ──────
  function comparisonEmpty(c) {
    return !c || (!c.pattern_winners && !c.pattern_losers && !(c.decisive_factors || []).length);
  }

  function renderComparison(c) {
    const wrap = document.createElement("details");
    wrap.className = `comparison cmp-${c.citizen_alignment || "unknown"}`;
    wrap.open = true;

    const alignLabel = {
      favorable:   "🧭 Rasti yt përputhet me fituesit",
      mixed:       "⚖️ Rasti është i përzier — ka rreziqe",
      unfavorable: "⚠️ Rasti yt përputhet me humbësit — strategji mbrojtëse",
      unknown:     "🧭 Krahasim precedentesh",
    };

    // V6.4: decisive_differences is the structured "your case lacks Z"
    // engine. Prefer it when populated; fall back to the legacy
    // decisive_factors bullets for historical rows.
    const statusIcon = { "ka": "✅", "mungon": "❌", "e paqartë": "❓" };
    const statusLabel = { "ka": "E KA", "mungon": "MUNGON", "e paqartë": "E PAQARTË" };
    const diffs = (c.decisive_differences || []).filter((d) => d.attribute);
    const differencesHtml = diffs.length ? diffs.map((d) => {
      const cls = `cmp-diff-${(d.citizen_status || "e paqartë").replace(/\s+/g, "-")}`;
      const icon = statusIcon[d.citizen_status] || "❓";
      const label = statusLabel[d.citizen_status] || "E PAQARTË";
      const win = d.winners_have
        ? `<div class="cmp-diff-row"><span class="cmp-diff-key">Fituesit:</span> ${escapeHtml(d.winners_have)}</div>` : "";
      const lose = d.losers_lacked
        ? `<div class="cmp-diff-row"><span class="cmp-diff-key">Humbësit:</span> ${escapeHtml(d.losers_lacked)}</div>` : "";
      const action = d.action
        ? `<div class="cmp-diff-action"><strong>▶ Veprim:</strong> ${escapeHtml(d.action)}</div>` : "";
      return `
        <li class="cmp-diff ${cls}">
          <div class="cmp-diff-head">
            <span class="cmp-diff-status">${icon} ${label}</span>
            <span class="cmp-diff-attr">${escapeHtml(d.attribute)}</span>
          </div>
          ${win}
          ${lose}
          ${action}
        </li>
      `;
    }).join("") : "";

    const factors = (c.decisive_factors || []).map((f) =>
      `<li>${escapeHtml(f)}</li>`
    ).join("");

    wrap.innerHTML = `
      <summary>${alignLabel[c.citizen_alignment] || alignLabel.unknown}</summary>
      <div class="cmp-grid">
        ${c.pattern_winners ? `
          <div class="cmp-side cmp-winners">
            <div class="cmp-side-label">✅ Çfarë kishin fituesit</div>
            <div class="cmp-side-text">${escapeHtml(c.pattern_winners)}</div>
          </div>` : ""}
        ${c.pattern_losers ? `
          <div class="cmp-side cmp-losers">
            <div class="cmp-side-label">❌ Çfarë kishin humbësit</div>
            <div class="cmp-side-text">${escapeHtml(c.pattern_losers)}</div>
          </div>` : ""}
      </div>
      ${c.alignment_reason ? `<div class="cmp-reason">${escapeHtml(c.alignment_reason)}</div>` : ""}
      ${differencesHtml ? `
        <div class="cmp-factors-label">Diferencat vendimtare — a i ke, të mungojnë, apo janë të paqarta?</div>
        <ul class="cmp-diffs">${differencesHtml}</ul>` : (factors ? `
        <div class="cmp-factors-label">Faktorët vendimtar — kontrollo një nga një</div>
        <ul class="cmp-factors">${factors}</ul>` : "")}
    `;
    return wrap;
  }

  // ─── render timeline widget (anchors + deadlines with urgency) ──
  function renderTimeline(tl) {
    const wrap = document.createElement("details");
    wrap.className = "timeline";
    wrap.open = true;   // deadlines matter — do not hide them by default

    const urgencyLabel = {
      expired: "KALUAR",
      critical: "URGJENT",
      warning: "KUJDES",
      info: "INFO",
      unknown: "?",
    };
    const urgencyIcon = {
      expired: "⛔",
      critical: "🚨",
      warning: "⚠️",
      info: "🕐",
      unknown: "—",
    };

    const anchors = tl.anchors || [];
    const deadlines = tl.deadlines || [];
    const mostUrgent = deadlines.find(d => d.urgency === "critical" || d.urgency === "expired");
    const headerTone = mostUrgent
      ? (mostUrgent.urgency === "expired" ? "⛔ AFAT I KALUAR" : "🚨 AFAT URGJENT")
      : "⏰ Kronologjia & afatet";

    const anchorItems = anchors.map((a) => `
      <li class="tl-anchor">
        <span class="tl-dot">●</span>
        <span class="tl-date">${escapeHtml(a.date || "data e panjohur")}</span>
        <span class="tl-event">${escapeHtml(a.event)}</span>
        ${a.source_quote ? `<div class="tl-src">"${escapeHtml(a.source_quote)}"</div>` : ""}
      </li>
    `).join("");

    const deadlineItems = deadlines.map((d) => {
      const u = d.urgency || "unknown";
      const days = d.days_remaining;
      let timing;
      if (d.due_date && days !== null && days !== undefined) {
        if (days < 0) timing = `${-days} ditë më parë (${d.due_date})`;
        else if (days === 0) timing = `SOT (${d.due_date})`;
        else timing = `për ${days} ditë (${d.due_date})`;
      } else if (d.days_after) {
        timing = `brenda ${d.days_after} ditësh nga "${escapeHtml(d.anchor_event || "?")}"`;
      } else {
        timing = "afat i lidhur me një ngjarje të panjohur";
      }
      return `
        <li class="tl-deadline tl-urg-${u}">
          <span class="tl-urg-badge">${urgencyIcon[u]} ${urgencyLabel[u]}</span>
          <div class="tl-action">${escapeHtml(d.action)}</div>
          <div class="tl-timing">${escapeHtml(timing)}</div>
          ${d.article_ref ? `<div class="tl-ref">${escapeHtml(d.article_ref)}</div>` : ""}
        </li>
      `;
    }).join("");

    wrap.innerHTML = `
      <summary>${headerTone} ${deadlines.length ? `(${deadlines.length})` : ""}</summary>
      ${anchors.length ? `<div class="tl-section-label">Ngjarjet që nisin afatet</div>
        <ul class="tl-anchors">${anchorItems}</ul>` : ""}
      ${deadlines.length ? `<div class="tl-section-label">Afatet që duhen respektuar</div>
        <ul class="tl-deadlines">${deadlineItems}</ul>` : ""}
    `;
    return wrap;
  }

  // ─── tiny markdown → HTML ───────────────────────────────────────
  function renderMarkdown(md) {
    const lines = md.split("\n");
    const out = [];
    let inList = null;
    for (let raw of lines) {
      let l = raw;
      const hm = l.match(/^(#{1,4})\s+(.*)$/);
      if (hm) {
        closeList();
        const level = Math.min(hm[1].length + 1, 4);
        out.push(`<h${level}>${inline(hm[2])}</h${level}>`);
        continue;
      }
      if (/^---+$/.test(l.trim())) { closeList(); out.push("<hr>"); continue; }
      const bm = l.match(/^[\-\*•]\s+(.*)$/);
      if (bm) { openList("ul"); out.push(`<li>${inline(bm[1])}</li>`); continue; }
      const nm = l.match(/^\d+\.\s+(.*)$/);
      if (nm) { openList("ol"); out.push(`<li>${inline(nm[1])}</li>`); continue; }
      if (!l.trim()) { closeList(); out.push(""); continue; }
      closeList();
      out.push(`<p>${inline(l)}</p>`);
    }
    closeList();
    return out.join("\n").replace(/(<\/p>\s*){2,}/g, "</p>");

    function openList(kind) {
      if (inList === kind) return;
      closeList();
      out.push(`<${kind}>`); inList = kind;
    }
    function closeList() {
      if (inList) { out.push(`</${inList}>`); inList = null; }
    }
    function inline(s) {
      s = escapeHtml(s);
      s = s.replace(/\*\*([^\*]+)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/\*([^\*]+)\*/g, "<em>$1</em>");
      s = s.replace(/_([^_]+)_/g, "<em>$1</em>");
      s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
      return s;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }


  // ═══ CALENDAR (V7.10) ═════════════════════════════════════════════
  const calendarBtn   = document.getElementById("calendar-btn");
  const calendarView  = document.getElementById("calendar-view");
  const calendarBody  = document.getElementById("calendar-body");
  const calLabel      = document.getElementById("calendar-label");
  const calSub        = document.getElementById("calendar-sub");
  const calPrev       = document.getElementById("cal-prev");
  const calNext       = document.getElementById("cal-next");
  const calTodayBtn   = document.getElementById("cal-today");
  const calCloseBtn   = document.getElementById("cal-close");
  const calNewBtn     = document.getElementById("cal-new-btn");
  const calIcalBtn    = document.getElementById("cal-ical-btn");
  const viewBtns      = document.querySelectorAll(".view-btn");
  const calBadge      = document.getElementById("calendar-badge");

  const evModal       = document.getElementById("event-modal");
  const evForm        = document.getElementById("event-form");
  const evModalTitle  = document.getElementById("event-modal-title");
  const evDeleteBtn   = document.getElementById("event-delete-btn");

  const icalModal     = document.getElementById("ical-modal");
  const icalInput     = document.getElementById("ical-url-input");
  const icalCopyBtn   = document.getElementById("ical-copy-btn");

  const toastStack    = document.getElementById("toast-stack");

  const miniEl        = document.getElementById("cal-mini");
  const miniLabel     = document.getElementById("mini-label");
  const miniPrev      = document.getElementById("mini-prev");
  const miniNext      = document.getElementById("mini-next");

  const statPeriod    = document.getElementById("stat-period");
  const statUpcoming  = document.getElementById("stat-upcoming");
  const statOverdue   = document.getElementById("stat-overdue");
  const upcomingEl    = document.getElementById("cal-upcoming");

  const chipTpl       = document.getElementById("event-chip-tpl");
  const dayCellTpl    = document.getElementById("day-cell-tpl");

  // V7.10 header widgets
  const calTodayIcon  = document.getElementById("cal-today-icon");
  const iconMonthEl   = document.getElementById("icon-month");
  const iconDayEl     = document.getElementById("icon-day");
  const iconDowEl     = document.getElementById("icon-dow");
  const calJumpInput  = document.getElementById("cal-jump-input");
  const viewsSlider   = document.querySelector(".views-slider");
  const icalStatusDot = document.getElementById("ical-status-dot");
  const bdEls = {
    "seance":  document.getElementById("bd-seance"),
    "afat":    document.getElementById("bd-afat"),
    "takim":   document.getElementById("bd-takim"),
    "dorëzim": document.getElementById("bd-dorezim"),
    "tjetër":  document.getElementById("bd-tjeter"),
  };

  const MONTHS_SQ = ["Janar","Shkurt","Mars","Prill","Maj","Qershor",
                     "Korrik","Gusht","Shtator","Tetor","Nëntor","Dhjetor"];
  const MONTHS_SHORT_SQ = ["Jan","Shk","Mar","Pri","Maj","Qer","Kor","Gus","Sht","Tet","Nën","Dhj"];
  const DOW_SQ = ["Hën","Mar","Mër","Enj","Pre","Sht","Die"];
  const DOW_LONG_SQ = ["E hënë","E martë","E mërkurë","E enjte","E premte","E shtunë","E diel"];
  const KIND_LABEL_SQ = {
    takim: "Takim", seance: "Seancë", afat: "Afat",
    "dorëzim": "Dorëzim", "tjetër": "Tjetër",
  };

  let calCursor = _todayMidnight();
  let miniCursor = _todayMidnight();
  let calView   = "month";
  let calEvents = [];       // events for the current range
  let allEvents = [];       // broader range for mini + upcoming
  let editingEventId = null;
  let activeFilter = "all"; // kind filter
  let caseCache = null;
  let calScope  = "me";     // "me" — personal events; "firm" — master calendar

  function _todayMidnight() { const d = new Date(); d.setHours(0,0,0,0); return d; }
  function startOfWeek(d) {
    const x = new Date(d); x.setHours(0,0,0,0);
    const dow = (x.getDay() + 6) % 7;
    x.setDate(x.getDate() - dow);
    return x;
  }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
  }
  function pad(n) { return String(n).padStart(2, "0"); }
  function isoLocal(d) {
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function fmtTime(d) { return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function fmtShortDate(d) { return `${d.getDate()} ${MONTHS_SHORT_SQ[d.getMonth()]}`; }

  function computeRange(view, cursor) {
    if (view === "month") {
      const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
      const last  = new Date(cursor.getFullYear(), cursor.getMonth()+1, 0);
      return { from: startOfWeek(first), to: addDays(startOfWeek(last), 7) };
    }
    if (view === "week") {
      const from = startOfWeek(cursor);
      return { from, to: addDays(from, 7) };
    }
    if (view === "day") {
      const from = new Date(cursor); from.setHours(0,0,0,0);
      return { from, to: addDays(from, 1) };
    }
    // agenda: next 30 days from cursor
    const from = new Date(cursor); from.setHours(0,0,0,0);
    return { from, to: addDays(from, 30) };
  }

  function _hydrate(rawList) {
    return (rawList || []).map(ev => ({
      ...ev,
      _start: new Date(ev.starts_at),
      _end: ev.ends_at ? new Date(ev.ends_at) : null,
    }));
  }

  async function loadEvents() {
    const { from, to } = computeRange(calView, calCursor);
    const url = calScope === "firm"
      ? `/api/firm/calendar?start=${from.toISOString()}&end=${to.toISOString()}`
      : `/api/events?from=${from.toISOString()}&to=${to.toISOString()}`;
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        if (calScope === "firm" && resp.status === 403) {
          // Lost permission (role changed mid-session) — drop back to personal.
          calScope = "me";
          updateScopeToggle();
          return loadEvents();
        }
        calEvents = []; return;
      }
      const data = await resp.json();
      calEvents = _hydrate(data.events);
    } catch { calEvents = []; }
  }

  async function loadBroad() {
    // Broader window for mini-cal dots + upcoming panel (~90 days ahead, 30 back)
    const now = new Date();
    const from = addDays(now, -30);
    const to = addDays(now, 90);
    try {
      const resp = await fetch(`/api/events?from=${from.toISOString()}&to=${to.toISOString()}`);
      if (!resp.ok) { allEvents = []; return; }
      const data = await resp.json();
      allEvents = _hydrate(data.events);
    } catch { allEvents = []; }
  }

  function applyFilter(list) {
    if (activeFilter === "all") return list;
    return list.filter(e => (e.kind || "tjetër") === activeFilter);
  }

  function _weekNumber(d) {
    // ISO week number (Mon-based)
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const dow = (t.getUTCDay() + 6) % 7;
    t.setUTCDate(t.getUTCDate() - dow + 3);
    const firstThu = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
    return 1 + Math.round(((t - firstThu) / 86400000 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7);
  }
  function _dayOfYear(d) {
    const start = new Date(d.getFullYear(), 0, 0);
    return Math.floor((d - start) / 86400000);
  }
  function _pad(n) { return n < 10 ? "0" + n : "" + n; }
  function _daysInYear(y) {
    return ((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0) ? 366 : 365;
  }

  function updateAppIcon() {
    if (!iconMonthEl) return;
    const now = new Date();
    iconMonthEl.textContent = MONTHS_SHORT_SQ[now.getMonth()].toUpperCase();
    iconDayEl.textContent   = String(now.getDate());
    iconDowEl.textContent   = DOW_SQ[(now.getDay()+6)%7];
  }

  function updateViewsSlider() {
    if (!viewsSlider) return;
    const order = ["month", "week", "day", "agenda"];
    const idx = Math.max(0, order.indexOf(calView));
    viewsSlider.style.setProperty("--slider-w", `calc((100% - 6px) / ${order.length})`);
    viewsSlider.style.setProperty("--slider-x", `calc((100% - 6px) / ${order.length} * ${idx})`);
  }

  function updateBreakdown(events) {
    if (!bdEls.seance) return;
    const counts = { "seance": 0, "afat": 0, "takim": 0, "dorëzim": 0, "tjetër": 0 };
    (events || []).forEach(e => {
      const k = e.kind || "tjetër";
      if (k in counts) counts[k]++;
      else counts["tjetër"]++;
    });
    Object.entries(bdEls).forEach(([kind, el]) => {
      if (!el) return;
      el.textContent = counts[kind];
      const pill = el.closest(".cal-kind-pill");
      if (pill) pill.classList.toggle("dim", counts[kind] === 0);
    });
  }

  function _buildCalSub(count) {
    const now = new Date();
    const dowNow = DOW_LONG_SQ[(now.getDay()+6)%7];
    const timeNow = `${_pad(now.getHours())}:${_pad(now.getMinutes())}`;
    const wk = _weekNumber(calCursor);
    const doy = _dayOfYear(calCursor);
    const diy = _daysInYear(calCursor.getFullYear());
    let ctx;
    if (calView === "month") {
      ctx = `Pamja mujore · Java ${wk}`;
    } else if (calView === "week") {
      ctx = `Java ${wk} / 52`;
    } else if (calView === "day") {
      ctx = `Dita ${doy} / ${diy}`;
    } else {
      ctx = `30 ditët e ardhshme`;
    }
    const label = count === 1 ? "1 ngjarje" : `${count} ngjarje`;
    return `${dowNow} · ${timeNow} · ${ctx} · ${label}`;
  }

  function renderCalendar() {
    if (!calendarBody) return;
    if (calView === "month") {
      calLabel.textContent = `${MONTHS_SQ[calCursor.getMonth()]} ${calCursor.getFullYear()}`;
    } else if (calView === "week") {
      const from = startOfWeek(calCursor);
      const to   = addDays(from, 6);
      calLabel.textContent = `${from.getDate()} ${MONTHS_SHORT_SQ[from.getMonth()]} – ${to.getDate()} ${MONTHS_SHORT_SQ[to.getMonth()]} ${to.getFullYear()}`;
    } else if (calView === "day") {
      const dow = DOW_LONG_SQ[(calCursor.getDay()+6)%7];
      calLabel.textContent = `${dow}, ${calCursor.getDate()} ${MONTHS_SQ[calCursor.getMonth()]} ${calCursor.getFullYear()}`;
    } else {
      calLabel.textContent = "Agjenda";
    }
    viewBtns.forEach(b => {
      const active = b.dataset.view === calView;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    updateViewsSlider();
    updateAppIcon();

    calendarBody.innerHTML = "";
    const filtered = applyFilter(calEvents);
    calSub.textContent = _buildCalSub(calEvents.length);
    updateBreakdown(calEvents);
    if (calJumpInput) {
      const d = calCursor;
      calJumpInput.value = `${d.getFullYear()}-${_pad(d.getMonth()+1)}-${_pad(d.getDate())}`;
    }

    if (calView === "month")       renderMonth(filtered);
    else if (calView === "week")   renderTimed("week", filtered);
    else if (calView === "day")    renderTimed("day", filtered);
    else                           renderAgenda(filtered);

    renderMini();
    renderStats();
    renderUpcoming();
  }

  // ─── month view ─────────────────────────────────────────────────
  function renderMonth(events) {
    const wrap = document.createElement("div");
    wrap.className = "cal-month";

    const dowRow = document.createElement("div");
    dowRow.className = "cal-month-dowrow";
    DOW_SQ.forEach((d, i) => {
      const cell = document.createElement("div");
      cell.className = "cal-month-dow";
      if (i >= 5) cell.classList.add("weekend");
      cell.textContent = d;
      dowRow.appendChild(cell);
    });
    wrap.appendChild(dowRow);

    const grid = document.createElement("div");
    grid.className = "cal-month-grid";
    const month = calCursor.getMonth();
    const { from, to } = computeRange("month", calCursor);
    const today = _todayMidnight();
    for (let d = new Date(from); d < to; d = addDays(d, 1)) {
      const cell = _buildDayCell(d, month, today);
      const dayEvents = events.filter(e => sameDay(e._start, d));
      const evHolder = cell.querySelector(".day-cell-events");
      dayEvents.slice(0, 3).forEach(ev => evHolder.appendChild(_buildChip(ev)));
      if (dayEvents.length > 3) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "day-more";
        more.textContent = `+${dayEvents.length - 3} më shumë`;
        const dc = new Date(d);
        more.addEventListener("click", (e) => {
          e.stopPropagation();
          calCursor = dc; calView = "day";
          loadEvents().then(renderCalendar);
        });
        evHolder.appendChild(more);
      }
      grid.appendChild(cell);
    }
    wrap.appendChild(grid);
    calendarBody.appendChild(wrap);
  }

  function _buildDayCell(date, currentMonth, today) {
    const dayCopy = new Date(date);
    let cell;
    if (dayCellTpl) {
      cell = dayCellTpl.content.firstElementChild.cloneNode(true);
    } else {
      cell = document.createElement("div");
      cell.className = "day-cell";
      cell.innerHTML = `<div class="day-cell-head"><span class="day-num"></span><button type="button" class="day-add">＋</button></div><div class="day-cell-events"></div>`;
    }
    if (date.getMonth() !== currentMonth) cell.classList.add("other-month");
    const dow = (date.getDay() + 6) % 7;
    if (dow >= 5) cell.classList.add("weekend");
    if (sameDay(date, today)) cell.classList.add("today");
    cell.querySelector(".day-num").textContent = date.getDate();
    cell.querySelector(".day-add")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const at = new Date(dayCopy); at.setHours(10, 0, 0, 0);
      openEventModal(null, at);
    });
    cell.addEventListener("click", (e) => {
      if (e.target.closest(".event-chip, .day-more, .day-add")) return;
      const at = new Date(dayCopy); at.setHours(10, 0, 0, 0);
      openEventModal(null, at);
    });
    return cell;
  }

  function _buildChip(ev) {
    let chip;
    if (chipTpl) {
      chip = chipTpl.content.firstElementChild.cloneNode(true);
    } else {
      chip = document.createElement("button");
      chip.type = "button";
      chip.className = "event-chip";
      chip.innerHTML = `<span class="event-chip-dot"></span><span class="event-chip-time"></span><span class="event-chip-title"></span>`;
    }
    chip.dataset.kind = ev.kind || "tjetër";
    if (ev.done) chip.classList.add("done");
    if (ev.source === "auto") chip.classList.add("auto");
    const timeSpan = chip.querySelector(".event-chip-time");
    const titleSpan = chip.querySelector(".event-chip-title");
    timeSpan.textContent = ev.all_day ? "" : fmtTime(ev._start);
    titleSpan.textContent = ev.title;
    chip.title = `${KIND_LABEL_SQ[ev.kind] || ""} · ${ev.title}${ev.location ? " — " + ev.location : ""}`;
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      openEventModal(ev);
    });
    return chip;
  }

  // ─── week/day timed grid ─────────────────────────────────────────
  function renderTimed(mode, events) {
    const wrap = document.createElement("div");
    wrap.className = `cal-timed ${mode}`;

    // time column
    const timeCol = document.createElement("div");
    timeCol.className = "time-col";
    const emptyHeader = document.createElement("div");
    emptyHeader.className = "col-header";
    timeCol.appendChild(emptyHeader);
    for (let h = 0; h < 24; h++) {
      const slot = document.createElement("div");
      slot.className = "time-slot";
      slot.textContent = `${pad(h)}:00`;
      timeCol.appendChild(slot);
    }
    wrap.appendChild(timeCol);

    const today = _todayMidnight();
    const days = mode === "week" ? 7 : 1;
    const base = mode === "week" ? startOfWeek(calCursor) : new Date(calCursor);

    for (let i = 0; i < days; i++) {
      const dayDate = addDays(base, i);
      const col = document.createElement("div");
      col.className = "day-col";
      const header = document.createElement("div");
      header.className = "col-header";
      if (sameDay(dayDate, today)) header.classList.add("today");
      header.innerHTML = `${DOW_SQ[(dayDate.getDay()+6)%7]}<strong>${dayDate.getDate()}</strong>`;
      col.appendChild(header);
      for (let h = 0; h < 24; h++) {
        const slot = document.createElement("div");
        slot.className = "hour-slot half";
        slot.addEventListener("click", () => {
          const at = new Date(dayDate); at.setHours(h, 0, 0, 0);
          openEventModal(null, at);
        });
        col.appendChild(slot);
      }
      // timed events
      events.filter(e => sameDay(e._start, dayDate)).forEach(ev => {
        col.appendChild(_buildTimedEvent(ev));
      });
      // "now" line for today
      if (sameDay(dayDate, today)) {
        const now = new Date();
        const nowLine = document.createElement("div");
        nowLine.className = "now-line";
        const headerH = 35;
        const slotH = 44;
        const top = headerH + (now.getHours() + now.getMinutes()/60) * slotH;
        nowLine.style.top = `${top}px`;
        nowLine.style.position = "absolute";
        nowLine.style.left = "0";
        nowLine.style.right = "0";
        nowLine.style.borderTop = "2px solid var(--red)";
        nowLine.style.zIndex = "3";
        col.style.position = "relative";
        col.appendChild(nowLine);
      }
      col.style.position = "relative";
      wrap.appendChild(col);
    }
    calendarBody.appendChild(wrap);
  }

  function _buildTimedEvent(ev) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "timed-event";
    el.dataset.kind = ev.kind || "tjetër";
    if (ev.done) el.classList.add("done");
    const headerH = 35;
    const slotH   = 44;
    const start   = ev._start.getHours() + ev._start.getMinutes()/60;
    const duration = ev._end ? Math.max(0.5, (ev._end - ev._start)/3600000) : 1;
    el.style.top    = `${headerH + start * slotH + 1}px`;
    el.style.height = `${duration * slotH - 3}px`;
    const timeStr = ev.all_day
      ? "Gjithë ditën"
      : `${fmtTime(ev._start)}${ev._end ? "–" + fmtTime(ev._end) : ""}`;
    el.innerHTML = `
      <div class="te-time">${escapeHtml(timeStr)}</div>
      <div class="te-title">${escapeHtml(ev.title)}</div>
      ${ev.location ? `<div class="te-location">📍 ${escapeHtml(ev.location)}</div>` : ""}`;
    el.title = `${KIND_LABEL_SQ[ev.kind] || ""} · ${ev.title}`;
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      openEventModal(ev);
    });
    return el;
  }

  // ─── agenda ─────────────────────────────────────────────────────
  function renderAgenda(events) {
    const wrap = document.createElement("div");
    wrap.className = "cal-agenda";
    if (!events.length) {
      wrap.innerHTML = `<div class="cal-empty"><strong>Agjenda është bosh</strong>Asnjë ngjarje në 30 ditët e ardhshme. Klikoni <em>+ Ngjarje e re</em> për të shtuar.</div>`;
      calendarBody.appendChild(wrap);
      return;
    }
    const byDay = new Map();
    events.slice().sort((a,b) => a._start - b._start).forEach(ev => {
      const key = `${ev._start.getFullYear()}-${pad(ev._start.getMonth()+1)}-${pad(ev._start.getDate())}`;
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(ev);
    });
    const today = _todayMidnight();
    byDay.forEach((evs, key) => {
      const [y,m,dd] = key.split("-").map(Number);
      const d = new Date(y, m-1, dd);
      const card = document.createElement("section");
      card.className = "agenda-day";
      if (sameDay(d, today)) card.classList.add("is-today");
      const head = document.createElement("header");
      head.className = "agenda-day-head";
      head.innerHTML = `<h4>${DOW_LONG_SQ[(d.getDay()+6)%7]}, ${d.getDate()} ${MONTHS_SQ[d.getMonth()]}</h4>
                       <span class="agenda-day-sub">${evs.length} ngjarje${evs.length===1?"":""}</span>`;
      card.appendChild(head);
      const list = document.createElement("div");
      list.className = "agenda-items";
      evs.forEach(ev => list.appendChild(_buildAgendaItem(ev)));
      card.appendChild(list);
      wrap.appendChild(card);
    });
    calendarBody.appendChild(wrap);
  }

  function _buildAgendaItem(ev) {
    const row = document.createElement("div");
    row.className = "agenda-item";
    row.dataset.kind = ev.kind || "tjetër";
    if (ev.done) row.classList.add("done");
    const time = ev.all_day ? "—" : fmtTime(ev._start);
    const metas = [];
    if (ev.location) metas.push(`<span>📍 ${escapeHtml(ev.location)}</span>`);
    if (ev.case_title) metas.push(`<span>📁 ${escapeHtml(ev.case_title)}</span>`);
    if (ev.source === "auto") metas.push(`<span>✨ Auto</span>`);
    row.innerHTML = `
      <div class="ag-time">${time}</div>
      <div class="ag-bar"></div>
      <div class="ag-body">
        <div class="ag-title">${escapeHtml(ev.title)}</div>
        ${metas.length ? `<div class="ag-meta">${metas.join("")}</div>` : ""}
      </div>
      <div class="ag-kind">${escapeHtml(KIND_LABEL_SQ[ev.kind] || ev.kind || "")}</div>`;
    row.addEventListener("click", () => openEventModal(ev));
    return row;
  }

  // ─── mini month ─────────────────────────────────────────────────
  function renderMini() {
    if (!miniEl) return;
    miniLabel.textContent = `${MONTHS_SQ[miniCursor.getMonth()]} ${miniCursor.getFullYear()}`;
    miniEl.innerHTML = "";
    DOW_SQ.forEach(d => {
      const el = document.createElement("div");
      el.className = "mini-dow";
      el.textContent = d.charAt(0);
      miniEl.appendChild(el);
    });
    const first = new Date(miniCursor.getFullYear(), miniCursor.getMonth(), 1);
    const from = startOfWeek(first);
    const today = _todayMidnight();
    const eventDays = new Set(allEvents.map(e =>
      `${e._start.getFullYear()}-${pad(e._start.getMonth()+1)}-${pad(e._start.getDate())}`));
    for (let i = 0; i < 42; i++) {
      const d = addDays(from, i);
      if (i >= 35 && d.getMonth() !== miniCursor.getMonth()) break;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cal-mini-day";
      btn.textContent = d.getDate();
      if (d.getMonth() !== miniCursor.getMonth()) btn.classList.add("other");
      if (sameDay(d, today)) btn.classList.add("today");
      if (sameDay(d, calCursor)) btn.classList.add("active");
      const key = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
      if (eventDays.has(key)) btn.classList.add("has-ev");
      const dc = new Date(d);
      btn.addEventListener("click", async () => {
        calCursor = dc;
        miniCursor = new Date(dc.getFullYear(), dc.getMonth(), 1);
        if (calView === "month" && calCursor.getMonth() !== calCursor.getMonth()) {
          // stay
        }
        await loadEvents();
        renderCalendar();
      });
      miniEl.appendChild(btn);
    }
  }

  // ─── stats + upcoming ────────────────────────────────────────────
  function renderStats() {
    if (!statPeriod) return;
    const filtered = applyFilter(calEvents);
    statPeriod.textContent = filtered.length;
    const now = new Date();
    const in48 = new Date(now.getTime() + 48*3600*1000);
    const upc = allEvents.filter(e => !e.done && e._start >= now && e._start <= in48);
    statUpcoming.textContent = upc.length;
    const overdue = allEvents.filter(e => !e.done && e._start < now && e.kind === "afat");
    statOverdue.textContent = overdue.length;
  }

  function renderUpcoming() {
    if (!upcomingEl) return;
    const now = new Date();
    const horizon = new Date(now.getTime() + 30*86400000);
    const list = allEvents
      .filter(e => !e.done && e._start >= now && e._start <= horizon)
      .sort((a,b) => a._start - b._start)
      .slice(0, 6);
    upcomingEl.innerHTML = "";
    if (!list.length) {
      upcomingEl.innerHTML = `<li class="cal-upcoming-empty">Asnjë ngjarje e planifikuar.</li>`;
      return;
    }
    list.forEach(ev => {
      const li = document.createElement("li");
      li.className = "cal-upcoming-item";
      const diffMs = ev._start - now;
      const days = Math.floor(diffMs / 86400000);
      const hours = Math.floor(diffMs / 3600000);
      let inLabel;
      if (days === 0 && hours < 1) {
        const mins = Math.max(1, Math.floor(diffMs / 60000));
        inLabel = `${mins} min`;
        li.classList.add("up-soon");
      } else if (days === 0) { inLabel = `${hours}h`; li.classList.add("up-soon"); }
      else if (days === 1) inLabel = "nesër";
      else if (days < 7)   inLabel = `+${days} ditë`;
      else                 inLabel = fmtShortDate(ev._start);
      const kindColor = {
        seance:"var(--cal-seance)", afat:"var(--cal-afat)", takim:"var(--cal-takim)",
        "dorëzim":"var(--cal-dorez)", "tjetër":"var(--cal-tjeter)",
      }[ev.kind || "tjetër"];
      li.innerHTML = `
        <div class="up-bar" style="background:${kindColor}"></div>
        <div class="up-body">
          <div class="up-title">${escapeHtml(ev.title)}</div>
          <div class="up-meta">${fmtShortDate(ev._start)}${ev.all_day?"":" · "+fmtTime(ev._start)}${ev.location?" · "+escapeHtml(ev.location):""}</div>
        </div>
        <div class="up-in">${inLabel}</div>`;
      li.addEventListener("click", () => openEventModal(ev));
      upcomingEl.appendChild(li);
    });
  }

  // ─── scope toggle (Personal / Studio) ───────────────────────────
  const calScopeToggle = document.getElementById("cal-scope-toggle");
  function updateScopeToggle() {
    if (!calScopeToggle) return;
    calScopeToggle.querySelectorAll(".scope-btn").forEach((b) => {
      const on = b.dataset.scope === calScope;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
  async function refreshScopeAvailability() {
    if (!calScopeToggle) return;
    try {
      const r = await fetch("/api/firm");
      if (!r.ok) { calScopeToggle.hidden = true; return; }
      const data = await r.json();
      const canSeeAll = !!(data.permissions && data.permissions.all_cases);
      const hasFirm = !!data.firm && !data.firm.is_personal;
      calScopeToggle.hidden = !(canSeeAll && hasFirm);
      if (calScopeToggle.hidden && calScope === "firm") calScope = "me";
    } catch { calScopeToggle.hidden = true; }
  }
  calScopeToggle?.querySelectorAll(".scope-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      const scope = b.dataset.scope;
      if (scope === calScope) return;
      calScope = scope;
      updateScopeToggle();
      await loadEvents();
      renderCalendar();
    });
  });

  // ─── open/close ─────────────────────────────────────────────────
  async function openCalendar() {
    calendarView.hidden = false;
    document.body.style.overflow = "hidden";
    miniCursor = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
    updateAppIcon();
    startLiveClock();
    refreshIcalStatus();
    await refreshScopeAvailability();
    updateScopeToggle();
    await Promise.all([loadEvents(), loadBroad()]);
    renderCalendar();
  }
  function closeCalendar() {
    calendarView.hidden = true;
    document.body.style.overflow = "";
  }

  async function _ensureCases() {
    if (caseCache) return caseCache;
    try { caseCache = await fetchCases(); } catch { caseCache = []; }
    return caseCache;
  }

  async function openEventModal(ev, prefillDate) {
    editingEventId = ev ? ev.id : null;
    evModalTitle.textContent = ev ? "Ndrysho ngjarjen" : "Ngjarje e re";
    evDeleteBtn.hidden = !ev;
    evForm.reset();
    const caseSelect = evForm.querySelector('select[name="case_id"]');
    caseSelect.innerHTML = '<option value="">— I pavarur —</option>';
    const cases = await _ensureCases();
    cases.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.title;
      caseSelect.appendChild(opt);
    });
    if (ev) {
      evForm.title.value    = ev.title || "";
      evForm.kind.value     = ev.kind || "tjetër";
      evForm.case_id.value  = ev.case_id || "";
      evForm.starts_at.value= isoLocal(new Date(ev.starts_at));
      evForm.ends_at.value  = ev.ends_at ? isoLocal(new Date(ev.ends_at)) : "";
      evForm.all_day.checked= !!ev.all_day;
      evForm.location.value = ev.location || "";
      evForm.description.value = ev.description || "";
      const offs = (ev.reminders || []).map(r => r.offset_minutes);
      evForm.querySelectorAll('input[name="rem"]').forEach(cb => {
        cb.checked = offs.includes(Number(cb.value));
      });
    } else {
      const d = prefillDate ? new Date(prefillDate) : new Date();
      if (!prefillDate) d.setHours(d.getHours()+1, 0, 0, 0);
      evForm.starts_at.value = isoLocal(d);
      const defRem = evForm.querySelector('input[name="rem"][value="1440"]');
      if (defRem) defRem.checked = true;
    }
    // Substitutes panel: only for hearings on existing firm-scoped events.
    refreshSubstitutes(ev);
    // Re-fetch when the user changes kind (e.g. flips to seance after open).
    evForm.kind?.addEventListener("change", () => refreshSubstitutes(ev), { once: true });
    evModal.hidden = false;
    setTimeout(() => evForm.title?.focus(), 50);
  }

  async function refreshSubstitutes(ev) {
    const section = document.getElementById("substitutes-section");
    const list = document.getElementById("substitutes-list");
    if (!section || !list) return;
    section.hidden = true;
    list.innerHTML = "";
    if (!ev || !ev.id || ev.kind !== "seance" || !ev.case_id) return;
    try {
      const r = await fetch(`/api/events/${ev.id}/substitutes`);
      if (!r.ok) return;
      const data = await r.json();
      if (!data.candidates.length) {
        list.innerHTML = `<p class="substitutes-empty">Asnjë avokat tjetër në studio.</p>`;
        section.hidden = false;
        return;
      }
      list.innerHTML = data.candidates.map((c) => {
        const conflict = c.has_conflict
          ? `<span class="sub-conflict" title="Ka një ngjarje tjetër në të njëjtën orë">⚠ konflikt</span>`
          : `<span class="sub-free">✓ i lirë</span>`;
        return `<div class="substitute-row">
          <div>
            <strong>${escapeHtml(c.username)}</strong>
            <span class="sub-role">${escapeHtml(c.role_label)}</span>
          </div>
          <div class="sub-meta">
            <span>📁 ${c.active_cases}</span>
            <span>⚖️ ${c.upcoming_hearings}</span>
            <span>⏰ ${c.urgent_deadlines}</span>
            ${conflict}
          </div>
        </div>`;
      }).join("");
      section.hidden = false;
    } catch {}
  }

  function closeEventModal() {
    evModal.hidden = true;
    editingEventId = null;
  }

  async function submitEvent(e) {
    e.preventDefault();
    const fd = new FormData(evForm);
    const startLocal = fd.get("starts_at");
    const endLocal   = fd.get("ends_at");
    if (!startLocal) return;
    const reminders = Array.from(evForm.querySelectorAll('input[name="rem"]:checked'))
      .map(cb => ({ offset_minutes: Number(cb.value), channel: "telegram" }));
    const payload = {
      title: fd.get("title"),
      kind: fd.get("kind") || "tjetër",
      case_id: fd.get("case_id") || null,
      starts_at: new Date(startLocal).toISOString(),
      ends_at: endLocal ? new Date(endLocal).toISOString() : null,
      all_day: !!fd.get("all_day"),
      location: fd.get("location") || "",
      description: fd.get("description") || "",
      reminders,
    };
    const url = editingEventId ? `/api/events/${editingEventId}` : "/api/events";
    const method = editingEventId ? "PATCH" : "POST";
    let saved = false;
    try {
      const resp = await fetch(url, {
        method, headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        toast(err.error || "Nuk u ruajt ngjarja", "error");
        return;
      }
      saved = true;
      closeEventModal();
      toast(editingEventId ? "Ngjarja u përditësua" : "Ngjarja u ruajt");
    } catch (err) {
      console.error("event save network error:", err);
      if (!saved) toast("Gabim rrjeti", "error");
      return;
    }
    // Refresh UI after save. If rendering throws, keep the success toast
    // and log — do NOT show "Gabim rrjeti" because the save succeeded.
    try {
      await Promise.all([loadEvents(), loadBroad()]);
      renderCalendar();
      refreshBadge();
    } catch (err) {
      console.error("calendar refresh after save failed:", err);
    }
  }

  async function deleteEvent() {
    if (!editingEventId) return;
    if (!confirm("Të fshijmë këtë ngjarje?")) return;
    try {
      const resp = await fetch(`/api/events/${editingEventId}`, { method: "DELETE" });
      if (!resp.ok) { toast("Nuk u fshi", "error"); return; }
      closeEventModal();
      toast("Ngjarja u fshi");
      await Promise.all([loadEvents(), loadBroad()]);
      renderCalendar();
      refreshBadge();
    } catch {
      toast("Gabim rrjeti", "error");
    }
  }

  // ─── iCal + Telegram modal ──────────────────────────────────────
  async function openIcalModal() {
    try {
      const [icalResp, tgResp] = await Promise.all([
        fetch("/api/calendar/ical-url"),
        fetch("/api/settings/telegram"),
      ]);
      if (!icalResp.ok) { toast("Nuk u ngarkua URL-ja", "error"); return; }
      const data = await icalResp.json();
      icalInput.value = data.url || "";
      const tgInput = document.getElementById("tg-chat-input");
      const tgStatus = document.getElementById("tg-status");
      if (tgInput && tgResp.ok) {
        const tgData = await tgResp.json();
        tgInput.value = tgData.chat_id || "";
        if (tgStatus) {
          tgStatus.textContent = tgData.linked
            ? "✅ Telegram-i është lidhur. Kujtesat do të dërgohen automatikisht."
            : "Telegram-i nuk është lidhur ende.";
        }
      }
      icalModal.hidden = false;
    } catch { toast("Gabim rrjeti", "error"); }
  }
  function closeIcalModal() { icalModal.hidden = true; }

  icalCopyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(icalInput.value);
      toast("URL-ja u kopjua");
    } catch {
      icalInput.select();
      document.execCommand("copy");
      toast("URL-ja u kopjua");
    }
  });

  document.getElementById("tg-save-btn")?.addEventListener("click", async () => {
    const tgInput = document.getElementById("tg-chat-input");
    const tgStatus = document.getElementById("tg-status");
    const raw = (tgInput?.value || "").trim();
    try {
      const resp = await fetch("/api/settings/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: raw }),
      });
      const data = await resp.json();
      if (!resp.ok) { toast(data.error || "Nuk u ruajt", "error"); return; }
      if (tgStatus) {
        tgStatus.textContent = data.linked
          ? "✅ Telegram-i është lidhur."
          : "Telegram-i u shkëput.";
      }
      toast(data.linked ? "Telegram-i u lidh" : "Telegram-i u shkëput");
      refreshIcalStatus();
    } catch { toast("Gabim rrjeti", "error"); }
  });

  // ─── toast ──────────────────────────────────────────────────────
  function toast(msg, kind = "ok") {
    if (!toastStack) return;
    const el = document.createElement("div");
    el.className = "toast";
    if (kind !== "ok") el.dataset.kind = kind;
    const icon = kind === "error" ? "!" : (kind === "info" ? "i" : "✓");
    el.innerHTML = `<span class="toast-icon">${icon}</span><span>${escapeHtml(msg)}</span>`;
    toastStack.appendChild(el);
    setTimeout(() => {
      el.classList.add("closing");
      setTimeout(() => el.remove(), 260);
    }, 3000);
  }

  // ─── badge ──────────────────────────────────────────────────────
  async function refreshBadge() {
    try {
      const now = new Date();
      const in48 = new Date(now.getTime() + 48*3600*1000);
      const resp = await fetch(`/api/events?start=${now.toISOString()}&end=${in48.toISOString()}`);
      if (!resp.ok) return;
      const data = await resp.json();
      const count = (data.events || []).filter(e => !e.done).length;
      if (calBadge) {
        if (count > 0) {
          calBadge.hidden = false;
          calBadge.textContent = count > 99 ? "99+" : String(count);
        } else {
          calBadge.hidden = true;
        }
      }
    } catch {}
    loadDeadlineBanner();
  }

  async function loadDeadlineBanner() {
    var el = document.getElementById("deadline-banner");
    if (!el) return;
    try {
      var r = await fetch("/api/agenda/upcoming?days=7");
      if (!r.ok) { el.hidden = true; return; }
      var d = await r.json();
      var od = d.overdue || [], up = d.upcoming || [];
      var today = (d.counts && d.counts.today) || 0;
      if (!od.length && !up.length) { el.hidden = true; return; }
      var parts = [];
      if (od.length) parts.push('<b class="db-overdue">' + od.length + (od.length === 1 ? t(' e skaduar') : t(' të skaduara')) + '</b>');
      if (today) parts.push('<b class="db-today">' + today + t(' sot') + '</b>');
      var soon = up.length - today;
      if (soon > 0) parts.push(soon + t(' në 7 ditë'));
      var next = od[0] || up[0];
      var nextTxt = next ? (escapeHtml(next.title || '') + (next.case_title ? ' · ' + escapeHtml(next.case_title) : '')) : '';
      el.innerHTML = '<span class="db-icon">⏰</span>' +
        '<span class="db-text"><b>' + t('Afatet:') + '</b> ' + parts.join(' · ') +
        (nextTxt ? ' — <span class="db-next">' + nextTxt + '</span>' : '') + '</span>' +
        '<button type="button" class="db-open">' + t('Hap kalendarin') + '</button>' +
        '<button type="button" class="db-close" aria-label="Mbyll">×</button>';
      el.classList.toggle("db-alert", (od.length > 0 || today > 0));
      el.hidden = false;
      var ob = el.querySelector(".db-open"); if (ob) ob.onclick = function () { el.hidden = true; if (typeof openCalendar === "function") openCalendar(); };
      var cb = el.querySelector(".db-close"); if (cb) cb.onclick = function () { el.hidden = true; };
    } catch (e) { el.hidden = true; }
  }

  var _waBtn = document.getElementById("wa-link-btn");
  if (_waBtn) _waBtn.addEventListener("click", async function () {
    var dd = document.getElementById("user-dropdown"); if (dd) dd.hidden = true;
    var cur = {};
    try { var rr = await fetch("/api/settings/whatsapp"); if (rr.ok) cur = await rr.json(); } catch (e) {}
    var ready = !!cur.backend_ready;
    var ov = document.createElement("div"); ov.className = "wa-modal-ov";
    ov.innerHTML = '<div class="wa-modal">' +
      '<button class="wa-x" type="button" aria-label="Mbyll">×</button>' +
      '<h3>📱 WhatsApp për kujtesat</h3>' +
      '<p class="wa-sub">Merr kujtesat e afateve dhe seancave direkt në WhatsApp.</p>' +
      '<label class="wa-lab">Numri yt (me prefiks shteti)</label>' +
      '<input class="wa-inp" type="tel" placeholder="p.sh. 355691234567" value="' + (cur.phone ? escapeHtml(cur.phone) : '') + '">' +
      '<div class="wa-note ' + (ready ? 'ok' : 'warn') + '">' + (ready
        ? '✓ Kanali WhatsApp është aktiv.'
        : '⚠ Numri ruhet tani; dërgimi aktivizohet kur të lidhet Meta WhatsApp (token + template i miratuar).') + '</div>' +
      '<div class="wa-row"><button class="wa-save" type="button">Ruaj</button><span class="wa-msg"></span></div>' +
      '</div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector(".wa-x").onclick = close;
    ov.querySelector(".wa-save").onclick = async function () {
      var inp = ov.querySelector(".wa-inp"), msg = ov.querySelector(".wa-msg"), btn = ov.querySelector(".wa-save");
      btn.disabled = true; msg.textContent = "";
      try {
        var r = await fetch("/api/settings/whatsapp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: inp.value }) });
        var d = await r.json(); if (!r.ok) throw new Error(d.error || "Gabim");
        msg.textContent = d.linked ? "✓ U ruajt" : "✓ U hoq";
        if (typeof toast === "function") toast(d.linked ? "WhatsApp u lidh" : "WhatsApp u hoq", "ok");
        setTimeout(close, 700);
      } catch (e) { msg.textContent = e.message; btn.disabled = false; }
    };
  });

  var _mailBtn = document.getElementById("mail-link-btn");
  if (_mailBtn) _mailBtn.addEventListener("click", async function () {
    var dd = document.getElementById("user-dropdown"); if (dd) dd.hidden = true;
    var cur = {};
    try { var rr = await fetch("/api/settings/reminder-email"); if (rr.ok) cur = await rr.json(); } catch (e) {}
    var ready = !!cur.backend_ready;
    var val = cur.email || cur.suggestion || "";
    var ov = document.createElement("div"); ov.className = "wa-modal-ov";
    ov.innerHTML = '<div class="wa-modal">' +
      '<button class="wa-x" type="button" aria-label="Mbyll">×</button>' +
      '<h3>✉️ Email për kujtesat</h3>' +
      '<p class="wa-sub">Çdo studio i merr kujtesat në adresën e vet.</p>' +
      '<label class="wa-lab">Email-i i studios tuaj</label>' +
      '<input class="wa-inp" type="email" placeholder="p.sh. studio@shembull.al" value="' + (val ? escapeHtml(val) : '') + '">' +
      '<div class="wa-note ' + (ready ? 'ok' : 'warn') + '">' + (ready
        ? '✓ Kanali email është aktiv.'
        : '⚠ Adresa ruhet tani; dërgimi aktivizohet kur të verifikohet domeni dërgues në Resend.') + '</div>' +
      '<div class="wa-row"><button class="wa-save" type="button">Ruaj</button><span class="wa-msg"></span></div>' +
      '</div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector(".wa-x").onclick = close;
    ov.querySelector(".wa-save").onclick = async function () {
      var inp = ov.querySelector(".wa-inp"), msg = ov.querySelector(".wa-msg"), btn = ov.querySelector(".wa-save");
      btn.disabled = true; msg.textContent = "";
      try {
        var r = await fetch("/api/settings/reminder-email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: inp.value }) });
        var d = await r.json(); if (!r.ok) throw new Error(d.error || "Gabim");
        msg.textContent = d.linked ? "✓ U ruajt" : "✓ U hoq";
        if (typeof toast === "function") toast(d.linked ? "Email u lidh" : "Email u hoq", "ok");
        setTimeout(close, 700);
      } catch (e) { msg.textContent = e.message; btn.disabled = false; }
    };
  });

  // ─── nav wiring ─────────────────────────────────────────────────
  calendarBtn?.addEventListener("click", openCalendar);
  calCloseBtn?.addEventListener("click", closeCalendar);
  calNewBtn?.addEventListener("click", () => openEventModal());
  calIcalBtn?.addEventListener("click", openIcalModal);
  calTodayIcon?.addEventListener("click", async () => {
    calCursor = _todayMidnight();
    miniCursor = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
    await loadEvents();
    renderCalendar();
  });
  calJumpInput?.addEventListener("change", async () => {
    if (!calJumpInput.value) return;
    const [y, m, d] = calJumpInput.value.split("-").map(Number);
    if (!y || !m || !d) return;
    calCursor = new Date(y, m-1, d);
    miniCursor = new Date(y, m-1, 1);
    if (calView === "agenda") calView = "day";
    await loadEvents();
    renderCalendar();
  });

  // live clock — refresh subtitle every minute so "HH:MM · N ngjarje" stays current
  let liveClockTimer = null;
  function startLiveClock() {
    if (liveClockTimer) return;
    liveClockTimer = setInterval(() => {
      if (!calendarView || calendarView.hidden) return;
      updateAppIcon();
      calSub.textContent = _buildCalSub(calEvents.length);
    }, 60000);
  }

  async function refreshIcalStatus() {
    if (!icalStatusDot) return;
    try {
      const [tg, ical] = await Promise.all([
        fetch("/api/settings/telegram").then(r => r.ok ? r.json() : null).catch(() => null),
        fetch("/api/calendar/ical-url").then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      const tgLinked = !!(tg && tg.linked);
      const icalReady = !!(ical && ical.url);
      icalStatusDot.classList.remove("linked", "partial");
      if (tgLinked && icalReady) {
        icalStatusDot.classList.add("linked");
        icalStatusDot.title = "Telegram + iCal të lidhura";
      } else if (tgLinked || icalReady) {
        icalStatusDot.classList.add("partial");
        icalStatusDot.title = tgLinked ? "Telegram i lidhur · iCal jo" : "iCal i lidhur · Telegram jo";
      } else {
        icalStatusDot.title = "Jo i lidhur";
      }
    } catch {}
  }

  async function navigate(dir) {
    if (calView === "month") {
      calCursor = new Date(calCursor.getFullYear(), calCursor.getMonth()+dir, 1);
    } else if (calView === "week") {
      calCursor = addDays(calCursor, 7*dir);
    } else if (calView === "day") {
      calCursor = addDays(calCursor, dir);
    } else {
      calCursor = addDays(calCursor, 30*dir);
    }
    miniCursor = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
    await loadEvents();
    renderCalendar();
  }
  calPrev?.addEventListener("click", () => navigate(-1));
  calNext?.addEventListener("click", () => navigate(1));
  calTodayBtn?.addEventListener("click", async () => {
    calCursor = _todayMidnight();
    miniCursor = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
    await loadEvents();
    renderCalendar();
  });
  miniPrev?.addEventListener("click", () => {
    miniCursor = new Date(miniCursor.getFullYear(), miniCursor.getMonth()-1, 1);
    renderMini();
  });
  miniNext?.addEventListener("click", () => {
    miniCursor = new Date(miniCursor.getFullYear(), miniCursor.getMonth()+1, 1);
    renderMini();
  });
  viewBtns.forEach(btn => btn.addEventListener("click", async () => {
    calView = btn.dataset.view;
    await loadEvents();
    renderCalendar();
  }));

  // ─── filters ────────────────────────────────────────────────────
  document.querySelectorAll(".cal-filter-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cal-filter-pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeFilter = btn.dataset.filter;
      renderCalendar();
    });
  });
  document.getElementById("filter-reset")?.addEventListener("click", () => {
    document.querySelectorAll(".cal-filter-pill").forEach(b =>
      b.classList.toggle("active", b.dataset.filter === "all"));
    activeFilter = "all";
    renderCalendar();
  });

  // ─── modal wiring ───────────────────────────────────────────────
  evForm?.addEventListener("submit", submitEvent);
  evDeleteBtn?.addEventListener("click", deleteEvent);
  evModal?.querySelectorAll("[data-close]").forEach(el =>
    el.addEventListener("click", closeEventModal));
  icalModal?.querySelectorAll("[data-close]").forEach(el =>
    el.addEventListener("click", closeIcalModal));

  // ─── keyboard shortcuts ─────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!icalModal.hidden) { closeIcalModal(); return; }
      if (!evModal.hidden)   { closeEventModal(); return; }
      if (!calendarView.hidden) { closeCalendar(); return; }
    }
    if (calendarView.hidden) return;
    if (!evModal.hidden || !icalModal.hidden) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (e.key === "ArrowLeft" || e.key === "h") { navigate(-1); }
    else if (e.key === "ArrowRight" || e.key === "l") { navigate(1); }
    else if (e.key === "t" || e.key === "T") {
      calCursor = _todayMidnight();
      miniCursor = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
      loadEvents().then(renderCalendar);
    }
    else if (e.key === "n" || e.key === "N") { openEventModal(); }
    else if (e.key === "m" || e.key === "M") { calView = "month"; loadEvents().then(renderCalendar); }
    else if (e.key === "w" || e.key === "W") { calView = "week"; loadEvents().then(renderCalendar); }
    else if (e.key === "d" || e.key === "D") { calView = "day"; loadEvents().then(renderCalendar); }
    else if (e.key === "a" || e.key === "A") { calView = "agenda"; loadEvents().then(renderCalendar); }
  });

  // Badge polling — pick up auto-created events from dossier analysis
  refreshBadge();
  setInterval(refreshBadge, 5 * 60 * 1000);

  // ══════════════════════════════════════════════════════════════════
  //  V7.11 — PRO TOOLS (stress-test, audit, draft, cascade)
  // ══════════════════════════════════════════════════════════════════

  const proMenuBtn = document.getElementById("pro-menu-btn");
  const proMenu = document.getElementById("pro-menu");
  function _gateProMenu() {
    if (!proMenu) return;
    var isAdmin = (document.body.dataset.admin === "1");
    var owned = isAdmin ? ["avokat", "prokuror", "noter"]
      : (document.body.dataset.modules || document.body.dataset.profession || "avokat")
          .split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    if (!owned.length) owned = ["avokat"];
    var GATE = {
      stress: ["avokat", "prokuror"], bench: ["avokat", "prokuror"], genio: ["avokat", "prokuror"], precedent: ["avokat", "prokuror"],
      draft: ["avokat", "prokuror"], contract: ["avokat", "prokuror"], corporate: ["avokat", "prokuror"],
      settlement: ["avokat", "prokuror"], coach: ["avokat", "prokuror"], expertise: ["avokat", "prokuror"],
      intake: ["avokat", "prokuror"], regjistri: ["avokat", "prokuror"], hublive: ["avokat", "prokuror"],
      devilconsult: ["avokat", "prokuror"], adversary: ["avokat", "prokuror"], prescription: ["avokat", "prokuror"],
      hubpros: ["prokuror"], hubnoter: ["noter"]
    };
    Array.prototype.forEach.call(proMenu.querySelectorAll(".pro-menu-item[data-pro]"), function (el) {
      var need = GATE[el.getAttribute("data-pro")];
      el.style.display = (need && !need.some(function (m) { return owned.indexOf(m) >= 0; })) ? "none" : "";
    });
    var kids = Array.prototype.slice.call(proMenu.children);
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].classList && kids[i].classList.contains("pro-menu-divider")) {
        var vis = false;
        for (var j = i + 1; j < kids.length; j++) {
          var k = kids[j];
          if (k.classList && k.classList.contains("pro-menu-divider")) break;
          if (k.classList && k.classList.contains("pro-menu-item") && k.style.display !== "none") { vis = true; break; }
        }
        kids[i].style.display = vis ? "" : "none";
      }
    }
  }
  _gateProMenu();
  const stressModal = document.getElementById("stress-modal");
  const auditModal = document.getElementById("audit-modal");
  const draftModal = document.getElementById("draft-modal");
  const PRO_MODALS = {
    stress: stressModal,
    draft: draftModal,
    "intake": document.getElementById("intake-modal"),
    "clients": document.getElementById("clients-modal"),
    "jargon": document.getElementById("jargon-modal"),
    "contract": document.getElementById("contract-modal"),
    "money": document.getElementById("money-modal"),
    "genio": document.getElementById("genio-modal"),
    "precedent": document.getElementById("precedent-modal"),
    "settlement": document.getElementById("settlement-modal"),
    "financial": document.getElementById("financial-modal"),
    "corporate": document.getElementById("corporate-modal"),
    "bench": document.getElementById("bench-modal"),
    "coach": document.getElementById("coach-modal"),
  };

  function _renderActReport(d) {
    if (d.empty) return "";
    if (d.clean) return '<div class="ac-badge ac-ok">\u2705 Të gjitha ' + d.verified + ' nenet e cituara janë të vlefshme dhe në fuqi.</div>';
    var h = '<div class="ac-summary">Gjithsej ' + d.total + ' citime \u00b7 <b style="color:#1c7a3e">' + d.verified + ' të vlefshme</b>' +
      (d.fake.length ? ' \u00b7 <b style="color:#c0392b">' + d.fake.length + ' inekzistente</b>' : "") +
      (d.repealed.length ? ' \u00b7 <b style="color:#a1341a">' + d.repealed.length + ' të shfuqizuara</b>' : "") +
      (d.needs_code.length ? ' \u00b7 <b style="color:#8a6a1d">' + d.needs_code.length + ' të paqarta</b>' : "") + "</div>";
    function block(title, arr, cls) {
      if (!arr.length) return "";
      return '<div class="ac-block ' + cls + '"><div class="ac-bt">' + title + '</div><ul>' +
        arr.map(function (i) {
          return "<li>" + escapeHtml(i.raw || ("neni " + i.number)) +
            (i.code_label ? ' <span class="ac-code">' + escapeHtml(i.code_label) + "</span>" : "") + "</li>";
        }).join("") + "</ul></div>";
    }
    h += block("\ud83d\udd34 Nene INEKZISTENTE \u2014 hiqi ose korrigjoji", d.fake, "ac-bad");
    h += block("\ud83d\udfe0 Nene TË SHFUQIZUARA \u2014 jo më në fuqi", d.repealed, "ac-warn");
    h += block("\ud83d\udfe1 Nene TË PAQARTA \u2014 specifiko kodin", d.needs_code, "ac-unk");
    return h;
  }
  async function _extractFileText(file, statusEl) {
    var fd = new FormData();
    fd.append("file", file);
    if (statusEl) statusEl.textContent = "Po lexoj dokumentin\u2026";
    var r = await fetch("/api/extract-text", { method: "POST", body: fd });
    var d = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
    return d;
  }

  function _openFableTool(cfg) {
    var ov = document.getElementById(cfg.id);
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = cfg.id; ov.className = "ac-overlay";
    var attachHtml = cfg.attach
      ? '<div class="ac-attach-row"><label class="ac-attach">\ud83d\udcce Bashkëngjit PDF/foto<input type="file" class="ft-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label><span class="ac-attach-hint">ose ngjit tekstin poshtë</span></div>'
      : "";
    ov.innerHTML =
      '<div class="ac-modal">' +
        '<div class="ac-head"><span>' + cfg.title + '</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
        '<div class="ac-sub">' + cfg.sub + '</div>' +
        attachHtml +
        '<textarea class="ac-ta" placeholder="' + cfg.placeholder + '"></textarea>' +
        '<div class="ac-row"><button class="ac-run" type="button">' + cfg.btn + '</button><span class="ac-status"></span></div>' +
        '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        ftFile = ov.querySelector(".ft-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (ftFile) ftFile.onchange = async function () {
      var file = ftFile.files && ftFile.files[0]; if (!file) return;
      run.disabled = true;
      try {
        var dd = await _extractFileText(file, status);
        var tx = (dd.text || "").trim();
        if (!tx) { status.textContent = "Dokumenti nuk ka tekst të lexueshëm."; }
        else { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
               status.textContent = dd.used_vision_ocr ? "\u2713 Lexuar me OCR" : "\u2713 Dokumenti u lexua"; }
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; ftFile.value = ""; }
    };
    run.onclick = async function () {
      var val = (ta.value || "").trim();
      if (val.length < 15) { status.textContent = "Shkruaj pak më shumë."; return; }
      run.disabled = true; status.textContent = cfg.loading; result.innerHTML = "";
      try {
        var payload = {}; payload[cfg.payloadKey] = val;
        var r = await fetch(cfg.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(result, cfg.source || "research", cfg.saveTitle || "Kërkim", d.markdown || "");
        if (cfg.calendar) _addToCalendar(result, cfg.calendarTitle || cfg.saveTitle || "Afat", d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function openDevilConsult() {
    _openFableTool({ id: "consult-ov", title: "\ud83d\ude08 Pyet Avokatin e Djallit",
      sub: "Përshkruaj situatën ose pyetjen. Avokati i Djallit të jep këndin fitues, kurthin dhe lëvizjen e zgjuar.",
      placeholder: "P.sh. Klienti nënshkroi një kontratë me penalitet 5% në ditë vonesë. Si ta sulmoj?",
      btn: "Pyet \u2192", loading: "Avokati i Djallit po mendon\u2026", endpoint: "/api/devil-consult", payloadKey: "situation", attach: true, source: "devil", saveTitle: "Avokati i Djallit" });
  }

  function openAdversary() {
    _openFableTool({ id: "adv-ov", title: "\u2694\ufe0f Kundërshtari",
      sub: "Ngjit një kontratë ose akt. Avokati i palës kundërshtare do të gjejë çdo dobësi dhe si do ta godasë.",
      placeholder: "Ngjit tekstin e plotë të kontratës ose aktit që do të stress-testohet\u2026",
      btn: "Sulmo \u2192", loading: "Kundërshtari po sulmon\u2026", endpoint: "/api/adversary", payloadKey: "text", attach: true, source: "adversary", saveTitle: "Kundërshtari" });
  }

  function openFableDraft() {
    var ov = document.getElementById("fabledraft-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "fabledraft-ov"; ov.className = "ac-overlay";
    ov.innerHTML =
      '<div class="ac-modal">' +
        '<div class="ac-head"><span>\u270d\ufe0f Redakto me Tetramorph</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
        '<div class="ac-sub">Zgjidh llojin dhe p\u00ebrshkruaj \u00e7far\u00eb t\u00eb duhet. Tetramorph harton dokumentin; \u00e7do nen i cituar kalon nga Verifikuar.</div>' +
        '<select class="fd-kind">' +
          '<option value="contract">\ud83d\udcc4 Kontrat\u00eb</option>' +
          '<option value="act">\u2696\ufe0f Akt procedural (padi/ankim)</option>' +
          '<option value="aktakuze">\ud83c\udfdb\ufe0f Aktakuzë (prokuror)</option>' +
          '<option value="clause">\ud83d\udcce Klauzol\u00eb</option>' +
          '<option value="letter">\u2709\ufe0f Let\u00ebr zyrtare</option>' +
        '</select>' +
        '<div class="ac-attach-row"><label class="ac-attach">\ud83d\udcce Bashk\u00ebngjit PDF/foto<input type="file" class="fd-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label><span class="ac-attach-hint">ose p\u00ebrshkruaj posht\u00eb</span></div>' +
        '<textarea class="ac-ta" placeholder="P.sh. Kontrat\u00eb qiraje p\u00ebr ambient biznesi. Qiradh\u00ebn\u00ebs [emri], qiramarr\u00ebs [emri]. Qira 1200 EUR/muaj, afat 5 vjet, ndalohet n\u00ebnqiraja, penalitet 0.1%/dit\u00eb von\u00ebs, garanci 3 muaj\u2026"></textarea>' +
        '<label class="ac-clauses"><input type="checkbox" class="fd-useclauses"> \ud83d\udcda P\u00ebrdor klauzolat e studios</label>' +
        '<div class="ac-row"><button class="ac-run" type="button">Harto \u2192</button><span class="ac-status"></span></div>' +
        '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var kind = ov.querySelector(".fd-kind"), ta = ov.querySelector(".ac-ta"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result");
    var fdFile = ov.querySelector(".fd-file");
    if (fdFile) fdFile.onchange = async function () {
      var file = fdFile.files && fdFile.files[0];
      if (!file) return;
      run.disabled = true;
      try {
        var dd = await _extractFileText(file, status);
        var tx = (dd.text || "").trim();
        if (!tx) { status.textContent = "Dokumenti nuk ka tekst t\u00eb lexuesh\u00ebm."; }
        else {
          ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
          status.textContent = dd.used_vision_ocr ? "\u2713 Lexuar me OCR" : "\u2713 Dokumenti u lexua";
        }
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; fdFile.value = ""; }
    };
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    run.onclick = async function () {
      var brief = (ta.value || "").trim();
      if (brief.length < 15) { status.textContent = "P\u00ebrshkruaj pak m\u00eb shum\u00eb."; return; }
      run.disabled = true; status.textContent = "Tetramorph po harton\u2026"; result.innerHTML = "";
      try {
        var r = await fetch("/api/fable-draft", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: kind.value, brief: brief, use_clauses: !!(ov.querySelector(".fd-useclauses") && ov.querySelector(".fd-useclauses").checked) }),
        });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) {
          result.insertBefore(renderCitationsBadge(d.citations, null), out);
        }
        var copy = document.createElement("button");
        copy.className = "fd-copy"; copy.type = "button"; copy.textContent = "\ud83d\udccb Kopjo tekstin";
        copy.onclick = function () {
          navigator.clipboard.writeText(d.markdown || "").then(function () {
            copy.textContent = "\u2713 U kopjua";
          }).catch(function () {});
        };
        result.appendChild(copy);
        _addSaveToCase(result, "draft", "Draft: " + (kind ? kind.value : ""), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  async function openExpertise(preselect) {
    var ov = document.getElementById("exp-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "exp-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>\ud83c\udfaf Modele Ekspertize</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
      '<div class="exp-body"><em>Po ngarkoj\u2026</em></div>' +
      "</div>";
    document.body.appendChild(ov);
    var body = ov.querySelector(".exp-body");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var tpls = [];
    try { var r = await fetch("/api/expertise/templates"); if (r.ok) tpls = (await r.json()).templates || []; } catch (e) {}
    function grid() {
      body.innerHTML = '<div class="exp-sub">Zgjidh llojin e \u00e7\u00ebshtjes. Modeli t\u00eb jep baz.n ligjore, elementet q\u00eb duhen provuar, provat, afatet, mbrojtjet \u2014 dhe p\u00ebr \u00e7\u00ebshtjet penale, t\u00eb DYja mendjet (prokuror + avokat).</div><div class="exp-grid"></div>';
      var g = body.querySelector(".exp-grid");
      tpls.forEach(function (t) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "exp-card";
        b.innerHTML = '<span class="exp-ico">' + t.emoji + '</span><span class="exp-label">' + escapeHtml(t.label) +
          '</span><span class="exp-dom exp-dom-' + t.domain + '">' + (t.domain === "penal" ? "penale" : "civile") + '</span>';
        b.onclick = function () { detail(t); };
        g.appendChild(b);
      });
    }
    function _pl(title, arr) {
      return (arr && arr.length) ? '<div class="exp-pl"><b>' + title + '</b><ul>' +
        arr.map(function (x) { return '<li>' + escapeHtml(x) + '</li>'; }).join("") + '</ul></div>' : "";
    }
    function detail(t) {
      body.innerHTML =
        '<button class="exp-back" type="button">\u2190 Mbrapa</button>' +
        '<div class="exp-title">' + t.emoji + ' ' + escapeHtml(t.label) + '</div>' +
        _pl("Elementet q\u00eb duhen provuar", t.elements) +
        _pl("Provat tipike", t.evidence) +
        _pl("Mbrojtjet / pikat e dob\u00ebta", t.defenses) +
        _pl("Afatet", t.deadlines) +
        _pl("Pyetje udh\u00ebzuese", t.questions) +
        '<div class="exp-attachrow"><label class="ac-attach">\ud83d\udcce Bashk\u00ebngjit PDF/foto<input type="file" class="exp-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label></div>' +
        '<textarea class="ac-ta exp-ta" placeholder="P\u00ebrshkruaj faktet e \u00e7\u00ebshtjes (ose bashk\u00ebngjit dokumentet)\u2026"></textarea>' +
        '<div class="ac-row"><button class="ac-run exp-run" type="button">Gjenero ekspertiz\u00ebn \u2192</button><span class="ac-status exp-status"></span></div>' +
        '<div class="ac-result exp-result"></div>';
      body.querySelector(".exp-back").onclick = grid;
      var ta = body.querySelector(".exp-ta"), run = body.querySelector(".exp-run"),
          status = body.querySelector(".exp-status"), result = body.querySelector(".exp-result"),
          file = body.querySelector(".exp-file");
      if (file) file.onchange = async function () {
        var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
        try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
          if (tx) { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
            status.textContent = dd.used_vision_ocr ? "\u2713 Lexuar me OCR" : "\u2713 Dokumenti u lexua"; } }
        catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
      };
      run.onclick = async function () {
        var facts = (ta.value || "").trim();
        if (facts.length < 15) { status.textContent = "P\u00ebrshkruaj faktet."; return; }
        run.disabled = true; status.textContent = "Po nd\u00ebrtoj ekspertiz\u00ebn me dy mendjet\u2026 (~3-4 min)"; result.innerHTML = "";
        try {
          var r = await fetch("/api/expertise/analyze", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ case_type: t.key, facts: facts }) });
          var d = await r.json();
          if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
          status.textContent = "";
          result.innerHTML = '<div class="fd-out"></div>';
          var out = result.querySelector(".fd-out");
          out.innerHTML = renderMarkdown(d.markdown || "");
          if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
          if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
          _addSaveToCase(result, "expertise", "Ekspertiz\u00eb: " + t.label, d.markdown || "");
          _addToCalendar(result, "Afat", d.markdown || "");
        } catch (e) { status.textContent = "Gabim: " + e.message; }
        finally { run.disabled = false; }
      };
      setTimeout(function () { ta.focus(); }, 50);
    }
    if (preselect) {
      var pre = tpls.filter(function (x) { return x.key === preselect; })[0];
      if (pre) { detail(pre); } else { grid(); }
    } else { grid(); }
  }

  async function openClientsDir() {
    var ov = document.getElementById("cdir-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "cdir-ov"; ov.className = "ac-overlay";
    ov.innerHTML =
      '<div class="ac-modal cdir-modal">' +
        '<div class="ac-head"><span>\ud83d\udc65 Klientët & Kërkimet</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
        '<input type="text" class="cdir-search" placeholder="\ud83d\udd0d Kërko klient, rast ose kërkim\u2026" />' +
        '<button type="button" class="cdir-addbtn">\u2795 Shto klient</button>' +
        '<div class="cdir-addform" hidden>' +
          '<input class="cdir-f-name" placeholder="Emri i klientit *" />' +
          '<input class="cdir-f-phone" placeholder="Telefoni" />' +
          '<input class="cdir-f-email" placeholder="Email" />' +
          '<div class="cdir-addrow"><button type="button" class="cdir-f-save">Ruaj klientin (krijon rast të ri)</button><span class="cdir-f-status"></span></div>' +
        '</div>' +
        '<div class="cdir-body"><em>Po ngarkoj\u2026</em></div>' +
      "</div>";
    document.body.appendChild(ov);
    var body = ov.querySelector(".cdir-body"), search = ov.querySelector(".cdir-search");
    var addBtn = ov.querySelector(".cdir-addbtn"), addForm = ov.querySelector(".cdir-addform");
    if (addBtn) addBtn.onclick = function () { addForm.hidden = !addForm.hidden; };
    var saveBtn = ov.querySelector(".cdir-f-save");
    if (saveBtn) saveBtn.onclick = async function () {
      var nm = (ov.querySelector(".cdir-f-name").value || "").trim();
      var ph = (ov.querySelector(".cdir-f-phone").value || "").trim();
      var em = (ov.querySelector(".cdir-f-email").value || "").trim();
      var st = ov.querySelector(".cdir-f-status");
      if (nm.length < 2) { st.textContent = "Shkruaj emrin."; return; }
      saveBtn.disabled = true; st.textContent = "Duke ruajtur\u2026";
      try {
        var cr = await fetch("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: nm }) });
        var c = await cr.json();
        if (!cr.ok) throw new Error(c.error || "rast");
        var clr = await fetch("/api/cases/" + c.id + "/clients", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: nm, phone: ph, email: em }) });
        if (!clr.ok) { var e = await clr.json().catch(function () { return {}; }); throw new Error(e.error || "klient"); }
        st.textContent = "\u2713 Klienti u shtua (u krijua rast i ri)";
        ov.querySelector(".cdir-f-name").value = ""; ov.querySelector(".cdir-f-phone").value = ""; ov.querySelector(".cdir-f-email").value = "";
        if (typeof renderCaseList === "function") renderCaseList();
        try { var rr = await fetch("/api/firm/clients"); if (rr.ok) data = await rr.json(); } catch (e2) {}
        render(search.value);
      } catch (e) { st.textContent = "Gabim: " + e.message; }
      finally { saveBtn.disabled = false; }
    };
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var data = { clients: [], research: [] };
    try {
      var r = await fetch("/api/firm/clients");
      if (r.ok) data = await r.json();
    } catch (e) {}
    function render(q) {
      q = (q || "").trim().toLowerCase();
      var clients = data.clients || [], research = data.research || [];
      var fc = clients.filter(function (c) {
        return !q || ((c.name || "") + " " + (c.phone || "") + " " + (c.email || "")).toLowerCase().indexOf(q) >= 0;
      });
      var fr = research.filter(function (it) {
        return !q || ((it.title || "") + " " + (it.client_name || "") + " " + (it.case_title || "") + " " + (it.content || "")).toLowerCase().indexOf(q) >= 0;
      });
      var h = '<div class="cdir-sec">\ud83d\udc64 Klientët (' + clients.length + ')</div>';
      if (!fc.length) h += '<div class="cdir-empty">Ende asnjë klient. Shtoje një klient te një rast (menu PRO \u2192 Klientët & Portal).</div>';
      fc.forEach(function (c) {
        h += '<div class="cdir-client"><div class="cdir-cname">' + escapeHtml(c.name || "") +
          (c.phone ? ' · <span class="cdir-meta">' + escapeHtml(c.phone) + '</span>' : "") + '</div><div class="cdir-cases">';
        (c.cases || []).forEach(function (cs) {
          h += '<button class="cdir-case" type="button" data-case="' + cs.case_id + '">\ud83d\udcc1 ' + escapeHtml(cs.case_title || "Rast") + '</button>';
        });
        h += "</div></div>";
      });
      h += '<div class="cdir-sec">\ud83d\uddc2\ufe0f Kërkimet e ruajtura (' + research.length + ')</div>';
      if (!fr.length) h += '<div class="cdir-empty">Asnjë kërkim i ruajtur. Ruaj një përgjigje ose vegël PRO me \u201c\ud83d\udcbe Ruaj në fashikull\u201d.</div>';
      fr.forEach(function (it) {
        h += '<div class="cdir-res" data-id="' + it.id + '"><div class="cdir-rhead">' +
          '<span class="research-src">' + escapeHtml(_srcLabel(it.source)) + '</span>' +
          (it.client_name ? '<span class="research-cli">\ud83d\udc64 ' + escapeHtml(it.client_name) + '</span>' : "") +
          '<button class="cdir-case cdir-caselink" type="button" data-case="' + it.case_id + '">\ud83d\udcc1 ' + escapeHtml(it.case_title || "Rast") + '</button>' +
          '<span class="cdir-rttl">' + escapeHtml(it.title || "") + '</span></div>' +
          '<div class="cdir-rbody" hidden></div></div>';
      });
      body.innerHTML = h;
      Array.prototype.forEach.call(body.querySelectorAll(".cdir-case"), function (b) {
        b.addEventListener("click", function (e) {
          e.stopPropagation();
          var cid = b.getAttribute("data-case");
          close();
          if (typeof selectCase === "function") selectCase(cid);
        });
      });
      Array.prototype.forEach.call(body.querySelectorAll(".cdir-res"), function (el) {
        var it = fr.filter(function (x) { return String(x.id) === el.getAttribute("data-id"); })[0];
        el.querySelector(".cdir-rhead").addEventListener("click", function (e) {
          if (e.target.closest(".cdir-case")) return;
          var bd = el.querySelector(".cdir-rbody");
          if (bd.hidden) { bd.innerHTML = renderMarkdown((it && it.content) || ""); bd.hidden = false; }
          else bd.hidden = true;
        });
      });
    }
    search.addEventListener("input", function () { render(search.value); });
    render("");
  }

  function openProsecutor() {
    _openFableTool({ id: "pros-ov", title: "\ud83c\udfdb\ufe0f Analiza e prokurorit",
      sub: "Përshkruaj faktet ose fashikullin. Merr kualifikimin ligjor, mjaftueshmërinë e provave, hapat hetimorë dhe review-n e objektivitetit (ana e mbrojtjes).",
      placeholder: "Përshkruaj faktet e çështjes penale (ose bashkëngjit fashikullin)\u2026",
      btn: "Analizo \u2192", loading: "Po ndërtoj analizën e prokurorit\u2026 (~3-4 min)",
      endpoint: "/api/prosecutor/analyze", payloadKey: "facts", attach: true,
      source: "prosecutor", saveTitle: "Analiza e prokurorit", calendar: true, calendarTitle: "Afat procedural" });
  }

  async function openNotaryDeed() {
    var ov = document.getElementById("nd-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "nd-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>\ud83d\udcdc Redakto akt notarial</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
      '<div class="ac-sub">Zgjidh llojin e aktit dhe jep të dhënat. Merr një draft të plotë me klauzolat e detyrueshme (çdo nen kalon nga Verifikuar). Noteri e verifikon dhe e nënshkruan.</div>' +
      '<select class="fd-kind nd-kind"></select>' +
      '<div class="nd-must"></div>' +
      '<div class="ac-attach-row"><label class="ac-attach">\ud83d\udcce Bashkëngjit PDF/foto<input type="file" class="nd-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label></div>' +
      '<textarea class="ac-ta" placeholder="Jep të dhënat: palët, objekti, çmimi, nr. pasurie, data… (ato që s\u2019i ke, do vihen [___])"></textarea>' +
      '<label class="ac-clauses"><input type="checkbox" class="nd-useclauses"> 📚 Përdor klauzolat e studios</label>' +
      '<div class="ac-row"><button class="ac-run" type="button">Harto aktin \u2192</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var kind = ov.querySelector(".nd-kind"), must = ov.querySelector(".nd-must"),
        ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        file = ov.querySelector(".nd-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var types = [];
    try { var r = await fetch("/api/notary/deed-types"); if (r.ok) types = (await r.json()).types || []; } catch (e) {}
    kind.innerHTML = types.map(function (t) { return '<option value="' + t.key + '">' + t.emoji + ' ' + escapeHtml(t.label) + '</option>'; }).join("");
    function showMust() {
      var t = types.filter(function (x) { return x.key === kind.value; })[0];
      must.innerHTML = t ? '<div class="nd-must-box"><b>Klauzolat e detyrueshme:</b><ul>' +
        (t.must || []).map(function (m) { return '<li>' + escapeHtml(m) + '</li>'; }).join("") + '</ul></div>' : "";
    }
    kind.onchange = showMust; showMust();
    if (file) file.onchange = async function () {
      var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
      try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
        if (tx) { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
          status.textContent = dd.used_vision_ocr ? "\u2713 Lexuar me OCR" : "\u2713 Dokumenti u lexua"; } }
      catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
    };
    run.onclick = async function () {
      var details = (ta.value || "").trim();
      if (details.length < 10) { status.textContent = "Jep të dhënat."; return; }
      run.disabled = true; status.textContent = "Po harton aktin\u2026 (~3-4 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/draft", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ deed_type: kind.value, details: details, use_clauses: !!(ov.querySelector(".nd-useclauses") && ov.querySelector(".nd-useclauses").checked) }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var copy = document.createElement("button"); copy.className = "fd-copy"; copy.type = "button"; copy.textContent = "\ud83d\udccb Kopjo tekstin";
        copy.onclick = function () { navigator.clipboard.writeText(d.markdown || "").then(function () { copy.textContent = "\u2713 U kopjua"; }).catch(function () {}); };
        result.appendChild(copy);
        _addSaveToCase(result, "notary", "Akt: " + (kind.options[kind.selectedIndex] ? kind.options[kind.selectedIndex].text : ""), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function openNotaryCheck() {
    _openFableTool({ id: "ncheck-ov", title: "\u2705 Kontroll vlefshmërie akti",
      sub: "Ngjit aktin notarial. Kontrollohen klauzolat e detyrueshme, mospërputhjet dhe nenet e cituara — para noterizimit.",
      placeholder: "Ngjit tekstin e plotë të aktit notarial\u2026",
      btn: "Kontrollo \u2192", loading: "Po kontrolloj aktin\u2026 (~2-3 min)",
      endpoint: "/api/notary/check", payloadKey: "text", attach: true, source: "notary", saveTitle: "Kontroll akti" });
  }

  function openNotarySuccession() {
    _openFableTool({ id: "nsucc-ov", title: "\u2696\ufe0f Analizë trashëgimie",
      sub: "Përshkruaj gjendjen familjare (i ndjeri, bashkëshorti, fëmijët, prindërit…). Merr trashëgimtarët dhe pjesët takuese, të bazuara në ligj.",
      placeholder: "P.sh. I ndjeri la bashkëshorten dhe 2 fëmijë; prindërit jetojnë; pasuria: apartament + kursime\u2026",
      btn: "Analizo \u2192", loading: "Po llogaris trashëgiminë\u2026 (~2-3 min)",
      endpoint: "/api/notary/succession", payloadKey: "situation", attach: false, source: "notary", saveTitle: "Analizë trashëgimie" });
  }

  async function openProkura() {
    var ov = document.getElementById("prok-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "prok-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>📝 Redakto prokurë</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Zgjidh formën dhe tagrat. Merr një prokurë të plotë, gati për noterizim (çdo nen kalon nga Verifikuar). Noteri e verifikon dhe e nënshkruan.</div>' +
      '<div class="prok-forms nd-must-box"></div>' +
      '<div class="prok-scopes nd-must-box"><em>Po ngarkoj…</em></div>' +
      '<div class="ac-row" style="gap:10px;flex-wrap:wrap"><input type="text" class="prok-dur ac-ta" style="min-height:auto;height:38px;flex:1;min-width:180px" placeholder="Afati (p.sh. 1 vit — ose lere bosh)" /><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="prok-subdel" /> Lejo nën-delegim</label></div>' +
      '<textarea class="ac-ta" placeholder="Të dhënat: i përfaqësuari (emër, atësi, ID), përfaqësuesi (emër, ID), pasuria/shoqëria nëse ka… (ato që s’i ke do vihen [___])"></textarea>' +
      '<label class="ac-clauses"><input type="checkbox" class="prok-useclauses"> 📚 Përdor klauzolat e studios</label>' +
      '<div class="ac-row"><button class="ac-run" type="button">Harto prokurën →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var forms = ov.querySelector(".prok-forms"), scopesBox = ov.querySelector(".prok-scopes"),
        ta = ov.querySelector(".ac-ta:not(.prok-dur)") || ov.querySelectorAll(".ac-ta")[1],
        dur = ov.querySelector(".prok-dur"), subdel = ov.querySelector(".prok-subdel"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var data = { forms: [], scopes: [] };
    try { var r = await fetch("/api/notary/prokura-scopes"); if (r.ok) data = await r.json(); } catch (e) {}
    forms.innerHTML = '<b>Forma:</b><div style="margin-top:6px">' + (data.forms || []).map(function (f, i) {
      return '<label style="display:block;margin:3px 0"><input type="radio" name="prokform" value="' + f.key + '"' +
        (f.key === "e_posacme" ? " checked" : "") + '> ' + escapeHtml(f.label) + '</label>';
    }).join("") + '</div>';
    scopesBox.innerHTML = '<b>Tagrat / qëllimet (zgjidh një ose disa):</b><div class="prok-scope-grid" style="margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:2px 14px">' +
      (data.scopes || []).map(function (sc) {
        return '<label style="display:flex;gap:6px;align-items:flex-start;font-size:13px"><input type="checkbox" class="prok-sc" value="' + sc.key + '"> ' + escapeHtml(sc.label) + '</label>';
      }).join("") + '</div>';
    run.onclick = async function () {
      var form = (ov.querySelector('input[name="prokform"]:checked') || {}).value || "e_posacme";
      var scope_keys = Array.prototype.map.call(ov.querySelectorAll(".prok-sc:checked"), function (c) { return c.value; });
      var details = (ta.value || "").trim();
      if (form === "e_posacme" && !scope_keys.length) { status.textContent = "Zgjidh të paktën një tager (ose forma e përgjithshme)."; return; }
      if (details.length < 10) { status.textContent = "Jep të dhënat e palëve."; return; }
      run.disabled = true; status.textContent = "Po harton prokurën… (~2-3 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/prokura", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ form: form, scope_keys: scope_keys, details: details, duration: (dur.value || "").trim(), subdelegation: !!subdel.checked, use_clauses: !!(ov.querySelector(".prok-useclauses") && ov.querySelector(".prok-useclauses").checked) }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var copy = document.createElement("button"); copy.className = "fd-copy"; copy.type = "button"; copy.textContent = "📋 Kopjo tekstin";
        copy.onclick = function () { navigator.clipboard.writeText(d.markdown || "").then(function () { copy.textContent = "✓ U kopjua"; }).catch(function () {}); };
        result.appendChild(copy);
        _addSaveToCase(result, "notary", "Prokurë", d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  async function openDeclaration() {
    var ov = document.getElementById("ndecl-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "ndecl-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>✍️ Deklaratë noteriale</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Zgjidh llojin e deklaratës dhe jep të dhënat. Merr një deklaratë të plotë (çdo nen kalon nga Verifikuar). Noteri e verifikon dhe e nënshkruan.</div>' +
      '<select class="fd-kind ndecl-kind"></select>' +
      '<div class="ndecl-must nd-must"></div>' +
      '<textarea class="ac-ta" placeholder="Jep të dhënat: deklaruesi, i mituri/objekti, periudha… (ato që s’i ke do vihen [___])"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Harto deklaratën →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var kind = ov.querySelector(".ndecl-kind"), must = ov.querySelector(".ndecl-must"),
        ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var types = [];
    try { var r = await fetch("/api/notary/declaration-types"); if (r.ok) types = (await r.json()).types || []; } catch (e) {}
    kind.innerHTML = types.map(function (t) { return '<option value="' + t.key + '">' + t.emoji + ' ' + escapeHtml(t.label) + '</option>'; }).join("");
    function showMust() {
      var t = types.filter(function (x) { return x.key === kind.value; })[0];
      must.innerHTML = t ? '<div class="nd-must-box"><b>Elementet e detyrueshme:</b><ul>' +
        (t.must || []).map(function (m) { return '<li>' + escapeHtml(m) + '</li>'; }).join("") + '</ul></div>' : "";
    }
    kind.onchange = showMust; showMust();
    run.onclick = async function () {
      var details = (ta.value || "").trim();
      if (details.length < 10) { status.textContent = "Jep të dhënat."; return; }
      run.disabled = true; status.textContent = "Po harton deklaratën… (~2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/declaration", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decl_type: kind.value, details: details }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var copy = document.createElement("button"); copy.className = "fd-copy"; copy.type = "button"; copy.textContent = "📋 Kopjo tekstin";
        copy.onclick = function () { navigator.clipboard.writeText(d.markdown || "").then(function () { copy.textContent = "✓ U kopjua"; }).catch(function () {}); };
        result.appendChild(copy);
        _addSaveToCase(result, "notary", "Deklaratë: " + (kind.options[kind.selectedIndex] ? kind.options[kind.selectedIndex].text : ""), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function openDocsChecklist() {
    _openFableTool({ id: "ndocs-ov", title: "📋 Dokumentet e nevojshme",
      sub: "Përshkruaj aktin/shërbimin noterial. Merr listën e plotë të dokumenteve që duhet të sjellë klienti dhe kush i lëshon.",
      placeholder: "P.sh. Kontratë shitje apartamenti mes dy personave fizikë…",
      btn: "Listo dokumentet →", loading: "Po përgatis listën…",
      endpoint: "/api/notary/documents", payloadKey: "act", attach: false, source: "notary", saveTitle: "Dokumentet e nevojshme" });
  }

  function openRevocation() {
    _openFableTool({ id: "nrev-ov", title: "♻️ Revokim prokure",
      sub: "Përshkruaj (ose ngjit) prokurën që do të revokohet dhe të dhënat e palëve. Merr aktin e revokimit, gati për noterizim, me njoftimet e detyrueshme ndaj të tretëve (neni 74 KC).",
      placeholder: "P.sh. Revokoj prokurën nr. ___ rep., datë __.__.____, hartuar te noteri ___, dhënë përfaqësuesit ___ (ID ___), për shitje pasurie…",
      btn: "Harto revokimin →", loading: "Po harton revokimin… (~2 min)",
      endpoint: "/api/notary/revocation", payloadKey: "details", attach: true, source: "notary", saveTitle: "Revokim prokure" });
  }

  async function openConflictCheck() {
    var ov = document.getElementById("nconf-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "nconf-ov"; ov.className = "ac-overlay";
    var hasCase = !!activeCaseId;
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🚦 Kontroll konfliktesh</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Krahason aktin e ri me aktet e ruajtura më parë të të njëjtit rast/klient dhe gjen konfliktet (dy prokura që japin të njëjtin tager, akte kontradiktore, prokurë e revokuar që përdoret ende…).' +
        (hasCase ? '' : ' <b>⚠️ Hap një rast me akte të ruajtura që krahasimi të ketë kuptim.</b>') + '</div>' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit PDF/foto<input type="file" class="nconf-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label></div>' +
      '<textarea class="ac-ta" placeholder="Ngjit tekstin e plotë të AKTIT TË RI që do të noterizohet…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Kontrollo konfliktet →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        file = ov.querySelector(".nconf-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (file) file.onchange = async function () {
      var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
      try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
        if (tx) { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
          status.textContent = dd.used_vision_ocr ? "✓ Lexuar me OCR" : "✓ Dokumenti u lexua"; } }
      catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
    };
    run.onclick = async function () {
      var newAct = (ta.value || "").trim();
      if (newAct.length < 20) { status.textContent = "Ngjit aktin e ri."; return; }
      run.disabled = true; status.textContent = "Po kontrolloj konfliktet… (~2-3 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/conflicts", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ case_id: activeCaseId || "", new_act: newAct }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        _addSaveToCase(result, "notary", "Kontroll konfliktesh", d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function openProsPlan() {
    _openFableTool({ id: "pplan-ov", title: "🔎 Plani i hetimit",
      sub: "Nga kallëzimi ose faktet, merr një plan hetimi: hipotezat, veprimet hetimore, kush të pyetet, afatet dhe objektiviteti. Prokurori vendos.",
      placeholder: "Përshkruaj kallëzimin / faktet e çështjes…",
      btn: "Ndërto planin →", loading: "Po ndërtoj planin e hetimit… (~3 min)",
      endpoint: "/api/prosecutor/investigation-plan", payloadKey: "facts", attach: true, source: "prosecutor", saveTitle: "Plani i hetimit" });
  }

  function openProsMeasure() {
    _openFableTool({ id: "pmeas-ov", title: "🔒 Kërkesë për masë sigurimi",
      sub: "Harton projekt-kërkesën (fumus + periculum + proporcionalitet). ⚠️ Vetëm projekt — gjykata vendos; nuk rekomandohet arresti si i sigurt.",
      placeholder: "Faktet, vepra, dyshimi i arsyeshëm, rreziqet konkrete…",
      btn: "Harto kërkesën →", loading: "Po harton kërkesën për masë… (~3 min)",
      endpoint: "/api/prosecutor/coercive-measure", payloadKey: "facts", attach: true, source: "prosecutor", saveTitle: "Kërkesë për masë sigurimi" });
  }

  function openProsDismissal() {
    _openFableTool({ id: "pdism-ov", title: "🗄️ Kërkesë për pushim / mosfillim",
      sub: "Harton projekt-vendimin e arsyetuar për pushim ose mosfillim. Vendimi i takon prokurorit.",
      placeholder: "Faktet dhe pse nuk ka vend për ndjekje…",
      btn: "Harto projektin →", loading: "Po harton… (~3 min)",
      endpoint: "/api/prosecutor/dismissal", payloadKey: "facts", attach: true, source: "prosecutor", saveTitle: "Pushim / Mosfillim" });
  }

  function openProsStress() {
    _openFableTool({ id: "pstress-ov", title: "🛡️ Stres-test i aktit (ana e mbrojtjes)",
      sub: "Ngjit një akt të prokurorisë (aktakuzë, kërkesë mase, analizë). Gjen dobësitë, pavlefshmëritë procedurale dhe provat shfajësuese para paraqitjes.",
      placeholder: "Ngjit tekstin e plotë të aktit…",
      btn: "Testo aktin →", loading: "Po e stres-testoj… (~2-3 min)",
      endpoint: "/api/prosecutor/stress-test", payloadKey: "text", attach: true, source: "prosecutor", saveTitle: "Stres-test i aktit" });
  }

  function openProsComplaint() {
    _openFableTool({ id: "pcompl-ov", title: "🧾 Ndihmë për kallëzim penal",
      sub: "Nga rrëfimi yt, merr një kallëzim të plotë, ku dorëzohet (Prokuroria vs SPAK) dhe dokumentet për t'u bashkangjitur. Ndihmesë, jo këshillë ligjore.",
      placeholder: "Trego çfarë të ndodhi: kush, çfarë, kur, ku, çfarë dëmi, çfarë provash ke…",
      btn: "Përgatit kallëzimin →", loading: "Po përgatis kallëzimin… (~2-3 min)",
      endpoint: "/api/prosecutor/complaint", payloadKey: "facts", attach: true, source: "prosecutor", saveTitle: "Kallëzim penal" });
  }

  function openProsVictim() {
    _openFableTool({ id: "pvict-ov", title: "⚖️ Të drejtat e viktimës",
      sub: "Shpjegim i thjeshtë i të drejtave (neni 58 KPP) dhe i fazave të procesit për të dëmtuarin.",
      placeholder: "Përshkruaj situatën tënde…",
      btn: "Shpjego →", loading: "Po përgatis shpjegimin…",
      endpoint: "/api/prosecutor/victim-rights", payloadKey: "facts", attach: false, source: "prosecutor", saveTitle: "Të drejtat e viktimës" });
  }

  function openProsAppeal() {
    _openFableTool({ id: "pappeal-ov", title: "📤 Ankim kundër pushimit",
      sub: "Deshifron një vendim pushimi/mosfillimi dhe harton ankimin drejtuar gjykatës. ⚠️ Afatet janë vendimtare — verifikoji.",
      placeholder: "Përshkruaj ose ngjit vendimin e pushimit/mosfillimit…",
      btn: "Harto ankimin →", loading: "Po harton ankimin… (~2-3 min)",
      endpoint: "/api/prosecutor/dismissal-appeal", payloadKey: "facts", attach: true, source: "prosecutor", saveTitle: "Ankim kundër pushimit", calendar: true, calendarTitle: "Afat ankimi" });
  }

  function openProsDelay() {
    _openFableTool({ id: "pdelay-ov", title: "📨 Ankesa për vonesa",
      sub: "Harton ankesat për vonesa: te prokuroria, te Avokati i Popullit, dhe kërkesë për kopje aktesh.",
      placeholder: "Prej sa kohësh po vonon, çfarë çështjeje, çfarë ke kërkuar…",
      btn: "Harto ankesat →", loading: "Po harton ankesat…",
      endpoint: "/api/prosecutor/delay", payloadKey: "facts", attach: false, source: "prosecutor", saveTitle: "Ankesa për vonesa" });
  }

  async function openProsAct() {
    var ov = document.getElementById("pact-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "pact-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🧩 Veprime hetimore</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Zgjidh veprimin dhe jep faktet. Merr kërkesën/urdhrin me bazën ligjore, kushtet dhe arsyetimin (çdo nen kalon nga Verifikuar). Prokurori/gjykata vendos.</div>' +
      '<select class="fd-kind pact-kind"></select>' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit PDF/foto<input type="file" class="pact-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label></div>' +
      '<textarea class="ac-ta" placeholder="Faktet: çfarë kërkohet, ku/te kush, çfarë prove pritet…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Harto kërkesën →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var kind = ov.querySelector(".pact-kind"), ta = ov.querySelector(".ac-ta"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result"), file = ov.querySelector(".pact-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var kinds = [];
    try { var r = await fetch("/api/prosecutor/act-kinds"); if (r.ok) kinds = (await r.json()).kinds || []; } catch (e) {}
    kind.innerHTML = kinds.map(function (k) { return '<option value="' + k.key + '">' + escapeHtml(k.label) + '</option>'; }).join("");
    if (file) file.onchange = async function () {
      var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
      try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
        if (tx) { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
          status.textContent = dd.used_vision_ocr ? "✓ Lexuar me OCR" : "✓ Dokumenti u lexua"; } }
      catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
    };
    run.onclick = async function () {
      var facts = (ta.value || "").trim();
      if (facts.length < 15) { status.textContent = "Jep faktet."; return; }
      run.disabled = true; status.textContent = "Po harton kërkesën… (~2-3 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/prosecutor/investigative-act", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: kind.value, facts: facts }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(result, "prosecutor", "Veprim hetimor: " + (kind.options[kind.selectedIndex] ? kind.options[kind.selectedIndex].text : ""), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function _openHub(cfg) {
    var ov = document.getElementById(cfg.id);
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = cfg.id; ov.className = "ac-overlay";
    var fns = [], body = "";
    (cfg.sections || []).forEach(function (sec) {
      if (sec.label) body += '<div class="hub-sec">' + escapeHtml(sec.label) + '</div>';
      body += '<div class="exp-grid">';
      sec.cards.forEach(function (c) {
        var idx = fns.length; fns.push(c.fn);
        body += '<button type="button" class="exp-card" data-fn="' + idx + '">' +
          '<span class="exp-ico">' + c.emoji + '</span>' +
          '<span class="exp-label">' + escapeHtml(c.label) + '</span>' +
          (c.tag ? '<span class="exp-dom exp-dom-' + (c.tagKind || "penal") + '">' + escapeHtml(c.tag) + '</span>' : '') +
          '</button>';
      });
      body += '</div>';
    });
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>' + cfg.title + '</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="exp-body">' + (cfg.sub ? '<div class="exp-sub">' + cfg.sub + '</div>' : '') + body + '</div>' +
      '</div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    Array.prototype.forEach.call(ov.querySelectorAll(".exp-card"), function (b) {
      b.onclick = function () {
        var f = fns[parseInt(b.getAttribute("data-fn"), 10)];
        close();
        if (typeof f === "function") setTimeout(f, 10);
      };
    });
  }

  function openProsHub() {
    _openHub({ id: "prohub-ov", title: "🏛️ Super Prokurori",
      sub: "Vegla për prokurorin dhe për qytetarin. Zgjidh një funksion. Çdo output kalon nga Verifikuar — prokurori/gjykata vendos dhe firmos.",
      sections: [
        { label: "— PROKURORI —", cards: [
          { emoji: "🏛️", label: "Analiza e prokurorit", tag: "analizë", fn: openProsecutor },
          { emoji: "📜", label: "Aktakuzë", tag: "draft", fn: openIndictment },
          { emoji: "🔎", label: "Plani i hetimit", tag: "hetim", fn: openProsPlan },
          { emoji: "🧩", label: "Veprime hetimore", tag: "kërkesë", fn: openProsAct },
          { emoji: "🔒", label: "Kërkesë për masë sigurimi", tag: "kërkesë", fn: openProsMeasure },
          { emoji: "🗄️", label: "Pushim / Mosfillim", tag: "projekt", fn: openProsDismissal },
          { emoji: "🛡️", label: "Stres-test i aktit", tag: "kontroll", fn: openProsStress },
          { emoji: "⏰", label: "Parashkrimi & afatet", tag: "afat", fn: openPrescription } ] },
        { label: "— QYTETARI —", cards: [
          { emoji: "🧾", label: "Ndihmë për kallëzim penal", tag: "qytetar", tagKind: "civil", fn: openProsComplaint },
          { emoji: "⚖️", label: "Të drejtat e viktimës", tag: "qytetar", tagKind: "civil", fn: openProsVictim },
          { emoji: "📤", label: "Ankim kundër pushimit", tag: "qytetar", tagKind: "civil", fn: openProsAppeal },
          { emoji: "📨", label: "Ankesa për vonesa", tag: "qytetar", tagKind: "civil", fn: openProsDelay } ] }
      ] });
  }

  function openNoterHub() {
    _openHub({ id: "noterhub-ov", title: "📜 Super Noteri",
      sub: "Vegla noteriale: procure, akte, deklarata, kontrolle. Zgjidh një funksion. Çdo nen kalon nga Verifikuar — noteri e verifikon dhe e nënshkruan.",
      sections: [
        { label: "— HARTIM —", cards: [
          { emoji: "📸", label: "Lexo & mbush (auto)", tag: "hartim", fn: openExtract },
          { emoji: "📝", label: "Redakto prokurë", tag: "hartim", fn: openProkura },
          { emoji: "📜", label: "Redakto akt notarial", tag: "hartim", fn: openNotaryDeed },
          { emoji: "✍️", label: "Deklaratë noteriale", tag: "hartim", fn: openDeclaration },
          { emoji: "📚", label: "Klauzolat e studios", tag: "hartim", fn: openClauses } ] },
        { label: "— KONTROLL & ANALIZË —", cards: [
          { emoji: "🕵️", label: "Ispektor (Revizor Senior)", tag: "kontroll", fn: openIspektor },
          { emoji: "✅", label: "Kontroll vlefshmërie", tag: "kontroll", fn: openNotaryCheck },
          { emoji: "🚦", label: "Kontroll konfliktesh", tag: "kontroll", fn: openConflictCheck },
          { emoji: "⚖️", label: "Analizë trashëgimie", tag: "analizë", fn: openNotarySuccession },
          { emoji: "♻️", label: "Revokim prokure", tag: "akt", fn: openRevocation },
          { emoji: "🔮", label: "Çka nëse… (simulator)", tag: "analizë", fn: openWhatIf } ] },
        { label: "— NDIHMË —", cards: [
          { emoji: "✅", label: "Checklist fashikulli (auto)", tag: "ndihmë", tagKind: "civil", fn: openChecklist },
          { emoji: "🗣️", label: "Për klientin (shpjego/email)", tag: "ndihmë", tagKind: "civil", fn: openClientComm },
          { emoji: "🔎", label: "Regjistri (kërko akte)", tag: "ndihmë", tagKind: "civil", fn: openRegistry },
          { emoji: "📋", label: "Dokumentet e nevojshme", tag: "ndihmë", tagKind: "civil", fn: openDocsChecklist },
          { emoji: "🧮", label: "Tarifat & taksat", tag: "ndihmë", tagKind: "civil", fn: openNotaryFees } ] },
        { label: "— STUDIO —", cards: [
          { emoji: "📊", label: "Paneli i studios", tag: "studio", tagKind: "civil", fn: openDashboard } ] }
      ] });
  }

  function openDeepVerify() {
    _openFableTool({ id: "dverify-ov", title: "🔬 Verifikim i thellë",
      sub: "Ngjit një përgjigje ose tekst juridik. Kontrollohet nëse çdo nen i cituar VËRTET e mbështet pohimin — kundrejt tekstit REAL të nenit nga korpusi.",
      placeholder: "Ngjit tekstin/përgjigjen juridike që do të kontrollohet…",
      btn: "Verifiko thellë →", loading: "Po kontrolloj çdo pohim kundrejt tekstit real… (~2-3 min)",
      endpoint: "/api/deep-verify", payloadKey: "text", attach: true, source: "research", saveTitle: "Verifikim i thellë" });
  }

  function openLawLive() {
    _openFableTool({ id: "lawlive-ov", title: "🌐 A është ende në fuqi?",
      sub: "Shkruaj ligjin/nenin. Kontrollohet ONLINE te burimet zyrtare (QBZ / Fletorja Zyrtare) nëse është në fuqi, i ndryshuar apo i shfuqizuar — me burime.",
      placeholder: "P.sh. Neni 134 i Kodit Penal; ose Ligji nr. 7895, datë 27.1.1995…",
      btn: "Kontrollo online →", loading: "Po kontrolloj te burimet zyrtare online… (~2-3 min)",
      endpoint: "/api/law-live", payloadKey: "query", attach: false, source: "research", saveTitle: "Kontroll ligji (live)" });
  }

  function openLivingHub() {
    _openHub({ id: "livehub-ov", title: "🟢 Ligj i gjallë",
      sub: "Besueshmëria — asi ynë: kontrollo që teksti të mbështetet VËRTET nga nenet, dhe që ligji të jetë ENDE në fuqi.",
      sections: [ { cards: [
        { emoji: "🔬", label: "Verifikim i thellë", tag: "besueshmëri", tagKind: "civil", fn: openDeepVerify },
        { emoji: "🌐", label: "A është ende në fuqi?", tag: "live", tagKind: "civil", fn: openLawLive } ] } ] });
  }

  async function openIntake() {
    var ov = document.getElementById("intake-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "intake-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🎙️ Pika e parë — tregoni problemin</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Tregoni me fjalët tuaja çfarë ju ndodhi (me zë ose me shkrim). Ju themi nëse ka çështje, sa urgjente është, kush ju ndihmon — dhe ju përgatisim dokumentin e parë. Orientim, jo këshillë përfundimtare.</div>' +
      '<div class="intake-inrow"><button type="button" class="intake-mic" title="Fol shqip">🎙️</button>' +
      '<textarea class="ac-ta intake-ta" placeholder="P.sh. Më rrahu një fqinj para 3 ditësh, kam mavijosje dhe një dëshmitar…"></textarea></div>' +
      '<div class="ac-row"><button class="ac-run" type="button">Më orjento →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".intake-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        mic = ov.querySelector(".intake-mic");
    function close() { try { if (rec) rec.stop(); } catch (e) {} ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });

    // voice (Web Speech), same pattern as rehearsal
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var rec = null, listening = false;
    if (!SR) { mic.setAttribute("disabled", ""); mic.title = "Shfletuesi yt nuk e mbështet diktimin."; }
    else mic.onclick = function () {
      if (listening) { try { rec.stop(); } catch (e) {} listening = false; mic.classList.remove("listening"); return; }
      rec = new SR(); rec.lang = "sq-AL"; rec.interimResults = true; rec.continuous = true;
      var baseline = ta.value;
      rec.onresult = function (e) {
        var interim = "", final = "";
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var t = e.results[i][0].transcript;
          if (e.results[i].isFinal) final += t + " "; else interim += t;
        }
        if (final) baseline = (baseline ? baseline.trim() + " " : "") + final.trim();
        ta.value = (baseline + (interim ? " " + interim : "")).trim();
      };
      rec.onerror = function () { listening = false; mic.classList.remove("listening"); };
      rec.onend = function () { if (listening) { try { rec.start(); } catch (e) {} } };
      try { rec.start(); listening = true; mic.classList.add("listening"); }
      catch (e) { status.textContent = "S'fillova mikrofonin."; }
    };

    var ROUTE_MAP = {
      proscomplaint: ["🧾 Përgatit kallëzimin", openProsComplaint],
      prosvictim: ["⚖️ Të drejtat e tua", openProsVictim],
      prosdelay: ["📨 Ankesa për vonesa", openProsDelay],
      expertise: ["🎯 Analizë e çështjes", openExpertise],
      noterdeed: ["📜 Redakto akt notarial", openNotaryDeed],
      noterprokura: ["📝 Redakto prokurë", openProkura],
      notersucc: ["⚖️ Analizë trashëgimie", openNotarySuccession],
      devil: ["🔮 Këshillë strategjike", openDevilConsult]
    };

    run.onclick = async function () {
      var story = (ta.value || "").trim();
      if (story.length < 15) { status.textContent = "Tregoni pak më shumë."; return; }
      if (listening) { try { rec.stop(); } catch (e) {} listening = false; mic.classList.remove("listening"); }
      run.disabled = true; status.textContent = "Po ju orjentoj… (~1-2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/intake/triage", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ story: story }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var rt = ROUTE_MAP[d.route];
        if (rt) {
          var go = document.createElement("button");
          go.className = "ac-run intake-go"; go.type = "button";
          go.textContent = "Vazhdo → " + rt[0];
          go.onclick = function () {
            close();
            setTimeout(function () {
              rt[1]();
              setTimeout(function () {
                var overlays = document.querySelectorAll(".ac-overlay");
                var last = overlays[overlays.length - 1];
                var nta = last && last.querySelector(".ac-ta");
                if (nta && !nta.value) { nta.value = story; }
              }, 80);
            }, 10);
          };
          result.appendChild(go);
        }
        _addSaveToCase(result, "research", "Pika e parë (triazh)", d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function _renderFkTimeline(res) {
    var h = "";
    if (res.summary) h += '<div class="fk-sum">' + escapeHtml(res.summary) + '</div>';
    var ev = res.events || [];
    if (ev.length) {
      h += '<ol class="fk-tl">' + ev.map(function (e) {
        return '<li><span class="fk-date">' + escapeHtml(e.date || "?") + '</span>' +
          '<div><b>' + escapeHtml(e.type || "") + '</b> — ' + escapeHtml(e.summary || "") +
          (e.parties && e.parties.length ? '<div class="fk-meta">👥 ' + escapeHtml(e.parties.join(", ")) + '</div>' : "") +
          (e.source_doc ? '<div class="fk-src">📄 ' + escapeHtml(e.source_doc) + (e.source_excerpt ? ': “' + escapeHtml(e.source_excerpt) + '”' : "") + '</div>' : "") +
          (e.legal_significance ? '<div class="fk-sig">⚖️ ' + escapeHtml(e.legal_significance) + '</div>' : "") +
          '</div></li>';
      }).join("") + '</ol>';
    }
    var ct = res.contradictions || [];
    if (ct.length) {
      h += '<div class="fk-h">⚔️ Kontradikta (' + ct.length + ')</div>' + ct.map(function (c) {
        return '<div class="fk-ct fk-' + (c.severity || "medium") + '"><b>' + escapeHtml(c.issue || "") + '</b>' +
          (c.claims ? '<ul>' + c.claims.map(function (x) { return '<li>' + escapeHtml(x.value || "") + ' — <i>' + escapeHtml(x.source || "") + '</i></li>'; }).join("") + '</ul>' : "") +
          (c.tactical_note ? '<div class="fk-meta">🎯 ' + escapeHtml(c.tactical_note) + '</div>' : "") + '</div>';
      }).join("");
    }
    var gp = res.gaps || [];
    if (gp.length) {
      h += '<div class="fk-h">🕳️ Boshllëqe (' + gp.length + ')</div>' + gp.map(function (g) {
        return '<div class="fk-gap">' + escapeHtml((g.from || "?") + " → " + (g.to || "?")) + ' (' + (g.duration_days || 0) + ' ditë): ' + escapeHtml(g.concern || "") + '</div>';
      }).join("");
    }
    return h || '<em>Asnjë ngjarje e datuar nuk u gjet.</em>';
  }

  async function openFascikull() {
    var ov = document.getElementById("fk-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "fk-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>🗂️ Fashikulli intelligjent</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="exp-body">' +
        '<div class="exp-sub">Inteligjenca mbi dokumentet e rastit: kronologjia, kush tha çfarë, pyet dokumentet, gjilpëra — të gjitha të bazuara VETËM te dokumentet e ngarkuara [Dok N].</div>' +
        '<div class="fk-caseinfo"></div>' +
        '<details class="fk-sec" open><summary>📅 Kronologjia (ngjarje · kontradikta · boshllëqe)</summary>' +
          '<div class="ac-row"><button class="ac-run fk-tl-btn" type="button">Ndërto/rifresko kronologjinë →</button><span class="ac-status fk-tl-st"></span></div>' +
          '<div class="ac-result fk-tl-res"></div></details>' +
        '<details class="fk-sec"><summary>🗣️ Kush tha çfarë (versionet & përplasjet)</summary>' +
          '<div class="ac-row"><button class="ac-run fk-who-btn" type="button">Harto hartën →</button><span class="ac-status fk-who-st"></span></div>' +
          '<div class="ac-result fk-who-res"></div></details>' +
        '<details class="fk-sec"><summary>🔍 Pyet dokumentet</summary>' +
          '<textarea class="ac-ta fk-ask-ta" placeholder="P.sh. Cila është data e njoftimit dhe kush e nënshkroi?"></textarea>' +
          '<div class="ac-row"><button class="ac-run fk-ask-btn" type="button">Pyet →</button><span class="ac-status fk-ask-st"></span></div>' +
          '<div class="ac-result fk-ask-res"></div></details>' +
        '<details class="fk-sec"><summary>💉 Gjilpëra në kashtë (detajin e mbivështruar)</summary>' +
          '<div class="ac-row"><button class="ac-run fk-nd-btn" type="button">Gjej gjilpërën →</button><span class="ac-status fk-nd-st"></span></div>' +
          '<div class="ac-result fk-nd-res"></div></details>' +
        '<details class="fk-sec"><summary>🔎 Regjistri (kërko akte semantik)</summary>' +
          '<input type="text" class="research-search fk-rg-q" placeholder="🔎 P.sh. dhurime me uzufrukt, ku shfaqet 7/512…" />' +
          '<label class="ck-dossier"><input type="checkbox" class="fk-rg-case" checked> Vetëm ky rast (çaktivizoje për tërë studion)</label>' +
          '<div class="ac-row"><button class="ac-run fk-rg-btn" type="button">Kërko →</button><span class="ac-status fk-rg-st"></span></div>' +
          '<div class="ac-result fk-rg-res"></div></details>' +
        '<details class="fk-sec"><summary>🕵️ Ispektor i aktit (revizor senior)</summary>' +
          '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit<input type="file" class="fk-isp-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden></label></div>' +
          '<textarea class="ac-ta fk-isp-ta" placeholder="Ngjit aktin që do të inspektohet (kontratë, akt notarial, padi, aktakuzë…)…"></textarea>' +
          '<div class="ac-row"><button class="ac-run fk-isp-btn" type="button">Inspekto →</button><span class="ac-status fk-isp-st"></span></div>' +
          '<div class="ac-result fk-isp-res"></div></details>' +
        '<details class="fk-sec"><summary>📸 Lexo & mbush (nxjerr të dhënat)</summary>' +
          '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit<input type="file" class="fk-ext-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden multiple></label>' +
            '<label class="ck-dossier"><input type="checkbox" class="fk-ext-case" checked> Nga dokumentet e rastit</label></div>' +
          '<textarea class="ac-ta fk-ext-ta" placeholder="Ose ngjit tekstin e dokumentit…"></textarea>' +
          '<div class="ac-row"><button class="ac-run fk-ext-btn" type="button">Nxirr të dhënat →</button><span class="ac-status fk-ext-st"></span></div>' +
          '<div class="ac-result fk-ext-res"></div></details>' +
        '<details class="fk-sec"><summary>🔮 Çka nëse… (simulator)</summary>' +
          '<textarea class="ac-ta fk-wi-act" placeholder="Akti aktual (ngjit tekstin ose parametrat)…"></textarea>' +
          '<textarea class="ac-ta fk-wi-change" style="min-height:60px" placeholder="Ndryshimi që po mendon — p.sh. Çka nëse shtoj një uzufrukt?"></textarea>' +
          '<div class="ac-row"><button class="ac-run fk-wi-btn" type="button">Simulo →</button><span class="ac-status fk-wi-st"></span></div>' +
          '<div class="ac-result fk-wi-res"></div></details>' +
        '<details class="fk-sec"><summary>📚 Klauzolat e studios</summary>' +
          '<div class="ac-row"><button class="ac-run fk-cl-manage" type="button">📚 Menaxho / shto klauzola</button></div>' +
          '<div class="fk-cl-list"></div></details>' +
      '</div></div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var info = ov.querySelector(".fk-caseinfo");
    async function refreshInfo() {
      var txt = "";
      if (activeCaseId) {
        try {
          var rd = await fetch("/api/cases/" + activeCaseId + "/documents");
          if (rd.ok) {
            var dj = await rd.json(); var docs = dj.documents || []; var n = docs.length;
            var ready = docs.filter(function (d) { return (d.status || "") === "ready"; }).length;
            txt = n ? ('<span class="fk-ok">📎 ' + n + ' dokument(e)' + (ready < n ? (' · ' + (n - ready) + ' në përpunim…') : ' gati') + '</span>')
                    : '<span class="fk-warn">Asnjë dokument — ngarko për të nisur.</span>';
          }
        } catch (e) {}
      } else {
        txt = '<span class="fk-warn">Do të krijohet një rast i ri kur të ngarkosh.</span>';
      }
      info.innerHTML = '<div class="fk-uprow"><label class="fk-upload">📎 Ngarko dokumente<input type="file" multiple class="fk-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx,.txt" hidden></label> ' + txt + '</div>';
      var fkFile = info.querySelector(".fk-file");
      if (fkFile) fkFile.onchange = async function () {
        if (!fkFile.files || !fkFile.files.length) return;
        var files = [].slice.call(fkFile.files); fkFile.value = "";
        var lbl = info.querySelector(".fk-upload"); if (lbl) lbl.textContent = "⏳ Po ngarkoj…";
        try { await uploadFiles(files); } catch (e) {}
        await refreshInfo();
      };
    }
    await refreshInfo();
    function _need() { if (!activeCaseId) { return false; } return true; }
    function _render(res, box, md) {
      if (!md || !String(md).trim()) {
        box.innerHTML = '<div class="fk-warn">📎 Nuk ka dokumente të gatshme në këtë dosje. Ngarko dokumente te dosja (📎) dhe prit sa të përpunohen — pastaj kjo vegël i analizon.</div>';
        return;
      }
      box.innerHTML = '<div class="fd-out"></div>';
      var out = box.querySelector(".fd-out");
      out.innerHTML = renderMarkdown(md || "");
      if (res && res.citations) { highlightNeni(out, buildCitStatusMap(res.citations));
        if (res.citations.stats && res.citations.stats.total > 0) box.insertBefore(renderCitationsBadge(res.citations, null), out); }
      _addSaveToCase(box, "research", "Fashikull", md || "");
    }
    // Kronologjia — try cached, then build on click
    var tlBtn = ov.querySelector(".fk-tl-btn"), tlSt = ov.querySelector(".fk-tl-st"), tlRes = ov.querySelector(".fk-tl-res");
    if (activeCaseId) { try { var rc = await fetch("/api/cases/" + activeCaseId + "/timeline");
      if (rc.ok) { var cj = await rc.json(); if (cj.result) { tlRes.innerHTML = _renderFkTimeline(cj.result); tlSt.textContent = "e ruajtur"; } } } catch (e) {} }
    tlBtn.onclick = async function () {
      if (!_need()) { tlSt.textContent = "Hap një rast."; return; }
      tlBtn.disabled = true; tlSt.textContent = "Po lexoj dokumentet dhe ndërtoj kronologjinë… (~1-2 min)";
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/timeline", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        tlRes.innerHTML = _renderFkTimeline(d.result || {});
        tlSt.textContent = "✓ " + ((d.result && d.result.event_count) || 0) + " ngjarje · " + ((d.result && (d.result.contradictions || []).length) || 0) + " kontradikta";
      } catch (e) { tlSt.textContent = "Gabim: " + e.message; } finally { tlBtn.disabled = false; }
    };
    // Kush tha çfarë
    var whoBtn = ov.querySelector(".fk-who-btn"), whoSt = ov.querySelector(".fk-who-st"), whoRes = ov.querySelector(".fk-who-res");
    whoBtn.onclick = async function () {
      if (!_need()) { whoSt.textContent = "Hap një rast."; return; }
      whoBtn.disabled = true; whoSt.textContent = "Po hartoj kush-tha-çfarë… (~2 min)";
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/who-said", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        whoSt.textContent = ""; _render(d, whoRes, d.markdown);
      } catch (e) { whoSt.textContent = "Gabim: " + e.message; } finally { whoBtn.disabled = false; }
    };
    // Pyet dokumentet
    var askTa = ov.querySelector(".fk-ask-ta"), askBtn = ov.querySelector(".fk-ask-btn"), askSt = ov.querySelector(".fk-ask-st"), askRes = ov.querySelector(".fk-ask-res");
    askBtn.onclick = async function () {
      if (!_need()) { askSt.textContent = "Hap një rast."; return; }
      var q = (askTa.value || "").trim(); if (q.length < 5) { askSt.textContent = "Shkruaj pyetjen."; return; }
      askBtn.disabled = true; askSt.textContent = "Po lexoj dokumentet…";
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/vault", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        askSt.textContent = d.truncated ? ("shfrytëzuar " + d.n_docs + " dok") : "";
        _render(d, askRes, d.answer);
      } catch (e) { askSt.textContent = "Gabim: " + e.message; } finally { askBtn.disabled = false; }
    };
    // Gjilpëra
    var ndBtn = ov.querySelector(".fk-nd-btn"), ndSt = ov.querySelector(".fk-nd-st"), ndRes = ov.querySelector(".fk-nd-res");
    ndBtn.onclick = async function () {
      if (!_need()) { ndSt.textContent = "Hap një rast."; return; }
      ndBtn.disabled = true; ndSt.textContent = "Po gjurmoj gjilpërën…";
      try {
        var r = await fetch("/api/cases/" + activeCaseId + "/needle", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        ndSt.textContent = ""; _render(d, ndRes, d.markdown);
      } catch (e) { ndSt.textContent = "Gabim: " + e.message; } finally { ndBtn.disabled = false; }
    };
    var rgQ = ov.querySelector(".fk-rg-q"), rgCase = ov.querySelector(".fk-rg-case"),
        rgBtn = ov.querySelector(".fk-rg-btn"), rgSt = ov.querySelector(".fk-rg-st"), rgRes = ov.querySelector(".fk-rg-res");
    async function rgGo() {
      var query = (rgQ.value || "").trim();
      if (query.length < 2) { rgSt.textContent = "Shkruaj pyetjen."; return; }
      rgBtn.disabled = true; rgSt.textContent = "Po kërkoj… (~1 min)"; rgRes.innerHTML = "";
      try {
        var payload = { query: query };
        if (rgCase && rgCase.checked && activeCaseId) payload.case_id = activeCaseId;
        var r = await fetch("/api/registry/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        rgSt.textContent = "";
        rgRes.innerHTML = '<div class="fd-out"></div>';
        rgRes.querySelector(".fd-out").innerHTML = renderMarkdown(d.markdown || "");
        var matches = d.matches || [];
        if (matches.length) {
          var ul = document.createElement("ul"); ul.className = "research-list"; ul.style.marginTop = "10px";
          matches.forEach(function (it) {
            var li = document.createElement("li"); li.className = "research-item";
            var head = document.createElement("div"); head.className = "research-head";
            head.innerHTML = '<span class="research-src">' + escapeHtml(_srcLabel(it.source)) + '</span>' +
              (it.client_name ? '<span class="research-cli">👤 ' + escapeHtml(it.client_name) + '</span>' : "") +
              '<span class="research-ttl">' + escapeHtml(it.title || "") + '</span>';
            var body = document.createElement("div"); body.className = "research-body"; body.hidden = true;
            head.addEventListener("click", function () { if (body.hidden) { body.innerHTML = renderMarkdown(it.content || ""); body.hidden = false; } else body.hidden = true; });
            li.appendChild(head); li.appendChild(body); ul.appendChild(li);
          });
          rgRes.appendChild(ul);
        }
      } catch (e) { rgSt.textContent = "Gabim: " + e.message; }
      finally { rgBtn.disabled = false; }
    }
    rgBtn.onclick = rgGo;
    rgQ.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); rgGo(); } });
    // Ispektor
    var ispTa = ov.querySelector(".fk-isp-ta"), ispBtn = ov.querySelector(".fk-isp-btn"),
        ispSt = ov.querySelector(".fk-isp-st"), ispRes = ov.querySelector(".fk-isp-res"), ispFile = ov.querySelector(".fk-isp-file");
    if (ispFile) ispFile.onchange = async function () {
      var f = ispFile.files && ispFile.files[0]; if (!f) return; ispBtn.disabled = true;
      try { var dd = await _extractFileText(f, ispSt); var tx = (dd.text || "").trim();
        if (tx) ispTa.value = ispTa.value.trim() ? (ispTa.value.trim() + "\n\n" + tx) : tx; }
      catch (e) {} finally { ispBtn.disabled = false; ispFile.value = ""; }
    };
    ispBtn.onclick = async function () {
      var text = (ispTa.value || "").trim();
      if (text.length < 30) { ispSt.textContent = "Ngjit aktin."; return; }
      ispBtn.disabled = true; ispSt.textContent = "Po inspektoj… (~2-3 min)"; ispRes.innerHTML = "";
      try {
        var r = await fetch("/api/notary/inspect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text, case_id: activeCaseId || "" }) });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        ispSt.textContent = "";
        ispRes.innerHTML = _riskGauge(d.risk, d.verdict) + '<div class="fd-out"></div>';
        var out = ispRes.querySelector(".fd-out"); out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) ispRes.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(ispRes, "notary", "Ispektim akti", (d.risk != null ? ("Rreziku: " + d.risk + "/100\n\n") : "") + (d.markdown || ""));
      } catch (e) { ispSt.textContent = "Gabim: " + e.message; } finally { ispBtn.disabled = false; }
    };
    // Lexo & mbush
    var extTa = ov.querySelector(".fk-ext-ta"), extCase = ov.querySelector(".fk-ext-case"), extBtn = ov.querySelector(".fk-ext-btn"),
        extSt = ov.querySelector(".fk-ext-st"), extRes = ov.querySelector(".fk-ext-res"), extFile = ov.querySelector(".fk-ext-file");
    if (extFile) extFile.onchange = async function () {
      var files = extFile.files ? [].slice.call(extFile.files) : []; if (!files.length) return; extBtn.disabled = true;
      if (extCase) extCase.checked = false;
      for (var i = 0; i < files.length; i++) { try { var dd = await _extractFileText(files[i], extSt); var tx = (dd.text || "").trim(); if (tx) extTa.value = extTa.value.trim() ? (extTa.value.trim() + "\n\n" + tx) : tx; } catch (e) {} }
      extSt.textContent = "✓ u lexuan"; extBtn.disabled = false; extFile.value = "";
    };
    extBtn.onclick = async function () {
      var text = (extTa.value || "").trim(); var payload = {};
      if (text) payload.text = text; else if (extCase && extCase.checked && activeCaseId) payload.case_id = activeCaseId;
      else { extSt.textContent = "Jep tekstin ose zgjidh dokumentet e rastit."; return; }
      extBtn.disabled = true; extSt.textContent = "Po nxjerr të dhënat… (~1-2 min)"; extRes.innerHTML = "";
      try {
        var r = await fetch("/api/notary/extract", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error === "text_required" ? "Nuk ka tekst — bashkëngjit ose përdor dokumentet e rastit." : (d.error || ("HTTP " + r.status)));
        extSt.textContent = "";
        extRes.innerHTML = '<div class="fd-out"></div>'; extRes.querySelector(".fd-out").innerHTML = renderMarkdown(d.markdown || "");
        var cpx = document.createElement("button"); cpx.className = "fd-copy"; cpx.type = "button"; cpx.textContent = "📋 Kopjo";
        cpx.onclick = function () { navigator.clipboard.writeText(d.markdown || "").then(function () { cpx.textContent = "✓ U kopjua"; }).catch(function () {}); };
        extRes.appendChild(cpx);
        _addSaveToCase(extRes, "notary", "Të dhëna të nxjerra", d.markdown || "");
      } catch (e) { extSt.textContent = "Gabim: " + e.message; } finally { extBtn.disabled = false; }
    };
    // Çka nëse
    var wiAct = ov.querySelector(".fk-wi-act"), wiChange = ov.querySelector(".fk-wi-change"), wiBtn = ov.querySelector(".fk-wi-btn"),
        wiSt = ov.querySelector(".fk-wi-st"), wiRes = ov.querySelector(".fk-wi-res");
    wiBtn.onclick = async function () {
      var act = (wiAct.value || "").trim(), change = (wiChange.value || "").trim();
      if (act.length < 15) { wiSt.textContent = "Jep aktin aktual."; return; }
      if (change.length < 4) { wiSt.textContent = "Shkruaj ndryshimin."; return; }
      wiBtn.disabled = true; wiSt.textContent = "Po simuloj… (~2 min)"; wiRes.innerHTML = "";
      try {
        var r = await fetch("/api/notary/whatif", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ act: act, change: change }) });
        var d = await r.json(); if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        wiSt.textContent = "";
        wiRes.innerHTML = '<div class="fd-out"></div>'; var out = wiRes.querySelector(".fd-out"); out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) wiRes.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(wiRes, "notary", "Simulim: " + change.slice(0, 50), d.markdown || "");
      } catch (e) { wiSt.textContent = "Gabim: " + e.message; } finally { wiBtn.disabled = false; }
    };
    // Klauzolat
    var clManage = ov.querySelector(".fk-cl-manage"), clList = ov.querySelector(".fk-cl-list");
    if (clManage) clManage.onclick = function () { close(); setTimeout(function () { openClauses(); }, 10); };
    (async function clLoad() {
      try {
        var r = await fetch("/api/firm/clauses"); var d = await r.json(); var cl = d.clauses || [];
        if (!cl.length) { clList.innerHTML = '<div class="fk-warn" style="margin-top:8px">Ende asnjë klauzolë — kliko lart për të shtuar.</div>'; return; }
        var ul = document.createElement("ul"); ul.className = "research-list"; ul.style.marginTop = "8px";
        cl.forEach(function (c) {
          var li = document.createElement("li"); li.className = "research-item";
          var head = document.createElement("div"); head.className = "research-head";
          head.innerHTML = (c.category ? '<span class="research-src">' + escapeHtml(c.category) + '</span>' : '') + '<span class="research-ttl">' + escapeHtml(c.label || "") + '</span>';
          var body = document.createElement("div"); body.className = "research-body"; body.hidden = true;
          head.addEventListener("click", function () { if (body.hidden) { body.innerHTML = renderMarkdown(c.content || ""); body.hidden = false; } else body.hidden = true; });
          li.appendChild(head); li.appendChild(body); ul.appendChild(li);
        });
        clList.innerHTML = ""; clList.appendChild(ul);
      } catch (e) {}
    })();
  }

  async function openAfati() {
    var ov = document.getElementById("afati-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "afati-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>⏰ Motori i afateve</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Zgjidh ngjarjen-nisëse dhe datën. Llogariten TË GJITHA afatet procedurale që lindin, të bazuara në nenet reale (kur teksti s’jep numër, të thotë ta verifikosh). Pastaj i shton në kalendar me një klik. Profesionisti konfirmon.</div>' +
      '<div class="ac-row" style="gap:8px;flex-wrap:wrap">' +
        '<select class="fd-kind afati-trig" style="flex:1;min-width:200px"></select>' +
        '<label style="display:flex;align-items:center;gap:6px">Data e ngjarjes <input type="date" class="afati-date"></label>' +
      '</div>' +
      '<textarea class="ac-ta afati-ta" placeholder="Detaje (opsionale): p.sh. arrestim në flagrancë për vjedhje; vendimi u njoftua sot…"></textarea>' +
      '<div class="ac-row"><button class="ac-run afati-run" type="button">Llogarit afatet →</button><span class="ac-status afati-st"></span></div>' +
      '<div class="ac-result afati-res"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var trig = ov.querySelector(".afati-trig"), date = ov.querySelector(".afati-date"),
        ta = ov.querySelector(".afati-ta"), run = ov.querySelector(".afati-run"),
        status = ov.querySelector(".afati-st"), result = ov.querySelector(".afati-res");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var triggers = [];
    try { var r = await fetch("/api/afati/triggers"); if (r.ok) triggers = (await r.json()).triggers || []; } catch (e) {}
    trig.innerHTML = triggers.map(function (t) { return '<option value="' + t.key + '">' + escapeHtml(t.label) + '</option>'; }).join("");
    run.onclick = async function () {
      run.disabled = true; status.textContent = "Po llogaris afatet… (~2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/afati/compute", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ trigger: trig.value, event_date: date.value || "", facts: (ta.value || "").trim() }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var afatet = d.afatet || [];
        if (afatet.length) {
          var box = document.createElement("div");
          box.className = "afati-cal";
          box.innerHTML = '<div class="afati-cal-h">📅 Shto në kalendar (kontrollo datat para se t’i ruash):</div>' +
            afatet.map(function (a, i) {
              return '<label class="afati-cal-row"><input type="checkbox" class="afati-cb" data-i="' + i + '" checked> ' +
                '<input type="date" class="afati-cd" data-i="' + i + '" value="' + escapeHtml(a.date) + '"> ' +
                '<span>' + escapeHtml(a.title) + '</span></label>';
            }).join("") +
            '<div class="ac-row"><button type="button" class="ac-run afati-add">➕ Shto të zgjedhurat në kalendar</button><span class="ac-status afati-add-st"></span></div>';
          result.appendChild(box);
          var addBtn = box.querySelector(".afati-add"), addSt = box.querySelector(".afati-add-st");
          addBtn.onclick = async function () {
            if (!activeCaseId) { addSt.textContent = "Hap ose krijo një rast që t’i ruash."; return; }
            var rows = box.querySelectorAll(".afati-cb");
            var todo = [];
            Array.prototype.forEach.call(rows, function (cb) {
              if (!cb.checked) return;
              var i = cb.getAttribute("data-i");
              var dd = box.querySelector('.afati-cd[data-i="' + i + '"]').value;
              if (dd) todo.push({ title: afatet[i].title, date: dd });
            });
            if (!todo.length) { addSt.textContent = "Zgjidh të paktën një afat me datë."; return; }
            addBtn.disabled = true; addSt.textContent = "Duke ruajtur…";
            var ok = 0;
            for (var j = 0; j < todo.length; j++) {
              try {
                var rr = await fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ title: todo[j].title, kind: "afat", starts_at: todo[j].date + "T09:00:00",
                    case_id: activeCaseId, reminders: [43200, 10080, 1440] }) });
                if (rr.ok) ok++;
              } catch (e) {}
            }
            addSt.textContent = "✓ U shtuan " + ok + "/" + todo.length + " afate (me alarm 30/7/1 ditë para)";
            addBtn.disabled = false;
          };
        }
        _addSaveToCase(result, "research", "Afatet procedurale", d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { trig.focus(); }, 50);
  }

  function _riskGauge(risk, verdict) {
    if (risk === null || risk === undefined) return "";
    var lvl = risk <= 20 ? "ok" : (risk <= 50 ? "warn" : "danger");
    var word = risk <= 20 ? "I ulët" : (risk <= 50 ? "Mesatar" : "I lartë");
    return '<div class="isp-gauge isp-' + lvl + '">' +
      '<div class="isp-num">' + risk + '<span>/100</span></div>' +
      '<div class="isp-bar"><i style="width:' + risk + '%"></i></div>' +
      '<div class="isp-cap">Indeksi i rrezikut · <b>' + word + '</b></div>' +
      (verdict ? '<div class="isp-verdict">' + escapeHtml(verdict) + '</div>' : '') +
      '</div>';
  }

  async function openIspektor() {
    var ov = document.getElementById("isp-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "isp-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🕵️ Ispektor — Revizor Senior</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Ngjit aktin (ose bashkëngjit PDF/foto). Inspektori e SULMON si një gjyqtar dhe jep një indeks rreziku 0-100, problemet sipas rëndësisë dhe rregullimet. Nëse ka një rast hapur, krahason edhe me aktet e ruajtura. Ndihmesë — noteri vendos.</div>' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit PDF/foto<input type="file" class="isp-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden></label></div>' +
      '<textarea class="ac-ta" placeholder="Ngjit tekstin e plotë të aktit notarial që do të inspektohet…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Inspekto aktin →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        file = ov.querySelector(".isp-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (file) file.onchange = async function () {
      var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
      try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
        if (tx) { ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx;
          status.textContent = dd.used_vision_ocr ? "✓ Lexuar me OCR" : "✓ Dokumenti u lexua"; } }
      catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
    };
    run.onclick = async function () {
      var text = (ta.value || "").trim();
      if (text.length < 30) { status.textContent = "Ngjit aktin."; return; }
      run.disabled = true; status.textContent = "Inspektori po e sulmon aktin… (~2-3 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/inspect", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text, case_id: activeCaseId || "" }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        var gauge = _riskGauge(d.risk, d.verdict);
        result.innerHTML = gauge + '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(result, "notary", "Ispektim akti", (gauge ? ("Indeksi i rrezikut: " + d.risk + "/100 — " + (d.verdict || "") + "\n\n") : "") + (d.markdown || ""));
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  async function openExtract() {
    var ov = document.getElementById("ext-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "ext-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>📸 Lexo & mbush</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Bashkëngjit ose ngjit një ose disa dokumente (ID, certifikatë pronësie/ASHK, ekstrakt QKB, akt i mëparshëm…). Nxjerr të dhënat e strukturuara — VETËM ato që gjenden, pa shpikur — dhe i çon direkt te bozza e aktit.</div>' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit PDF/foto<input type="file" class="ext-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden multiple></label></div>' +
      '<textarea class="ac-ta" placeholder="Ose ngjit këtu tekstin e dokumentit/dokumenteve…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Nxirr të dhënat →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result"),
        file = ov.querySelector(".ext-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (file) file.onchange = async function () {
      var files = file.files ? [].slice.call(file.files) : []; if (!files.length) return;
      run.disabled = true;
      for (var i = 0; i < files.length; i++) {
        try { var dd = await _extractFileText(files[i], status); var tx = (dd.text || "").trim();
          if (tx) ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + tx) : tx; }
        catch (e) { status.textContent = "Gabim: " + e.message; }
      }
      status.textContent = "✓ " + files.length + " dokument(e) u lexuan"; run.disabled = false; file.value = "";
    };
    run.onclick = async function () {
      var text = (ta.value || "").trim();
      if (text.length < 20) { status.textContent = "Bashkëngjit ose ngjit dokumentin."; return; }
      run.disabled = true; status.textContent = "Po nxjerr të dhënat… (~1-2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/extract", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        var extracted = d.markdown || "";
        result.innerHTML = '<div class="fd-out"></div>';
        result.querySelector(".fd-out").innerHTML = renderMarkdown(extracted);
        var go = document.createElement("button");
        go.className = "ac-run"; go.type = "button"; go.style.marginTop = "12px";
        go.textContent = "📄 Vazhdo në draft me këto të dhëna →";
        go.onclick = function () {
          var mode = localStorage.getItem("sa_mode") || (document.body && document.body.dataset ? document.body.dataset.profession : "") || "noter";
          var fn = mode === "prokuror" ? openIndictment : (mode === "avokat" ? openFableDraft : openNotaryDeed);
          close();
          setTimeout(function () {
            fn();
            setTimeout(function () {
              var ovs = document.querySelectorAll(".ac-overlay");
              var last = ovs[ovs.length - 1];
              var t = last && last.querySelector(".ac-ta");
              if (t && !t.value) { t.value = extracted; try { t.focus(); } catch (e) {} }
            }, 140);
          }, 10);
        };
        result.appendChild(go);
        var cpx = document.createElement("button"); cpx.className = "fd-copy"; cpx.type = "button"; cpx.textContent = "📋 Kopjo të dhënat";
        cpx.onclick = function () { navigator.clipboard.writeText(extracted).then(function () { cpx.textContent = "✓ U kopjua"; }).catch(function () {}); };
        result.appendChild(cpx);
        _addSaveToCase(result, "notary", "Të dhëna të nxjerra", extracted);
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function _compGauge(pct) {
    if (pct === null || pct === undefined) return "";
    var lvl = pct >= 80 ? "ok" : (pct >= 50 ? "warn" : "danger");
    var word = pct >= 80 ? "I plotë" : (pct >= 50 ? "I pjesshëm" : "I paplotë");
    return '<div class="isp-gauge isp-' + lvl + '">' +
      '<div class="isp-num">' + pct + '<span>/100</span></div>' +
      '<div class="isp-bar"><i style="width:' + pct + '%"></i></div>' +
      '<div class="isp-cap">Plotësia e fashikullit · <b>' + word + '</b></div></div>';
  }

  async function openChecklist() {
    var ov = document.getElementById("ck-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "ck-ov"; ov.className = "ac-overlay";
    var hasCase = !!activeCaseId;
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>✅ Checklist i fashikullit</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Shkruaj llojin e aktit dhe jep dokumentet (bashkëngjit/ngjit, ose përdor fashikullin e rastit). Kontrollohet çfarë ËSHTË, çfarë MUNGON dhe çfarë ka SKADUAR, me një indeks plotësie.</div>' +
      '<input type="text" class="ac-ta ck-act" style="min-height:auto;height:40px" placeholder="Lloji i aktit — p.sh. Kontratë shitje apartamenti" />' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit PDF/foto<input type="file" class="ck-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden multiple></label>' +
      (hasCase ? '<label class="ck-dossier"><input type="checkbox" class="ck-usecase" checked> Përdor dokumentet e rastit</label>' : '') + '</div>' +
      '<textarea class="ac-ta ck-docs" placeholder="Ose ngjit tekstin e dokumenteve…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Kontrollo fashikullin →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var actIn = ov.querySelector(".ck-act"), docs = ov.querySelector(".ck-docs"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result"), file = ov.querySelector(".ck-file"),
        useCase = ov.querySelector(".ck-usecase");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (file) file.onchange = async function () {
      var files = file.files ? [].slice.call(file.files) : []; if (!files.length) return;
      run.disabled = true; if (useCase) useCase.checked = false;
      for (var i = 0; i < files.length; i++) {
        try { var dd = await _extractFileText(files[i], status); var tx = (dd.text || "").trim();
          if (tx) docs.value = docs.value.trim() ? (docs.value.trim() + "\n\n" + tx) : tx; } catch (e) {}
      }
      status.textContent = "✓ " + files.length + " dokument(e) u lexuan"; run.disabled = false; file.value = "";
    };
    run.onclick = async function () {
      var act = (actIn.value || "").trim();
      if (act.length < 3) { status.textContent = "Shkruaj llojin e aktit."; return; }
      var text = (docs.value || "").trim();
      var payload = { act: act };
      if (text) payload.text = text;
      else if (useCase && useCase.checked && activeCaseId) payload.case_id = activeCaseId;
      else { status.textContent = "Jep dokumentet ose zgjidh fashikullin e rastit."; return; }
      run.disabled = true; status.textContent = "Po kontrolloj fashikullin… (~1-2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/checklist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error === "documents_required" ? "Nuk ka dokumente — bashkëngjit ose hap një rast me dokumente." : (d.error || ("HTTP " + r.status)));
        status.textContent = "";
        result.innerHTML = _compGauge(d.completeness) + '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        _addSaveToCase(result, "notary", "Checklist: " + act, (d.completeness != null ? ("Plotësia: " + d.completeness + "/100\n\n") : "") + (d.markdown || ""));
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { actIn.focus(); }, 50);
  }

  async function openClientComm() {
    var ov = document.getElementById("cc-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "cc-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🗣️ Për klientin</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Zgjidh: shpjego aktin me fjalë të thjeshta për klientin, ose gjenero një email gati për dërgim. Ngjit aktin ose kontekstin.</div>' +
      '<select class="fd-kind cc-kind"></select>' +
      '<textarea class="ac-ta" placeholder="Ngjit aktin (për shpjegimin) ose kontekstin (lloji akti, emri klientit, çfarë duhet, data)…"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Gjenero →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var kind = ov.querySelector(".cc-kind"), ta = ov.querySelector(".ac-ta"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    var kinds = [];
    try { var r = await fetch("/api/notary/client-kinds"); if (r.ok) kinds = (await r.json()).kinds || []; } catch (e) {}
    kind.innerHTML = kinds.map(function (k) { return '<option value="' + k.key + '">' + escapeHtml(k.label) + '</option>'; }).join("");
    run.onclick = async function () {
      var text = (ta.value || "").trim();
      if (text.length < 10) { status.textContent = "Ngjit aktin ose kontekstin."; return; }
      run.disabled = true; status.textContent = "Po gjeneroj… (~1-2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/client", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: kind.value, text: text }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        var copy = document.createElement("button"); copy.className = "fd-copy"; copy.type = "button"; copy.textContent = "📋 Kopjo";
        copy.onclick = function () { navigator.clipboard.writeText(d.markdown || "").then(function () { copy.textContent = "✓ U kopjua"; }).catch(function () {}); };
        result.appendChild(copy);
        _addSaveToCase(result, "notary", (kind.options[kind.selectedIndex] ? kind.options[kind.selectedIndex].text : "Për klientin"), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  async function openRegistry() {
    var ov = document.getElementById("reg-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "reg-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>🔎 Regjistri i akteve</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="exp-body">' +
        '<div class="exp-sub">Kërko me KUPTIM te aktet e ruajtura të studios — jo vetëm fjalët. P.sh. “dhurime me uzufrukt”, “ku shfaqet pasuria 7/512”, “aktet e Arben Dodës”, “shitjet e 2024”.</div>' +
        '<input type="text" class="research-search reg-q" placeholder="🔎 Shkruaj pyetjen…" />' +
        '<div class="ac-row"><button class="ac-run reg-run" type="button">Kërko →</button><span class="ac-status reg-st"></span></div>' +
        '<div class="ac-result reg-res"></div>' +
      '</div></div>';
    document.body.appendChild(ov);
    var q = ov.querySelector(".reg-q"), run = ov.querySelector(".reg-run"),
        status = ov.querySelector(".reg-st"), result = ov.querySelector(".reg-res");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    async function go() {
      var query = (q.value || "").trim();
      if (query.length < 2) { status.textContent = "Shkruaj pyetjen."; return; }
      run.disabled = true; status.textContent = "Po kërkoj në regjistër… (~1 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/registry/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        result.querySelector(".fd-out").innerHTML = renderMarkdown(d.markdown || "");
        var matches = d.matches || [];
        if (matches.length) {
          var ul = document.createElement("ul"); ul.className = "research-list"; ul.style.marginTop = "12px";
          matches.forEach(function (it) {
            var li = document.createElement("li"); li.className = "research-item";
            var head = document.createElement("div"); head.className = "research-head";
            head.innerHTML = '<span class="research-src">' + escapeHtml(_srcLabel(it.source)) + '</span>' +
              (it.client_name ? '<span class="research-cli">👤 ' + escapeHtml(it.client_name) + '</span>' : "") +
              '<span class="research-ttl">' + escapeHtml(it.title || "") + '</span>' +
              (it.created_at ? '<span class="research-cli">' + escapeHtml(String(it.created_at).slice(0, 10)) + '</span>' : "");
            var body = document.createElement("div"); body.className = "research-body"; body.hidden = true;
            head.addEventListener("click", function () {
              if (body.hidden) { body.innerHTML = renderMarkdown(it.content || ""); body.hidden = false; } else body.hidden = true;
            });
            li.appendChild(head); li.appendChild(body); ul.appendChild(li);
          });
          result.appendChild(ul);
        }
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    }
    run.onclick = go;
    q.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); go(); } });
    setTimeout(function () { q.focus(); }, 50);
  }

  async function openWhatIf() {
    var ov = document.getElementById("wi-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "wi-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal">' +
      '<div class="ac-head"><span>🔮 Çka nëse… (simulator)</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="ac-sub">Jep aktin aktual dhe një ndryshim që po mendon. Simulohen efektet juridike, tatimet/tarifat (tregues), rreziqet e reja, dokumentet shtesë dhe pasojat në të ardhmen.</div>' +
      '<div class="ac-attach-row"><label class="ac-attach">📎 Bashkëngjit aktin (PDF/foto)<input type="file" class="wi-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.docx" hidden></label></div>' +
      '<textarea class="ac-ta wi-act" placeholder="Akti aktual — ngjit tekstin ose parametrat kryesorë…"></textarea>' +
      '<textarea class="ac-ta wi-change" style="min-height:70px" placeholder="Ndryshimi që po mendon — p.sh. “Çka nëse shtoj një uzufrukt për shitësin?” ose “Çka nëse çmimi bëhet 3M në vend të 5M?”"></textarea>' +
      '<div class="ac-row"><button class="ac-run" type="button">Simulo →</button><span class="ac-status"></span></div>' +
      '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var actTa = ov.querySelector(".wi-act"), changeTa = ov.querySelector(".wi-change"),
        run = ov.querySelector(".ac-run"), status = ov.querySelector(".ac-status"),
        result = ov.querySelector(".ac-result"), file = ov.querySelector(".wi-file");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    if (file) file.onchange = async function () {
      var f = file.files && file.files[0]; if (!f) return; run.disabled = true;
      try { var dd = await _extractFileText(f, status); var tx = (dd.text || "").trim();
        if (tx) { actTa.value = actTa.value.trim() ? (actTa.value.trim() + "\n\n" + tx) : tx;
          status.textContent = "✓ Dokumenti u lexua"; } }
      catch (e) { status.textContent = "Gabim: " + e.message; } finally { run.disabled = false; file.value = ""; }
    };
    run.onclick = async function () {
      var act = (actTa.value || "").trim(), change = (changeTa.value || "").trim();
      if (act.length < 15) { status.textContent = "Jep aktin aktual."; return; }
      if (change.length < 4) { status.textContent = "Shkruaj ndryshimin që po mendon."; return; }
      run.disabled = true; status.textContent = "Po simuloj impaktin… (~2 min)"; result.innerHTML = "";
      try {
        var r = await fetch("/api/notary/whatif", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ act: act, change: change }) });
        var d = await r.json();
        if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = "";
        result.innerHTML = '<div class="fd-out"></div>';
        var out = result.querySelector(".fd-out");
        out.innerHTML = renderMarkdown(d.markdown || "");
        if (d.citations) highlightNeni(out, buildCitStatusMap(d.citations));
        if (d.citations && d.citations.stats && d.citations.stats.total > 0) result.insertBefore(renderCitationsBadge(d.citations, null), out);
        _addSaveToCase(result, "notary", "Simulim: " + change.slice(0, 60), d.markdown || "");
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    setTimeout(function () { actTa.focus(); }, 50);
  }

  async function openClauses() {
    var ov = document.getElementById("cl-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "cl-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>📚 Klauzolat e studios</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="exp-body">' +
        '<div class="exp-sub">Ruaj klauzolat/formulimet e preferuara të studios. Kur harton një akt ose prokurë, zgjidh “Përdor klauzolat e studios” dhe drafteri i përdor, duke ruajtur stilin tënd.</div>' +
        '<input type="text" class="cl-label" placeholder="Titulli (p.sh. Klauzolë çmimi i paguar)" style="width:100%;box-sizing:border-box;margin-bottom:6px" />' +
        '<input type="text" class="cl-cat" placeholder="Kategoria (opsionale — p.sh. shitje, prokurë, dhurim)" style="width:100%;box-sizing:border-box;margin-bottom:6px" />' +
        '<textarea class="ac-ta cl-content" placeholder="Teksti i klauzolës…"></textarea>' +
        '<div class="ac-row"><button class="ac-run cl-add" type="button">➕ Ruaj klauzolën</button><span class="ac-status cl-st"></span></div>' +
        '<div class="cl-list"><em>Po ngarkoj…</em></div>' +
      '</div></div>';
    document.body.appendChild(ov);
    var label = ov.querySelector(".cl-label"), cat = ov.querySelector(".cl-cat"),
        content = ov.querySelector(".cl-content"), add = ov.querySelector(".cl-add"),
        st = ov.querySelector(".cl-st"), list = ov.querySelector(".cl-list");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    async function load() {
      list.innerHTML = "<em>Po ngarkoj…</em>";
      try {
        var r = await fetch("/api/firm/clauses"); var d = await r.json();
        var cl = d.clauses || [];
        if (!cl.length) { list.innerHTML = '<div class="fk-warn">Ende asnjë klauzolë. Shto të parën lart.</div>'; return; }
        list.innerHTML = "";
        var ul = document.createElement("ul"); ul.className = "research-list";
        cl.forEach(function (c) {
          var li = document.createElement("li"); li.className = "research-item";
          var head = document.createElement("div"); head.className = "research-head";
          head.innerHTML = (c.category ? '<span class="research-src">' + escapeHtml(c.category) + '</span>' : '') +
            '<span class="research-ttl">' + escapeHtml(c.label || "") + '</span>' +
            '<button class="research-del" title="Fshij" type="button">×</button>';
          var body = document.createElement("div"); body.className = "research-body"; body.hidden = true;
          head.addEventListener("click", function (e) {
            if (e.target.classList.contains("research-del")) return;
            if (body.hidden) { body.innerHTML = renderMarkdown(c.content || ""); body.hidden = false; } else body.hidden = true;
          });
          head.querySelector(".research-del").addEventListener("click", async function (e) {
            e.stopPropagation();
            if (!confirm("Fshij këtë klauzolë?")) return;
            try { await fetch("/api/firm/clauses/" + c.id, { method: "DELETE" }); } catch (e2) {}
            load();
          });
          li.appendChild(head); li.appendChild(body); ul.appendChild(li);
        });
        list.appendChild(ul);
      } catch (e) { list.innerHTML = '<div class="fk-warn">Gabim gjatë ngarkimit.</div>'; }
    }
    add.onclick = async function () {
      var lb = (label.value || "").trim(), ct = (content.value || "").trim();
      if (lb.length < 2 || ct.length < 3) { st.textContent = "Jep titullin dhe tekstin."; return; }
      add.disabled = true; st.textContent = "Duke ruajtur…";
      try {
        var r = await fetch("/api/firm/clauses", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: lb, category: (cat.value || "").trim(), content: ct }) });
        if (!r.ok) throw new Error();
        label.value = ""; cat.value = ""; content.value = ""; st.textContent = "✓ U ruajt"; load();
      } catch (e) { st.textContent = "Gabim gjatë ruajtjes."; } finally { add.disabled = false; }
    };
    load();
    setTimeout(function () { label.focus(); }, 50);
  }

  function _barRows(pairs, label) {
    if (!pairs || !pairs.length) return "";
    var max = Math.max.apply(null, pairs.map(function (p) { return p[1]; })) || 1;
    return '<div class="dash-h">' + escapeHtml(label) + '</div>' + pairs.map(function (p) {
      return '<div class="dash-row"><span class="dash-lbl">' + escapeHtml(String(p[0] || "-")) + '</span>' +
        '<span class="dash-track"><i style="width:' + Math.round(p[1] / max * 100) + '%"></i></span>' +
        '<span class="dash-n">' + p[1] + '</span></div>';
    }).join("");
  }

  async function openDashboard() {
    var ov = document.getElementById("dash-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "dash-ov"; ov.className = "ac-overlay";
    ov.innerHTML = '<div class="ac-modal exp-modal">' +
      '<div class="ac-head"><span>📊 Paneli i studios</span><button class="ac-x" type="button" aria-label="Mbyll">×</button></div>' +
      '<div class="exp-body"><div class="dash-body"><em>Po ngarkoj…</em></div></div></div>';
    document.body.appendChild(ov);
    var body = ov.querySelector(".dash-body");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    try {
      var r = await fetch("/api/firm/dashboard"); var d = await r.json();
      var insp = d.inspections || {};
      var srcLabels = { research: "Kërkim", expertise: "Ekspertizë", prosecutor: "Prokuror", notary: "Noter", deadlines: "Afatet" };
      var bySource = (d.by_source || []).map(function (p) { return [srcLabels[p[0]] || p[0], p[1]]; });
      var cards =
        '<div class="dash-cards">' +
          '<div class="dash-card"><div class="dash-num">' + (d.total_acts || 0) + '</div><div class="dash-cap">Akte të ruajtura</div></div>' +
          '<div class="dash-card"><div class="dash-num">' + (d.total_clients || 0) + '</div><div class="dash-cap">Klientë</div></div>' +
          '<div class="dash-card"><div class="dash-num">' + (d.total_clauses || 0) + '</div><div class="dash-cap">Klauzola studios</div></div>' +
          '<div class="dash-card"><div class="dash-num">' + (insp.avg_risk == null ? "—" : insp.avg_risk) + '</div><div class="dash-cap">Rreziku mesatar (Ispektor)</div></div>' +
        '</div>';
      var note = (d.total_acts ? "" : '<div class="fk-warn" style="margin:10px 0">Paneli rritet ndërsa ruan akte me “💾 Ruaj në fashikull” dhe përdor Ispektorin. Tani është bosh.</div>');
      body.innerHTML = cards + note +
        _barRows(bySource, "Sipas llojit") +
        _barRows(d.top_clients, "Klientët më aktivë") +
        _barRows(d.by_month, "Aktiviteti mujor") +
        (insp.count ? ('<div class="dash-h">Ispektor</div><div class="dash-row"><span class="dash-lbl">Inspektime</span><span class="dash-n">' + insp.count + '</span></div><div class="dash-row"><span class="dash-lbl">Me rrezik të lartë (&gt;50)</span><span class="dash-n">' + (insp.high || 0) + '</span></div>') : "");
    } catch (e) { body.innerHTML = '<div class="fk-warn">Nuk u ngarkua paneli.</div>'; }
  }

  // ── i18n (Fase C) — Italian UI for IT sessions ────────────────────────────
  var UI_LANG = (document.body && document.body.dataset ? document.body.dataset.lang : "") || "sq";
  var I18N_IT = {
    tagline: "La battaglia si vince prima di iniziare.",
    codes: "codici", articles: "articoli", calendar: "Calendario",
    my_cases: "I miei casi", new_case: "Nuovo caso",
    wa_reminders: "WhatsApp per i promemoria", email_reminders: "Email per i promemoria", logout: "Esci",
    intake_ai: "Intake cliente (AI)", clients_research: "Clienti & Ricerche",
    composer_hint: "Apri un caso per iniziare la conversazione",
    ask_placeholder: "Scrivi qui la tua domanda\u2026",
    no_cases: "Non hai ancora nessun caso aperto. Clicca \"Nuovo caso\" per iniziare."
  };
  // mode-bar: match the TEXT part (emoji-agnostic); longest keys first.
  var MODEBAR_TXT = [
    ["Super Prokurori", "Super Procuratore"], ["Super Noteri", "Super Notaio"],
    ["Modele Ekspertize", "Modelli di perizia"], ["Fashikulli", "Fascicolo"],
    ["Afatet", "Scadenze"], ["Ligj i gjall\u00eb", "Legge viva"],
    ["Pika e par\u00eb", "Primo contatto"],
    ["Avokat", "Avvocato"], ["Prokuror", "Procuratore"], ["Noter", "Notaio"]
  ];
  var T_IT = {
    "Afatet:": "Scadenze:", "Hap kalendarin": "Apri calendario",
    " sot": " oggi", " n\u00eb 7 dit\u00eb": " in 7 giorni",
    " e skaduar": " scaduta", " t\u00eb skaduara": " scadute",
    "\ud83d\udcbe Ruaj n\u00eb fashikull": "\ud83d\udcbe Salva nel fascicolo",
    "\u2713 U ruajt n\u00eb fashikull": "\u2713 Salvato nel fascicolo",
    "\ud83d\uddc2\ufe0f Shiko t\u00eb ruajturat": "\ud83d\uddc2\ufe0f Vedi i salvati"
  };
  function t(sq) { return (UI_LANG === "it" && T_IT[sq]) ? T_IT[sq] : sq; }

  function tMode(sq) {
    if (UI_LANG !== "it") return sq;
    for (var i = 0; i < MODEBAR_TXT.length; i++) {
      if (sq.indexOf(MODEBAR_TXT[i][0]) >= 0) return sq.replace(MODEBAR_TXT[i][0], MODEBAR_TXT[i][1]);
    }
    return sq;
  }
  function applyStaticI18n(root) {
    if (UI_LANG !== "it") return;
    var r = root || document;
    Array.prototype.forEach.call(r.querySelectorAll("[data-i18n]"), function (el) {
      var k = el.getAttribute("data-i18n"); if (I18N_IT[k]) el.textContent = I18N_IT[k];
    });
    Array.prototype.forEach.call(r.querySelectorAll("[data-i18n-ph]"), function (el) {
      var k = el.getAttribute("data-i18n-ph"); if (I18N_IT[k]) el.setAttribute("placeholder", I18N_IT[k]);
    });
  }
  applyStaticI18n();

  function initModeBar() {
    var bar = document.getElementById("mode-bar");
    if (!bar) return;
    var FN = {
      openExpertise: openExpertise, openProsecutor: openProsecutor,
      openFableDraft: openFableDraft, openDevilConsult: openDevilConsult,
      openAdversary: openAdversary, openNotaryDeed: openNotaryDeed,
      openNotaryCheck: openNotaryCheck, openNotarySuccession: openNotarySuccession,
      openIndictment: openIndictment, openPrescription: openPrescription,
      openNotaryFees: openNotaryFees,
      openProkura: openProkura, openDeclaration: openDeclaration, openDocsChecklist: openDocsChecklist,
      openRevocation: openRevocation, openConflictCheck: openConflictCheck,
      openIntake: openIntake, openFascikull: openFascikull, openAfati: openAfati,
      openProsHub: openProsHub, openNoterHub: openNoterHub, openLivingHub: openLivingHub,
      openProsPlan: openProsPlan, openProsAct: openProsAct, openProsMeasure: openProsMeasure,
      openProsDismissal: openProsDismissal, openProsStress: openProsStress,
      openProsComplaint: openProsComplaint, openProsVictim: openProsVictim,
      openProsAppeal: openProsAppeal, openProsDelay: openProsDelay,
      openAbuzimPolicor: function () { openExpertise("abuzim_policor"); }
    };
    var LABELS = { avokat: "\u2696\ufe0f Avokat", prokuror: "\ud83c\udfdb\ufe0f Prokuror", noter: "\ud83d\udcdc Noter" };
    var TOOLS = {
      avokat: [["\ud83c\udfaf Modele Ekspertize", "openExpertise"], ["\ud83d\uddc2\ufe0f Fashikulli", "openFascikull"], ["\u23f0 Afatet", "openAfati"], ["\ud83d\udfe2 Ligj i gjall\u00eb", "openLivingHub"]],
      prokuror: [["\ud83c\udfdb\ufe0f Super Prokurori", "openProsHub"], ["\ud83d\uddc2\ufe0f Fashikulli", "openFascikull"], ["\u23f0 Afatet", "openAfati"], ["\ud83c\udfaf Modele Ekspertize", "openExpertise"], ["\ud83d\udfe2 Ligj i gjall\u00eb", "openLivingHub"]],
      noter: [["\ud83d\udcdc Super Noteri", "openNoterHub"], ["\ud83d\uddc2\ufe0f Fashikulli", "openFascikull"], ["\ud83d\udfe2 Ligj i gjall\u00eb", "openLivingHub"]]
    };
    var _INTAKE = ["\ud83c\udf99\ufe0f Pika e parë", "openIntake"];
    ["avokat", "prokuror", "noter"].forEach(function (m) { if (TOOLS[m]) TOOLS[m].unshift(_INTAKE); });
    var _isAdmin = (document.body.dataset.admin === "1");
    var owned = _isAdmin ? ["avokat", "prokuror", "noter"]
      : (document.body.dataset.modules || document.body.dataset.profession || "avokat")
          .split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    if (!owned.length) owned = ["avokat"];
    // No free legal chat for users without avokat/prokuror (e.g. noter-only).
    var _canChat = _isAdmin || owned.indexOf("avokat") >= 0 || owned.indexOf("prokuror") >= 0;
    if (!_canChat) {
      var _af = document.getElementById("ask-form"); if (_af) _af.style.display = "none";
      var _ch = document.getElementById("composer-hint"); if (_ch) _ch.textContent = "";
    }
    var prof = (document.body.dataset.profession || "avokat");
    var mode = localStorage.getItem("sa_mode") || prof;
    if (owned.indexOf(mode) < 0) mode = owned[0];
    function render() {
      var chips = ["avokat", "prokuror", "noter"].map(function (m) {
        var ownedM = owned.indexOf(m) >= 0;
        return '<button type="button" class="mode-chip' + (m === mode ? " active" : "") + (ownedM ? "" : " locked") + '" data-mode="' + m + '"' + (ownedM ? "" : ' data-locked="1"') + '>' + tMode(LABELS[m]) + (ownedM ? "" : " \ud83d\udd12") + '</button>';
      }).join("");
      var tools = (TOOLS[mode] || []).map(function (t, i) {
        return '<button type="button" class="mode-tool" data-i="' + i + '">' + tMode(t[0]) + '</button>';
      }).join("");
      bar.innerHTML = '<div class="mode-chips">' + chips + '</div><div class="mode-tools">' + tools + '</div>';
      Array.prototype.forEach.call(bar.querySelectorAll(".mode-chip"), function (b) {
        b.onclick = function () {
          if (b.getAttribute("data-locked")) { if (typeof toast === "function") toast("Ky modul nuk përfshihet në abonimin tuaj. Kontakto studion për ta shtuar.", "warn"); return; }
          mode = b.getAttribute("data-mode"); localStorage.setItem("sa_mode", mode); render();
        };
      });
      Array.prototype.forEach.call(bar.querySelectorAll(".mode-tool"), function (b) {
        b.onclick = function () {
          var t = TOOLS[mode][parseInt(b.getAttribute("data-i"), 10)];
          var fn = t && FN[t[1]];
          if (typeof fn === "function") fn();
        };
      });
    }
    render();
  }

  function openIndictment() {
    _openFableTool({ id: "indict-ov", title: "\ud83d\udcdc Aktakuzë (prokuror)",
      sub: "Përshkruaj faktet. Merr një draft aktakuze të strukturuar (palët, faktet, kualifikimi ligjor, provat, kërkesa), me nene nga korpusi.",
      placeholder: "Përshkruaj faktet e çështjes penale\u2026",
      btn: "Harto aktakuzën \u2192", loading: "Po harton aktakuzën\u2026 (~3-4 min)",
      endpoint: "/api/prosecutor/indictment", payloadKey: "facts", attach: true,
      source: "prosecutor", saveTitle: "Aktakuzë", calendar: true, calendarTitle: "Afat penal" });
  }

  function openPrescription() {
    _openFableTool({ id: "presc-ov", title: "\u23f0 Parashkrimi & afatet",
      sub: "Përshkruaj veprën ose pretendimin DHE datën. Llogaritet afati i parashkrimit (Kodi Penal neni 66 ose Kodi Civil neni 124+), data e skadimit dhe a ka skaduar sot.",
      placeholder: "P.sh. Vjedhje e kryer më 03.01.2020… OSE padi civile për dëm më 10.05.2019\u2026",
      btn: "Llogarit \u2192", loading: "Po llogaris parashkrimin\u2026 (~2-3 min)",
      endpoint: "/api/deadlines/prescription", payloadKey: "facts", attach: false,
      source: "deadlines", saveTitle: "Parashkrimi & afatet", calendar: true });
  }

  function openNotaryFees() {
    var ov = document.getElementById("fees-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "fees-ov"; ov.className = "ac-overlay";
    function inp(id, label, val, hint) {
      return '<label class="fee-lbl">' + label + (hint ? ' <span class="fee-hint">' + hint + '</span>' : '') +
        '<input type="number" id="' + id + '" value="' + val + '" min="0"></label>';
    }
    ov.innerHTML = '<div class="ac-modal fees-modal">' +
      '<div class="ac-head"><span>\ud83e\uddee Llogaritës tarifash & taksash</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
      '<div class="ac-sub">Për shitje/dhurim pasurie të paluajtshme. Tarifat janë të REDAKTUESHME — verifiko vlerat zyrtare aktuale.</div>' +
      '<div class="fee-grid">' +
        inp("fee-val", "Vlera e transaksionit (ALL)", 10000000) +
        inp("fee-m2", "Sipërfaqja (m²)", 80) +
        inp("fee-buy", "Vlera e blerjes (për tatimin mbi fitimin, ALL)", 7000000) +
      '</div>' +
      '<div class="fee-rates"><b>Tarifat (redakto):</b><div class="fee-grid">' +
        inp("fee-tm2", "Taksa e kalimit — ndërtesë (ALL/m²)", 1000, "Tiranë banim ~1000, tregtar ~2000") +
        inp("fee-gain", "Tatimi mbi fitimin (%)", 15, "5% me rivlerësim deri 31.12.2026") +
        inp("fee-reg", "Regjistrimi ASHK (ALL)", 3500) +
        inp("fee-sub", "Depozitim te ASHK nga noteri (ALL)", 4000) +
      '</div></div>' +
      '<div class="fee-result"></div>' +
      '<details class="fee-fixed"><summary>Tarifa fikse noteriale (referencë)</summary><ul>' +
        '<li>Prokurë: 3.000 (e posaçme) / 5.000 (e përgjithshme) ALL</li>' +
        '<li>Testament: 8.000 (zyrë) / 10.000 (shtëpi); depozitim 3.000; hapje 5.000</li>' +
        '<li>Hipotekë: 2.000–15.000 sipas kredisë</li>' +
        '<li>Dëshmi trashëgimie: 10.000 (ligjore) / 15.000 (me testament)</li>' +
        '<li>Themelim shoqërie: 20.000 (sh.p.k.) / 30.000 (sh.a.)</li>' +
        '<li>Këmbim: 10.000 · Certifikatë pronësie (ASHK): 1.500</li>' +
      '</ul></details>' +
      '<div class="fee-warn">\u26a0\ufe0f Vlera TREGUESE. Verifiko: paketa fiskale e bashkisë (taksa/m²), VKM \u00e7mimet e referencës (baza s\u2019mund të jetë nën \u00e7mimin e referencës së zonës), tarifat noteriale 2026, dhe TVSH 20% nëse noteri e aplikon.</div>' +
      "</div>";
    document.body.appendChild(ov);
    ov.querySelector(".ac-x").onclick = function () { ov.remove(); };
    ov.addEventListener("click", function (e) { if (e.target === ov) ov.remove(); });
    function num(id) { var v = parseFloat((document.getElementById(id) || {}).value); return isNaN(v) ? 0 : v; }
    function fmt(n) { return Math.round(n).toLocaleString("de-DE") + " ALL"; }
    function scale(v) {
      if (v <= 6000000) return 0.35; if (v <= 15000000) return 0.30;
      if (v <= 50000000) return 0.28; if (v <= 100000000) return 0.25; return 0.23;
    }
    function recompute() {
      var v = num("fee-val"), m2 = num("fee-m2"), buy = num("fee-buy");
      var r = scale(v), notary = v * r / 100;
      var transfer = m2 * num("fee-tm2");
      var gainBase = Math.max(0, v - buy), gainTax = gainBase * num("fee-gain") / 100;
      var reg = num("fee-reg") + num("fee-sub");
      var total = notary + transfer + gainTax + reg;
      document.querySelector("#fees-ov .fee-result").innerHTML =
        '<table class="fee-tbl">' +
        '<tr><td>Tarifa noteriale (' + r + '% e vlerës)</td><td>' + fmt(notary) + '</td></tr>' +
        '<tr><td>Taksa e kalimit (' + m2 + ' m² × ' + fmt(num("fee-tm2")).replace(" ALL", "") + ')</td><td>' + fmt(transfer) + '</td></tr>' +
        '<tr><td>Tatimi mbi fitimin (' + num("fee-gain") + '% × ' + fmt(gainBase).replace(" ALL", "") + ')</td><td>' + fmt(gainTax) + '</td></tr>' +
        '<tr><td>Regjistrim + depozitim (ASHK)</td><td>' + fmt(reg) + '</td></tr>' +
        '<tr class="fee-total"><td><b>TOTALI</b></td><td><b>' + fmt(total) + '</b></td></tr>' +
        '</table>';
    }
    Array.prototype.forEach.call(ov.querySelectorAll("input"), function (i) { i.addEventListener("input", recompute); });
    recompute();
  }

  function _addToCalendar(container, title, md) {
    if (!container) return;
    var wrap = document.createElement("div");
    wrap.className = "cal-wrap";
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "cal-btn";
    btn.innerHTML = "\ud83d\udcc5 Shto afatin n\u00eb kalendar";
    var form = document.createElement("div");
    form.className = "cal-form"; form.hidden = true;
    // best-effort: pull the last DD.MM.YYYY from the analysis as a default
    var guess = "";
    var dates = (md || "").match(/(\d{1,2})[.\/](\d{1,2})[.\/](20\d{2})/g);
    if (dates && dates.length) {
      var p = dates[dates.length - 1].split(/[.\/]/);
      guess = p[2] + "-" + ("0" + p[1]).slice(-2) + "-" + ("0" + p[0]).slice(-2);
    }
    form.innerHTML =
      '<label class="cal-lbl">Data e afatit<input type="date" class="cal-date" value="' + guess + '"></label>' +
      '<label class="cal-lbl">Titulli<input type="text" class="cal-title" value="' + escapeHtml(title) + '"></label>' +
      '<div class="cal-row"><button type="button" class="cal-save">Ruaj n\u00eb kalendar</button><span class="cal-status"></span></div>' +
      '<div class="cal-hint">\u2713 Verifiko dat\u00ebn nga analiza para se ta ruash. Do t\u00eb marr\u00ebsh alarm 30, 7 dhe 1 dit\u00eb para.</div>';
    btn.addEventListener("click", function () { form.hidden = !form.hidden; });
    wrap.appendChild(btn); wrap.appendChild(form); container.appendChild(wrap);
    form.querySelector(".cal-save").addEventListener("click", async function () {
      var st = form.querySelector(".cal-status");
      if (!activeCaseId) { st.textContent = "Hap ose krijo nj\u00eb rast q\u00eb ta ruash."; return; }
      var d = form.querySelector(".cal-date").value;
      var t = (form.querySelector(".cal-title").value || "Afat").trim();
      if (!d) { st.textContent = "Zgjidh dat\u00ebn e afatit."; return; }
      st.textContent = "Duke ruajtur\u2026";
      try {
        var r = await fetch("/api/events", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: t, kind: "afat", starts_at: d + "T09:00:00",
            case_id: activeCaseId, reminders: [43200, 10080, 1440] }),
        });
        if (!r.ok) { var e = await r.json().catch(function () { return {}; }); throw new Error(e.error || ("HTTP " + r.status)); }
        st.textContent = "\u2713 U shtua n\u00eb kalendar (me alarm 30/7/1 dit\u00eb para)";
      } catch (e) { st.textContent = "Gabim: " + e.message; }
    });
  }

  function openActCheck() {
    var ov = document.getElementById("actcheck-ov");
    if (ov) ov.remove();
    ov = document.createElement("div");
    ov.id = "actcheck-ov"; ov.className = "ac-overlay";
    ov.innerHTML =
      '<div class="ac-modal">' +
        '<div class="ac-head"><span>\ud83d\udee1\ufe0f Kontroll cilësie i aktit</span><button class="ac-x" type="button" aria-label="Mbyll">\u00d7</button></div>' +
        '<div class="ac-sub">Ngjit tekstin e aktit (padi, ankim, memorie, kontratë). Verifikohen nenet e cituara: inekzistente, të shfuqizuara ose të paqarta \u2014 para depozitimit.</div>' +
        '<div class="ac-attach-row"><label class="ac-attach">\ud83d\udcce Bashkëngjit PDF/foto<input type="file" class="ac-file" accept=".pdf,.jpg,.jpeg,.png,.webp,.svg,.tif,.tiff" hidden></label><span class="ac-attach-hint">ose ngjit tekstin poshtë</span></div>' +
        '<textarea class="ac-ta" placeholder="Ngjit këtu tekstin e aktit\u2026"></textarea>' +
        '<div class="ac-row"><button class="ac-run" type="button">Kontrollo aktin</button><span class="ac-status"></span></div>' +
        '<div class="ac-result"></div>' +
      "</div>";
    document.body.appendChild(ov);
    var ta = ov.querySelector(".ac-ta"), run = ov.querySelector(".ac-run"),
        status = ov.querySelector(".ac-status"), result = ov.querySelector(".ac-result");
    function close() { ov.remove(); }
    ov.querySelector(".ac-x").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    run.onclick = async function () {
      var txt = (ta.value || "").trim();
      if (txt.length < 10) { status.textContent = "Ngjit tekstin e aktit."; return; }
      run.disabled = true; status.textContent = "Po verifikoj nenet\u2026"; result.innerHTML = "";
      try {
        var r = await fetch("/api/act-check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: txt }) });
        var d = await r.json();
        if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
        status.textContent = ""; result.innerHTML = _renderActReport(d);
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; }
    };
    var acFile = ov.querySelector(".ac-file");
    if (acFile) acFile.onchange = async function () {
      var file = acFile.files && acFile.files[0];
      if (!file) return;
      run.disabled = true;
      try {
        var d = await _extractFileText(file, status);
        var t = (d.text || "").trim();
        if (!t) { status.textContent = "Dokumenti nuk ka tekst të lexueshëm."; }
        else {
          ta.value = ta.value.trim() ? (ta.value.trim() + "\n\n" + t) : t;
          status.textContent = d.used_vision_ocr ? "\u2713 Lexuar me OCR \u2014 kontrollo tekstin" : "\u2713 Dokumenti u lexua";
        }
      } catch (e) { status.textContent = "Gabim: " + e.message; }
      finally { run.disabled = false; acFile.value = ""; }
    };
    setTimeout(function () { ta.focus(); }, 50);
  }

  function openProModal(key) {
    const m = PRO_MODALS[key];
    if (!m) return;
    m.hidden = false;
    document.body.style.overflow = "hidden";
    if (key === "draft") ensureDraftTypes();
    if (key === "clients") loadClientsForCase();
    if (key === "contract") loadContractHistory();
    if (key === "money") loadMoneyForCase();
    if (key === "genio") initGenio();
    if (key === "precedent") initPrecedent();
    if (key === "settlement") initSettlement();
    if (key === "financial") initFinancial();
    if (key === "corporate") initCorporate();
    if (key === "bench") initBench();
    if (key === "coach") initCoach();
  }
  function closeProModal(m) {
    m.hidden = true;
    const anyOpen = Object.values(PRO_MODALS).some(x => x && !x.hidden);
    if (!anyOpen) document.body.style.overflow = "";
  }

  // menu toggle
  proMenuBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    const expanded = proMenuBtn.getAttribute("aria-expanded") === "true";
    proMenuBtn.setAttribute("aria-expanded", expanded ? "false" : "true");
    if (!expanded) _gateProMenu();
    proMenu.hidden = expanded;
  });
  document.getElementById("pro-menu-close")?.addEventListener("click", (e) => {
    e.stopPropagation();
    proMenu.hidden = true;
    proMenuBtn.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("click", (e) => {
    if (!proMenu || proMenu.hidden) return;
    if (proMenu.contains(e.target) || proMenuBtn.contains(e.target)) return;
    proMenu.hidden = true;
    proMenuBtn.setAttribute("aria-expanded", "false");
  });
  proMenu?.querySelectorAll("[data-pro]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-pro");
      proMenu.hidden = true;
      proMenuBtn.setAttribute("aria-expanded", "false");
      if (key === "actcheck") { openActCheck(); }
      else if (key === "hubpros") { openProsHub(); }
      else if (key === "hubnoter") { openNoterHub(); }
      else if (key === "hublive") { openLivingHub(); }
      else if (key === "inspekt") { openIspektor(); }
      else if (key === "lexombush") { openExtract(); }
      else if (key === "regjistri") { openRegistry(); }
      else if (key === "cklist") { openChecklist(); }
      else if (key === "whatif") { openWhatIf(); }
      else if (key === "klauzolat") { openClauses(); }
      else if (key === "intake") { openIntake(); }
      else if (key === "fascikull") { openFascikull(); }
      else if (key === "afati") { openAfati(); }
      else if (key === "expertise") { openExpertise(); }
      else if (key === "prosecutor") { openProsecutor(); }
      else if (key === "indictment") { openIndictment(); }
      else if (key === "prosplan") { openProsPlan(); }
      else if (key === "prosact") { openProsAct(); }
      else if (key === "prosmeasure") { openProsMeasure(); }
      else if (key === "prosdismiss") { openProsDismissal(); }
      else if (key === "prosstress") { openProsStress(); }
      else if (key === "proscomplaint") { openProsComplaint(); }
      else if (key === "prosvictim") { openProsVictim(); }
      else if (key === "prosappeal") { openProsAppeal(); }
      else if (key === "prosdelay") { openProsDelay(); }
      else if (key === "prescription") { openPrescription(); }
      else if (key === "notaryprokura") { openProkura(); }
      else if (key === "notarydecl") { openDeclaration(); }
      else if (key === "notarydocs") { openDocsChecklist(); }
      else if (key === "notaryrevoke") { openRevocation(); }
      else if (key === "notaryconflict") { openConflictCheck(); }
      else if (key === "notarydeed") { openNotaryDeed(); }
      else if (key === "notarycheck") { openNotaryCheck(); }
      else if (key === "notarysucc") { openNotarySuccession(); }
      else if (key === "notaryfees") { openNotaryFees(); }
      else if (key === "fabledraft") { openFableDraft(); }
      else if (key === "devilconsult") { openDevilConsult(); }
      else if (key === "adversary") { openAdversary(); }
      else { openProModal(key); }
    });
  });
  // modal close wiring (backdrop + × button)
  Object.values(PRO_MODALS).forEach((m) => {
    if (!m) return;
    m.querySelectorAll("[data-close]").forEach((el) => {
      el.addEventListener("click", () => closeProModal(m));
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    Object.values(PRO_MODALS).forEach((m) => {
      if (m && !m.hidden) closeProModal(m);
    });
  });

  // ── ① RED TEAM (stress-test single + adversarial loop) ───────────
  const stressInput = document.getElementById("stress-hypothesis");
  const stressRun = document.getElementById("stress-run");
  const stressStatus = document.getElementById("stress-status");
  const stressResult = document.getElementById("stress-result");
  const stressRoundsField = document.getElementById("stress-rounds-field");
  const stressRoundsSel = document.getElementById("stress-rounds");
  let stressMode = "single";

  document.querySelectorAll("[data-stress-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      stressMode = btn.dataset.stressMode;
      document.querySelectorAll("[data-stress-mode]").forEach((b) => {
        const on = b === btn;
        b.classList.toggle("pro-seg-active", on);
        b.setAttribute("aria-selected", on ? "true" : "false");
      });
      if (stressRoundsField) stressRoundsField.hidden = stressMode !== "loop";
      stressRun.textContent = stressMode === "loop"
        ? "⚔️ Nis betejën multi-raund →"
        : "Lësho stres-testin →";
    });
  });

  stressRun?.addEventListener("click", async () => {
    if (!activeCaseId) {
      stressStatus.textContent = "Hap një rast së pari.";
      stressStatus.className = "pro-status error";
      return;
    }
    const text = (stressInput.value || "").trim();
    const minLen = stressMode === "loop" ? 30 : 20;
    if (text.length < minLen) {
      stressStatus.textContent = `Shkruaj të paktën ${minLen} karaktere.`;
      stressStatus.className = "pro-status error";
      return;
    }
    stressRun.disabled = true;
    stressResult.hidden = true;
    stressStatus.className = "pro-status";

    try {
      if (stressMode === "loop") {
        const rounds = parseInt(stressRoundsSel?.value || "5", 10);
        stressStatus.textContent = `⚔️ Po fillon beteja — ${rounds} raunde (~${rounds} min)...`;
        const r = await fetch(`/api/cases/${activeCaseId}/adversarial`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hypothesis: text, max_rounds: rounds }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        renderAdversarialInto(stressResult, data.result);
        stressResult.hidden = false;
        const summary = data.result.summary || {};
        stressStatus.textContent = `✓ ${data.result.round_count} raunde · verdikti: ${summary.verdict_likelihood || "?"}`;
        stressStatus.className = "pro-status ok";
        toast("Beteja përfundoi.", "success");
      } else {
        stressStatus.textContent = "Po stres-teston… (~60s)";
        const resp = await fetch(`/api/cases/${activeCaseId}/stress-test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ hypothesis: text }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        renderStressResult(data.result);
        stressStatus.textContent = "Gati ✓";
        stressStatus.className = "pro-status ok";
        toast("Stres-testi u ruajt në rastin", "ok");
      }
    } catch (err) {
      stressStatus.textContent = "Gabim: " + err.message;
      stressStatus.className = "pro-status error";
    } finally {
      stressRun.disabled = false;
    }
  });

  function renderStressResult(r) {
    if (!r) return;
    const score = r.score || {};
    const weaknessesHtml = (r.weaknesses || []).map(w => `
      <div class="weakness-row">
        <div class="row-head">
          <strong>${escapeHtml(w.point || "")}</strong>
          <span class="sev-badge sev-${escapeHtml(w.severity || "medium")}">${escapeHtml(w.type || "")} · ${escapeHtml(w.severity || "")}</span>
        </div>
        ${w.why_it_hurts ? `<div class="notes">${escapeHtml(w.why_it_hurts)}</div>` : ""}
      </div>`).join("");
    const xexHtml = (r.cross_examination || []).map((q, i) => `
      <div class="question-row">
        <strong>#${i+1} · ${escapeHtml(q.target || "")}</strong>
        <p>“${escapeHtml(q.q || "")}”</p>
        ${q.trap ? `<div class="notes"><em>Kurthi:</em> ${escapeHtml(q.trap)}</div>` : ""}
      </div>`).join("");
    const objHtml = (r.procedural_objections || []).map(o => `
      <div class="cascade-row">
        <div class="row-head">
          <strong>${escapeHtml(o.objection || "")}</strong>
          <span class="status-badge status-${escapeHtml(o.timing || "")}">${escapeHtml(o.timing || "")}</span>
        </div>
        ${o.article ? `<span class="citation">${escapeHtml(o.article)}</span>` : ""}
      </div>`).join("");
    const advHtml = (r.adverse_jurisprudence || []).map(a => `
      <div class="audit-row">
        <div class="row-head"><strong>${escapeHtml(a.cite || "")}</strong></div>
        <div class="note">${escapeHtml(a.how_it_hurts || "")}</div>
      </div>`).join("");
    const judgesHtml = (r.judges_questions || []).map(q =>
      `<li>${escapeHtml(q)}</li>`).join("");

    stressResult.innerHTML = `
      <div class="score-block">
        <div class="score-num">${score.winnability != null ? score.winnability : "—"}<small>/100</small></div>
        <div>
          <div class="score-label">Shanset e fitimit · risk ${escapeHtml(score.risk_level || "—")}</div>
          <div class="score-summary">${escapeHtml(score.verdict_summary || "")}</div>
        </div>
      </div>
      ${r.counter_brief ? `<div class="pro-section"><h4>Memorie e kundërshtarit</h4><p>${escapeHtml(r.counter_brief).replace(/\n/g,"<br>")}</p></div>` : ""}
      ${weaknessesHtml ? `<div class="pro-section"><h4>Dobësitë e rastit tënd</h4>${weaknessesHtml}</div>` : ""}
      ${xexHtml ? `<div class="pro-section"><h4>Kryq-pyetja — ${(r.cross_examination||[]).length} pyetje</h4>${xexHtml}</div>` : ""}
      ${objHtml ? `<div class="pro-section"><h4>Kundërshtime procedurale</h4>${objHtml}</div>` : ""}
      ${advHtml ? `<div class="pro-section"><h4>Jurisprudencë e kundërt</h4>${advHtml}</div>` : ""}
      ${judgesHtml ? `<div class="pro-section"><h4>Pyetje që do bëjë gjykatësi</h4><ul>${judgesHtml}</ul></div>` : ""}
    `;
    stressResult.hidden = false;
  }

  // ── ② AUDIT ─────────────────────────────────────────────────────
  const auditInput = document.getElementById("audit-source");
  const auditRun = document.getElementById("audit-run");
  const auditStatus = document.getElementById("audit-status");
  const auditResult = document.getElementById("audit-result");

  auditRun?.addEventListener("click", async () => {
    const text = (auditInput.value || "").trim();
    if (text.length < 40) {
      auditStatus.textContent = "Teksti është shumë i shkurtër (min 40 karaktere).";
      auditStatus.className = "pro-status error";
      return;
    }
    auditRun.disabled = true;
    auditStatus.textContent = "Po auditon citimet…";
    auditStatus.className = "pro-status";
    auditResult.hidden = true;
    try {
      const body = { text };
      if (activeCaseId) body.case_id = activeCaseId;
      const resp = await fetch("/api/citation-audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      renderAuditResult(data.result);
      auditStatus.textContent = "Gati ✓";
      auditStatus.className = "pro-status ok";
    } catch (err) {
      auditStatus.textContent = "Gabim: " + err.message;
      auditStatus.className = "pro-status error";
    } finally {
      auditRun.disabled = false;
    }
  });

  function renderAuditResult(r) {
    if (!r) return;
    const sum = r.summary || {};
    const findings = r.findings || [];
    const rows = findings.map(f => `
      <div class="audit-row">
        <div class="row-head">
          <strong>${escapeHtml(f.citation_text || "")}</strong>
          <span class="status-badge status-${escapeHtml(f.status || "unclear")}">${escapeHtml(f.status || "unclear")}</span>
        </div>
        ${f.verdict ? `<div class="note">${escapeHtml(f.verdict)}</div>` : ""}
        ${f.correct_version ? `<div class="note"><em>Versioni i saktë:</em> ${escapeHtml(f.correct_version)}</div>` : ""}
        ${f.note ? `<div class="note">${escapeHtml(f.note)}</div>` : ""}
      </div>`).join("");
    auditResult.innerHTML = `
      <div class="score-block">
        <div class="score-num">${sum.correct != null ? sum.correct : "—"}<small> / ${sum.total || 0}</small></div>
        <div>
          <div class="score-label">Citime të sakta</div>
          <div class="score-summary">${escapeHtml(sum.overall_verdict || "")}</div>
        </div>
      </div>
      <div class="pro-section"><h4>Gjetjet (${findings.length})</h4>${rows || "<p>Asnjë citim i gjendur në tekst.</p>"}</div>
    `;
    auditResult.hidden = false;
  }

  // ── ③ DRAFT ─────────────────────────────────────────────────────
  const draftSelect = document.getElementById("draft-type");
  const draftInput = document.getElementById("draft-brief");
  const draftRun = document.getElementById("draft-run");
  const draftStatus = document.getElementById("draft-status");
  const draftResult = document.getElementById("draft-result");

  let draftTypesLoaded = false;
  async function ensureDraftTypes() {
    if (draftTypesLoaded) return;
    // Jinja pre-populates the options server-side; only fetch if the select
    // arrived empty (e.g. rendered before pro_features wiring was in place).
    if (draftSelect && draftSelect.options.length > 0) {
      draftTypesLoaded = true;
      return;
    }
    try {
      const resp = await fetch("/api/act-types");
      if (!resp.ok) { console.warn("act-types fetch failed:", resp.status); return; }
      const data = await resp.json();
      draftSelect.innerHTML = (data.items || []).map(t =>
        `<option value="${escapeHtml(t.key)}">${escapeHtml(t.label)}</option>`).join("");
      draftTypesLoaded = true;
    } catch (e) { console.warn("act-types fetch error:", e); }
  }

  draftRun?.addEventListener("click", async () => {
    const actType = draftSelect.value;
    const brief = (draftInput.value || "").trim();
    if (!actType) {
      draftStatus.textContent = "Zgjidh një lloj akti.";
      draftStatus.className = "pro-status error";
      return;
    }
    if (brief.length < 50) {
      draftStatus.textContent = "Përshkrimi është shumë i shkurtër (min 50 karaktere).";
      draftStatus.className = "pro-status error";
      return;
    }
    draftRun.disabled = true;
    draftStatus.textContent = "Po harton aktin… (mund të zgjasë deri në 2 min)";
    draftStatus.className = "pro-status";
    draftResult.hidden = true;
    try {
      const body = { act_type: actType, brief };
      if (activeCaseId) body.case_id = activeCaseId;
      const resp = await fetch("/api/draft-act", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      renderDraftResult(data);
      draftStatus.textContent = "Gati ✓";
      draftStatus.className = "pro-status ok";
      toast("Akti u hartua", "ok");
    } catch (err) {
      draftStatus.textContent = "Gabim: " + err.message;
      draftStatus.className = "pro-status error";
    } finally {
      draftRun.disabled = false;
    }
  });

  function renderDraftResult(data) {
    const d = data.draft || {};
    const cited = (d.cited_articles || []).map(a =>
      `<li>${escapeHtml(a.citation || (a.code + " nr. " + a.number))}</li>`).join("");
    const petitum = (d.petitum || []).map(p => `<li>${escapeHtml(p)}</li>`).join("");
    const warnings = (d.warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join("");
    draftResult.innerHTML = `
      <div class="score-block">
        <div class="score-num" style="font-size:22px;">📄</div>
        <div>
          <div class="score-label">${escapeHtml(d.title || "AKT")}</div>
          <div class="score-summary">${escapeHtml(d.court || "")} · ${escapeHtml(d.subject_matter || "")}</div>
        </div>
        <a class="secondary" style="padding:10px 14px;border-radius:10px;text-decoration:none;background:var(--gold-soft);color:var(--ink);border:1px solid var(--gold);" href="/api/draft-act/${encodeURIComponent(data.id)}/docx">⬇ .docx</a>
      </div>
      ${petitum ? `<div class="pro-section"><h4>KËRKOJMË (petitum)</h4><ol>${petitum}</ol></div>` : ""}
      <div class="pro-section"><h4>Teksti i aktit</h4><div class="draft-body">${escapeHtml(d.body_markdown || "").replace(/\n/g,"<br>")}</div></div>
      ${cited ? `<div class="pro-section"><h4>Bazë ligjore</h4><ul>${cited}</ul></div>` : ""}
      ${warnings ? `<div class="pro-section"><h4>⚠ Verifiko para depozitimit</h4><ul>${warnings}</ul></div>` : ""}
    `;
    draftResult.hidden = false;
  }

  // ── ④ CASCADE ───────────────────────────────────────────────────
  const cascadeTypeSel = document.getElementById("cascade-event-type");
  const cascadeDate = document.getElementById("cascade-event-date");
  const cascadeCompute = document.getElementById("cascade-compute");
  const cascadeSchedule = document.getElementById("cascade-schedule");
  const cascadeStatus = document.getElementById("cascade-status");
  const cascadeResult = document.getElementById("cascade-result");
  let cascadeLoaded = false;
  let cascadeLast = null;

  function setCascadeDefaultDate() {
    if (!cascadeDate || cascadeDate.value) return;
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth()+1).padStart(2,"0");
    const dd = String(today.getDate()).padStart(2,"0");
    cascadeDate.value = `${yyyy}-${mm}-${dd}`;
  }

  async function ensureCascadeTypes() {
    if (cascadeLoaded) return;
    setCascadeDefaultDate();
    if (cascadeTypeSel && cascadeTypeSel.options.length > 0) {
      cascadeLoaded = true;
      return;
    }
    try {
      const resp = await fetch("/api/cascade/event-types");
      if (!resp.ok) { console.warn("cascade event-types fetch failed:", resp.status); return; }
      const data = await resp.json();
      cascadeTypeSel.innerHTML = (data.items || []).map(t =>
        `<option value="${escapeHtml(t.key)}">${escapeHtml(t.label)}</option>`).join("");
      cascadeLoaded = true;
    } catch (e) { console.warn("cascade event-types fetch error:", e); }
  }

  cascadeCompute?.addEventListener("click", async () => {
    const eventType = cascadeTypeSel.value;
    const eventDate = cascadeDate.value;
    if (!eventType || !eventDate) {
      cascadeStatus.textContent = "Plotëso të dy fushat.";
      cascadeStatus.className = "pro-status error";
      return;
    }
    cascadeCompute.disabled = true;
    cascadeStatus.textContent = "Po llogarit…";
    cascadeStatus.className = "pro-status";
    try {
      const resp = await fetch("/api/cascade/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: eventType, event_date: eventDate }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      cascadeLast = data;
      renderCascade(data);
      cascadeSchedule.hidden = false;
      cascadeStatus.textContent = "Gati ✓";
      cascadeStatus.className = "pro-status ok";
    } catch (err) {
      cascadeStatus.textContent = "Gabim: " + err.message;
      cascadeStatus.className = "pro-status error";
    } finally {
      cascadeCompute.disabled = false;
    }
  });

  cascadeSchedule?.addEventListener("click", async () => {
    if (!cascadeLast) return;
    cascadeSchedule.disabled = true;
    try {
      const body = {
        event_type: cascadeLast.event_type,
        event_date: cascadeLast.event_date,
      };
      if (activeCaseId) body.case_id = activeCaseId;
      const resp = await fetch("/api/cascade/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      toast(`U shtuan ${data.events_created || 0} afate në kalendar`, "ok");
      cascadeSchedule.disabled = false;
      refreshBadge();
    } catch (err) {
      toast("Gabim: " + err.message, "error");
      cascadeSchedule.disabled = false;
    }
  });

  function renderCascade(data) {
    const rows = (data.derived_deadlines || []).map(d => `
      <div class="cascade-row">
        <div class="row-head">
          <strong>${escapeHtml(d.label)}</strong>
          <span class="status-badge status-${escapeHtml(d.status)}">${d.days_left < 0 ? "kaluar" : d.days_left === 0 ? "sot" : d.days_left + " ditë"}</span>
        </div>
        <div class="row-head">
          <span class="citation">${escapeHtml(d.citation)}</span>
          <span class="sev-badge sev-${escapeHtml(d.urgency)}">${escapeHtml(d.urgency)}</span>
        </div>
        <div class="notes"><strong>Afati:</strong> ${escapeHtml(d.due_date)} (+${d.days} ${d.counting === "business" ? "ditë pune" : "ditë kalendarike"}) · <em>${escapeHtml(d.notes || "")}</em></div>
      </div>`).join("");
    cascadeResult.innerHTML = `
      <div class="pro-section"><h4>${escapeHtml(data.event_label)} — ${escapeHtml(data.event_date)}</h4>${rows || "<p>Asnjë afat i derivuar.</p>"}</div>
    `;
    cascadeResult.hidden = false;
  }

  // ══════════════════════════════════════════════════════════════════
  //  V7.12 ⑤ — TIMELINE DEL FASCICOLO
  // ══════════════════════════════════════════════════════════════════

  const timelineBuild = document.getElementById("timeline-build");
  const timelineDelete = document.getElementById("timeline-delete");
  const timelineStatus = document.getElementById("timeline-status");
  const timelineResult = document.getElementById("timeline-result");

  // When the modal opens we lazily fetch any existing timeline.
  async function loadTimelineForCase() {
    if (!activeCaseId) {
      timelineStatus.textContent = "Hap një rast së pari.";
      timelineStatus.className = "pro-status error";
      timelineResult.hidden = true;
      timelineDelete.hidden = true;
      return;
    }
    timelineStatus.textContent = "Po lexoj...";
    timelineStatus.className = "pro-status";
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/timeline`);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      if (data.result) {
        renderCaseTimelineModal(data.result, data.updated_at);
        timelineStatus.textContent = `E rifreskuar: ${formatTimeAgo(data.updated_at)}`;
        timelineStatus.className = "pro-status ok";
        timelineDelete.hidden = false;
      } else {
        timelineStatus.textContent = "Nuk ka linjë kohore — kliko për ta ndërtuar.";
        timelineStatus.className = "pro-status";
        timelineResult.hidden = true;
        timelineDelete.hidden = true;
      }
    } catch (e) {
      console.warn("timeline load failed:", e);
      timelineStatus.textContent = "Nuk u ngarkua — provo ndërto.";
      timelineStatus.className = "pro-status error";
    }
  }

  timelineBuild?.addEventListener("click", async () => {
    if (!activeCaseId) {
      timelineStatus.textContent = "Hap një rast së pari.";
      timelineStatus.className = "pro-status error";
      return;
    }
    timelineBuild.disabled = true;
    timelineStatus.textContent = "🔄 Po lexoj dokumentet dhe ndërtoj kronologjinë (~60-120s)...";
    timelineStatus.className = "pro-status";
    timelineResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/timeline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "HTTP " + r.status);
      renderCaseTimelineModal(data.result, data.updated_at);
      timelineStatus.textContent = `✓ ${data.result.event_count} ngjarje · ${(data.result.contradictions || []).length} kontradikta · ${(data.result.gaps || []).length} boshllëqe`;
      timelineStatus.className = "pro-status ok";
      timelineDelete.hidden = false;
      toast("Linja kohore u ndërtua.", "success");
    } catch (err) {
      timelineStatus.textContent = "Gabim: " + err.message;
      timelineStatus.className = "pro-status error";
    } finally {
      timelineBuild.disabled = false;
    }
  });

  timelineDelete?.addEventListener("click", async () => {
    if (!activeCaseId) return;
    if (!confirm("Fshi linjën kohore aktuale?")) return;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/timeline`, { method: "DELETE" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      timelineResult.hidden = true;
      timelineDelete.hidden = true;
      timelineStatus.textContent = "U fshi.";
      timelineStatus.className = "pro-status";
    } catch (e) {
      timelineStatus.textContent = "Gabim: " + e.message;
      timelineStatus.className = "pro-status error";
    }
  });

  function formatTimeAgo(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (!t) return iso;
    const sec = Math.max(1, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s më parë`;
    if (sec < 3600) return `${Math.floor(sec/60)}m më parë`;
    if (sec < 86400) return `${Math.floor(sec/3600)}h më parë`;
    return new Date(iso).toLocaleDateString("sq-AL");
  }

  function renderCaseTimelineModal(result, updatedAt) {
    const events = result.events || [];
    const contradictions = result.contradictions || [];
    const gaps = result.gaps || [];
    const summary = result.summary || "";

    const eventsHtml = events.map((e, i) => {
      const typeIcon = {
        njoftim: "📨", kontrate: "✍️", pushim: "🚪", pagese: "💰",
        mesazh: "💬", seance: "⚖️", demti: "🩹", vendim: "📜", tjeter: "•",
      }[e.type] || "•";
      const partiesHtml = (e.parties || []).map(p =>
        `<span class="tl-party">${escapeHtml(p)}</span>`).join("");
      const confBadge = e.date_confidence !== "exact"
        ? `<span class="tl-conf">${escapeHtml(e.date_confidence)}</span>` : "";
      return `
        <div class="tl-event" data-i="${i}">
          <div class="tl-dot tl-dot-${escapeHtml(e.type || "tjeter")}"></div>
          <div class="tl-card">
            <div class="tl-card-head">
              <span class="tl-date">${escapeHtml(e.date || "?")}${e.time ? " · " + escapeHtml(e.time) : ""}</span>
              ${confBadge}
              <span class="tl-icon">${typeIcon}</span>
            </div>
            <div class="tl-summary">${escapeHtml(e.summary || "")}</div>
            ${partiesHtml ? `<div class="tl-parties">${partiesHtml}</div>` : ""}
            ${e.legal_significance ? `<div class="tl-sig"><strong>Rëndësia:</strong> ${escapeHtml(e.legal_significance)}</div>` : ""}
            <div class="tl-source">📎 <em>${escapeHtml(e.source_doc || "?")}</em>${e.source_excerpt ? ` — "${escapeHtml(e.source_excerpt)}"` : ""}</div>
          </div>
        </div>`;
    }).join("");

    const contraHtml = contradictions.length ? `
      <div class="pro-section tl-contra">
        <h4>⚠️ Kontradikta (${contradictions.length})</h4>
        ${contradictions.map(c => `
          <div class="tl-contra-row">
            <div class="tl-contra-issue">
              <strong>${escapeHtml(c.issue || "")}</strong>
              <span class="sev-badge sev-${escapeHtml(c.severity || "medium")}">${escapeHtml(c.severity || "")}</span>
            </div>
            <ul>${(c.claims || []).map(cl =>
              `<li><code>${escapeHtml(cl.value || "")}</code> ← ${escapeHtml(cl.source || "")}</li>`).join("")}</ul>
            ${c.tactical_note ? `<p><em>Taktika:</em> ${escapeHtml(c.tactical_note)}</p>` : ""}
          </div>`).join("")}
      </div>` : "";

    const gapsHtml = gaps.length ? `
      <div class="pro-section tl-gaps">
        <h4>🕳️ Boshllëqe kohore (${gaps.length})</h4>
        ${gaps.map(g => `
          <div class="tl-gap-row">
            <strong>${escapeHtml(g.from || "?")} → ${escapeHtml(g.to || "?")}</strong>
            <span class="tl-gap-days">${g.duration_days || "?"} ditë</span>
            <p>${escapeHtml(g.concern || "")}</p>
          </div>`).join("")}
      </div>` : "";

    const summaryHtml = summary ? `
      <div class="pro-section tl-summary-box">
        <h4>📖 Përmbledhja</h4>
        <p>${escapeHtml(summary)}</p>
      </div>` : "";

    const meta = `
      <div class="tl-meta">
        ${result.event_count || 0} ngjarje · ${result.doc_count || 0} dokumente ·
        rifreskuar ${formatTimeAgo(updatedAt || result.generated_at)}
      </div>`;

    timelineResult.innerHTML = `
      ${meta}
      ${summaryHtml}
      ${contraHtml}
      ${gapsHtml}
      <div class="pro-section">
        <h4>📅 Kronologjia</h4>
        <div class="timeline-track">
          ${eventsHtml || "<p>Asnjë ngjarje e identifikuar.</p>"}
        </div>
      </div>
    `;
    timelineResult.hidden = false;
  }

  // ══════════════════════════════════════════════════════════════════
  //  V7.12 ⑥ — ADVERSARIAL LOOP (multi-round red team)
  // ══════════════════════════════════════════════════════════════════

  const adversarialHyp = document.getElementById("adversarial-hypothesis");
  const adversarialRoundsSel = document.getElementById("adversarial-rounds");
  const adversarialRun = document.getElementById("adversarial-run");
  const adversarialStatus = document.getElementById("adversarial-status");
  const adversarialResult = document.getElementById("adversarial-result");

  adversarialRun?.addEventListener("click", async () => {
    if (!activeCaseId) {
      adversarialStatus.textContent = "Hap një rast së pari.";
      adversarialStatus.className = "pro-status error";
      return;
    }
    const hyp = (adversarialHyp.value || "").trim();
    if (hyp.length < 30) {
      adversarialStatus.textContent = "Hipoteza është shumë e shkurtër (min 30 karaktere).";
      adversarialStatus.className = "pro-status error";
      return;
    }
    const rounds = parseInt(adversarialRoundsSel.value || "5", 10);
    adversarialRun.disabled = true;
    adversarialStatus.textContent = `⚔️ Po fillon beteja — ${rounds} raunde të planifikuara (~${rounds}min)...`;
    adversarialStatus.className = "pro-status";
    adversarialResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/adversarial`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hypothesis: hyp, max_rounds: rounds }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "HTTP " + r.status);
      renderAdversarial(data.result);
      const summary = data.result.summary || {};
      adversarialStatus.textContent = `✓ ${data.result.round_count} raunde · verdikti: ${summary.verdict_likelihood || "?"}`;
      adversarialStatus.className = "pro-status ok";
      toast("Beteja përfundoi.", "success");
    } catch (err) {
      adversarialStatus.textContent = "Gabim: " + err.message;
      adversarialStatus.className = "pro-status error";
    } finally {
      adversarialRun.disabled = false;
    }
  });

  function renderAdversarial(result) {
    const rounds = result.rounds || [];
    const summary = result.summary || {};
    const verdict = summary.verdict_likelihood || "uncertain";
    const verdictColor = {
      favorable: "ok", uncertain: "warning", unfavorable: "error",
    }[verdict] || "warning";

    const summaryHtml = `
      <div class="score-block">
        <div>
          <div class="score-label">Verdikti i pritur</div>
          <div class="score-num"><small>${escapeHtml(verdict)}</small></div>
        </div>
        <div class="score-summary">${escapeHtml(summary.key_takeaway || "")}</div>
        <div class="score-label">${rounds.length} raunde</div>
      </div>
      <div class="pro-section">
        <h4>🎯 Strategjia finale</h4>
        <p>${escapeHtml(summary.final_strategy || "")}</p>
      </div>
      ${(summary.ranked_action_items || []).length ? `
      <div class="pro-section">
        <h4>📋 Veprimet me prioritet</h4>
        <ol>${(summary.ranked_action_items || []).map(a =>
          `<li><strong>${escapeHtml(a.action || "")}</strong>${a.deadline_relative ? ` <em>(${escapeHtml(a.deadline_relative)})</em>` : ""}</li>`
        ).join("")}</ol>
      </div>` : ""}
      ${(summary.fortified_positions || []).length ? `
      <div class="pro-section">
        <h4>🛡️ Pozicionet e fortifikuara</h4>
        <ul>${(summary.fortified_positions || []).map(p => `<li>${escapeHtml(p)}</li>`).join("")}</ul>
      </div>` : ""}
      ${(summary.remaining_vulnerabilities || []).length ? `
      <div class="pro-section tl-contra">
        <h4>⚠️ Dobësi të mbetura</h4>
        <ul>${(summary.remaining_vulnerabilities || []).map(v => `<li>${escapeHtml(v)}</li>`).join("")}</ul>
      </div>` : ""}
    `;

    const roundsHtml = rounds.map(r => {
      const atk = r.attack || {};
      const dfn = r.defense || {};
      const conv = r.converged ? `<span class="tl-conf" style="color:var(--green)">konvergjuar</span>` : "";
      return `
        <details class="adv-round">
          <summary>
            <span class="adv-round-num">Raundi ${r.round}</span>
            <span class="adv-round-thesis">⚔️ ${escapeHtml(atk.attack_thesis || "")}</span>
            <span class="sev-badge sev-${escapeHtml(atk.risk_to_lawyer || "medium")}">${escapeHtml(atk.risk_to_lawyer || "")}</span>
            ${conv}
          </summary>
          <div class="adv-round-body">
            <div class="adv-side adv-attack">
              <h5>⚔️ Sulmi (${escapeHtml(atk.attack_type || "")})</h5>
              <p>${escapeHtml(atk.attack_argumentation || "")}</p>
              ${(atk.cited_articles || []).length ? `<div class="adv-cites">${atk.cited_articles.map(c => `<code>${escapeHtml(c)}</code>`).join(" · ")}</div>` : ""}
              ${atk.if_unanswered ? `<p class="adv-warn"><strong>Nëse nuk përgjigjet:</strong> ${escapeHtml(atk.if_unanswered)}</p>` : ""}
            </div>
            ${dfn.defense_thesis ? `
            <div class="adv-side adv-defense">
              <h5>🛡️ Mbrojtja</h5>
              <p><strong>${escapeHtml(dfn.defense_thesis)}</strong></p>
              <p>${escapeHtml(dfn.defense_argumentation || "")}</p>
              ${(dfn.cited_articles || []).length ? `<div class="adv-cites">${dfn.cited_articles.map(c => `<code>${escapeHtml(c)}</code>`).join(" · ")}</div>` : ""}
              ${dfn.concession ? `<p class="adv-concession"><em>Pranojmë:</em> ${escapeHtml(dfn.concession)}</p>` : ""}
              ${dfn.remaining_weakness ? `<p class="adv-warn"><em>Mbetet:</em> ${escapeHtml(dfn.remaining_weakness)}</p>` : ""}
            </div>` : `<div class="adv-side"><em>Pa kundërpërgjigje (konvergjuar).</em></div>`}
          </div>
        </details>`;
    }).join("");

    const html = `
      ${summaryHtml}
      <div class="pro-section">
        <h4>🥊 Raundet (${rounds.length})</h4>
        <div class="adv-rounds">${roundsHtml || "<p>Asnjë raund.</p>"}</div>
      </div>
    `;
    const target = renderAdversarial._target || adversarialResult;
    if (!target) return;
    target.innerHTML = html;
    target.hidden = false;
    renderAdversarial._target = null;
  }
  function renderAdversarialInto(container, result) {
    renderAdversarial._target = container;
    renderAdversarial(result);
  }

  // ── ⑦ STRATEGY COMPASS ───────────────────────────────────────────
  const strategyObjective = document.getElementById("strategy-objective");
  const strategyRun = document.getElementById("strategy-run");
  const strategyStatus = document.getElementById("strategy-status");
  const strategyResult = document.getElementById("strategy-result");

  strategyRun?.addEventListener("click", async () => {
    if (!activeCaseId) {
      strategyStatus.textContent = "Hap një rast së pari.";
      strategyStatus.className = "pro-status error";
      return;
    }
    const objective = (strategyObjective?.value || "").trim();
    if (objective.length < 10) {
      strategyStatus.textContent = "Shkruaj objektivin (min. 10 karaktere).";
      strategyStatus.className = "pro-status error";
      return;
    }
    strategyStatus.textContent = "🧭 Po ndërtohet pema e vendimeve…";
    strategyStatus.className = "pro-status loading";
    strategyRun.disabled = true;
    strategyResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/strategy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      renderStrategyCompass(data.result);
      const meta = data.result.meta || {};
      strategyStatus.textContent = `✓ ${meta.node_count || "?"} nyje · thellësi ${meta.depth ?? "?"}`;
      strategyStatus.className = "pro-status ok";
      toast("Pema u gjenerua.", "success");
    } catch (e) {
      strategyStatus.textContent = `❌ ${e.message}`;
      strategyStatus.className = "pro-status error";
    } finally {
      strategyRun.disabled = false;
    }
  });

  function renderStrategyCompass(result) {
    const root = result.root || {};
    const branches = result.branches || [];
    const recommendedPath = new Set(result.recommended_path || []);
    const insights = result.key_insights || [];
    const warnings = result.warnings || [];

    const childrenOf = {};
    branches.forEach((b) => {
      const pid = b.parent_id;
      if (!childrenOf[pid]) childrenOf[pid] = [];
      childrenOf[pid].push(b);
    });

    function pct(p) {
      if (typeof p !== "number") return "—";
      return `${Math.round(p * 100)}%`;
    }
    function probColor(p) {
      if (typeof p !== "number") return "neutral";
      if (p >= 0.65) return "ok";
      if (p >= 0.4) return "warning";
      return "error";
    }

    function renderNode(node, depth = 0) {
      const onPath = recommendedPath.has(node.id);
      const dead = node.is_dead_end;
      const recommended = node.is_recommended;
      const cls = [
        "compass-node",
        `compass-type-${escapeHtml(node.type || "decision")}`,
        onPath ? "compass-on-path" : "",
        dead ? "compass-dead" : "",
        recommended ? "compass-recommended" : "",
      ].filter(Boolean).join(" ");

      const pills = [];
      if (typeof node.probability_success === "number") {
        pills.push(`<span class="compass-pill compass-pill-${probColor(node.probability_success)}">📊 ${pct(node.probability_success)}</span>`);
      }
      if (node.estimated_cost_alm) {
        pills.push(`<span class="compass-pill">💰 ${escapeHtml(node.estimated_cost_alm)} L</span>`);
      }
      if (node.estimated_duration) {
        pills.push(`<span class="compass-pill">⏱ ${escapeHtml(node.estimated_duration)}</span>`);
      }
      if (recommended) {
        pills.push(`<span class="compass-pill compass-pill-ok">⭐ Rekomanduar</span>`);
      }
      if (dead) {
        pills.push(`<span class="compass-pill compass-pill-error">🚫 Rrugë pa krye</span>`);
      }

      const prosCons = (node.pros?.length || node.cons?.length) ? `
        <div class="compass-pros-cons">
          ${(node.pros || []).length ? `<div class="compass-pros"><strong>+</strong> ${node.pros.map(escapeHtml).join(" · ")}</div>` : ""}
          ${(node.cons || []).length ? `<div class="compass-cons"><strong>−</strong> ${node.cons.map(escapeHtml).join(" · ")}</div>` : ""}
        </div>
      ` : "";

      const basis = (node.legal_basis || []).length ? `
        <div class="compass-basis">${node.legal_basis.map(b => `<code>${escapeHtml(b)}</code>`).join(" · ")}</div>
      ` : "";

      const kids = childrenOf[node.id] || [];
      const kidsHtml = kids.length ? `
        <div class="compass-children">
          ${kids.map(k => renderNode(k, depth + 1)).join("")}
        </div>
      ` : "";

      return `
        <div class="${cls}" data-node-id="${escapeHtml(node.id)}">
          <div class="compass-node-card">
            <div class="compass-node-label">${escapeHtml(node.label || "")}</div>
            ${node.description ? `<p class="compass-node-desc">${escapeHtml(node.description)}</p>` : ""}
            ${pills.length ? `<div class="compass-pills">${pills.join("")}</div>` : ""}
            ${prosCons}
            ${basis}
          </div>
          ${kidsHtml}
        </div>
      `;
    }

    const treeHtml = root.id ? renderNode(root) : "<p>Pa rrënjë.</p>";
    const insightsHtml = insights.length ? `
      <div class="pro-section">
        <h4>💡 Mësime kyçe</h4>
        <ul>${insights.map(i => `<li>${escapeHtml(i)}</li>`).join("")}</ul>
      </div>` : "";
    const warningsHtml = warnings.length ? `
      <div class="pro-section tl-contra">
        <h4>⚠️ Paralajmërime</h4>
        <ul>${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul>
      </div>` : "";
    const pathHtml = (result.recommended_path || []).length ? `
      <div class="pro-section">
        <h4>⭐ Rruga e rekomanduar</h4>
        <div class="compass-path">${result.recommended_path.map(id => `<code>${escapeHtml(id)}</code>`).join(" → ")}</div>
      </div>` : "";

    strategyResult.innerHTML = `
      <div class="pro-section">
        <h4>🎯 Objektivi</h4>
        <p>${escapeHtml(result.objective || "")}</p>
      </div>
      ${pathHtml}
      <div class="pro-section">
        <h4>🧭 Pema e vendimeve</h4>
        <div class="compass-tree">${treeHtml}</div>
      </div>
      ${insightsHtml}
      ${warningsHtml}
    `;
    strategyResult.hidden = false;
  }

  // ─── studio (firm admin) ────────────────────────────────────────
  const studioBtn       = document.getElementById("studio-btn");
  const studioModal     = document.getElementById("studio-modal");
  const studioFirmName  = document.getElementById("studio-firm-name");
  const studioFirmMeta  = document.getElementById("studio-firm-meta");
  const studioSwitcher  = document.getElementById("studio-firm-switcher");
  const studioCreateBtn = document.getElementById("studio-create-btn");
  const studioMembersBody = document.getElementById("studio-members-body");
  const studioInvite    = document.getElementById("studio-invite");
  const studioInviteUsername = document.getElementById("studio-invite-username");
  const studioInviteRole = document.getElementById("studio-invite-role");
  const studioInviteBtn = document.getElementById("studio-invite-btn");
  const studioInviteStatus = document.getElementById("studio-invite-status");

  let studioState = { firm: null, members: [], role: null, permissions: {}, available_roles: [] };

  function openStudioModal() {
    if (!studioModal) return;
    studioModal.hidden = false;
    document.body.style.overflow = "hidden";
    loadStudio();
  }
  function closeStudioModal() {
    if (!studioModal) return;
    studioModal.hidden = true;
    document.body.style.overflow = "";
  }

  studioBtn?.addEventListener("click", openStudioModal);
  studioModal?.querySelectorAll("[data-close]").forEach((el) =>
    el.addEventListener("click", closeStudioModal),
  );

  async function loadStudio() {
    try {
      const [firmResp, listResp] = await Promise.all([
        fetch("/api/firm"),
        fetch("/api/firm/list"),
      ]);
      const firm = await firmResp.json();
      const list = await listResp.json();
      studioState = firm;
      renderStudioFirmHead(firm, list);
      renderStudioMembers(firm);
      renderStudioInvite(firm);
      renderCapacity(firm);
      loadReviewQueue();
    } catch (e) {
      studioMembersBody.innerHTML = `<tr><td colspan="4" class="studio-empty">Gabim: ${escapeHtml(e.message || "ngarkimi dështoi")}</td></tr>`;
    }
  }

  async function renderCapacity(firm) {
    const section = document.getElementById("capacity-section");
    const body = document.getElementById("capacity-body");
    const canSeeAll = !!(firm.permissions && firm.permissions.all_cases);
    const isShared = firm.firm && !firm.firm.is_personal;
    if (!section) return;
    if (!canSeeAll || !isShared) { section.hidden = true; return; }
    section.hidden = false;
    body.innerHTML = `<tr><td colspan="5" class="studio-empty">Duke llogaritur…</td></tr>`;
    try {
      const r = await fetch("/api/firm/capacity?days=7");
      if (!r.ok) { section.hidden = true; return; }
      const data = await r.json();
      if (!data.members.length) {
        body.innerHTML = `<tr><td colspan="5" class="studio-empty">Asnjë anëtar.</td></tr>`;
        return;
      }
      const maxScore = Math.max(...data.members.map(m => m.load_score), 1);
      body.innerHTML = data.members.map((m) => {
        const pct = Math.round((m.load_score / maxScore) * 100);
        const heat = pct >= 75 ? "high" : pct >= 40 ? "mid" : "low";
        return `<tr>
          <td>
            <strong>${escapeHtml(m.username)}</strong>
            <span class="capacity-role">${escapeHtml(m.role_label)}</span>
          </td>
          <td class="capacity-num">${m.active_cases}</td>
          <td class="capacity-num">${m.upcoming_hearings}</td>
          <td class="capacity-num">${m.urgent_deadlines}</td>
          <td>
            <div class="capacity-bar capacity-${heat}">
              <div class="capacity-fill" style="width:${pct}%"></div>
              <span class="capacity-bar-label">${m.load_score}</span>
            </div>
          </td>
        </tr>`;
      }).join("");
    } catch {
      section.hidden = true;
    }
  }

  function renderStudioFirmHead(firm, list) {
    if (!firm.firm) {
      studioFirmName.textContent = "—";
      studioFirmMeta.textContent = "Nuk ke ende një studio aktive.";
      studioSwitcher.innerHTML = "";
      return;
    }
    studioFirmName.textContent = firm.firm.name;
    const tags = [];
    if (firm.firm.is_personal) tags.push("personal");
    if (firm.role_label) tags.push(firm.role_label);
    studioFirmMeta.textContent = tags.length ? `· ${tags.join(" · ")}` : "";
    // Switcher
    studioSwitcher.innerHTML = "";
    (list.firms || []).forEach((f) => {
      const opt = document.createElement("option");
      opt.value = String(f.id);
      opt.textContent = f.name + (f.is_personal ? " (personal)" : "");
      if (f.id === list.active_firm_id) opt.selected = true;
      studioSwitcher.appendChild(opt);
    });
  }

  studioSwitcher?.addEventListener("change", async () => {
    const fid = parseInt(studioSwitcher.value, 10);
    if (!Number.isFinite(fid)) return;
    const r = await fetch("/api/firm/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firm_id: fid }),
    });
    if (r.ok) {
      toast("Studio u ndryshua", "ok");
      await loadStudio();
      await renderCaseList();
    } else {
      const err = await r.json().catch(() => ({}));
      toast(err.error || "Ndryshimi dështoi", "error");
    }
  });

  studioCreateBtn?.addEventListener("click", async () => {
    const name = prompt("Emri i studios së re:");
    if (!name || !name.trim()) return;
    const r = await fetch("/api/firm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    if (r.ok) {
      toast("Studio u krijua", "ok");
      await loadStudio();
      await renderCaseList();
    } else {
      const err = await r.json().catch(() => ({}));
      toast(err.error || "Krijimi dështoi", "error");
    }
  });

  function renderStudioMembers(firm) {
    const canManage = !!(firm.permissions && firm.permissions.manage_members);
    const rows = (firm.members || []).map((m) => {
      const isOwner = m.role === "owner";
      const roleSelect = canManage && !isOwner
        ? `<select class="studio-select studio-role-edit" data-member-id="${m.id}">
             ${(firm.available_roles || []).map((r) =>
               `<option value="${r.key}"${r.key === m.role ? " selected" : ""}>${escapeHtml(r.label)}</option>`).join("")}
           </select>`
        : `<span class="studio-role-badge studio-role-${escapeHtml(m.role)}">${escapeHtml(m.role_label || m.role)}</span>`;
      const removeBtn = canManage && !isOwner
        ? `<button type="button" class="studio-remove" data-member-id="${m.id}" title="Largo nga studio">×</button>`
        : "";
      return `<tr>
        <td><strong>${escapeHtml(m.username)}</strong></td>
        <td>${roleSelect}</td>
        <td><span class="studio-joined">${escapeHtml(m.joined_at.slice(0, 10))}</span></td>
        <td>${removeBtn}</td>
      </tr>`;
    }).join("");
    studioMembersBody.innerHTML = rows || `<tr><td colspan="4" class="studio-empty">Asnjë anëtar ende.</td></tr>`;

    // Wire role-edit selects
    studioMembersBody.querySelectorAll(".studio-role-edit").forEach((sel) => {
      sel.addEventListener("change", async () => {
        const mid = sel.dataset.memberId;
        const r = await fetch(`/api/firm/members/${mid}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: sel.value }),
        });
        if (r.ok) {
          toast("Roli u përditësua", "ok");
          await loadStudio();
        } else {
          const err = await r.json().catch(() => ({}));
          toast(err.error || "Ndryshimi i rolit dështoi", "error");
          await loadStudio();
        }
      });
    });
    // Wire remove buttons
    studioMembersBody.querySelectorAll(".studio-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Largoje këtë anëtar nga studio?")) return;
        const mid = btn.dataset.memberId;
        const r = await fetch(`/api/firm/members/${mid}`, { method: "DELETE" });
        if (r.ok) { toast("Anëtari u largua", "ok"); await loadStudio(); }
        else {
          const err = await r.json().catch(() => ({}));
          toast(err.error || "Largimi dështoi", "error");
        }
      });
    });
  }

  function renderStudioInvite(firm) {
    const canManage = !!(firm.permissions && firm.permissions.manage_members);
    studioInvite.hidden = !canManage;
    if (!canManage) return;
    studioInviteRole.innerHTML = (firm.available_roles || []).map((r) =>
      `<option value="${r.key}">${escapeHtml(r.label)}</option>`).join("");
  }

  // ─── review queue + submit-draft (praticante loop) ───────────────
  const reviewQueueEl = document.getElementById("review-queue");
  const reviewBadgeEl = document.getElementById("review-badge");
  const reviewHelpEl = document.getElementById("review-help");
  const draftSubmitKind = document.getElementById("draft-submit-kind");
  const draftSubmitTitleInput = document.getElementById("draft-submit-title-input");
  const draftSubmitContent = document.getElementById("draft-submit-content");
  const draftSubmitBtn = document.getElementById("draft-submit-btn");
  const draftSubmitStatus = document.getElementById("draft-submit-status");

  function prepareDraftSubmit() {
    if (!activeCaseId) {
      draftSubmitStatus.textContent = "Hap një rast së pari.";
      draftSubmitBtn.disabled = true;
      return;
    }
    draftSubmitBtn.disabled = false;
    draftSubmitStatus.textContent = "";
    draftSubmitTitleInput.value = "";
    draftSubmitContent.value = "";
    draftSubmitKind.value = "note";
  }

  draftSubmitBtn?.addEventListener("click", async () => {
    if (!activeCaseId) return;
    const title = draftSubmitTitleInput.value.trim();
    const content = draftSubmitContent.value.trim();
    if (content.length < 10) {
      draftSubmitStatus.textContent = "Përmbajtja shumë e shkurtër (min 10 shkronja).";
      return;
    }
    draftSubmitStatus.textContent = "Duke sotomet…";
    const r = await fetch(`/api/cases/${activeCaseId}/drafts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content, kind: draftSubmitKind.value }),
    });
    if (r.ok) {
      draftSubmitStatus.textContent = "✓ U dërgua për revizion.";
      toast("Bozza u sotomet për revizion", "ok");
      setTimeout(() => closeProModal(draftSubmitModal), 800);
    } else {
      const err = await r.json().catch(() => ({}));
      draftSubmitStatus.textContent = err.error || "Sotomatja dështoi.";
    }
  });

  async function loadReviewQueue() {
    if (!reviewQueueEl) return;
    try {
      const r = await fetch("/api/firm/review-queue?status=pending");
      if (!r.ok) { reviewQueueEl.innerHTML = ""; return; }
      const data = await r.json();
      const drafts = data.drafts || [];
      reviewBadgeEl.textContent = String(drafts.length);
      reviewBadgeEl.hidden = drafts.length === 0;
      if (data.can_review) {
        reviewHelpEl.textContent = drafts.length
          ? `Ti je avokat senior — këto bozza presin aprovimin tënd.`
          : `Asnjë bozzë në pritje. Kur praktikantët sotometojnë, do t'i shohësh këtu.`;
      } else {
        reviewHelpEl.textContent = drafts.length
          ? `Bozzat e tua që presin revizion (${drafts.length}).`
          : `Nuk ke bozza në pritje. Përdor "Sotomet bozzë" nga menuja Pro.`;
      }
      if (!drafts.length) {
        reviewQueueEl.innerHTML = "";
        return;
      }
      reviewQueueEl.innerHTML = drafts.map((d) => `
        <details class="review-card" data-draft-id="${d.id}">
          <summary>
            <span class="review-kind">${escapeHtml(d.kind_label)}</span>
            <strong>${escapeHtml(d.title)}</strong>
            <span class="review-meta">${escapeHtml(d.author_username)} · ${escapeHtml(d.case_title)} · ${escapeHtml(d.created_at.slice(0,10))}</span>
          </summary>
          <div class="review-body">
            <pre class="review-content">${escapeHtml(d.content)}</pre>
            ${data.can_review ? `
              <div class="review-actions">
                <textarea class="review-comment" placeholder="Komente (opsionale)…" rows="2"></textarea>
                <div class="review-action-row">
                  <button type="button" class="review-changes" data-id="${d.id}">↩ Kërko ndryshime</button>
                  <button type="button" class="review-approve primary" data-id="${d.id}">✓ Aprovo</button>
                </div>
              </div>` : `
              <div class="review-actions">
                <p class="pro-modal-sub">Pritet aprovimi.</p>
                <button type="button" class="review-withdraw" data-id="${d.id}">🗑 Tërhiq</button>
              </div>`}
          </div>
        </details>`).join("");
      // Wire actions
      reviewQueueEl.querySelectorAll(".review-approve").forEach((btn) => {
        btn.addEventListener("click", () => reviewAction(btn.dataset.id, "approved"));
      });
      reviewQueueEl.querySelectorAll(".review-changes").forEach((btn) => {
        btn.addEventListener("click", () => reviewAction(btn.dataset.id, "needs_changes"));
      });
      reviewQueueEl.querySelectorAll(".review-withdraw").forEach((btn) => {
        btn.addEventListener("click", () => withdrawDraft(btn.dataset.id));
      });
    } catch {}
  }

  async function reviewAction(draftId, status) {
    const card = reviewQueueEl.querySelector(`[data-draft-id="${draftId}"]`);
    const comment = card?.querySelector(".review-comment")?.value || "";
    const r = await fetch(`/api/drafts/${draftId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, comment }),
    });
    if (r.ok) {
      toast(status === "approved" ? "Bozza u aprovua" : "Komente u dërguan", "ok");
      await loadReviewQueue();
    } else {
      const err = await r.json().catch(() => ({}));
      toast(err.error || "Veprimi dështoi", "error");
    }
  }

  async function withdrawDraft(draftId) {
    if (!confirm("Tërhiqe këtë bozzë?")) return;
    const r = await fetch(`/api/drafts/${draftId}`, { method: "DELETE" });
    if (r.ok) { toast("Bozza u tërhoq", "ok"); await loadReviewQueue(); }
    else { toast("Tërheqja dështoi", "error"); }
  }

  // ─── intake AI ───────────────────────────────────────────────────
  const intakeBtn = document.getElementById("intake-btn");
  const intakeModal = document.getElementById("intake-modal");
  const intakeStepNum = document.getElementById("intake-step-num");
  const intakeProgressHint = document.getElementById("intake-progress-hint");
  const intakeTranscript = document.getElementById("intake-transcript");
  const intakeCurrentBlock = document.getElementById("intake-current-block");
  const intakeCurrentQuestion = document.getElementById("intake-current-question");
  const intakeWhy = document.getElementById("intake-why");
  const intakeAnswer = document.getElementById("intake-answer");
  const intakeNextBtn = document.getElementById("intake-next-btn");
  const intakeSkipBtn = document.getElementById("intake-skip-btn");
  const intakeFinalizeBlock = document.getElementById("intake-finalize-block");
  const intakeFinalizeBtn = document.getElementById("intake-finalize-btn");
  const intakeBackBtn = document.getElementById("intake-back-btn");
  const intakeResultBlock = document.getElementById("intake-result-block");
  const intakeResultSummary = document.getElementById("intake-result-summary");
  const intakeOpenCaseBtn = document.getElementById("intake-open-case-btn");
  const intakeStatus = document.getElementById("intake-status");

  let intakeHistory = [];
  let intakeCurrent = null;     // {question, why}
  let intakeFinalCaseId = null;

  function intakeReset() {
    intakeHistory = [];
    intakeCurrent = null;
    intakeFinalCaseId = null;
    if (intakeTranscript) intakeTranscript.innerHTML = "";
    if (intakeAnswer) intakeAnswer.value = "";
    if (intakeWhy) { intakeWhy.hidden = true; intakeWhy.textContent = ""; }
    if (intakeStatus) intakeStatus.textContent = "";
    if (intakeCurrentBlock) intakeCurrentBlock.hidden = false;
    if (intakeFinalizeBlock) intakeFinalizeBlock.hidden = true;
    if (intakeResultBlock) intakeResultBlock.hidden = true;
    if (intakeStepNum) intakeStepNum.textContent = "Pyetja 1";
    if (intakeProgressHint) intakeProgressHint.textContent = "AI po nis…";
    if (intakeCurrentQuestion) intakeCurrentQuestion.textContent = "Po nis intake-n…";
  }

  function intakeRenderTranscript() {
    if (!intakeTranscript) return;
    intakeTranscript.innerHTML = intakeHistory.map((qa, i) => `
      <div class="intake-qa">
        <div class="intake-qa-q"><span class="intake-qa-num">${i+1}.</span> ${escapeHtml(qa.q)}</div>
        <div class="intake-qa-a">${escapeHtml(qa.a)}</div>
      </div>
    `).join("");
    intakeTranscript.scrollTop = intakeTranscript.scrollHeight;
  }

  async function intakeRequestNext() {
    if (intakeProgressHint) intakeProgressHint.textContent = "AI po mendon…";
    if (intakeNextBtn) intakeNextBtn.disabled = true;
    if (intakeSkipBtn) intakeSkipBtn.disabled = true;
    try {
      const r = await fetch("/api/firm/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "next", history: intakeHistory }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (intakeStatus) intakeStatus.textContent = err.error || "Dështim";
        return;
      }
      const data = await r.json();
      if (data.done) {
        intakeShowFinalize();
        return;
      }
      intakeCurrent = { question: data.question, why: data.why };
      if (intakeCurrentQuestion) intakeCurrentQuestion.textContent = data.question;
      if (intakeWhy) {
        if (data.why) { intakeWhy.textContent = "💡 " + data.why; intakeWhy.hidden = false; }
        else { intakeWhy.hidden = true; }
      }
      if (intakeStepNum) intakeStepNum.textContent = `Pyetja ${data.step || (intakeHistory.length + 1)}`;
      if (intakeProgressHint) intakeProgressHint.textContent = "Përgjigju kur ke të dhënat";
      if (intakeAnswer) { intakeAnswer.value = ""; intakeAnswer.focus(); }
    } catch (e) {
      if (intakeStatus) intakeStatus.textContent = "Gabim rrjeti";
    } finally {
      if (intakeNextBtn) intakeNextBtn.disabled = false;
      if (intakeSkipBtn) intakeSkipBtn.disabled = false;
    }
  }

  function intakeShowFinalize() {
    if (intakeCurrentBlock) intakeCurrentBlock.hidden = true;
    if (intakeFinalizeBlock) intakeFinalizeBlock.hidden = false;
    if (intakeProgressHint) intakeProgressHint.textContent = "Gati për përmbledhje";
  }

  intakeBtn?.addEventListener("click", () => {
    intakeReset();
    openProModal("intake");
    intakeRequestNext();
  });

  function intakeRecordAnswer(answer) {
    if (!intakeCurrent) return;
    intakeHistory.push({ q: intakeCurrent.question, a: answer });
    intakeRenderTranscript();
    intakeCurrent = null;
  }

  intakeNextBtn?.addEventListener("click", () => {
    const ans = (intakeAnswer?.value || "").trim();
    if (!ans) { toast("Shkruaj përgjigjen ose kliko 'Kalo'", "warn"); return; }
    intakeRecordAnswer(ans);
    intakeRequestNext();
  });

  intakeSkipBtn?.addEventListener("click", () => {
    intakeRecordAnswer("(klienti nuk e di)");
    intakeRequestNext();
  });

  intakeBackBtn?.addEventListener("click", () => {
    if (intakeFinalizeBlock) intakeFinalizeBlock.hidden = true;
    if (intakeCurrentBlock) intakeCurrentBlock.hidden = false;
    intakeRequestNext();
  });

  intakeFinalizeBtn?.addEventListener("click", async () => {
    intakeFinalizeBtn.disabled = true;
    if (intakeStatus) intakeStatus.textContent = "AI po prodhon përmbledhjen…";
    try {
      const r = await fetch("/api/firm/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "finalize", history: intakeHistory }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (intakeStatus) intakeStatus.textContent = err.error || "Dështim";
        return;
      }
      const data = await r.json();
      intakeFinalCaseId = data.case_id;
      intakeRenderResult(data.brief, data.title);
      if (intakeFinalizeBlock) intakeFinalizeBlock.hidden = true;
      if (intakeResultBlock) intakeResultBlock.hidden = false;
      if (intakeProgressHint) intakeProgressHint.textContent = "Gati ✓";
      if (intakeStatus) intakeStatus.textContent = "";
    } catch (e) {
      if (intakeStatus) intakeStatus.textContent = "Gabim rrjeti";
    } finally {
      intakeFinalizeBtn.disabled = false;
    }
  });

  function intakeRenderResult(brief, title) {
    if (!intakeResultSummary) return;
    const lines = [];
    lines.push(`<div class="intake-r-title">📁 ${escapeHtml(title || "Rast i ri")}</div>`);
    if (brief.area) lines.push(`<div class="intake-r-row"><strong>Fusha:</strong> ${escapeHtml(brief.area)}</div>`);
    if (brief.urgency) lines.push(`<div class="intake-r-row"><strong>Urgjenca:</strong> <span class="urg-${escapeHtml(brief.urgency)}">${escapeHtml(brief.urgency)}</span></div>`);
    if (brief.client) lines.push(`<div class="intake-r-row"><strong>Klienti:</strong> ${escapeHtml(brief.client)}</div>`);
    if (brief.counterparty) lines.push(`<div class="intake-r-row"><strong>Kundërshtari:</strong> ${escapeHtml(brief.counterparty)}</div>`);
    if (brief.facts) lines.push(`<div class="intake-r-block"><strong>Faktet</strong><p>${escapeHtml(brief.facts)}</p></div>`);
    if (brief.deadlines) lines.push(`<div class="intake-r-block"><strong>Afate</strong><p>${escapeHtml(brief.deadlines)}</p></div>`);
    if (Array.isArray(brief.open_questions) && brief.open_questions.length) {
      lines.push(`<div class="intake-r-block"><strong>Pyetje të hapura</strong><ul>${
        brief.open_questions.map(q => `<li>${escapeHtml(q)}</li>`).join("")
      }</ul></div>`);
    }
    intakeResultSummary.innerHTML = lines.join("");
  }

  intakeOpenCaseBtn?.addEventListener("click", async () => {
    if (!intakeFinalCaseId) return;
    closeProModal(intakeModal);
    await renderCaseList();
    await selectCase(intakeFinalCaseId);
  });

  // ─── conflict-of-interest checker ────────────────────────────────
  const conflictQuery = document.getElementById("conflict-query");
  const conflictBtn   = document.getElementById("conflict-check-btn");
  const conflictResults = document.getElementById("conflict-results");

  async function runConflictCheck() {
    const q = (conflictQuery?.value || "").trim();
    if (q.length < 2) {
      conflictResults.hidden = false;
      conflictResults.innerHTML = `<p class="conflict-empty">Vendos të paktën 2 shkronja.</p>`;
      return;
    }
    conflictResults.hidden = false;
    conflictResults.innerHTML = `<p class="conflict-empty">Duke kërkuar…</p>`;
    try {
      const r = await fetch("/api/firm/conflict-check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        conflictResults.innerHTML = `<p class="conflict-empty">${escapeHtml(err.error || "Gabim")}.</p>`;
        return;
      }
      const data = await r.json();
      if (!data.matches.length) {
        conflictResults.innerHTML = `<div class="conflict-clear">
          <strong>✅ Asnjë konflikt</strong>
          <p>"${escapeHtml(q)}" nuk shfaqet në asnjë rast të studios. Mund ta pranosh sigurt.</p>
        </div>`;
        return;
      }
      const rows = data.matches.map((m) => `
        <div class="conflict-row" data-side="${escapeHtml(m.side)}">
          <div class="conflict-row-head">
            <strong>${escapeHtml(m.name)}</strong>
            <span class="conflict-side conflict-side-${escapeHtml(m.side)}">${_sideLabel(m.side)}</span>
            <span class="conflict-score" title="Përputhje">${Math.round(m.match_score * 100)}%</span>
          </div>
          <div class="conflict-row-meta">
            në rastin <em>${escapeHtml(m.case_title || "—")}</em> · ${escapeHtml(m.created_at.slice(0, 10))}
          </div>
        </div>`).join("");
      conflictResults.innerHTML = `<div class="conflict-warn">
        <strong>⚠️ ${data.count} përputhje${data.count === 1 ? "" : "e"} gjetur</strong>
        <p>Verifiko me kujdes para se të pranosh klientin e ri.</p>
      </div>${rows}`;
    } catch (e) {
      conflictResults.innerHTML = `<p class="conflict-empty">Gabim rrjeti: ${escapeHtml(e.message)}.</p>`;
    }
  }
  function _sideLabel(side) {
    switch (side) {
      case "client": return "klient";
      case "opponent": return "kundërshtar";
      case "third": return "palë e tretë";
      default: return "i panjohur";
    }
  }
  conflictBtn?.addEventListener("click", runConflictCheck);
  conflictQuery?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); runConflictCheck(); }
  });

  studioInviteBtn?.addEventListener("click", async () => {
    const username = (studioInviteUsername.value || "").trim();
    const role = studioInviteRole.value;
    if (!username) { studioInviteStatus.textContent = "Vendos një emër përdoruesi."; return; }
    studioInviteStatus.textContent = "Duke ftuar…";
    const r = await fetch("/api/firm/members", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, role }),
    });
    if (r.ok) {
      studioInviteStatus.textContent = "";
      studioInviteUsername.value = "";
      toast(`${username} u shtua si ${role}`, "ok");
      await loadStudio();
    } else {
      const err = await r.json().catch(() => ({}));
      studioInviteStatus.textContent = err.error || "Shtimi dështoi.";
    }
  });

  // ─── daily brief (V8.2) ──────────────────────────────────────────
  async function loadDailyBrief() {
    const el = document.getElementById("daily-brief");
    if (!el) return;
    try {
      const r = await fetch("/api/firm/today");
      if (!r.ok) return;
      const d = await r.json();
      const items = [];

      // Upcoming events (next 7 days)
      if (d.upcoming_events?.length) {
        const evs = d.upcoming_events.slice(0, 5).map(e => {
          const when = new Date(e.starts_at);
          const dd = String(when.getDate()).padStart(2, "0");
          const mm = String(when.getMonth() + 1).padStart(2, "0");
          const hh = String(when.getHours()).padStart(2, "0");
          const mn = String(when.getMinutes()).padStart(2, "0");
          return `<li><span class="db-when">${dd}/${mm} ${hh}:${mn}</span> <span class="db-kind">${escapeHtml(e.kind || "")}</span> ${escapeHtml(e.title)}</li>`;
        }).join("");
        items.push(`<div class="db-block">
          <h5>📅 Javën që vjen (${d.upcoming_events.length})</h5>
          <ul class="db-list">${evs}</ul>
        </div>`);
      }

      // Drafts to review (only if can_review)
      if (d.drafts_to_review?.length) {
        const drs = d.drafts_to_review.slice(0, 5).map(dr =>
          `<li>📝 <strong>${escapeHtml(dr.author_username)}</strong> — ${escapeHtml(dr.title)} <em>(${escapeHtml(dr.kind_label || dr.kind)})</em></li>`
        ).join("");
        items.push(`<div class="db-block db-warn">
          <h5>⏳ Për revizion (${d.drafts_to_review.length})</h5>
          <ul class="db-list">${drs}</ul>
        </div>`);
      }

      // My drafts pending feedback
      if (d.my_pending_drafts?.length) {
        const mps = d.my_pending_drafts.slice(0, 5).map(dr =>
          `<li>📝 ${escapeHtml(dr.title)} <em>— pret revizion</em></li>`
        ).join("");
        items.push(`<div class="db-block">
          <h5>🕒 Bozzat e mia në pritje</h5>
          <ul class="db-list">${mps}</ul>
        </div>`);
      }

      // Stage pipeline
      const sc = d.stage_counts || {};
      const stagePill = (s, label, emoji) =>
        sc[s] ? `<span class="db-pill stage-${s}">${emoji} ${label}: ${sc[s]}</span>` : "";
      const pipeline = [
        stagePill("intake", "Intake", "📥"),
        stagePill("preparation", "Përgatitje", "📚"),
        stagePill("hearing", "Seancë", "⚖️"),
        stagePill("decision", "Vendim", "📜"),
        stagePill("execution", "Ekzekutim", "🏁"),
      ].filter(Boolean).join(" ");
      if (pipeline) {
        items.push(`<div class="db-block">
          <h5>📊 Pipeline (${d.total_cases} raste)</h5>
          <div class="db-pipeline">${pipeline}</div>
        </div>`);
      }

      // Stale cases
      if (d.stale_cases?.length) {
        const sl = d.stale_cases.slice(0, 3).map(s =>
          `<li>💤 ${escapeHtml(s.title)} <em>(${s.days_silent} ditë pa lëvizje)</em></li>`
        ).join("");
        items.push(`<div class="db-block db-warn">
          <h5>💤 Raste pa lëvizje</h5>
          <ul class="db-list">${sl}</ul>
        </div>`);
      }

      if (!items.length) {
        el.hidden = true;
        return;
      }

      el.innerHTML = `<h4 class="db-title">🌅 Brifing i ditës — ${d.user}${d.firm ? " · " + escapeHtml(d.firm.name) : ""}</h4>${items.join("")}`;
      el.hidden = false;
    } catch (e) {
      // silently fail — widget is best-effort
    }
  }

  // ─── clients & portal (V8.3) ─────────────────────────────────────
  const clientsBtn = document.getElementById("clients-btn");
  const clientsCountBadge = document.getElementById("clients-count-badge");
  const clientsList = document.getElementById("clients-list");
  const clientsStatus = document.getElementById("clients-status");
  const clientAddForm = document.getElementById("client-add-form");
  const clientNameInput = document.getElementById("client-name");
  const clientPhoneInput = document.getElementById("client-phone");
  const clientEmailInput = document.getElementById("client-email");

  clientsBtn?.addEventListener("click", () => {
    if (!activeCaseId) return;
    openProModal("clients");
  });

  function setClientsCount(n) {
    if (!clientsCountBadge) return;
    if (n > 0) {
      clientsCountBadge.textContent = String(n);
      clientsCountBadge.hidden = false;
    } else {
      clientsCountBadge.hidden = true;
    }
  }

  async function refreshClientsCount() {
    if (!activeCaseId) { setClientsCount(0); return; }
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/clients`);
      if (!r.ok) return;
      const d = await r.json();
      setClientsCount((d.clients || []).length);
    } catch {}
  }

  function renderClientsList(list) {
    if (!clientsList) return;
    if (!list || !list.length) {
      clientsList.innerHTML = '<p class="clients-empty">Ende nuk ka klientë të lidhur me këtë rast.</p>';
      return;
    }
    const rows = list.map(c => {
      const lastView = c.last_viewed_at
        ? `Hyrja e fundit: ${escapeHtml(c.last_viewed_at.replace("T", " ").slice(0, 16))} UTC`
        : "Klienti ende nuk e ka hapur linkun.";
      const contactBits = [];
      if (c.phone) contactBits.push(`📞 ${escapeHtml(c.phone)}`);
      if (c.email) contactBits.push(`✉️ ${escapeHtml(c.email)}`);
      return `<div class="client-row" data-cid="${c.id}">
        <div class="client-row-head">
          <strong>${escapeHtml(c.name)}</strong>
          ${contactBits.length ? `<span class="client-contact">${contactBits.join(" · ")}</span>` : ""}
        </div>
        <div class="client-portal-row">
          <input type="text" class="client-portal-link" readonly value="${escapeHtml(c.portal_url)}" />
          <button type="button" class="ghost client-copy-btn" data-cid="${c.id}">📋 Kopjo</button>
        </div>
        <div class="client-row-meta">${lastView}</div>
        <div class="client-row-actions">
          <button type="button" class="ghost client-regen-btn" data-cid="${c.id}" title="Gjeneron një link të ri (i vjetri ndërpritet)">🔄 Rigjenero linkun</button>
          <button type="button" class="ghost danger client-delete-btn" data-cid="${c.id}">🗑️ Hiq klientin</button>
        </div>
      </div>`;
    }).join("");
    clientsList.innerHTML = rows;
    setClientsCount(list.length);
  }

  async function loadClientsForCase() {
    if (!activeCaseId) {
      clientsList.innerHTML = '<p class="clients-empty">Hap një rast së pari.</p>';
      return;
    }
    clientsStatus.textContent = "Po ngarkon…";
    clientsStatus.className = "pro-status";
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/clients`);
      if (!r.ok) {
        clientsStatus.textContent = "Nuk u arrit ngarkimi.";
        clientsStatus.className = "pro-status error";
        return;
      }
      const d = await r.json();
      renderClientsList(d.clients);
      clientsStatus.textContent = "";
    } catch {
      clientsStatus.textContent = "Gabim rrjeti.";
      clientsStatus.className = "pro-status error";
    }
  }

  clientAddForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const name = (clientNameInput.value || "").trim();
    if (!name) return;
    const body = {
      name,
      phone: (clientPhoneInput.value || "").trim() || undefined,
      email: (clientEmailInput.value || "").trim() || undefined,
    };
    clientsStatus.textContent = "Po krijon…";
    clientsStatus.className = "pro-status";
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/clients`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        clientsStatus.textContent = err.error || "Krijimi dështoi.";
        clientsStatus.className = "pro-status error";
        return;
      }
      clientNameInput.value = "";
      clientPhoneInput.value = "";
      clientEmailInput.value = "";
      clientsStatus.textContent = "Klienti u shtua. Linku është gati për t'u kopjuar.";
      clientsStatus.className = "pro-status ok";
      await loadClientsForCase();
    } catch {
      clientsStatus.textContent = "Gabim rrjeti.";
      clientsStatus.className = "pro-status error";
    }
  });

  clientsList?.addEventListener("click", async (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    const cid = t.getAttribute("data-cid");
    if (!cid) return;

    if (t.classList.contains("client-copy-btn")) {
      const row = clientsList.querySelector(`.client-row[data-cid="${cid}"]`);
      const link = row?.querySelector(".client-portal-link");
      if (!link) return;
      try {
        await navigator.clipboard.writeText(link.value);
        toast("Linku u kopjua", "ok");
      } catch {
        link.select();
        toast("Selektuar — kopjo me Cmd+C", "info");
      }
      return;
    }

    if (t.classList.contains("client-regen-btn")) {
      if (!confirm("Linku i vjetër do të bëhet i pavlefshëm. Vazhdoj?")) return;
      const r = await fetch(`/api/cases/${activeCaseId}/clients/${cid}/regenerate-token`, {
        method: "POST",
      });
      if (r.ok) {
        toast("Linku u rigjenerua", "ok");
        await loadClientsForCase();
      } else {
        toast("Rigjenerimi dështoi", "err");
      }
      return;
    }

    if (t.classList.contains("client-delete-btn")) {
      if (!confirm("Heq klientin? Linku do të bëhet i pavlefshëm.")) return;
      const r = await fetch(`/api/cases/${activeCaseId}/clients/${cid}`, {
        method: "DELETE",
      });
      if (r.ok) {
        toast("Klienti u hoq", "ok");
        await loadClientsForCase();
      } else {
        toast("Heqja dështoi", "err");
      }
    }
  });

  // expose so selectCase can refresh the badge
  window.__refreshClientsCount = refreshClientsCount;

  // ─── status updates (V8.3 part 2) ────────────────────────────────
  const updateBody = document.getElementById("status-update-body");
  const updateKind = document.getElementById("status-update-kind");
  const updatesStatus = document.getElementById("updates-status");
  const updatesList = document.getElementById("updates-list");
  const statusPublishBtn = document.getElementById("status-publish-btn");
  const statusAutoBtn = document.getElementById("status-auto-btn");
  const statusTranslateBtn = document.getElementById("status-translate-btn");

  const KIND_EMOJI = {
    status: "📍",
    milestone: "🏁",
    document_request: "📄",
    translation: "🔄",
  };

  function renderUpdatesList(updates) {
    if (!updatesList) return;
    if (!updates || !updates.length) {
      updatesList.innerHTML = '<p class="updates-empty">Ende asnjë lajm i publikuar.</p>';
      return;
    }
    updatesList.innerHTML = updates.map(u => {
      const when = (u.created_at || "").slice(0, 16).replace("T", " ");
      const emoji = KIND_EMOJI[u.kind] || "📍";
      const src = u.source_kind === "ai_translate" ? '<span class="upd-tag">🔄 nga përkthim</span>'
                : u.source_kind === "stage_change" ? '<span class="upd-tag">📊 nga faza</span>'
                : "";
      return `<div class="upd-row" data-uid="${u.id}">
        <div class="upd-row-head">
          <span class="upd-when">${escapeHtml(when)}</span>
          <span class="upd-kind">${emoji} ${escapeHtml(u.kind)}</span>
          ${src}
          <button type="button" class="upd-del" data-uid="${u.id}" title="Hiq lajmin">🗑️</button>
        </div>
        <div class="upd-body">${escapeHtml(u.body_sq)}</div>
        ${u.author_username ? `<div class="upd-by">— ${escapeHtml(u.author_username)}</div>` : ""}
      </div>`;
    }).join("");
  }

  async function loadUpdates() {
    if (!activeCaseId || !updatesList) return;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/status-updates`);
      if (!r.ok) return;
      const d = await r.json();
      renderUpdatesList(d.updates);
    } catch {}
  }

  // load updates whenever clients modal opens
  const clientsModal = document.getElementById("clients-modal");
  if (clientsModal) {
    const obs = new MutationObserver(() => {
      if (!clientsModal.hidden) loadUpdates();
    });
    obs.observe(clientsModal, { attributes: true, attributeFilter: ["hidden"] });
  }

  statusPublishBtn?.addEventListener("click", async () => {
    if (!activeCaseId) return;
    const body_sq = (updateBody.value || "").trim();
    if (body_sq.length < 10) {
      updatesStatus.textContent = "Lajmi është shumë i shkurtër.";
      updatesStatus.className = "pro-status error";
      return;
    }
    updatesStatus.textContent = "Po publikon…";
    updatesStatus.className = "pro-status";
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/status-updates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          body_sq, kind: updateKind.value || "status",
          source_kind: updateBody.dataset.source || "manual",
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        updatesStatus.textContent = err.error || "Publikimi dështoi.";
        updatesStatus.className = "pro-status error";
        return;
      }
      updateBody.value = "";
      updateBody.dataset.source = "manual";
      updatesStatus.textContent = "Lajmi u publikua. Klienti do ta shohë në portal.";
      updatesStatus.className = "pro-status ok";
      await loadUpdates();
    } catch {
      updatesStatus.textContent = "Gabim rrjeti.";
      updatesStatus.className = "pro-status error";
    }
  });

  updatesList?.addEventListener("click", async (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    if (!t.classList.contains("upd-del")) return;
    const uid = t.getAttribute("data-uid");
    if (!uid) return;
    if (!confirm("Heq lajmin? Klienti nuk do ta shohë më.")) return;
    const r = await fetch(`/api/cases/${activeCaseId}/status-updates/${uid}`, {
      method: "DELETE",
    });
    if (r.ok) { toast("Lajmi u hoq", "ok"); await loadUpdates(); }
    else toast("Heqja dështoi", "err");
  });

  statusAutoBtn?.addEventListener("click", async () => {
    if (!activeCaseId) return;
    statusAutoBtn.disabled = true;
    updatesStatus.textContent = "AI po sugjeron lajmin… (~10s)";
    updatesStatus.className = "pro-status";
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/auto-status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        updatesStatus.textContent = err.error || "Sugjerimi dështoi.";
        updatesStatus.className = "pro-status error";
        return;
      }
      const d = await r.json();
      updateBody.value = d.body_sq || "";
      updateBody.dataset.source = "ai_translate";
      if (d.kind && updateKind) updateKind.value = d.kind;
      updatesStatus.textContent = "Sugjerimi u ngarkua. Edito sipas nevojës dhe publiko.";
      updatesStatus.className = "pro-status ok";
    } catch {
      updatesStatus.textContent = "Gabim rrjeti.";
      updatesStatus.className = "pro-status error";
    } finally {
      statusAutoBtn.disabled = false;
    }
  });

  // ─── jargon translator modal ─────────────────────────────────────
  const jargonModal = document.getElementById("jargon-modal");
  const jargonSource = document.getElementById("jargon-source");
  const jargonRunBtn = document.getElementById("jargon-run-btn");
  const jargonResult = document.getElementById("jargon-result");
  const jargonPlain = document.getElementById("jargon-plain");
  const jargonTerms = document.getElementById("jargon-terms");
  const jargonUseBtn = document.getElementById("jargon-use-btn");
  const jargonStatus = document.getElementById("jargon-status");

  statusTranslateBtn?.addEventListener("click", () => {
    if (!activeCaseId) return;
    // Pre-populate from current textarea so the lawyer can paste-and-go
    if (jargonSource && updateBody.value && !jargonSource.value) {
      jargonSource.value = updateBody.value;
    }
    jargonResult.hidden = true;
    jargonStatus.textContent = "";
    openProModal("jargon");
  });

  jargonRunBtn?.addEventListener("click", async () => {
    if (!activeCaseId) return;
    const text = (jargonSource.value || "").trim();
    if (text.length < 20) {
      jargonStatus.textContent = "Teksti është shumë i shkurtër (min 20 karaktere).";
      jargonStatus.className = "pro-status error";
      return;
    }
    jargonRunBtn.disabled = true;
    jargonStatus.textContent = "Po përkthen… (~10s)";
    jargonStatus.className = "pro-status";
    jargonResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/translate-jargon`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_text: text }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        jargonStatus.textContent = err.error || "Përkthimi dështoi.";
        jargonStatus.className = "pro-status error";
        return;
      }
      const d = await r.json();
      jargonPlain.textContent = d.plain_sq || "";
      if (d.jargon_terms?.length) {
        jargonTerms.innerHTML = '<strong>Fjalët teknike të përkthyera:</strong> ' +
          d.jargon_terms.map(t => `<span class="jargon-term">${escapeHtml(t)}</span>`).join(" ");
      } else {
        jargonTerms.innerHTML = "";
      }
      jargonResult.hidden = false;
      jargonStatus.textContent = "Gati. Mund ta përdorësh si lajm ose ta editosh.";
      jargonStatus.className = "pro-status ok";
    } catch {
      jargonStatus.textContent = "Gabim rrjeti.";
      jargonStatus.className = "pro-status error";
    } finally {
      jargonRunBtn.disabled = false;
    }
  });

  jargonUseBtn?.addEventListener("click", () => {
    const txt = jargonPlain.textContent || "";
    if (!txt) return;
    updateBody.value = txt;
    updateBody.dataset.source = "ai_translate";
    if (updateKind) updateKind.value = "translation";
    closeProModal(jargonModal);
    if (clientsModal && clientsModal.hidden) openProModal("clients");
    updatesStatus.textContent = "Versioni i thjeshtuar u kopjua. Edito dhe publiko.";
    updatesStatus.className = "pro-status ok";
  });

  // ─── contract review (V8.4) ──────────────────────────────────────
  const contractLabel = document.getElementById("contract-label");
  const contractSource = document.getElementById("contract-source");
  const contractRunBtn = document.getElementById("contract-run-btn");
  const contractResult = document.getElementById("contract-result");
  const contractHistory = document.getElementById("contract-history");
  const contractStatus = document.getElementById("contract-status");
  const contractInputBlock = document.getElementById("contract-input-block");

  function levelBadge(level) {
    const map = {
      ok: { c: "ok", t: "🟢 Standarde" },
      watch: { c: "watch", t: "🟡 Vëmendje" },
      risk: { c: "risk", t: "🔴 Rrezik" },
    };
    const m = map[level] || map.ok;
    return `<span class="cr-level cr-level-${m.c}">${m.t}</span>`;
  }

  function riskBar(score) {
    const s = Math.max(0, Math.min(100, score | 0));
    let cls = "cr-bar-low";
    if (s >= 60) cls = "cr-bar-high";
    else if (s >= 30) cls = "cr-bar-mid";
    return `<div class="cr-risk">
      <div class="cr-risk-bar"><div class="cr-risk-fill ${cls}" style="width:${s}%"></div></div>
      <div class="cr-risk-num">Risk: <strong>${s}</strong>/100</div>
    </div>`;
  }

  function renderContractResult(payload) {
    const r = payload.result || {};
    const clauses = r.clauses || [];
    const obligations = r.obligations || [];
    const deadlines = r.deadlines || [];
    const gdpr = r.gdpr_flags || [];
    const missing = r.missing_clauses || [];
    const parties = r.parties || [];
    const score = payload.risk_score ?? r.risk_score ?? 0;

    const clausesHtml = clauses.length ? clauses.map(c => `
      <div class="cr-clause cr-level-${c.level || 'ok'}">
        <div class="cr-clause-head">
          <strong>${c.n ? '#' + c.n + ' · ' : ''}${escapeHtml(c.title || '')}</strong>
          ${levelBadge(c.level)}
        </div>
        ${c.excerpt ? `<blockquote class="cr-excerpt">${escapeHtml(c.excerpt)}</blockquote>` : ""}
        ${c.issue ? `<div class="cr-issue"><strong>Vërejtje:</strong> ${escapeHtml(c.issue)}</div>` : ""}
        ${c.suggestion ? `<div class="cr-suggestion"><strong>Sugjerim:</strong> ${escapeHtml(c.suggestion)}</div>` : ""}
      </div>`).join("") : '<p class="updates-empty">Asnjë klauzolë e analizuar.</p>';

    const obligationsHtml = obligations.length ? `<table class="cr-table">
      <thead><tr><th>Pala</th><th>Detyrimi</th><th>Afati</th></tr></thead>
      <tbody>${obligations.map(o => `<tr>
        <td>${escapeHtml(o.party || '')}</td>
        <td>${escapeHtml(o.duty || '')}</td>
        <td>${escapeHtml(o.deadline || '—')}</td>
      </tr>`).join("")}</tbody>
    </table>` : "";

    const deadlinesHtml = deadlines.length ? `<ul class="cr-list">
      ${deadlines.map(d => `<li><strong>${escapeHtml(d.when || '')}:</strong> ${escapeHtml(d.what || '')} <em>(${escapeHtml(d.who || '')})</em></li>`).join("")}
    </ul>` : "";

    const gdprHtml = gdpr.length ? `<ul class="cr-list cr-gdpr">
      ${gdpr.map(g => `<li class="cr-gdpr-${g.severity || 'low'}"><strong>${escapeHtml(g.severity || 'low').toUpperCase()}:</strong> ${escapeHtml(g.flag || '')} ${g.location ? `<em>(${escapeHtml(g.location)})</em>` : ""}</li>`).join("")}
    </ul>` : '<p class="cr-empty">Asnjë rrezik GDPR-AL i identifikuar.</p>';

    const missingHtml = missing.length ? `<ul class="cr-list cr-missing">
      ${missing.map(m => `<li>⚠️ ${escapeHtml(m)}</li>`).join("")}
    </ul>` : "";

    contractResult.innerHTML = `
      <div class="cr-head">
        <div>
          <h4>${escapeHtml(payload.contract_label || r.summary?.slice(0,60) || 'Rishikim')}</h4>
          ${r.contract_kind ? `<span class="cr-kind">${escapeHtml(r.contract_kind)}</span>` : ""}
          ${parties.length ? `<span class="cr-parties">Palët: ${parties.map(p => escapeHtml(p)).join(" ↔ ")}</span>` : ""}
        </div>
        ${riskBar(score)}
      </div>
      ${r.summary ? `<p class="cr-summary">${escapeHtml(r.summary)}</p>` : ""}

      <h5>📋 Klauzolat (${clauses.length})</h5>
      ${clausesHtml}

      ${obligations.length ? `<h5>🤝 Detyrimet</h5>${obligationsHtml}` : ""}
      ${deadlines.length ? `<h5>⏰ Afatet</h5>${deadlinesHtml}` : ""}

      <h5>🛡️ GDPR-AL</h5>
      ${gdprHtml}

      ${missing.length ? `<h5>❓ Klauzola që mungojnë</h5>${missingHtml}` : ""}
    `;
    contractResult.hidden = false;
  }

  async function loadContractHistory() {
    if (!activeCaseId || !contractHistory) return;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/contract-reviews`);
      if (!r.ok) return;
      const d = await r.json();
      const reviews = d.reviews || [];
      if (!reviews.length) {
        contractHistory.innerHTML = "";
        return;
      }
      contractHistory.innerHTML = `
        <h5>📚 Rishikime të mëparshme</h5>
        <ul class="cr-history-list">
          ${reviews.map(r => {
            const score = r.risk_score ?? 0;
            const cls = score >= 60 ? "high" : score >= 30 ? "mid" : "low";
            return `<li>
              <button type="button" class="cr-history-item" data-rid="${r.id}">
                <strong>${escapeHtml(r.contract_label || r.summary?.slice(0,40) || '(pa etiketë)')}</strong>
                <span class="cr-history-meta">${escapeHtml((r.created_at || '').slice(0,10))} · risk: <span class="cr-history-score-${cls}">${score}</span></span>
              </button>
              <button type="button" class="ghost cr-history-del" data-rid="${r.id}">🗑️</button>
            </li>`;
          }).join("")}
        </ul>`;
    } catch {}
  }

  const contractFile = document.getElementById("contract-file");
  contractFile?.addEventListener("change", async () => {
    const file = contractFile.files && contractFile.files[0];
    if (!file) return;
    if (contractRunBtn) contractRunBtn.disabled = true;
    try {
      const d = await _extractFileText(file, contractStatus);
      const t = (d.text || "").trim();
      if (!t) { contractStatus.textContent = "Dokumenti nuk ka tekst të lexueshëm."; }
      else {
        contractSource.value = contractSource.value.trim() ? (contractSource.value.trim() + "\n\n" + t) : t;
        contractStatus.textContent = d.used_vision_ocr ? "\u2713 Lexuar me OCR \u2014 kontrollo tekstin" : "\u2713 Dokumenti u lexua";
        if (contractLabel && !contractLabel.value.trim() && d.filename) contractLabel.value = d.filename.replace(/\.[^.]+$/, "").slice(0, 120);
      }
    } catch (e) { contractStatus.textContent = "Gabim: " + e.message; }
    finally { if (contractRunBtn) contractRunBtn.disabled = false; contractFile.value = ""; }
  });

  contractRunBtn?.addEventListener("click", async () => {
    if (!activeCaseId) {
      contractStatus.textContent = "Hap një rast së pari.";
      contractStatus.className = "pro-status error";
      return;
    }
    const text = (contractSource.value || "").trim();
    if (text.length < 100) {
      contractStatus.textContent = "Kontrata është shumë e shkurtër (min 100 karaktere).";
      contractStatus.className = "pro-status error";
      return;
    }
    contractRunBtn.disabled = true;
    contractStatus.textContent = "Po analizon kontratën… (~60-90s)";
    contractStatus.className = "pro-status";
    contractResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/contract-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contract_text: text,
          contract_label: (contractLabel.value || "").trim() || undefined,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        contractStatus.textContent = err.error || "Rishikimi dështoi.";
        contractStatus.className = "pro-status error";
        return;
      }
      const payload = await r.json();
      renderContractResult(payload);
      contractStatus.textContent = "Gati. Rishikimi u ruajt për këtë rast.";
      contractStatus.className = "pro-status ok";
      await loadContractHistory();
    } catch {
      contractStatus.textContent = "Gabim rrjeti.";
      contractStatus.className = "pro-status error";
    } finally {
      contractRunBtn.disabled = false;
    }
  });

  contractHistory?.addEventListener("click", async (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    const item = t.closest(".cr-history-item");
    const del = t.closest(".cr-history-del");
    if (item) {
      const rid = item.getAttribute("data-rid");
      const r = await fetch(`/api/cases/${activeCaseId}/contract-reviews/${rid}`);
      if (r.ok) {
        const payload = await r.json();
        renderContractResult(payload);
        contractStatus.textContent = "Rishikimi u ringarkua.";
        contractStatus.className = "pro-status";
      }
    }
    if (del) {
      const rid = del.getAttribute("data-rid");
      if (!confirm("Heq këtë rishikim?")) return;
      const r = await fetch(`/api/cases/${activeCaseId}/contract-reviews/${rid}`, {
        method: "DELETE",
      });
      if (r.ok) { toast("Rishikimi u hoq", "ok"); await loadContractHistory(); }
    }
  });

  // ── 💰 V8.5 MONEY (time tracking + invoices) ─────────────────────
  const moneyModal = document.getElementById("money-modal");
  const timeDate = document.getElementById("time-date");
  const timeMinutes = document.getElementById("time-minutes");
  const timeKind = document.getElementById("time-kind");
  const timeRate = document.getElementById("time-rate");
  const timeDesc = document.getElementById("time-desc");
  const timeAddBtn = document.getElementById("time-add-btn");
  const timeStatus = document.getElementById("time-status");
  const timeList = document.getElementById("time-list");
  const moneyUnbilledPill = document.getElementById("money-unbilled");
  const invoiceClient = document.getElementById("invoice-client");
  const invoiceVat = document.getElementById("invoice-vat");
  const invoiceDue = document.getElementById("invoice-due");
  const invoiceAddress = document.getElementById("invoice-address");
  const invoiceNotes = document.getElementById("invoice-notes");
  const invoiceCreateBtn = document.getElementById("invoice-create-btn");
  const invoiceStatus = document.getElementById("invoice-status");
  const invoicesList = document.getElementById("invoices-list");
  const invoiceDetail = document.getElementById("invoice-detail");

  let _tariffCache = null;

  function fmtMoney(cents, currency) {
    if (cents == null) return "—";
    const sign = cents < 0 ? "-" : "";
    const c = Math.abs(cents);
    const whole = Math.floor(c / 100);
    const frac = String(c % 100).padStart(2, "0");
    return `${sign}${whole.toLocaleString("sq-AL")}.${frac} ${currency || "EUR"}`;
  }

  function fmtHours(minutes) {
    return (minutes / 60).toFixed(2);
  }

  async function ensureTariff() {
    if (_tariffCache) return _tariffCache;
    try {
      const r = await fetch("/api/firm/tariff");
      if (r.ok) _tariffCache = await r.json();
    } catch {}
    return _tariffCache;
  }

  function todayISO() {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  async function loadMoneyForCase() {
    if (!activeCaseId) {
      timeList.innerHTML = '<p class="money-empty">Hap një rast për të regjistruar orë.</p>';
      invoicesList.innerHTML = "";
      return;
    }
    if (!timeDate.value) timeDate.value = todayISO();
    await ensureTariff();
    await Promise.all([loadTimeEntries(), loadInvoicesList()]);
  }

  async function loadTimeEntries() {
    timeList.innerHTML = '<p class="money-empty">Duke ngarkuar…</p>';
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/time-entries`);
      if (!r.ok) throw new Error("fetch failed");
      const data = await r.json();
      const entries = data.entries || [];
      const unbilledTotal = data.total_unbilled_cents || 0;
      moneyUnbilledPill.textContent = entries.length
        ? `${entries.filter(e => !e.billed_invoice_id).length} të papaguara · ${fmtMoney(unbilledTotal, entries[0]?.currency || "EUR")}`
        : "";
      if (!entries.length) {
        timeList.innerHTML = '<p class="money-empty">Ende asnjë orë e regjistruar për këtë rast.</p>';
        return;
      }
      timeList.innerHTML = entries.map(e => {
        const billed = e.billed_invoice_id
          ? `<span class="money-billed-pill" title="Faturuar">📄 #${e.billed_invoice_id}</span>`
          : `<span class="money-unbilled-pill">papaguar</span>`;
        return `
          <div class="money-entry ${e.billed_invoice_id ? "billed" : ""}">
            <div class="money-entry-main">
              <div class="money-entry-head">
                <strong>${escapeHtml(e.entry_date)}</strong>
                <span class="money-entry-kind">${escapeHtml(e.activity_label)}</span>
                ${billed}
              </div>
              <div class="money-entry-desc">${escapeHtml(e.description)}</div>
            </div>
            <div class="money-entry-meta">
              <div class="money-entry-time">${fmtHours(e.minutes)} h × ${fmtMoney(e.hourly_rate, e.currency)}/h</div>
              <div class="money-entry-amount">${fmtMoney(e.amount_cents, e.currency)}</div>
              <button type="button" class="icon-btn danger small" data-del-entry="${e.id}" title="Fshi">🗑️</button>
            </div>
          </div>`;
      }).join("");
    } catch (err) {
      timeList.innerHTML = '<p class="money-empty error">Nuk u ngarkuan orët.</p>';
    }
  }

  async function loadInvoicesList() {
    invoicesList.innerHTML = '<p class="money-empty">Duke ngarkuar…</p>';
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/invoices`);
      if (!r.ok) throw new Error("fetch failed");
      const data = await r.json();
      const invs = data.invoices || [];
      if (!invs.length) {
        invoicesList.innerHTML = '<p class="money-empty">Ende asnjë faturë për këtë rast.</p>';
        return;
      }
      invoicesList.innerHTML = invs.map(inv => `
        <div class="money-invoice money-invoice-${inv.status}">
          <div class="money-invoice-head">
            <strong>${escapeHtml(inv.invoice_no)}</strong>
            <span class="money-invoice-status status-${inv.status}">${invoiceStatusLabel(inv.status)}</span>
          </div>
          <div class="money-invoice-meta">
            <span>${escapeHtml(inv.issue_date)} → ${inv.due_date ? escapeHtml(inv.due_date) : "—"}</span>
            <span>${escapeHtml(inv.client_name)}</span>
            <strong>${fmtMoney(inv.total_cents, inv.currency)}</strong>
          </div>
          <div class="money-invoice-actions">
            <button type="button" class="ghost small" data-inv-view="${inv.id}">📄 Shfaq</button>
            <button type="button" class="ghost small" data-inv-status="${inv.id}" data-status="sent" ${inv.status !== "draft" ? "disabled" : ""}>✉️ Dërguar</button>
            <button type="button" class="ghost small" data-inv-status="${inv.id}" data-status="paid" ${inv.status === "paid" ? "disabled" : ""}>✅ Paguar</button>
            <button type="button" class="ghost small" data-inv-status="${inv.id}" data-status="cancelled" ${inv.status === "cancelled" ? "disabled" : ""}>🚫 Anuluar</button>
            <button type="button" class="icon-btn danger small" data-inv-del="${inv.id}" title="Fshi (rikthen orët)">🗑️</button>
          </div>
        </div>
      `).join("");
    } catch (err) {
      invoicesList.innerHTML = '<p class="money-empty error">Nuk u ngarkuan faturat.</p>';
    }
  }

  function invoiceStatusLabel(s) {
    return ({ draft: "Bozzë", sent: "Dërguar", paid: "Paguar", cancelled: "Anuluar" })[s] || s;
  }

  // Auto-fill rate when activity_kind changes
  timeKind?.addEventListener("change", () => {
    if (!_tariffCache || timeRate.value) return;
    const cents = _tariffCache.tariff?.[timeKind.value];
    if (cents != null) timeRate.placeholder = `auto (${(cents / 100).toFixed(0)})`;
  });

  timeAddBtn?.addEventListener("click", async () => {
    if (!activeCaseId) {
      timeStatus.textContent = "Hap një rast së pari.";
      timeStatus.className = "pro-status error";
      return;
    }
    const minutes = parseInt(timeMinutes.value, 10);
    const description = (timeDesc.value || "").trim();
    if (!minutes || minutes <= 0) {
      timeStatus.textContent = "Vendos numrin e minutave.";
      timeStatus.className = "pro-status error"; return;
    }
    if (!description) {
      timeStatus.textContent = "Shkruaj një përshkrim të shkurtër.";
      timeStatus.className = "pro-status error"; return;
    }
    const body = {
      minutes, description,
      activity_kind: timeKind.value,
      entry_date: timeDate.value || null,
    };
    if (timeRate.value) body.hourly_rate = Math.round(parseFloat(timeRate.value) * 100);
    timeStatus.textContent = "Duke shtuar…";
    timeStatus.className = "pro-status";
    timeAddBtn.disabled = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/time-entries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || "shtimi dështoi");
      }
      timeStatus.textContent = "U shtua.";
      timeStatus.className = "pro-status ok";
      timeMinutes.value = ""; timeDesc.value = ""; timeRate.value = "";
      await loadTimeEntries();
      toast("Ora u regjistrua", "ok");
    } catch (err) {
      timeStatus.textContent = err.message;
      timeStatus.className = "pro-status error";
    } finally {
      timeAddBtn.disabled = false;
    }
  });

  timeList?.addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del-entry]");
    if (!del) return;
    if (!confirm("Heq këtë regjistrim?")) return;
    const eid = del.getAttribute("data-del-entry");
    const r = await fetch(`/api/cases/${activeCaseId}/time-entries/${eid}`, { method: "DELETE" });
    if (r.ok) { toast("U hoq", "ok"); await loadTimeEntries(); }
  });

  invoiceCreateBtn?.addEventListener("click", async () => {
    if (!activeCaseId) {
      invoiceStatus.textContent = "Hap një rast së pari.";
      invoiceStatus.className = "pro-status error"; return;
    }
    const client_name = (invoiceClient.value || "").trim();
    if (!client_name) {
      invoiceStatus.textContent = "Vendos emrin e klientit.";
      invoiceStatus.className = "pro-status error"; return;
    }
    const body = {
      client_name,
      client_address: (invoiceAddress.value || "").trim() || null,
      vat_rate: parseInt(invoiceVat.value, 10) || 0,
      due_date: invoiceDue.value || null,
      notes: (invoiceNotes.value || "").trim() || null,
    };
    invoiceStatus.textContent = "Duke gjeneruar…";
    invoiceStatus.className = "pro-status";
    invoiceCreateBtn.disabled = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/invoice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || "krijimi dështoi");
      }
      const inv = await r.json();
      invoiceStatus.textContent = `Faturë ${inv.invoice_no} e gjeneruar.`;
      invoiceStatus.className = "pro-status ok";
      invoiceClient.value = ""; invoiceAddress.value = "";
      invoiceNotes.value = ""; invoiceDue.value = "";
      await Promise.all([loadTimeEntries(), loadInvoicesList()]);
      renderInvoiceDetail(inv);
      toast(`📄 ${inv.invoice_no} e gatshme`, "ok");
    } catch (err) {
      invoiceStatus.textContent = err.message;
      invoiceStatus.className = "pro-status error";
    } finally {
      invoiceCreateBtn.disabled = false;
    }
  });

  function renderInvoiceDetail(inv) {
    invoiceDetail.hidden = false;
    const md = inv.markdown || "";
    invoiceDetail.innerHTML = `
      <div class="money-invoice-detail-head">
        <h4>📄 ${escapeHtml(inv.invoice_no)} — ${escapeHtml(inv.client_name)}</h4>
        <div>
          <button type="button" class="ghost small" id="invoice-copy-md">📋 Kopjo Markdown</button>
          <button type="button" class="ghost small" id="invoice-download-md">⬇️ Shkarko .md</button>
          <button type="button" class="icon-btn" id="invoice-detail-close" title="Mbyll">×</button>
        </div>
      </div>
      <pre class="money-invoice-md">${escapeHtml(md)}</pre>
    `;
    document.getElementById("invoice-copy-md")?.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(md); toast("U kopjua", "ok"); }
      catch { toast("Kopja dështoi", "error"); }
    });
    document.getElementById("invoice-download-md")?.addEventListener("click", () => {
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${inv.invoice_no}.md`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    });
    document.getElementById("invoice-detail-close")?.addEventListener("click", () => {
      invoiceDetail.hidden = true; invoiceDetail.innerHTML = "";
    });
  }

  invoicesList?.addEventListener("click", async (e) => {
    const view = e.target.closest("[data-inv-view]");
    const stat = e.target.closest("[data-inv-status]");
    const del = e.target.closest("[data-inv-del]");
    if (view) {
      const id = view.getAttribute("data-inv-view");
      const r = await fetch(`/api/cases/${activeCaseId}/invoices/${id}`);
      if (r.ok) renderInvoiceDetail(await r.json());
    }
    if (stat) {
      const id = stat.getAttribute("data-inv-status");
      const status = stat.getAttribute("data-status");
      const r = await fetch(`/api/cases/${activeCaseId}/invoices/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (r.ok) { toast(`Statusi → ${invoiceStatusLabel(status)}`, "ok"); await loadInvoicesList(); }
    }
    if (del) {
      if (!confirm("Heq këtë faturë? Orët do të kthehen si të papaguara.")) return;
      const id = del.getAttribute("data-inv-del");
      const r = await fetch(`/api/cases/${activeCaseId}/invoices/${id}`, { method: "DELETE" });
      if (r.ok) { toast("Faturë u hoq", "ok"); invoiceDetail.hidden = true; invoiceDetail.innerHTML = ""; await Promise.all([loadTimeEntries(), loadInvoicesList()]); }
    }
  });

  // ── 🤖 V8.6 AGENT (scan + auto-letters) ─────────────────────────
  const agentModal = document.getElementById("agent-modal");
  const agentScanBtn = document.getElementById("agent-scan-btn");
  const agentScanStatus = document.getElementById("agent-scan-status");
  const agentSuggestions = document.getElementById("agent-suggestions");
  const letterKindSel = document.getElementById("letter-kind");
  const letterRecipient = document.getElementById("letter-recipient");
  const letterSubject = document.getElementById("letter-subject");
  const letterContext = document.getElementById("letter-context");
  const letterDraftBtn = document.getElementById("letter-draft-btn");
  const letterDraftStatus = document.getElementById("letter-draft-status");
  const lettersList = document.getElementById("letters-list");
  const letterDetail = document.getElementById("letter-detail");

  const SUGGESTION_ICONS = {
    followup_client: "📞",
    draft_letter: "✍️",
    request_docs: "📂",
    precedent_alert: "⚖️",
    deadline_reminder: "⏰",
  };

  async function loadAgentForCase() {
    if (!activeCaseId) {
      agentSuggestions.innerHTML = '<p class="agent-empty">Hap një rast së pari.</p>';
      lettersList.innerHTML = "";
      return;
    }
    await Promise.all([loadSuggestions(), loadLetters()]);
  }

  async function loadSuggestions() {
    agentSuggestions.innerHTML = '<p class="agent-empty">Duke ngarkuar…</p>';
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/agent/suggestions`);
      if (!r.ok) throw new Error();
      const data = await r.json();
      renderSuggestions(data.suggestions || []);
    } catch {
      agentSuggestions.innerHTML = '<p class="agent-empty error">Gabim në ngarkim.</p>';
    }
  }

  function renderSuggestions(items) {
    if (!items.length) {
      agentSuggestions.innerHTML = '<p class="agent-empty">Asnjë sugjerim aktiv. Kliko "Skanoj rastin" për të kërkuar veprime të reja.</p>';
      return;
    }
    agentSuggestions.innerHTML = items.map(s => {
      const ico = SUGGESTION_ICONS[s.kind] || "💡";
      const exec = s.status === "executed"
        ? `<span class="agent-pill agent-pill-done">✅ E ekzekutuar (#${s.executed_letter_id || "?"})</span>` : "";
      const payload = s.payload || {};
      const actions = s.status !== "executed" ? `
        <div class="agent-suggestion-actions">
          ${s.kind === "draft_letter" || payload.letter_kind ? `<button type="button" class="primary small" data-execute-letter="${s.id}">✍️ Drafto letrën</button>` : ""}
          ${s.kind !== "draft_letter" ? `<button type="button" class="ghost small" data-execute-letter="${s.id}">✍️ Drafto letër</button>` : ""}
          <button type="button" class="ghost small" data-dismiss="${s.id}">🗑️ Hidhe</button>
        </div>
      ` : "";
      return `
        <div class="agent-suggestion agent-status-${s.status}">
          <div class="agent-suggestion-head">
            <span class="agent-ico">${ico}</span>
            <strong>${escapeHtml(s.title)}</strong>
            <span class="agent-kind">${escapeHtml(s.kind_label)}</span>
            ${exec}
          </div>
          <p class="agent-rationale">${escapeHtml(s.rationale)}</p>
          ${actions}
        </div>`;
    }).join("");
  }

  agentScanBtn?.addEventListener("click", async () => {
    if (!activeCaseId) {
      agentScanStatus.textContent = "Hap një rast së pari.";
      agentScanStatus.className = "pro-status error"; return;
    }
    agentScanStatus.textContent = "Po skanoj rastin (mund të zgjasë 20-40s)…";
    agentScanStatus.className = "pro-status";
    agentScanBtn.disabled = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/agent/scan`, { method: "POST" });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || "skanimi dështoi");
      }
      const data = await r.json();
      agentScanStatus.textContent = data.suggestions.length
        ? `${data.suggestions.length} sugjerime të reja.`
        : "Asnjë veprim urgjent — gjithçka në rregull.";
      agentScanStatus.className = "pro-status ok";
      await loadSuggestions();
    } catch (err) {
      agentScanStatus.textContent = err.message;
      agentScanStatus.className = "pro-status error";
    } finally {
      agentScanBtn.disabled = false;
    }
  });

  agentSuggestions?.addEventListener("click", async (e) => {
    const exec = e.target.closest("[data-execute-letter]");
    const dismiss = e.target.closest("[data-dismiss]");
    if (exec) {
      const sid = parseInt(exec.getAttribute("data-execute-letter"), 10);
      const r = await fetch(`/api/cases/${activeCaseId}/agent/suggestions`);
      const data = r.ok ? await r.json() : { suggestions: [] };
      const s = (data.suggestions || []).find(x => x.id === sid);
      if (!s) return;
      const payload = s.payload || {};
      letterKindSel.value = payload.letter_kind || "client_followup";
      letterRecipient.value = payload.recipient || "";
      letterSubject.value = payload.subject || s.title || "";
      letterContext.value = `Bazuar te sugjerimi: ${s.title}\n${s.rationale}`;
      // Trigger draft with the suggestion ID so it gets marked executed.
      await draftLetter(sid);
    }
    if (dismiss) {
      const sid = dismiss.getAttribute("data-dismiss");
      const r = await fetch(`/api/cases/${activeCaseId}/agent/suggestions/${sid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "dismissed" }),
      });
      if (r.ok) { toast("U hodh", "ok"); await loadSuggestions(); }
    }
  });

  async function draftLetter(suggestionId = null) {
    if (!activeCaseId) {
      letterDraftStatus.textContent = "Hap një rast së pari.";
      letterDraftStatus.className = "pro-status error"; return;
    }
    const body = {
      kind: letterKindSel.value,
      recipient: (letterRecipient.value || "").trim(),
      subject: (letterSubject.value || "").trim(),
      context: (letterContext.value || "").trim(),
    };
    if (suggestionId) body.from_suggestion_id = suggestionId;
    letterDraftStatus.textContent = "Po draftohet (15-30s)…";
    letterDraftStatus.className = "pro-status";
    letterDraftBtn.disabled = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/letters`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || "drafti dështoi");
      }
      const letter = await r.json();
      letterDraftStatus.textContent = "Drafti u krijua.";
      letterDraftStatus.className = "pro-status ok";
      letterContext.value = "";
      renderLetterDetail(letter);
      await Promise.all([loadLetters(), loadSuggestions()]);
      toast("✍️ Letër e draftuar", "ok");
    } catch (err) {
      letterDraftStatus.textContent = err.message;
      letterDraftStatus.className = "pro-status error";
    } finally {
      letterDraftBtn.disabled = false;
    }
  }

  letterDraftBtn?.addEventListener("click", () => draftLetter());

  async function loadLetters() {
    lettersList.innerHTML = '<p class="agent-empty">Duke ngarkuar…</p>';
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/letters`);
      if (!r.ok) throw new Error();
      const data = await r.json();
      const items = data.letters || [];
      if (!items.length) {
        lettersList.innerHTML = '<p class="agent-empty">Ende asnjë letër e draftuar.</p>';
        return;
      }
      lettersList.innerHTML = items.map(l => `
        <div class="agent-letter agent-letter-${l.status}">
          <div class="agent-letter-head">
            <strong>${escapeHtml(l.subject || l.kind_label)}</strong>
            <span class="agent-letter-kind">${escapeHtml(l.kind_label)}</span>
            <span class="agent-letter-status status-${l.status}">${letterStatusLabel(l.status)}</span>
          </div>
          <div class="agent-letter-meta">
            <span>${l.recipient ? "Për: " + escapeHtml(l.recipient) : ""}</span>
            <span>${escapeHtml(l.created_at.slice(0, 10))}</span>
          </div>
          <div class="agent-letter-actions">
            <button type="button" class="ghost small" data-letter-view="${l.id}">📄 Shfaq</button>
            <button type="button" class="ghost small" data-letter-status="${l.id}" data-status="sent" ${l.status !== "draft" ? "disabled" : ""}>✉️ Shëno si dërguar</button>
            <button type="button" class="ghost small" data-letter-status="${l.id}" data-status="archived" ${l.status === "archived" ? "disabled" : ""}>📦 Arkivo</button>
            <button type="button" class="icon-btn danger small" data-letter-del="${l.id}" title="Fshi">🗑️</button>
          </div>
        </div>
      `).join("");
    } catch {
      lettersList.innerHTML = '<p class="agent-empty error">Gabim në ngarkim.</p>';
    }
  }

  function letterStatusLabel(s) {
    return ({ draft: "Bozzë", sent: "Dërguar", archived: "Arkivuar" })[s] || s;
  }

  function renderLetterDetail(l) {
    letterDetail.hidden = false;
    const md = l.body_md || "";
    letterDetail.innerHTML = `
      <div class="agent-letter-detail-head">
        <h4>📄 ${escapeHtml(l.subject || l.kind_label)} ${l.recipient ? "— " + escapeHtml(l.recipient) : ""}</h4>
        <div>
          <button type="button" class="ghost small" id="letter-edit-toggle">✏️ Modifiko</button>
          <button type="button" class="ghost small" id="letter-copy-md">📋 Kopjo</button>
          <button type="button" class="ghost small" id="letter-download-md">⬇️ Shkarko</button>
          <button type="button" class="icon-btn" id="letter-detail-close" title="Mbyll">×</button>
        </div>
      </div>
      <pre id="letter-body-view" class="agent-letter-md">${escapeHtml(md)}</pre>
      <textarea id="letter-body-edit" class="agent-letter-edit" hidden rows="14">${escapeHtml(md)}</textarea>
      <div id="letter-edit-actions" class="pro-actions" hidden>
        <button type="button" class="primary" id="letter-save-edit">💾 Ruaj</button>
        <button type="button" class="ghost" id="letter-cancel-edit">Anulo</button>
      </div>
    `;
    const view = document.getElementById("letter-body-view");
    const edit = document.getElementById("letter-body-edit");
    const editActions = document.getElementById("letter-edit-actions");

    document.getElementById("letter-edit-toggle")?.addEventListener("click", () => {
      view.hidden = true; edit.hidden = false; editActions.hidden = false;
      edit.focus();
    });
    document.getElementById("letter-cancel-edit")?.addEventListener("click", () => {
      edit.value = md; view.hidden = false; edit.hidden = true; editActions.hidden = true;
    });
    document.getElementById("letter-save-edit")?.addEventListener("click", async () => {
      const newBody = edit.value;
      const r = await fetch(`/api/cases/${activeCaseId}/letters/${l.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body_md: newBody }),
      });
      if (r.ok) { toast("Ruajtur", "ok"); renderLetterDetail(await r.json()); }
    });
    document.getElementById("letter-copy-md")?.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(md); toast("U kopjua", "ok"); }
      catch { toast("Kopja dështoi", "error"); }
    });
    document.getElementById("letter-download-md")?.addEventListener("click", () => {
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `letter-${l.id}.md`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    });
    document.getElementById("letter-detail-close")?.addEventListener("click", () => {
      letterDetail.hidden = true; letterDetail.innerHTML = "";
    });
  }

  lettersList?.addEventListener("click", async (e) => {
    const view = e.target.closest("[data-letter-view]");
    const stat = e.target.closest("[data-letter-status]");
    const del = e.target.closest("[data-letter-del]");
    if (view) {
      const id = view.getAttribute("data-letter-view");
      const r = await fetch(`/api/cases/${activeCaseId}/letters/${id}`);
      if (r.ok) renderLetterDetail(await r.json());
    }
    if (stat) {
      const id = stat.getAttribute("data-letter-status");
      const status = stat.getAttribute("data-status");
      const r = await fetch(`/api/cases/${activeCaseId}/letters/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (r.ok) { toast(`Status → ${letterStatusLabel(status)}`, "ok"); await loadLetters(); }
    }
    if (del) {
      if (!confirm("Heq këtë letër?")) return;
      const id = del.getAttribute("data-letter-del");
      const r = await fetch(`/api/cases/${activeCaseId}/letters/${id}`, { method: "DELETE" });
      if (r.ok) { toast("U hoq", "ok"); letterDetail.hidden = true; letterDetail.innerHTML = ""; await loadLetters(); }
    }
  });

  // ── 🎭 V8.8 REHEARSAL (judge / opposing / coach) ─────────────────
  const rehearsalModal = document.getElementById("rehearsal-modal");
  const rehearsalFeed = document.getElementById("rehearsal-feed");
  const rehearsalInput = document.getElementById("rehearsal-input");
  const rehearsalMicBtn = document.getElementById("rehearsal-mic-btn");
  const rehearsalSendBtn = document.getElementById("rehearsal-send-btn");
  const rehearsalClearBtn = document.getElementById("rehearsal-clear-btn");
  const rehearsalTtsToggle = document.getElementById("rehearsal-tts-toggle");
  const rehearsalStatus = document.getElementById("rehearsal-status");
  const rehearsalModeBtns = document.querySelectorAll(".rehearsal-mode-btn");

  let rehearsalMode = "judge";
  let rehearsalHistory = [];   // [{role, content}]
  let rehearsalRec = null;
  let rehearsalListening = false;

  function initRehearsal() {
    if (!rehearsalHistory.length) {
      rehearsalFeed.innerHTML = '<p class="rehearsal-empty">Zgjidh një rol më lart, pastaj shkruaj ose dikto argumentin tënd. AI-i do të të përgjigjet në rolin e zgjedhur.</p>';
    }
  }

  rehearsalModeBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      rehearsalModeBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      rehearsalMode = btn.getAttribute("data-mode");
      rehearsalStatus.textContent = `Rol: ${btn.querySelector("strong").textContent}`;
      rehearsalStatus.className = "pro-status";
    });
  });

  function renderRehearsalFeed() {
    if (!rehearsalHistory.length) {
      rehearsalFeed.innerHTML = '<p class="rehearsal-empty">Zgjidh një rol më lart, pastaj shkruaj ose dikto argumentin tënd.</p>';
      return;
    }
    rehearsalFeed.innerHTML = rehearsalHistory.map(t => {
      const cls = t.role === "user" ? "rh-user" : `rh-assistant rh-${t.mode || "judge"}`;
      const label = t.role === "user" ? "🎤 TI"
        : t.mode === "judge" ? "⚖️ GJYQTARI"
        : t.mode === "opposing" ? "🥊 KUNDËRSHTARI"
        : "🎓 TRAJNERI";
      return `
        <div class="rehearsal-bubble ${cls}">
          <div class="rh-meta">${label}</div>
          <div>${escapeHtml(t.content).replace(/\n/g, "<br>")}</div>
        </div>`;
    }).join("");
    rehearsalFeed.scrollTop = rehearsalFeed.scrollHeight;
  }

  function speakReply(text) {
    if (!rehearsalTtsToggle.checked) return;
    if (!("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "sq-AL";
      u.rate = 1.0;
      window.speechSynthesis.speak(u);
    } catch {}
  }

  rehearsalSendBtn?.addEventListener("click", async () => {
    const text = (rehearsalInput.value || "").trim();
    if (text.length < 10) {
      rehearsalStatus.textContent = "Shkruaj të paktën 10 karaktere.";
      rehearsalStatus.className = "pro-status error";
      return;
    }
    rehearsalHistory.push({ role: "user", content: text });
    rehearsalInput.value = "";
    renderRehearsalFeed();
    rehearsalStatus.textContent = "AI po mendon…";
    rehearsalStatus.className = "pro-status";
    rehearsalSendBtn.disabled = true;

    const body = {
      mode: rehearsalMode,
      user_text: text,
      history: rehearsalHistory.slice(0, -1).map(t => ({
        role: t.role,
        content: t.content,
      })),
    };
    if (activeCaseId) body.case_id = activeCaseId;

    try {
      const r = await fetch("/api/rehearsal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || "AI dështoi");
      }
      const data = await r.json();
      rehearsalHistory.push({ role: "assistant", mode: data.mode, content: data.reply });
      renderRehearsalFeed();
      rehearsalStatus.textContent = "✓";
      rehearsalStatus.className = "pro-status ok";
      speakReply(data.reply);
    } catch (err) {
      rehearsalStatus.textContent = err.message;
      rehearsalStatus.className = "pro-status error";
    } finally {
      rehearsalSendBtn.disabled = false;
    }
  });

  rehearsalClearBtn?.addEventListener("click", () => {
    if (rehearsalHistory.length && !confirm("Pastroj sesionin?")) return;
    rehearsalHistory = [];
    renderRehearsalFeed();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    rehearsalStatus.textContent = "Sesioni u pastrua.";
    rehearsalStatus.className = "pro-status ok";
  });

  // Voice input
  const RehSR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!RehSR) {
    rehearsalMicBtn?.setAttribute("disabled", "");
    rehearsalMicBtn?.setAttribute("title", "Shfletuesi yt nuk e mbështet diktimin.");
  } else {
    rehearsalMicBtn?.addEventListener("click", () => {
      if (rehearsalListening) {
        try { rehearsalRec?.stop(); } catch {}
        rehearsalListening = false;
        rehearsalMicBtn.classList.remove("listening");
        return;
      }
      rehearsalRec = new RehSR();
      rehearsalRec.lang = "sq-AL";
      rehearsalRec.interimResults = true;
      rehearsalRec.continuous = true;
      let baseline = rehearsalInput.value;
      rehearsalRec.onresult = (e) => {
        let interim = "", final = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) final += t + " ";
          else interim += t;
        }
        if (final) baseline = (baseline ? baseline.trim() + " " : "") + final.trim();
        rehearsalInput.value = (baseline + (interim ? " " + interim : "")).trim();
      };
      rehearsalRec.onerror = () => { rehearsalListening = false; rehearsalMicBtn.classList.remove("listening"); };
      rehearsalRec.onend = () => {
        if (rehearsalListening) { try { rehearsalRec.start(); } catch {} }
      };
      try {
        rehearsalRec.start();
        rehearsalListening = true;
        rehearsalMicBtn.classList.add("listening");
      } catch {
        rehearsalStatus.textContent = "S'fillova mikrofonin.";
        rehearsalStatus.className = "pro-status error";
      }
    });
  }

  // Stop voice/TTS when modal closes
  rehearsalModal?.addEventListener("transitionend", () => {});

  // ── V8.9 INBOX ──────────────────────────────────────────────────
  const inboxModal = document.getElementById("inbox-modal");
  const inboxList = document.getElementById("inbox-list");
  const inboxDetail = document.getElementById("inbox-detail");
  const inboxDetailBody = document.getElementById("inbox-detail-body");
  const inboxStatus = document.getElementById("inbox-status");
  const inboxBadge = document.getElementById("pro-inbox-badge");
  const inboxRefreshBtn = document.getElementById("inbox-refresh-btn");
  const inboxShareLinkBtn = document.getElementById("inbox-share-link-btn");
  const inboxDetailBack = document.getElementById("inbox-detail-back");
  const inboxTabs = document.querySelectorAll(".inbox-tab");
  let inboxCurrentTab = "new";
  let inboxLeads = [];

  const URGENCY_BADGE = {
    high: { label: "🔴 Urgjente", cls: "u-high" },
    medium: { label: "🟡 E zakonshme", cls: "u-medium" },
    low: { label: "🟢 Jo urgjente", cls: "u-low" },
  };
  const SOURCE_BADGE = { web: "🌐 Web", telegram: "✈️ Telegram", manual: "✍️ Manual" };

  function setInboxStatus(msg, kind) {
    if (!inboxStatus) return;
    inboxStatus.textContent = msg || "";
    inboxStatus.className = "pro-status" + (kind ? " " + kind : "");
  }

  async function loadInbox() {
    if (!inboxList) return;
    inboxList.innerHTML = '<p class="inbox-empty">Duke ngarkuar…</p>';
    inboxDetail.hidden = true;
    try {
      const r = await fetch("/api/leads", { credentials: "same-origin" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        inboxList.innerHTML = `<p class="inbox-empty">Gabim: ${err.error || r.status}</p>`;
        return;
      }
      const data = await r.json();
      inboxLeads = data.leads || [];
      const counts = data.counts || {};
      ["new", "contacted", "converted", "rejected"].forEach((k) => {
        const el = document.getElementById("inbox-count-" + k);
        if (el) el.textContent = counts[k] || 0;
      });
      if (inboxBadge) {
        if (counts.new > 0) {
          inboxBadge.textContent = counts.new;
          inboxBadge.hidden = false;
        } else {
          inboxBadge.hidden = true;
        }
      }
      renderInboxList();
    } catch (e) {
      inboxList.innerHTML = '<p class="inbox-empty">S\'mund të lidhem me serverin.</p>';
    }
  }

  function renderInboxList() {
    const filtered = inboxLeads.filter(l => l.status === inboxCurrentTab);
    if (!filtered.length) {
      const labels = { new: "kërkesa të reja", contacted: "kërkesa të kontaktuara",
                       converted: "kërkesa të konvertuara", rejected: "kërkesa të refuzuara" };
      inboxList.innerHTML = `<p class="inbox-empty">Asnjë ${labels[inboxCurrentTab] || "kërkesë"} për momentin.</p>`;
      return;
    }
    inboxList.innerHTML = filtered.map(l => {
      const urg = URGENCY_BADGE[l.ai_urgency] || URGENCY_BADGE.medium;
      const summary = (l.ai_summary || l.problem_text || "").slice(0, 180);
      const when = (l.created_at || "").slice(0, 16).replace("T", " ");
      const contact = [l.contact_phone, l.contact_email].filter(Boolean).join(" · ");
      return `<button type="button" class="inbox-card-row" data-lead="${l.id}">
        <div class="inbox-row-head">
          <span class="inbox-urgency ${urg.cls}">${urg.label}</span>
          <span class="inbox-source">${SOURCE_BADGE[l.source] || l.source}</span>
          ${l.ai_area && l.ai_area !== "tjeter" ? `<span class="inbox-area">${l.ai_area}</span>` : ""}
          <span class="inbox-when">${when}</span>
        </div>
        <div class="inbox-row-name"><strong>${escapeHtml(l.contact_name)}</strong>${contact ? ` <em>· ${escapeHtml(contact)}</em>` : ""}</div>
        <div class="inbox-row-summary">${escapeHtml(summary)}${summary.length === 180 ? "…" : ""}</div>
      </button>`;
    }).join("");
    inboxList.querySelectorAll("[data-lead]").forEach(btn => {
      btn.addEventListener("click", () => openLeadDetail(parseInt(btn.dataset.lead, 10)));
    });
  }

  function openLeadDetail(leadId) {
    const lead = inboxLeads.find(l => l.id === leadId);
    if (!lead) return;
    const urg = URGENCY_BADGE[lead.ai_urgency] || URGENCY_BADGE.medium;
    const missing = (lead.ai_missing || []);
    const contactBits = [];
    if (lead.contact_phone) contactBits.push(`<a href="tel:${escapeHtml(lead.contact_phone)}">📞 ${escapeHtml(lead.contact_phone)}</a>`);
    if (lead.contact_email) contactBits.push(`<a href="mailto:${escapeHtml(lead.contact_email)}">✉️ ${escapeHtml(lead.contact_email)}</a>`);
    inboxDetailBody.innerHTML = `
      <div class="inbox-detail-head">
        <h4>${escapeHtml(lead.contact_name)}</h4>
        <div class="inbox-detail-meta">
          <span class="inbox-urgency ${urg.cls}">${urg.label}</span>
          <span class="inbox-source">${SOURCE_BADGE[lead.source] || lead.source}</span>
          ${lead.ai_area && lead.ai_area !== "tjeter" ? `<span class="inbox-area">${escapeHtml(lead.ai_area)}</span>` : ""}
          <span class="inbox-when">${(lead.created_at || "").slice(0, 16).replace("T", " ")}</span>
        </div>
      </div>
      ${contactBits.length ? `<div class="inbox-contacts">${contactBits.join(" &nbsp;|&nbsp; ")}</div>` : ""}
      ${lead.ai_summary ? `<div class="inbox-summary"><strong>Përmbledhje AI:</strong> ${escapeHtml(lead.ai_summary)}</div>` : ""}
      <div class="inbox-problem">
        <strong>Përshkrimi origjinal:</strong>
        <pre>${escapeHtml(lead.problem_text)}</pre>
      </div>
      ${missing.length ? `<div class="inbox-missing">
        <strong>Pyetje të rëndësishme që mungojnë:</strong>
        <ul>${missing.map(q => `<li>${escapeHtml(q)}</li>`).join("")}</ul>
      </div>` : ""}
      <div class="inbox-actions">
        ${lead.status === "new" ? `<button type="button" class="primary" data-act="convert" data-lead="${lead.id}">📁 Konverto në rast</button>` : ""}
        ${lead.status === "new" ? `<button type="button" class="ghost" data-act="contacted" data-lead="${lead.id}">📞 Shëno: kontaktuar</button>` : ""}
        ${lead.status !== "converted" && lead.status !== "rejected" ? `<button type="button" class="ghost danger" data-act="reject" data-lead="${lead.id}">🚫 Refuzo</button>` : ""}
        ${lead.status === "converted" && lead.converted_case_id ? `<button type="button" class="primary" data-act="open-case" data-case="${escapeHtml(lead.converted_case_id)}">↗ Hap rastin</button>` : ""}
      </div>
    `;
    inboxList.style.display = "none";
    inboxDetail.hidden = false;
    inboxDetailBody.querySelectorAll("[data-act]").forEach(btn => {
      btn.addEventListener("click", () => handleLeadAction(btn.dataset.act, btn.dataset.lead, btn.dataset.case));
    });
  }

  async function handleLeadAction(action, leadId, caseId) {
    if (action === "open-case" && caseId) {
      closeProModal(inboxModal);
      await renderCaseList();
      await selectCase(caseId);
      return;
    }
    if (action === "convert") {
      setInboxStatus("Po krijoj rastin…");
      try {
        const r = await fetch(`/api/leads/${leadId}/convert`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({}),
        });
        const data = await r.json();
        if (!r.ok) {
          setInboxStatus("Gabim: " + (data.error || r.status), "error");
          return;
        }
        setInboxStatus("Rasti u krijua.", "ok");
        closeProModal(inboxModal);
        await renderCaseList();
        if (data.case_id) await selectCase(data.case_id);
      } catch (e) {
        setInboxStatus("Gabim lidhjeje.", "error");
      }
      return;
    }
    if (action === "contacted" || action === "reject") {
      const newStatus = action === "contacted" ? "contacted" : "rejected";
      setInboxStatus("Po ruaj…");
      try {
        const r = await fetch(`/api/leads/${leadId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ status: newStatus, claim: action === "contacted" }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          setInboxStatus("Gabim: " + (err.error || r.status), "error");
          return;
        }
        setInboxStatus("U ruajt.", "ok");
        await loadInbox();
      } catch (e) {
        setInboxStatus("Gabim lidhjeje.", "error");
      }
    }
  }

  inboxTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      inboxTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      inboxCurrentTab = tab.dataset.tab;
      inboxList.style.display = "";
      inboxDetail.hidden = true;
      renderInboxList();
    });
  });
  inboxRefreshBtn?.addEventListener("click", loadInbox);
  inboxDetailBack?.addEventListener("click", () => {
    inboxDetail.hidden = true;
    inboxList.style.display = "";
  });
  inboxShareLinkBtn?.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/firm/list", { credentials: "same-origin" });
      if (!r.ok) { setInboxStatus("S'gjeta studion.", "error"); return; }
      const data = await r.json();
      const active = (data.firms || []).find(f => f.id === data.active_firm_id) || (data.firms || [])[0];
      if (!active || !active.slug) { setInboxStatus("Studio pa slug.", "error"); return; }
      const url = `${location.origin}/intake/${active.slug}`;
      try { await navigator.clipboard.writeText(url); setInboxStatus("Linku u kopjua: " + url, "ok"); }
      catch { setInboxStatus(url, "ok"); }
    } catch (e) {
      setInboxStatus("Gabim lidhjeje.", "error");
    }
  });

  // Poll inbox count every 60s when logged in (badge on the pro-menu)
  async function pollInboxBadge() {
    try {
      const r = await fetch("/api/leads?status=new", { credentials: "same-origin" });
      if (!r.ok) return;
      const data = await r.json();
      const n = (data.counts && data.counts.new) || 0;
      if (inboxBadge) {
        if (n > 0) { inboxBadge.textContent = n; inboxBadge.hidden = false; }
        else { inboxBadge.hidden = true; }
      }
    } catch {}
  }
  setInterval(pollInboxBadge, 60000);
  pollInboxBadge();

  // ════════════════════════════════════════════════════════════════
  //   V8.14 → V9.0 — UI WIRING (financial / workflow / time-recon /
  //   settlement / genio)
  // ════════════════════════════════════════════════════════════════

  function fmtEur(cents) {
    if (cents == null) return "—";
    const v = Math.round(cents / 100);
    return v.toLocaleString("sq-AL") + " €";
  }
  function fmtEurFloat(eur) {
    if (eur == null || Number.isNaN(eur)) return "—";
    return Math.round(eur).toLocaleString("sq-AL") + " €";
  }
  function htmlEsc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── V9.0 GENIO LEGALE ──────────────────────────────────────────
  const genioRunBtn   = document.getElementById("genio-run");
  const genioDescEl   = document.getElementById("genio-description");
  const genioStatusEl = document.getElementById("genio-status");
  const genioGrid     = document.getElementById("genio-grid");
  const genioHistEl   = document.getElementById("genio-history");
  let _genioES = null;

  function initGenio() {
    if (!activeCaseId) {
      genioStatusEl.textContent = "Hap një rast së pari.";
      genioStatusEl.className = "pro-status error";
      return;
    }
    genioStatusEl.textContent = "";
    genioStatusEl.className = "pro-status";
    loadGenioHistory();
  }
  async function loadGenioHistory() {
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/genio`);
      if (!r.ok) return;
      const data = await r.json();
      genioHistEl.innerHTML = `<option value="">— i ri —</option>` +
        (data.items || []).map(b => {
          const dt = (b.started_at || "").slice(0, 16).replace("T", " ");
          return `<option value="${b.id}">#${b.id} · ${b.status} · ${dt}</option>`;
        }).join("");
    } catch {}
  }
  genioHistEl?.addEventListener("change", async () => {
    const id = genioHistEl.value;
    if (!id) return;
    try {
      const r = await fetch(`/api/genio/${id}`);
      if (!r.ok) return;
      const brief = await r.json();
      genioGrid.hidden = false;
      Object.entries(brief.by_key || {}).forEach(([key, res]) => {
        renderGenioCard(key, res);
      });
      genioStatusEl.textContent = `Brief #${brief.id} u ngarkua ✓`;
      genioStatusEl.className = "pro-status ok";
    } catch (e) {
      genioStatusEl.textContent = "Gabim ngarkimi: " + e.message;
      genioStatusEl.className = "pro-status error";
    }
  });
  genioRunBtn?.addEventListener("click", () => {
    if (!activeCaseId) return;
    if (_genioES) { try { _genioES.close(); } catch {} _genioES = null; }
    const desc = (genioDescEl.value || "").trim();
    genioGrid.hidden = false;
    genioGrid.querySelectorAll(".genio-card").forEach(c => {
      c.classList.remove("is-done", "is-error");
      c.classList.add("is-running");
      c.querySelector(".genio-badge").textContent = "duke menduar…";
      c.querySelector(".genio-body").innerHTML = "";
    });
    genioStatusEl.textContent = "Genio po pyet 6 mendje paralele…";
    genioStatusEl.className = "pro-status";
    genioRunBtn.disabled = true;

    fetch(`/api/cases/${activeCaseId}/genio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: desc }),
    }).then(async (resp) => {
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const p of parts) {
          const line = p.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const evt = JSON.parse(line.slice(5).trim());
            handleGenioEvent(evt);
          } catch {}
        }
      }
    }).catch((err) => {
      genioStatusEl.textContent = "Gabim: " + err.message;
      genioStatusEl.className = "pro-status error";
    }).finally(() => {
      genioRunBtn.disabled = false;
    });
  });
  function handleGenioEvent(evt) {
    if (evt.type === "perspective") {
      renderGenioCard(evt.result.key, evt.result);
    } else if (evt.type === "completed") {
      genioStatusEl.textContent = `U mbarua në ${(evt.elapsed_ms/1000).toFixed(1)}s ✓`;
      genioStatusEl.className = "pro-status ok";
    } else if (evt.type === "done") {
      loadGenioHistory();
    }
  }
  function renderGenioCard(key, res) {
    const card = genioGrid.querySelector(`.genio-card[data-key="${key}"]`);
    if (!card) return;
    card.classList.remove("is-running");
    const badge = card.querySelector(".genio-badge");
    const body = card.querySelector(".genio-body");
    if (res.kind === "error") {
      card.classList.add("is-error");
      badge.textContent = "gabim";
      body.textContent = res.error || "—";
      return;
    }
    card.classList.add("is-done");
    badge.textContent = `${(res.ms/1000).toFixed(1)}s`;
    body.innerHTML = renderGenioContent(key, res);
  }
  function renderGenioContent(key, res) {
    if (res.kind === "text" || !res.parsed) {
      return `<div>${htmlEsc(res.raw || "").replace(/\n/g, "<br>")}</div>`;
    }
    const p = res.parsed;
    if (key === "riframing") {
      return `<div class="gn-section"><span class="gn-label">Aktual:</span> ${htmlEsc(p.current_framing||"—")}</div>` +
        `<ul>${(p.alternatives||[]).map(a => `<li><strong>${htmlEsc(a.name)}</strong> (rank ${a.rank}) — ${htmlEsc(a.thesis||"")}</li>`).join("")}</ul>` +
        `<div class="gn-section"><span class="gn-label">Verdikti:</span> ${htmlEsc(p.verdict||"")}</div>`;
    }
    if (key === "kill_shot") {
      return `<ul>${(p.kill_shots||[]).map(k => `<li><strong>#${k.rank} ${htmlEsc(k.title||"")}</strong> — letaliteti ${k.lethality}/10. ${htmlEsc(k.mechanics||"")}<br><em>Kontrasulmi:</em> ${htmlEsc(k.our_counter_prep||"")}</li>`).join("")}</ul>` +
        (p.fatal_combo_warning ? `<div class="gn-section"><span class="gn-label">Combo:</span> ${htmlEsc(p.fatal_combo_warning)}</div>` : "");
    }
    if (key === "leverage") {
      return `<ul>${(p.leverage_points||[]).map(l => `<li><strong>#${l.rank} ${htmlEsc(l.lever||"")}</strong> (rrezik etik: ${l.ethical_risk})<br>${htmlEsc(l.why_it_works||"")}<br><em>Aktivizim:</em> ${htmlEsc(l.activation||"")}</li>`).join("")}</ul>`;
    }
    if (key === "decision_tree") {
      return `<div class="gn-section"><span class="gn-label">Rrënja:</span> ${htmlEsc(p.root_label||"")}</div>` +
        `<ul>${(p.branches||[]).map(b => `<li><strong>${htmlEsc(b.our_move||"")}</strong>: ${(b.their_responses||[]).map(r => `${htmlEsc(r.label||"")} (p=${r.probability}, EV=${fmtEurFloat(r.expected_value_eur)})`).join(" · ")}</li>`).join("")}</ul>` +
        `<div class="gn-section"><span class="gn-label">EV totale:</span> ${fmtEurFloat(p.expected_value_total_eur)} — ${htmlEsc(p.recommended_path||"")}</div>`;
    }
    if (key === "brutal_truth") {
      const rv = p.real_value_eur || {};
      return `<div class="gn-section"><span class="gn-label">Vlera reale:</span> ${fmtEurFloat(rv.low)} → <strong>${fmtEurFloat(rv.likely)}</strong> → ${fmtEurFloat(rv.high)}</div>` +
        `<div class="gn-section"><span class="gn-label">Win prob:</span> ${Math.round((p.win_probability||0)*100)}%</div>` +
        `<div class="gn-section"><span class="gn-label">Rekomandimi:</span> <strong>${htmlEsc(p.honest_recommendation||"")}</strong></div>` +
        `<div class="gn-section"><span class="gn-label">Thuaji klientit:</span> ${htmlEsc(p.what_to_tell_client_today||"")}</div>`;
    }
    return `<pre style="font-size:11px;white-space:pre-wrap">${htmlEsc(JSON.stringify(p, null, 2))}</pre>`;
  }

  // ── V9.2 PRECEDENT PATTERN ANALYZER ────────────────────────────
  const precRunBtn   = document.getElementById("precedent-run");
  const precDescEl   = document.getElementById("precedent-description");
  const precTopkEl   = document.getElementById("precedent-topk");
  const precStatusEl = document.getElementById("precedent-status");
  const precResultEl = document.getElementById("precedent-result");
  const precHistEl   = document.getElementById("precedent-history");

  function initPrecedent() {
    if (precStatusEl) {
      precStatusEl.textContent = "";
      precStatusEl.className = "pro-status";
    }
    loadPrecedentHistory();
  }
  async function loadPrecedentHistory() {
    if (!precHistEl) return;
    try {
      const url = activeCaseId
        ? `/api/cases/${activeCaseId}/precedent`
        : `/api/precedent`;
      const r = await fetch(url);
      if (!r.ok) return;
      const data = await r.json();
      precHistEl.innerHTML = `<option value="">— i ri —</option>` +
        (data.items || []).map(b => {
          const dt = (b.started_at || "").slice(0, 16).replace("T", " ");
          const lbl = (b.case_description || "").slice(0, 50);
          return `<option value="${b.id}">#${b.id} · ${b.status} · ${dt} · ${htmlEsc(lbl)}</option>`;
        }).join("");
    } catch {}
  }
  precHistEl?.addEventListener("change", async () => {
    const id = precHistEl.value;
    if (!id) return;
    try {
      const r = await fetch(`/api/precedent/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const row = await r.json();
      renderPrecedentBrief(row.brief || {});
      precStatusEl.textContent = `Brief #${row.id} u ngarkua ✓`;
      precStatusEl.className = "pro-status ok";
    } catch (e) {
      precStatusEl.textContent = "Gabim ngarkimi: " + e.message;
      precStatusEl.className = "pro-status error";
    }
  });
  precRunBtn?.addEventListener("click", async () => {
    const desc = (precDescEl.value || "").trim();
    if (!desc && !activeCaseId) {
      precStatusEl.textContent = "Shkruaj një përshkrim ose hap një rast.";
      precStatusEl.className = "pro-status error";
      return;
    }
    const topK = parseInt(precTopkEl.value || "5", 10);
    precRunBtn.disabled = true;
    precStatusEl.textContent = "Po kërkon precedentët, po lexon ratio decidendi, po sintetizon… (~2-4 min — mos e mbyll dritaren, po punon)";
    precStatusEl.className = "pro-status";
    precResultEl.hidden = true;
    try {
      const body = { case_description: desc, top_k: topK };
      if (activeCaseId) body.case_id = activeCaseId;
      const r = await fetch(`/api/precedent-analyzer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${r.status}`);
      }
      const started = await r.json();
      const briefId = started.brief_id;
      // The analysis runs server-side (~4-6 min). Poll for the result so
      // we never hold a fragile multi-minute connection open (that dropped
      // as 'load failed'). A blip on one poll just retries the next.
      const t0 = Date.now();
      let done = false;
      for (let i = 0; i < 200 && !done; i++) {
        await new Promise((res) => setTimeout(res, 5000));
        let row;
        try {
          const pr = await fetch(`/api/precedent/${briefId}`);
          if (!pr.ok) continue;
          row = await pr.json();
        } catch (_e) { continue; }
        if (row.status && row.status !== "running") {
          done = true;
          renderPrecedentBrief(row.brief || {});
          const sec = ((row.elapsed_ms || (Date.now() - t0)) / 1000).toFixed(0);
          precStatusEl.textContent = row.status === "error"
            ? "Analiza dështoi. Provo përsëri."
            : `Gati në ${sec}s ✓ (#${briefId})`;
          precStatusEl.className = row.status === "error" ? "pro-status error" : "pro-status ok";
          loadPrecedentHistory();
        } else {
          const el = Math.round((Date.now() - t0) / 1000);
          precStatusEl.textContent = `Po analizon precedentët… (${el}s — mos e mbyll)`;
        }
      }
      if (!done) {
        precStatusEl.textContent = "Po zgjat më shumë — shiko te 'Histori briefe' pas pak.";
        precStatusEl.className = "pro-status";
        loadPrecedentHistory();
      }
    } catch (e) {
      precStatusEl.textContent = "Gabim: " + e.message;
      precStatusEl.className = "pro-status error";
    } finally {
      precRunBtn.disabled = false;
    }
  });
  function _courtLabel(code) {
    return ({
      "kushtetuese": "Gjykata Kushtetuese",
      "gjykata_elarte": "Gjykata e Lartë",
      "ecthr_albania": "GjEDNj (Shqipëri)",
    })[code] || code;
  }
  function renderPrecedentBrief(brief) {
    if (!brief || (brief._parse_error && !brief.precedents?.length)) {
      const why = brief?._parse_error || "Asnjë rezultat.";
      precResultEl.innerHTML = `<div class="pro-status error">${htmlEsc(why)}</div>`;
      precResultEl.hidden = false;
      return;
    }
    const moves = brief.moves_to_imitate || [];
    const traps = brief.traps_to_avoid || [];
    const ks = brief.kill_shot || {};
    const perP = brief.per_precedent || [];
    const div = brief.divergence_warning || "";
    const precs = brief.precedents || [];

    const movesHtml = moves.length
      ? `<ul class="prec-list prec-moves">${moves.map(m => `
          <li>
            <div class="prec-cite">${htmlEsc(m.cite || "")}</div>
            <div class="prec-text">${htmlEsc(m.move || "")}</div>
            <div class="prec-why"><em>Pse zbatohet:</em> ${htmlEsc(m.why_applicable || "")}</div>
          </li>`).join("")}</ul>`
      : `<div class="pro-modal-sub">Asnjë lëvizje fituese e qartë në precedentët e marrë.</div>`;

    const trapsHtml = traps.length
      ? `<ul class="prec-list prec-traps">${traps.map(t => `
          <li>
            <div class="prec-cite">${htmlEsc(t.cite || "")}</div>
            <div class="prec-text">${htmlEsc(t.mistake || "")}</div>
            <div class="prec-why"><em>Sinjal:</em> ${htmlEsc(t.warning_signal || "")}</div>
          </li>`).join("")}</ul>`
      : `<div class="pro-modal-sub">Asnjë kurth i qartë në precedentët e marrë.</div>`;

    const ksHtml = (ks && ks.exists)
      ? `<div class="prec-killshot">
           <div class="prec-killshot-title">💥 Kill-shot</div>
           <div class="prec-text">${htmlEsc(ks.move || "")}</div>
           <div class="prec-why"><em>Bazuar mbi:</em> ${(ks.based_on || []).map(htmlEsc).join(" · ") || "—"}</div>
         </div>`
      : `<div class="pro-modal-sub">Nuk u identifikua kill-shot i vetëm i qartë.</div>`;

    const divHtml = div
      ? `<div class="prec-divergence"><strong>⚠ Sinjale të përziera:</strong> ${htmlEsc(div)}</div>`
      : "";

    const perPMap = new Map((perP || []).map(p => [p.cite, p.relevance]));
    const precsHtml = precs.length
      ? `<ul class="prec-cards">${precs.map(p => {
          const ratioBadge = p.has_ratio
            ? `<span class="prec-badge prec-badge-ratio">ratio ✓</span>`
            : `<span class="prec-badge prec-badge-noratio">vetëm metadata</span>`;
          const arch = p.archetype ? `<span class="prec-arch">${htmlEsc(p.archetype)}</span>` : "";
          const rel = perPMap.get(p.citation) || "";
          const link = p.source_url
            ? `<a href="${htmlEsc(p.source_url)}" target="_blank" rel="noopener">burimi ↗</a>`
            : "";
          const dl = p.download
            ? `<a class="prec-dl" href="/api/precedent-file?f=${encodeURIComponent(p.download)}" title="Shkarko dokumentin origjinal">📎 Shkarko vendimin</a>`
            : "";
          return `
            <li class="prec-card">
              <header>
                <strong>${htmlEsc(p.citation || "")}</strong>
                <span class="prec-court">${htmlEsc(_courtLabel(p.court_code))}</span>
                ${ratioBadge}${arch}
              </header>
              ${p.objekti ? `<div class="prec-objekti">${htmlEsc(p.objekti)}</div>` : ""}
              <footer>
                ${p.outcome ? `<span class="prec-outcome">${htmlEsc(p.outcome)}</span>` : ""}
                <span class="prec-score">BM25: ${p.bm25_score ?? "—"}</span>
                ${link}${dl}
              </footer>
              ${rel ? `<div class="prec-relevance"><em>${htmlEsc(rel)}</em></div>` : ""}
            </li>`;
        }).join("")}</ul>`
      : `<div class="pro-modal-sub">Asnjë precedent i marrë.</div>`;

    precResultEl.innerHTML = `
      ${ksHtml}
      ${divHtml}
      <h4 class="studio-section-title">✓ Lëvizje për t'i imituar</h4>
      ${movesHtml}
      <h4 class="studio-section-title">✗ Kurthe për t'u shmangur</h4>
      ${trapsHtml}
      <h4 class="studio-section-title">📚 Precedentët e marrë (${precs.length})</h4>
      ${precsHtml}
    `;
    precResultEl.hidden = false;
  }

  // ── V9.6 RATIO COACH ───────────────────────────────────────────
  const coachRunBtn    = document.getElementById("coach-run-btn");
  const coachOutcome   = document.getElementById("coach-outcome");
  const coachSummary   = document.getElementById("coach-summary");
  const coachStatus    = document.getElementById("coach-status");
  const coachResult    = document.getElementById("coach-result");
  const coachExisting  = document.getElementById("coach-existing");
  const coachLibrary   = document.getElementById("coach-library");
  const coachRelevant  = document.getElementById("coach-relevant");

  document.querySelectorAll(".coach-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".coach-tab").forEach(b => b.classList.remove("coach-tab-active"));
      document.querySelectorAll(".coach-tab-panel").forEach(p => p.hidden = true);
      btn.classList.add("coach-tab-active");
      const panel = document.getElementById("coach-tab-" + btn.dataset.ctab);
      if (panel) panel.hidden = false;
      if (btn.dataset.ctab === "library") loadCoachLibrary();
      if (btn.dataset.ctab === "relevant") loadCoachRelevant();
      if (btn.dataset.ctab === "postmortem") loadExistingLesson();
    });
  });

  function initCoach() {
    coachStatus.textContent = "";
    coachResult.hidden = true;
    coachExisting.hidden = true;
    document.querySelectorAll(".coach-tab").forEach(b => {
      b.classList.toggle("coach-tab-active", b.dataset.ctab === "postmortem");
    });
    document.querySelectorAll(".coach-tab-panel").forEach(p => {
      p.hidden = p.id !== "coach-tab-postmortem";
    });
    loadExistingLesson();
  }

  async function loadExistingLesson() {
    if (!activeCaseId) {
      coachExisting.hidden = true;
      return;
    }
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/lesson`);
      if (!r.ok) { coachExisting.hidden = true; return; }
      const { lesson } = await r.json();
      if (!lesson) { coachExisting.hidden = true; return; }
      coachExisting.innerHTML = `
        <div class="coach-existing-banner">
          ✓ Ky fascikul tashmë ka post-mortem (${escHtml(lesson.outcome)} · ${(lesson.created_at||"").slice(0,10)})
          <button id="coach-show-existing" class="pro-btn-small">Shfaq</button>
          <button id="coach-del-existing" class="pro-btn-small">Fshi</button>
        </div>`;
      coachExisting.hidden = false;
      document.getElementById("coach-show-existing").addEventListener("click", () => {
        renderLesson(lesson.lesson_json, lesson.outcome);
      });
      document.getElementById("coach-del-existing").addEventListener("click", async () => {
        if (!confirm("Fshi mësimin e këtij fascikuli?")) return;
        await fetch(`/api/cases/${activeCaseId}/lesson`, { method: "DELETE" });
        coachExisting.hidden = true;
        coachResult.hidden = true;
      });
    } catch (e) { coachExisting.hidden = true; }
  }

  coachRunBtn && coachRunBtn.addEventListener("click", async () => {
    if (!activeCaseId) { coachStatus.textContent = "Hap një rast fillimisht."; return; }
    coachRunBtn.disabled = true;
    coachStatus.textContent = "AI po analizon historikun e fascikulit… (≈30-60s)";
    coachResult.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/post-mortem`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          outcome: coachOutcome.value,
          summary_hint: coachSummary.value.trim(),
        }),
      });
      const data = await r.json();
      if (!r.ok) { coachStatus.textContent = data.error || "Gabim."; return; }
      coachStatus.textContent = `✓ ${(data.elapsed_ms/1000).toFixed(1)}s · mësim #${data.lesson_id}`;
      renderLesson(data.lesson, data.outcome);
      loadExistingLesson();
    } catch (e) {
      coachStatus.textContent = "Gabim rrjeti.";
    } finally {
      coachRunBtn.disabled = false;
    }
  });

  function renderLesson(L, outcome) {
    if (!L) { coachResult.hidden = true; return; }
    if (L._parse_error) {
      coachResult.innerHTML = `<div class="coach-err">⚠️ Gabim parsimi: ${escHtml(L._parse_error)}</div>`;
      coachResult.hidden = false;
      return;
    }
    const outClass = outcome === "fituar" ? "coach-out-win"
                   : outcome === "humbur" ? "coach-out-lose"
                   : "coach-out-other";
    const wHtml = (L.what_worked || []).map(w => `<li>✓ ${escHtml(w)}</li>`).join("");
    const fHtml = (L.what_failed || []).map(w => `<li>✗ ${escHtml(w)}</li>`).join("");
    const wsHtml = (L.warning_signs_for_future || []).map(w => `<li>⚠️ ${escHtml(w)}</li>`).join("");
    const codes = (L.applicable_codes || []).map(c => `<span class="coach-tag">${escHtml(c)}</span>`).join(" ");
    const arts = (L.key_articles || []).map(c => `<span class="coach-tag coach-tag-art">${escHtml(c)}</span>`).join(" ");

    coachResult.innerHTML = `
      <div class="coach-card coach-archetype">
        <div class="coach-out ${outClass}">${escHtml(outcome || "")}</div>
        <h4>${escHtml(L.archetype || "—")}</h4>
        <div class="coach-tags">${codes} ${arts}</div>
      </div>
      <div class="coach-card coach-lesson-main">
        <h5>📌 Mësimi i transferueshëm</h5>
        <p>${escHtml(L.transferable_lesson || "")}</p>
      </div>
      <div class="coach-card coach-dispositive">
        <h5>🎯 Faktori vendimtar</h5>
        <p>${escHtml(L.dispositive_factor || "")}</p>
      </div>
      ${wHtml ? `<div class="coach-card coach-worked"><h5>Lëvizjet që funksionuan</h5><ul>${wHtml}</ul></div>` : ""}
      ${fHtml ? `<div class="coach-card coach-failed"><h5>Çfarë dështoi</h5><ul>${fHtml}</ul></div>` : ""}
      ${L.opponent_strategy ? `<div class="coach-card coach-opp"><h5>Strategjia e kundërshtarit</h5><p>${escHtml(L.opponent_strategy)}</p></div>` : ""}
      ${wsHtml ? `<div class="coach-card coach-warn"><h5>Sinjale që duhet të kërkosh në të ardhmen</h5><ul>${wsHtml}</ul></div>` : ""}
    `;
    coachResult.hidden = false;
  }

  async function loadCoachLibrary() {
    if (!coachLibrary) return;
    try {
      const r = await fetch("/api/lessons");
      const { items } = await r.json();
      if (!items.length) { coachLibrary.innerHTML = `<p class="coach-empty">Biblioteka e zbrazët.</p>`; return; }
      coachLibrary.innerHTML = items.map(L => {
        const outClass = L.outcome === "fituar" ? "coach-out-win"
                       : L.outcome === "humbur" ? "coach-out-lose" : "coach-out-other";
        return `<div class="coach-lib-item">
          <div class="coach-lib-head">
            <span class="coach-out ${outClass}">${escHtml(L.outcome || "")}</span>
            <span class="coach-lib-arch">${escHtml(L.archetype || "")}</span>
            <span class="coach-lib-date">${(L.created_at||"").slice(0,10)}</span>
          </div>
          <div class="coach-lib-case">${escHtml(L.case_title || L.case_id)}</div>
          <p class="coach-lib-lesson">${escHtml(L.transferable_lesson || "")}</p>
        </div>`;
      }).join("");
    } catch (e) { coachLibrary.innerHTML = `<p class="coach-empty">Gabim rrjeti.</p>`; }
  }

  async function loadCoachRelevant() {
    if (!coachRelevant) return;
    if (!activeCaseId) { coachRelevant.innerHTML = `<p class="coach-empty">Hap një fascikul fillimisht.</p>`; return; }
    coachRelevant.innerHTML = `<p class="coach-empty">Po kërkoj…</p>`;
    try {
      const r = await fetch("/api/lessons/relevant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: activeCaseId }),
      });
      const { items } = await r.json();
      if (!items.length) { coachRelevant.innerHTML = `<p class="coach-empty">Asnjë mësim relevant nga e shkuara.</p>`; return; }
      coachRelevant.innerHTML = items.map(m => {
        const outClass = m.outcome === "fituar" ? "coach-out-win"
                       : m.outcome === "humbur" ? "coach-out-lose" : "coach-out-other";
        return `<div class="coach-rel-item">
          <div class="coach-lib-head">
            <span class="coach-out ${outClass}">${escHtml(m.outcome || "")}</span>
            <span class="coach-lib-arch">${escHtml(m.archetype || "")}</span>
            <span class="coach-score">match ${m.relevance_score.toFixed(2)}</span>
          </div>
          <p class="coach-lib-lesson">${escHtml(m.transferable_lesson || "")}</p>
          ${m.overlap_terms?.length ? `<div class="coach-overlap">Terma të përbashkëta: ${m.overlap_terms.map(t=>`<code>${escHtml(t)}</code>`).join(" ")}</div>` : ""}
        </div>`;
      }).join("");
    } catch (e) { coachRelevant.innerHTML = `<p class="coach-empty">Gabim rrjeti.</p>`; }
  }

  // Auto-surface relevant lessons when a case is opened (called from selectCase).
  window.surfaceRelevantLessons = async function (caseId) {
    if (!caseId) return;
    const banner = document.getElementById("coach-banner");
    if (!banner) return;
    banner.hidden = true;
    banner.innerHTML = "";
    try {
      const r = await fetch("/api/lessons/relevant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId }),
      });
      if (!r.ok) return;
      const { items } = await r.json();
      if (!items.length) return;
      const top = items[0];
      banner.innerHTML = `
        <div class="coach-banner-inner">
          <span class="coach-banner-icon">📝</span>
          <div class="coach-banner-text">
            <strong>Mësim nga rast i ngjashëm:</strong> ${escHtml(top.transferable_lesson || top.archetype || "")}
            ${items.length > 1 ? ` <em>(+${items.length-1} të tjerë)</em>` : ""}
          </div>
          <button class="pro-btn-small" id="coach-banner-open">Shfaq të gjitha</button>
          <button class="pro-btn-small" id="coach-banner-dismiss" aria-label="Mbyll">×</button>
        </div>`;
      banner.hidden = false;
      document.getElementById("coach-banner-open").addEventListener("click", () => {
        openProModal("coach");
        // switch to relevant tab
        setTimeout(() => {
          const tab = document.querySelector('.coach-tab[data-ctab="relevant"]');
          if (tab) tab.click();
        }, 50);
      });
      document.getElementById("coach-banner-dismiss").addEventListener("click", () => {
        banner.hidden = true;
      });
    } catch (e) { /* silent */ }
  };

  // ── V9.5 VIGILANZA NORMATIVA ───────────────────────────────────
  const vigUploadBtn  = document.getElementById("vig-upload-btn");
  const vigUpContent  = document.getElementById("vig-up-content");
  const vigUpTitle    = document.getElementById("vig-up-title");
  const vigUpSource   = document.getElementById("vig-up-source");
  const vigUpUrl      = document.getElementById("vig-up-url");
  const vigUpDate     = document.getElementById("vig-up-pubdate");
  const vigUpStatus   = document.getElementById("vig-upload-status");
  const vigUpRes      = document.getElementById("vig-upload-result");
  const vigAlertsList = document.getElementById("vig-alerts-list");
  const vigAlertCount = document.getElementById("vig-alert-count");
  const vigShowDism   = document.getElementById("vig-show-dismissed");
  const vigRefreshBtn = document.getElementById("vig-refresh-btn");
  const vigUpdatesList= document.getElementById("vig-updates-list");
  const vigBadge      = document.getElementById("vigilanza-badge");
  const vigTopbarBtn  = document.getElementById("vigilanza-topbar-btn");

  vigTopbarBtn && vigTopbarBtn.addEventListener("click", () => openProModal("vigilanza"));

  // tab switching
  document.querySelectorAll(".vig-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".vig-tab").forEach(b => b.classList.remove("vig-tab-active"));
      document.querySelectorAll(".vig-tab-panel").forEach(p => p.hidden = true);
      btn.classList.add("vig-tab-active");
      const panel = document.getElementById("vig-tab-" + btn.dataset.vtab);
      if (panel) panel.hidden = false;
      if (btn.dataset.vtab === "alerts") loadVigAlerts();
      if (btn.dataset.vtab === "updates") loadVigUpdates();
    });
  });

  vigShowDism && vigShowDism.addEventListener("change", loadVigAlerts);
  vigRefreshBtn && vigRefreshBtn.addEventListener("click", () => {
    loadVigAlerts(); refreshVigBadge();
  });

  function initVigilanza() {
    vigUpRes.hidden = true;
    vigUpStatus.textContent = "";
    document.querySelectorAll(".vig-tab").forEach(b => {
      b.classList.toggle("vig-tab-active", b.dataset.vtab === "alerts");
    });
    document.querySelectorAll(".vig-tab-panel").forEach(p => {
      p.hidden = p.id !== "vig-tab-alerts";
    });
    loadVigAlerts();
  }

  async function refreshVigBadge() {
    try {
      const r = await fetch("/api/vigilanza/alerts/count");
      if (!r.ok) return;
      const { pending } = await r.json();
      if (pending > 0) {
        vigBadge.textContent = pending;
        vigBadge.hidden = false;
      } else {
        vigBadge.hidden = true;
      }
    } catch (e) { /* silent */ }
  }
  // Vigilanza UI suspended (no real Fletorja/gjykataelarte scraping yet).
  // Endpoints and modal logic remain wired; topbar button is hidden and badge polling is off.
  // Re-enable by removing `hidden` from #vigilanza-topbar-btn and restoring the interval below.
  // refreshVigBadge(); setInterval(refreshVigBadge, 120000);

  async function loadVigAlerts() {
    if (!vigAlertsList) return;
    const includeDism = vigShowDism && vigShowDism.checked;
    try {
      const r = await fetch(`/api/vigilanza/alerts${includeDism ? "?all=1" : ""}`);
      if (!r.ok) { vigAlertsList.innerHTML = `<p class="vig-empty">Gabim ngarkimi.</p>`; return; }
      const { items } = await r.json();
      vigAlertCount.textContent = items.filter(i => !i.dismissed).length;
      if (!items.length) {
        vigAlertsList.innerHTML = `<p class="vig-empty">Asnjë alert. Ngarko një ndryshim ligjor ose prit vendimin e radhës.</p>`;
        return;
      }
      vigAlertsList.innerHTML = items.map(renderVigAlert).join("");
      vigAlertsList.querySelectorAll(".vig-alert-dismiss").forEach(btn => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          await fetch(`/api/vigilanza/alerts/${id}/dismiss`, { method: "POST" });
          loadVigAlerts(); refreshVigBadge();
        });
      });
      vigAlertsList.querySelectorAll(".vig-alert-open-case").forEach(btn => {
        btn.addEventListener("click", () => {
          const cid = btn.dataset.caseId;
          if (cid) selectCase(cid);
          closeProModal(document.getElementById("vigilanza-modal"));
        });
      });
    } catch (e) { vigAlertsList.innerHTML = `<p class="vig-empty">Gabim rrjeti.</p>`; }
  }

  function renderVigAlert(a) {
    const cls = a.update_classification || {};
    const urgClass = (cls.urgency || "").includes("lartë") ? "vig-urg-high"
                   : (cls.urgency || "").includes("mesëm") ? "vig-urg-med" : "vig-urg-low";
    const score = (a.relevance_score || 0).toFixed(2);
    const dt = (a.created_at || "").slice(0, 10);
    const codes = (a.match_summary?.matched_codes || []).map(c => `<span class="vig-tag">${escHtml(c)}</span>`).join(" ");
    const arts = (a.match_summary?.matched_articles || []).map(c => `<span class="vig-tag vig-tag-art">${escHtml(c)}</span>`).join(" ");
    return `
      <div class="vig-alert ${a.dismissed ? 'vig-alert-dismissed' : ''}">
        <div class="vig-alert-head">
          <span class="vig-urg ${urgClass}">${escHtml(cls.urgency || "—")}</span>
          <span class="vig-score">match ${score}</span>
          <span class="vig-date">${dt}</span>
          ${a.dismissed ? '<span class="vig-dism">mënjanuar</span>' : ''}
        </div>
        <h4 class="vig-alert-title">${escHtml(a.update_title || "—")}</h4>
        <div class="vig-alert-meta">
          <strong>Fascikul:</strong> ${escHtml(a.case_title || a.case_id)} ·
          <strong>Burim:</strong> ${escHtml(a.update_source || "—")}
          ${a.update_url ? ` · <a href="${escHtml(a.update_url)}" target="_blank" rel="noopener">↗ burimi</a>` : ""}
        </div>
        <p class="vig-alert-summary">${escHtml(cls.summary || "")}</p>
        ${cls.actionable_for_lawyers ? `<div class="vig-alert-action">📌 ${escHtml(cls.actionable_for_lawyers)}</div>` : ""}
        ${(codes || arts) ? `<div class="vig-tags">${codes} ${arts}</div>` : ""}
        <div class="vig-alert-actions">
          <button class="pro-btn-small vig-alert-open-case" data-case-id="${escHtml(a.case_id)}">Hap fascikulin</button>
          ${!a.dismissed ? `<button class="pro-btn-small vig-alert-dismiss" data-id="${a.id}">Mënjano</button>` : ""}
        </div>
      </div>`;
  }

  vigUploadBtn && vigUploadBtn.addEventListener("click", async () => {
    const content = vigUpContent.value.trim();
    if (content.length < 50) { vigUpStatus.textContent = "Përmbajtja shumë e shkurtër (≥50 char)."; return; }
    vigUploadBtn.disabled = true;
    vigUpStatus.textContent = "AI po klasifikon dhe matchon… (≈20-40s)";
    vigUpRes.hidden = true;
    try {
      const r = await fetch("/api/vigilanza/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content, title: vigUpTitle.value.trim(),
          source: vigUpSource.value, source_url: vigUpUrl.value.trim(),
          published_at: vigUpDate.value || null,
        }),
      });
      const data = await r.json();
      if (!r.ok) { vigUpStatus.textContent = data.error || "Gabim."; return; }
      const cls = data.classification || {};
      const matchHtml = (data.matches || []).map(m =>
        `<li><strong>${escHtml(m.case_title || m.case_id)}</strong>
          <span class="vig-score">match ${m.relevance_score.toFixed(2)}</span>
          <div class="vig-tags">${(m.matched_codes||[]).map(c=>`<span class="vig-tag">${escHtml(c)}</span>`).join(" ")}
            ${(m.matched_articles||[]).map(c=>`<span class="vig-tag vig-tag-art">${escHtml(c)}</span>`).join(" ")}</div></li>`).join("");
      vigUpRes.innerHTML = `
        <div class="vig-summary-card">
          <h4>${escHtml(cls.title || "—")}</h4>
          <p>${escHtml(cls.summary || "")}</p>
          <div class="vig-meta">
            ${cls.kind ? `<span class="vig-tag">${escHtml(cls.kind)}</span>` : ""}
            ${cls.urgency ? `<span class="vig-tag">urgency: ${escHtml(cls.urgency)}</span>` : ""}
            ${cls.effective_date ? `<span class="vig-tag">hyn fuqi: ${escHtml(cls.effective_date)}</span>` : ""}
          </div>
          ${cls.actionable_for_lawyers ? `<p class="vig-alert-action">📌 ${escHtml(cls.actionable_for_lawyers)}</p>` : ""}
        </div>
        <h4 class="vig-sub">Fascikujt e prekur (${data.matches.length}, alerte të reja: ${data.alerts_created})</h4>
        <ul class="vig-match-list">${matchHtml || "<li class='vig-empty'>Asnjë fascikul i prekur.</li>"}</ul>`;
      vigUpRes.hidden = false;
      vigUpStatus.textContent = `✓ Krijuar update #${data.update_id}`;
      refreshVigBadge();
    } catch (e) {
      vigUpStatus.textContent = "Gabim rrjeti.";
    } finally {
      vigUploadBtn.disabled = false;
    }
  });

  async function loadVigUpdates() {
    if (!vigUpdatesList) return;
    try {
      const r = await fetch("/api/vigilanza/updates");
      const { items } = await r.json();
      if (!items.length) { vigUpdatesList.innerHTML = `<p class="vig-empty">Histori e zbrazët.</p>`; return; }
      vigUpdatesList.innerHTML = items.map(u => {
        const cls = u.classification || {};
        return `<div class="vig-update">
          <div class="vig-alert-head">
            <span class="vig-tag">${escHtml(u.source)}</span>
            <span class="vig-date">${(u.fetched_at||"").slice(0,10)}</span>
          </div>
          <h4>${escHtml(u.title)}</h4>
          <p>${escHtml(cls.summary || "")}</p>
          ${u.source_url ? `<a href="${escHtml(u.source_url)}" target="_blank" rel="noopener">↗ burimi</a>` : ""}
        </div>`;
      }).join("");
    } catch (e) { vigUpdatesList.innerHTML = `<p class="vig-empty">Gabim rrjeti.</p>`; }
  }

  // ── V9.4 BENCH MEMO ────────────────────────────────────────────
  const benchRunBtn  = document.getElementById("bench-run-btn");
  const benchDescEl  = document.getElementById("bench-desc");
  const benchOppEl   = document.getElementById("bench-opp");
  const benchCourtEl = document.getElementById("bench-court");
  const benchHistEl  = document.getElementById("bench-history");
  const benchStatusEl= document.getElementById("bench-status");
  const benchResEl   = document.getElementById("bench-result");

  function initBench() {
    benchStatusEl.textContent = "";
    benchResEl.hidden = true;
    benchResEl.innerHTML = "";
    loadBenchHistory();
  }

  async function loadBenchHistory() {
    benchHistEl.innerHTML = `<option value="">— Hap memo të mëparshme —</option>`;
    if (!activeCaseId) return;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/bench-memos`);
      if (!r.ok) return;
      const { items } = await r.json();
      (items || []).forEach(it => {
        const opt = document.createElement("option");
        opt.value = it.id;
        const dt = (it.completed_at || it.started_at || "").slice(0, 16).replace("T", " ");
        opt.textContent = `${dt} · ${it.court_code} · ${it.status}`;
        benchHistEl.appendChild(opt);
      });
    } catch (e) { /* silent */ }
  }

  benchHistEl && benchHistEl.addEventListener("change", async () => {
    const id = benchHistEl.value;
    if (!id) return;
    benchStatusEl.textContent = "Duke ngarkuar…";
    try {
      const r = await fetch(`/api/bench-memo/${id}`);
      if (!r.ok) { benchStatusEl.textContent = "Gabim ngarkimi"; return; }
      const data = await r.json();
      benchCourtEl.value = data.court_code || "gjykata_lartë";
      renderBenchMemo(data.memo);
      benchStatusEl.textContent = `✓ Memo ${id}`;
    } catch (e) { benchStatusEl.textContent = "Gabim rrjeti"; }
  });

  benchRunBtn && benchRunBtn.addEventListener("click", async () => {
    if (!activeCaseId) { benchStatusEl.textContent = "Hap një rast fillimisht."; return; }
    benchRunBtn.disabled = true;
    benchStatusEl.textContent = "Gjyqtari po e shqyrton çështjen… (≈45-90s)";
    benchResEl.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/bench-memo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: benchDescEl.value.trim(),
          court_code: benchCourtEl.value,
          opponent_filing: benchOppEl.value.trim(),
        }),
      });
      const data = await r.json();
      if (!r.ok) { benchStatusEl.textContent = data.error || "Gabim."; return; }
      benchStatusEl.textContent = `✓ ${(data.elapsed_ms/1000).toFixed(1)}s · memo #${data.memo_id}`;
      renderBenchMemo(data.memo);
      loadBenchHistory();
    } catch (e) {
      benchStatusEl.textContent = "Gabim rrjeti.";
    } finally {
      benchRunBtn.disabled = false;
    }
  });

  function renderBenchMemo(m) {
    if (!m) { benchResEl.hidden = true; return; }
    if (m._parse_error) {
      benchResEl.innerHTML = `<div class="bench-err">⚠️ Gabim parsimi: ${escHtml(m._parse_error)}</div>` +
        (m._raw ? `<details><summary>Përgjigja e papërpunuar</summary><pre>${escHtml(m._raw)}</pre></details>` : "");
      benchResEl.hidden = false;
      return;
    }

    const op = m.outcome_prediction || {};
    const pP = Number(op.p_plaintiff_pct) || 0;
    const pD = Number(op.p_defendant_pct) || 0;
    const conf = op.confidence || "i ulët";
    const rec = (m.recommendation || "").trim();
    const recCls = rec.startsWith("FIGHT") ? "bench-rec-fight"
                 : rec.startsWith("SETTLE") ? "bench-rec-settle"
                 : rec.startsWith("FOLD") ? "bench-rec-fold" : "";

    const lawHtml = (m.applicable_law || []).map(l =>
      `<li><strong>${escHtml(l.reference || "")}</strong>
        <span class="bench-rel bench-rel-${_relClass(l.relevance)}">${escHtml(l.relevance || "")}</span>
        <em>${escHtml(l.why || "")}</em></li>`).join("");

    const precHtml = (m.controlling_precedents || []).map(p =>
      `<li><strong>${escHtml(p.citation || "")}</strong> — ${escHtml(p.court || "")}
        <span class="bench-out">${escHtml(p.outcome || "")}</span>
        <span class="bench-rel bench-rel-${_relClass(p.weight)}">${escHtml(p.weight || "")}</span>
        <div class="bench-ratio">${escHtml(p.ratio_used || "")}</div></li>`).join("");

    const weakHtml = (m.our_weaknesses || []).map(w =>
      `<li><strong>${escHtml(w.point || "")}</strong>
        <span class="bench-sev bench-sev-${_sevClass(w.severity)}">${escHtml(w.severity || "")}</span>
        <div class="bench-attack">⚔️ ${escHtml(w.judge_attack || "")}</div></li>`).join("");

    const oppHtml = (m.opponent_strengths || []).map(s =>
      `<li><strong>${escHtml(s.point || "")}</strong>
        <span class="bench-rel bench-rel-${_relClass(s.weight)}">${escHtml(s.weight || "")}</span>
        <div class="bench-attack">${escHtml(s.why_judge_accepts || "")}</div></li>`).join("");

    const upgHtml = (m.argument_upgrades || []).map(u => {
      const shift = Number(u.p_shift_pct) || 0;
      const sCls = shift > 0 ? "bench-shift-pos" : shift < 0 ? "bench-shift-neg" : "";
      const sign = shift > 0 ? "+" : "";
      return `<li>
        <div class="bench-upg-cur"><strong>Tani:</strong> ${escHtml(u.current || "")}</div>
        <div class="bench-upg-new"><strong>Riformulim:</strong> ${escHtml(u.upgrade || "")}</div>
        <div class="bench-shift ${sCls}">P-shift: ${sign}${shift}%</div>
      </li>`;
    }).join("");

    const procHtml = (m.procedural_risks || []).map(r =>
      `<li><strong>⚠️ ${escHtml(r.risk || "")}</strong>
        <div class="bench-mit">↪ ${escHtml(r.mitigation || "")}</div></li>`).join("");

    benchResEl.innerHTML = `
      <div class="bench-card bench-card-rec ${recCls}">
        <div class="bench-rec-label">VERDIKTI I REKOMANDUAR</div>
        <div class="bench-rec-text">${escHtml(rec)}</div>
      </div>

      <div class="bench-card bench-card-issue">
        <h4>📜 Si do ta inkuadrojë gjyqtari</h4>
        <p>${escHtml(m.issue_framing || "")}</p>
      </div>

      <div class="bench-card bench-card-pred">
        <h4>🎯 Parashikimi i rezultatit · besueshmëri ${escHtml(conf)}</h4>
        <div class="bench-pred-bar">
          <div class="bench-pred-p" style="width:${pP}%" title="P(Paditësi fiton): ${pP}%">P ${pP}%</div>
          <div class="bench-pred-d" style="width:${pD}%" title="P(I padituri fiton): ${pD}%">D ${pD}%</div>
        </div>
        <div class="bench-pred-key"><strong>Faktori kyç:</strong> ${escHtml(op.key_factor || "")}</div>
        <div class="bench-pred-court"><em>Kalibrimi për gjykatën:</em> ${escHtml(op.court_calibration_note || "")}</div>
      </div>

      ${lawHtml ? `<div class="bench-card"><h4>📚 Nenet e zbatueshme</h4><ul class="bench-list">${lawHtml}</ul></div>` : ""}
      ${precHtml ? `<div class="bench-card"><h4>⚖️ Precedentë kontrollues</h4><ul class="bench-list">${precHtml}</ul></div>` : ""}
      ${weakHtml ? `<div class="bench-card bench-card-weak"><h4>🔴 Dobësitë tona që do të sulmohen</h4><ul class="bench-list">${weakHtml}</ul></div>` : ""}
      ${oppHtml ? `<div class="bench-card bench-card-opp"><h4>💪 Forcat e kundërshtarit që pranohen</h4><ul class="bench-list">${oppHtml}</ul></div>` : ""}
      ${upgHtml ? `<div class="bench-card bench-card-upg"><h4>🚀 Upgrade argumentesh</h4><ul class="bench-list">${upgHtml}</ul></div>` : ""}
      ${procHtml ? `<div class="bench-card"><h4>⚠️ Rreziqe procedurale</h4><ul class="bench-list">${procHtml}</ul></div>` : ""}
    `;
    benchResEl.hidden = false;
  }

  function _relClass(s) {
    s = (s || "").toLowerCase();
    if (s.includes("lartë") || s.includes("larte")) return "high";
    if (s.includes("mesëm") || s.includes("mesem")) return "med";
    return "low";
  }
  function _sevClass(s) { return _relClass(s); }

  // ── V9.3 CORPORATE INTELLIGENCE ────────────────────────────────
  const corpExtractBtn  = document.getElementById("corp-extract-btn");
  const corpDocText     = document.getElementById("corp-doc-text");
  const corpDocType     = document.getElementById("corp-doc-type");
  const corpDocName     = document.getElementById("corp-doc-name");
  const corpExtractSt   = document.getElementById("corp-extract-status");
  const corpExtractRes  = document.getElementById("corp-extract-result");
  const corpDocsList    = document.getElementById("corp-docs-list");
  const corpGateBtn     = document.getElementById("corp-gate-btn");
  const corpSignatory   = document.getElementById("corp-signatory");
  const corpValue       = document.getElementById("corp-value");
  const corpContractType= document.getElementById("corp-contract-type");
  const corpGateSt      = document.getElementById("corp-gate-status");
  const corpGateRes     = document.getElementById("corp-gate-result");
  const corpKycBtn      = document.getElementById("corp-kyc-btn");
  const corpKycSt       = document.getElementById("corp-kyc-status");
  const corpKycRes      = document.getElementById("corp-kyc-result");

  // Tab switching
  document.querySelectorAll(".corp-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".corp-tab").forEach(b => {
        b.classList.remove("corp-tab-active");
        b.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".corp-tab-panel").forEach(p => p.hidden = true);
      btn.classList.add("corp-tab-active");
      btn.setAttribute("aria-selected", "true");
      const panel = document.getElementById("corp-tab-" + btn.dataset.tab);
      if (panel) panel.hidden = false;
    });
  });

  function initCorporate() {
    corpExtractRes.hidden = true;
    corpGateRes.hidden = true;
    corpKycRes.hidden = true;
    corpExtractSt.textContent = "";
    corpGateSt.textContent = "";
    corpKycSt.textContent = "";
    // reset to extract tab
    document.querySelectorAll(".corp-tab").forEach(b => {
      b.classList.toggle("corp-tab-active", b.dataset.tab === "extract");
      b.setAttribute("aria-selected", b.dataset.tab === "extract" ? "true" : "false");
    });
    document.querySelectorAll(".corp-tab-panel").forEach(p => {
      p.hidden = p.id !== "corp-tab-extract";
    });
    loadCorpDocs();
  }

  async function loadCorpDocs() {
    if (!activeCaseId) { corpDocsList.hidden = true; return; }
    const r = await fetch(`/api/cases/${activeCaseId}/corporate`);
    if (!r.ok) { corpDocsList.hidden = true; return; }
    const { items } = await r.json();
    if (!items || !items.length) { corpDocsList.hidden = true; return; }
    corpDocsList.innerHTML = "<strong>Dokumente të ngarkuara:</strong> " +
      items.map(it =>
        `<span class="corp-doc-chip">${escHtml(it.doc_name)}
          <button class="corp-doc-del" data-id="${it.id}" aria-label="Fshi" title="Fshi">×</button>
        </span>`
      ).join("");
    corpDocsList.hidden = false;
    corpDocsList.querySelectorAll(".corp-doc-del").forEach(btn => {
      btn.addEventListener("click", async () => {
        await fetch(`/api/cases/${activeCaseId}/corporate/${btn.dataset.id}`, { method: "DELETE" });
        loadCorpDocs();
      });
    });
  }

  corpExtractBtn && corpExtractBtn.addEventListener("click", async () => {
    const docText = corpDocText.value.trim();
    if (!docText) { corpExtractSt.textContent = "Ngjit tekstin e dokumentit."; return; }
    if (!activeCaseId) { corpExtractSt.textContent = "Hap një rast fillimisht."; return; }
    corpExtractBtn.disabled = true;
    corpExtractSt.textContent = "Duke ekstraktuar me AI…";
    corpExtractRes.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/corporate/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          doc_text: docText,
          doc_name: corpDocName.value.trim() || corpDocType.options[corpDocType.selectedIndex].text,
          doc_type: corpDocType.value,
        }),
      });
      const data = await r.json();
      if (!r.ok) { corpExtractSt.textContent = data.error || "Gabim."; return; }
      corpExtractSt.textContent = `✓ ${(data.elapsed_ms/1000).toFixed(1)}s`;
      corpExtractRes.innerHTML = renderCorpExtracted(data.extracted);
      corpExtractRes.hidden = false;
      corpDocText.value = "";
      corpDocName.value = "";
      loadCorpDocs();
    } catch (e) {
      corpExtractSt.textContent = "Gabim rrjeti.";
    } finally {
      corpExtractBtn.disabled = false;
    }
  });

  corpGateBtn && corpGateBtn.addEventListener("click", async () => {
    const name = corpSignatory.value.trim();
    if (!name) { corpGateSt.textContent = "Shkruaj emrin e firmataret."; return; }
    if (!activeCaseId) { corpGateSt.textContent = "Hap një rast fillimisht."; return; }
    corpGateBtn.disabled = true;
    corpGateSt.textContent = "Duke kontrolluar autoritetin…";
    corpGateRes.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/corporate/gatekeeper`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signatory_name: name,
          value_all: parseFloat(corpValue.value) || 0,
          contract_type: corpContractType.value.trim() || "kontratë tregtare",
        }),
      });
      const data = await r.json();
      if (!r.ok) { corpGateSt.textContent = data.error || "Gabim."; return; }
      corpGateSt.textContent = `✓ ${(data.elapsed_ms/1000).toFixed(1)}s`;
      corpGateRes.innerHTML = renderGatekeeper(data);
      corpGateRes.hidden = false;
    } catch (e) {
      corpGateSt.textContent = "Gabim rrjeti.";
    } finally {
      corpGateBtn.disabled = false;
    }
  });

  corpKycBtn && corpKycBtn.addEventListener("click", async () => {
    if (!activeCaseId) { corpKycSt.textContent = "Hap një rast fillimisht."; return; }
    corpKycBtn.disabled = true;
    corpKycSt.textContent = "Duke analizuar gap-et KYC…";
    corpKycRes.hidden = true;
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/corporate/kyc`, { method: "POST" });
      const data = await r.json();
      if (!r.ok) { corpKycSt.textContent = data.error || "Gabim."; return; }
      corpKycSt.textContent = "✓ Analiza e plotë";
      corpKycRes.innerHTML = renderKyc(data);
      corpKycRes.hidden = false;
    } catch (e) {
      corpKycSt.textContent = "Gabim rrjeti.";
    } finally {
      corpKycBtn.disabled = false;
    }
  });

  function renderCorpExtracted(ex) {
    if (!ex) return "<p>Nuk u ekstraktua asgjë.</p>";
    const rows = [];
    if (ex.emri_shoqerise) rows.push(["Shoqëria", escHtml(ex.emri_shoqerise)]);
    if (ex.nuis)            rows.push(["NUIS", escHtml(ex.nuis)]);
    if (ex.forma_juridike)  rows.push(["Forma juridike", escHtml(ex.forma_juridike)]);
    if (ex.kapitali_themeltar) rows.push(["Kapitali", escHtml(String(ex.kapitali_themeltar)) + " ALL"]);
    if (ex.veprimtaria)     rows.push(["Veprimtaria", escHtml(ex.veprimtaria)]);
    if (ex.seli)            rows.push(["Selia", escHtml(ex.seli)]);

    let html = rows.length
      ? `<table class="corp-table">${rows.map(([k,v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`
      : "";

    if (ex.soci?.length) {
      html += `<h5 class="corp-sub">Aksionarë/Ortakë</h5><ul class="corp-list">` +
        ex.soci.map(s => `<li><strong>${escHtml(s.emri)}</strong> — ${s.quota_pct ?? "?"}% (${escHtml(s.lloji || "?")})</li>`).join("") +
        `</ul>`;
    }
    if (ex.cda?.length) {
      html += `<h5 class="corp-sub">Organi drejtues (CDA/Administrator)</h5><ul class="corp-list">` +
        ex.cda.map(c => {
          let line = `<strong>${escHtml(c.emri)}</strong> — ${escHtml(c.roli || "?")}`;
          if (c.nenshkrim_forme) line += ` · <em>${escHtml(c.nenshkrim_forme)}</em>`;
          if (c.limit_all) line += ` · limit ${Number(c.limit_all).toLocaleString()} ALL`;
          if (c.mandati_skadon) line += ` · skadon <strong>${escHtml(c.mandati_skadon)}</strong>`;
          return `<li>${line}</li>`;
        }).join("") + `</ul>`;
    }
    if (ex.procure?.length) {
      html += `<h5 class="corp-sub">Prokurorë / Autorizuar</h5><ul class="corp-list">` +
        ex.procure.map(p => {
          let line = `<strong>${escHtml(p.emri)}</strong> — ${escHtml(p.qellimi || "?")}`;
          if (p.limit_all) line += ` · limit ${Number(p.limit_all).toLocaleString()} ALL`;
          if (p.skadon) line += ` · skadon <strong class="${_daysClass(p.skadon)}">${escHtml(p.skadon)}</strong>`;
          if (p.forme) line += ` <em>(${escHtml(p.forme)})</em>`;
          return `<li>${line}</li>`;
        }).join("") + `</ul>`;
    }
    if (ex.anomalie?.length) {
      html += `<div class="corp-anomalie"><strong>⚠️ Anomali:</strong> <ul>` +
        ex.anomalie.map(a => `<li>${escHtml(a)}</li>`).join("") + `</ul></div>`;
    }
    return html || "<p>Asnjë të dhënë të identifikueshme.</p>";
  }

  function renderGatekeeper(d) {
    const ok = d.ka_autoritet;
    const badge = ok
      ? `<span class="corp-gate-ok">✓ KA AUTORITET</span>`
      : `<span class="corp-gate-no">✗ NUK KA AUTORITET</span>`;
    let html = `<div class="corp-gate-header">${badge}</div>`;
    if (d.baza_ligjore) html += `<p><strong>Baza ligjore:</strong> ${escHtml(d.baza_ligjore)}</p>`;
    if (d.fusha_e_autorizimit) html += `<p><strong>Fusha:</strong> ${escHtml(d.fusha_e_autorizimit)}</p>`;
    if (d.limit_financiar_all) {
      const cls = d.brenda_limitit === false ? "corp-warn" : "";
      html += `<p><strong>Limit:</strong> <span class="${cls}">${Number(d.limit_financiar_all).toLocaleString()} ALL</span>`;
      if (d.brenda_limitit === false) html += ` — <strong class="corp-warn">vlera e kontratës e kalon limitin!</strong>`;
      html += `</p>`;
    }
    if (d.skadon) {
      const cls = _daysClass(d.skadon);
      html += `<p><strong>Skadon:</strong> <span class="${cls}">${escHtml(d.skadon)}</span>`;
      if (d.dite_mbetur !== null && d.dite_mbetur !== undefined)
        html += ` (${d.dite_mbetur} ditë)`;
      html += `</p>`;
    }
    if (d.paralajmerime?.length) {
      html += `<ul class="corp-warn-list">` +
        d.paralajmerime.map(w => `<li>⚠️ ${escHtml(w)}</li>`).join("") + `</ul>`;
    }
    if (d.risqe?.length) {
      html += `<ul class="corp-risk-list">` +
        d.risqe.map(r2 => `<li>🔴 ${escHtml(r2)}</li>`).join("") + `</ul>`;
    }
    if (d.rekomandim) {
      html += `<div class="corp-rec">${escHtml(d.rekomandim)}</div>`;
    }
    return html;
  }

  function renderKyc(d) {
    const riskColor = { "i lartë": "corp-risk-high", "i mesëm": "corp-risk-med", "i ulët": "corp-risk-low" };
    let html = `<div class="corp-risk-badge ${riskColor[d.risk_level] || ''}">Rrezik: ${escHtml(d.risk_level || "?")}</div>`;
    if (d.emri_shoqerise) html += `<p><strong>${escHtml(d.emri_shoqerise)}</strong>${d.nuis ? " · NUIS: " + escHtml(d.nuis) : ""}</p>`;

    html += `<table class="corp-kyc-table">` +
      (d.checklist || []).map(item => {
        const icon = item.present ? "✅" : "❌";
        const cls  = item.present ? "" : "corp-missing";
        return `<tr class="${cls}"><td>${icon}</td><td>${escHtml(item.label)}</td><td class="corp-basis">${escHtml(item.basis)}</td></tr>`;
      }).join("") + `</table>`;

    if (d.expiring_soon?.length) {
      html += `<div class="corp-expiring"><strong>⏰ Skadon së shpejti:</strong><ul>` +
        d.expiring_soon.map(e2 => `<li>${escHtml(e2)}</li>`).join("") + `</ul></div>`;
    }
    if (d.anomalie?.length) {
      html += `<div class="corp-anomalie"><strong>⚠️ Anomali:</strong><ul>` +
        d.anomalie.map(a => `<li>${escHtml(a)}</li>`).join("") + `</ul></div>`;
    }
    if (d.missing?.length) {
      html += `<div class="corp-missing-block"><strong>Dokumente që mungojnë:</strong><ul>` +
        d.missing.map(m2 => `<li>${escHtml(m2)}</li>`).join("") + `</ul></div>`;
    }
    return html;
  }

  function _daysClass(dateStr) {
    if (!dateStr) return "";
    const diff = Math.round((new Date(dateStr) - Date.now()) / 86400000);
    if (diff < 0) return "corp-expired";
    if (diff <= 30) return "corp-expiring-soon";
    if (diff <= 60) return "corp-expiring-warn";
    return "";
  }

  // ── V8.17 SETTLEMENT MONTE CARLO ───────────────────────────────
  const settleDescEl   = document.getElementById("settle-desc");
  const settleOfferEl  = document.getElementById("settle-offer");
  const settleClaimEl  = document.getElementById("settle-claim");
  const settleRoleEl   = document.getElementById("settle-role");
  const settleRunBtn   = document.getElementById("settle-run");
  const settleStatusEl = document.getElementById("settle-status");
  const settleResultEl = document.getElementById("settle-result");
  const settleHistEl   = document.getElementById("settle-history-list");

  function initSettlement() {
    if (!activeCaseId) {
      settleStatusEl.textContent = "Hap një rast së pari.";
      settleStatusEl.className = "pro-status error";
      return;
    }
    settleStatusEl.textContent = "";
    settleStatusEl.className = "pro-status";
    loadSettleHistory();
  }
  async function loadSettleHistory() {
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/settlement-simulations`);
      if (!r.ok) return;
      const data = await r.json();
      const items = data.items || [];
      if (items.length === 0) {
        settleHistEl.innerHTML = `<li class="pro-modal-sub">Asnjë simulim deri tani.</li>`;
        return;
      }
      settleHistEl.innerHTML = items.map(s =>
        `<li><span>#${s.id} — ${(s.created_at||"").slice(0,16).replace("T"," ")}</span><strong>${htmlEsc(s.verdict||"—")}</strong></li>`
      ).join("");
    } catch {}
  }
  settleRunBtn?.addEventListener("click", async () => {
    const desc = (settleDescEl.value || "").trim();
    if (desc.length < 30) {
      settleStatusEl.textContent = "Përshkrim ≥ 30 karaktere.";
      settleStatusEl.className = "pro-status error";
      return;
    }
    const offer = parseFloat(settleOfferEl.value) || null;
    const claim = parseFloat(settleClaimEl.value) || null;
    const role = settleRoleEl.value;
    settleRunBtn.disabled = true;
    settleStatusEl.textContent = "Po lexon precedentët, elicit skenarët, lëshon 10k MC… (~70s)";
    settleStatusEl.className = "pro-status";
    settleResultEl.hidden = true;
    try {
      const body = { description: desc, plaintiff: role === "plaintiff" };
      if (offer != null) body.current_offer_eur = offer;
      if (claim != null) body.valore_in_causa_eur = claim;
      const r = await fetch(`/api/cases/${activeCaseId}/settlement-simulation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${r.status}`);
      }
      const data = await r.json();
      renderSettleResult(data);
      settleStatusEl.textContent = "Gati ✓";
      settleStatusEl.className = "pro-status ok";
      loadSettleHistory();
    } catch (e) {
      settleStatusEl.textContent = "Gabim: " + e.message;
      settleStatusEl.className = "pro-status error";
    } finally {
      settleRunBtn.disabled = false;
    }
  });
  function renderSettleResult(data) {
    const d = data.distribution || {};
    const r = data.recommendation || {};
    const verdict = r.verdict || "no_offer";
    const verdictLabel = {
      accept: "✓ PRANO ofertën",
      counter: "↔ KONTËR-OFERTË",
      reject: "✗ REFUZO",
      no_offer: "Asnjë ofertë e regjistruar"
    }[verdict] || verdict;
    const pct = (k) => {
      const v = d[k]; if (v == null) return "—";
      return Math.round(v).toLocaleString("sq-AL") + " €";
    };
    settleResultEl.innerHTML = `
      <h4 class="studio-section-title">📊 Shpërndarja (n=${data.samples})</h4>
      <div class="settle-distribution">
        <div class="settle-pctile"><div class="settle-pctile-key">P10</div><div class="settle-pctile-val">${pct("p10")}</div></div>
        <div class="settle-pctile"><div class="settle-pctile-key">P25</div><div class="settle-pctile-val">${pct("p25")}</div></div>
        <div class="settle-pctile"><div class="settle-pctile-key">P50</div><div class="settle-pctile-val">${pct("p50")}</div></div>
        <div class="settle-pctile"><div class="settle-pctile-key">P75</div><div class="settle-pctile-val">${pct("p75")}</div></div>
        <div class="settle-pctile"><div class="settle-pctile-key">P90</div><div class="settle-pctile-val">${pct("p90")}</div></div>
      </div>
      <div><span class="gn-label">EV mesatar:</span> <strong>${pct("mean")}</strong></div>
      <div class="settle-verdict ${verdict}">${verdictLabel}</div>
      ${r.suggested_counter != null ? `<div class="settle-recom"><span class="gn-label">Kontër-ofertë e sugjeruar:</span> <strong>${Math.round(r.suggested_counter).toLocaleString("sq-AL")} €</strong></div>` : ""}
      ${r.walk_away != null ? `<div class="settle-recom"><span class="gn-label">Walk-away:</span> ${Math.round(r.walk_away).toLocaleString("sq-AL")} €</div>` : ""}
      ${r.current_offer_percentile != null ? `<div class="settle-recom"><span class="gn-label">Oferta aktuale = perc. ${Math.round(r.current_offer_percentile*100)}</span> e shpërndarjes</div>` : ""}
      <h4 class="studio-section-title">🎲 Skenarët e elicituar</h4>
      <ul>${(data.scenarios||[]).map(s =>
        `<li><strong>${htmlEsc(s.name||s.label||"")}</strong> (p=${s.probability}) — ${Math.round(s.min_eur).toLocaleString()} → <strong>${Math.round(s.mode_eur).toLocaleString()}</strong> → ${Math.round(s.max_eur).toLocaleString()} €<br><em>${htmlEsc(s.rationale||"")}</em></li>`
      ).join("")}</ul>
    `;
    settleResultEl.hidden = false;
  }

  // ── V8.14 FINANCIAL OS ─────────────────────────────────────────
  const finTabs = document.querySelectorAll(".fin-tab");
  let _finLoaded = {};

  function initFinancial() {
    _finLoaded = {};
    finTabs.forEach(t => t.classList.toggle("is-active", t.dataset.fintab === "case"));
    document.querySelectorAll(".fin-pane").forEach(p => { p.hidden = p.dataset.finpane !== "case"; });
    loadFinPane("case");
  }
  finTabs.forEach(t => t.addEventListener("click", () => {
    const k = t.dataset.fintab;
    finTabs.forEach(x => x.classList.toggle("is-active", x === t));
    document.querySelectorAll(".fin-pane").forEach(p => { p.hidden = p.dataset.finpane !== k; });
    loadFinPane(k);
  }));
  async function loadFinPane(k) {
    if (_finLoaded[k]) return;
    const pane = document.querySelector(`.fin-pane[data-finpane="${k}"]`);
    pane.innerHTML = `<p class="pro-modal-sub">Po ngarkohet…</p>`;
    try {
      if (k === "case") {
        if (!activeCaseId) {
          pane.innerHTML = `<p class="pro-modal-sub">Hap një rast së pari.</p>`;
          return;
        }
        const r = await fetch(`/api/cases/${activeCaseId}/profitability`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const realPct = d.realization_rate != null ? (d.realization_rate * 100).toFixed(1) + "%" : "—";
        const hoursWorked = (d.worked_minutes || 0) / 60;
        pane.innerHTML = `
          <div class="fin-grid">
            <div class="fin-stat"><div class="fin-stat-label">Vlera e punës</div><div class="fin-stat-value">${fmtEur(d.worked_cents)}</div><div class="fin-stat-sub">${hoursWorked.toFixed(1)} orë të regjistruara</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Faturuar</div><div class="fin-stat-value">${fmtEur(d.billed_cents)}</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Paguar</div><div class="fin-stat-value">${fmtEur(d.paid_cents)}</div></div>
            <div class="fin-stat"><div class="fin-stat-label">WIP (papaturuar)</div><div class="fin-stat-value">${fmtEur(d.wip_cents)}</div><div class="fin-stat-sub">${((d.wip_minutes||0)/60).toFixed(1)} orë në pritje</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Realization</div><div class="fin-stat-value">${realPct}</div><div class="fin-stat-sub">paguar / vlerë e punës</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Pagesa në pritje</div><div class="fin-stat-value">${fmtEur(d.outstanding_cents)}</div></div>
          </div>`;
      } else if (k === "firm") {
        const r = await fetch(`/api/firm/realization`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const realPct = d.realization_rate != null ? (d.realization_rate * 100).toFixed(1) + "%" : "—";
        pane.innerHTML = `
          <div class="fin-grid">
            <div class="fin-stat"><div class="fin-stat-label">Realization studio</div><div class="fin-stat-value">${realPct}</div><div class="fin-stat-sub">paguar / vlerë e punës</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Vlera e punës</div><div class="fin-stat-value">${fmtEur(d.worked_cents)}</div></div>
            <div class="fin-stat"><div class="fin-stat-label">Paguar</div><div class="fin-stat-value">${fmtEur(d.paid_cents)}</div></div>
          </div>
          <p class="pro-modal-sub" style="margin-top:10px">Filtër kohor: ${htmlEsc(d.since || "asnjë (gjithë historia)")}.</p>`;
      } else if (k === "wip") {
        const r = await fetch(`/api/firm/wip-aging`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const items = d.items || [];
        const totalsByBucket = {};
        items.forEach(it => {
          const b = it.bucket || "?";
          if (!totalsByBucket[b]) totalsByBucket[b] = { cents: 0, count: 0 };
          totalsByBucket[b].cents += it.cents || 0;
          totalsByBucket[b].count += 1;
        });
        const order = ["90+", "61-90", "31-60", "0-30"];
        const buckets = order.filter(b => totalsByBucket[b]).map(b => ({ b, ...totalsByBucket[b] }));
        const rows = items.map(it =>
          `<tr><td>${htmlEsc(it.case_title||it.case_id)}</td><td><strong>${htmlEsc(it.bucket)}</strong></td><td>${(it.minutes/60).toFixed(1)}h</td><td>${fmtEur(it.cents)}</td><td>${htmlEsc(it.oldest_entry_date||"")}</td></tr>`).join("");
        pane.innerHTML = `
          <div class="fin-grid">
            ${buckets.map(b =>
              `<div class="fin-stat"><div class="fin-stat-label">${htmlEsc(b.b)} ditë</div><div class="fin-stat-value">${fmtEur(b.cents)}</div><div class="fin-stat-sub">${b.count} qelizë</div></div>`).join("") || `<p class="pro-modal-sub">Asnjë WIP e papaturuar.</p>`}
          </div>
          ${items.length ? `<table class="fin-table"><thead><tr><th>Rasti</th><th>Bucket</th><th>Orë</th><th>Vlera</th><th>Më e vjetra</th></tr></thead><tbody>${rows}</tbody></table>` : ""}`;
      } else if (k === "cashflow") {
        const r = await fetch(`/api/firm/cashflow`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const rows = (d.items||[]).map(w =>
          `<tr><td>${htmlEsc(w.bucket)}</td><td>${fmtEur(w.cents)}</td><td>${w.count} fatura</td><td>${htmlEsc(w.currency||"EUR")}</td></tr>`).join("");
        pane.innerHTML = `
          <p class="pro-modal-sub">Parashikim 90 ditë bazuar në fatura të 'sent'. <code>past_due</code> = afati ka kaluar.</p>
          <table class="fin-table"><thead><tr><th>Bucket</th><th>Vlera</th><th>Numri</th><th>Valuta</th></tr></thead><tbody>${rows||"<tr><td colspan='4'>Asnjë faturë në pritje</td></tr>"}</tbody></table>`;
      }
      _finLoaded[k] = true;
    } catch (e) {
      pane.innerHTML = `<p class="pro-status error">Gabim: ${htmlEsc(e.message)}</p>`;
    }
  }

  // ── V8.15 WORKFLOW LIBRARY ─────────────────────────────────────
  function initWorkflow() {
    loadWorkflowDefs();
    if (activeCaseId) loadWorkflowActive();
    else document.getElementById("wf-active").innerHTML = `<p class="pro-modal-sub">Hap një rast së pari.</p>`;
  }
  async function loadWorkflowDefs() {
    const el = document.getElementById("wf-definitions");
    try {
      const r = await fetch(`/api/workflows`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const defs = d.definitions || [];
      el.innerHTML = defs.map(def =>
        `<div class="wf-def" data-wf-key="${htmlEsc(def.key)}">
          <div class="wf-def-title">${htmlEsc(def.title||def.key)}</div>
          <div class="wf-def-desc">${htmlEsc(def.summary||"")}</div>
          <div class="pro-modal-sub" style="margin-top:6px">${(def.steps||[]).length} hapa · ~${def.estimated_days||"?"} ditë · ${htmlEsc(def.jurisdiction||"AL")}</div>
        </div>`
      ).join("") || `<p class="pro-modal-sub">Asnjë definicion.</p>`;
      el.querySelectorAll(".wf-def").forEach(c => {
        c.addEventListener("click", () => startWorkflow(c.dataset.wfKey));
      });
    } catch (e) {
      el.innerHTML = `<p class="pro-status error">Gabim: ${htmlEsc(e.message)}</p>`;
    }
  }
  async function startWorkflow(key) {
    if (!activeCaseId) { toast("Hap një rast së pari", "error"); return; }
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_key: key }),
      });
      if (!r.ok) {
        const e = await r.json().catch(()=>({}));
        throw new Error(e.error || `HTTP ${r.status}`);
      }
      toast("Fluxi u nis ✓", "ok");
      loadWorkflowActive();
    } catch (e) {
      toast("Gabim: " + e.message, "error");
    }
  }
  async function loadWorkflowActive() {
    const el = document.getElementById("wf-active");
    try {
      const r = await fetch(`/api/cases/${activeCaseId}/workflows`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const items = d.instances || [];
      if (items.length === 0) {
        el.innerHTML = `<p class="pro-modal-sub">Asnjë flux aktiv.</p>`;
        return;
      }
      el.innerHTML = items.map(wf => {
        const steps = (wf.steps||[]).map(s => {
          const cls = s.is_current ? "is-current" :
                      (s.completed ? "is-done" : "");
          return `<div class="wf-step ${cls}">
            <strong>${htmlEsc(s.title || s.id)}</strong>
            <span class="pro-modal-sub"> · ${htmlEsc(s.kind)}</span>
            ${s.is_current && wf.state === "active" ?
              `<button type="button" class="primary wf-advance-btn" data-wf="${wf.id}" data-step="${s.id}" style="float:right;font-size:11px;padding:3px 8px">→ Avanco</button>` : ""}
          </div>`;
        }).join("");
        const stateCls = wf.state === "completed" ? "completed" :
                         wf.state === "active" ? "running" : "";
        return `<div class="wf-card">
          <div class="wf-card-head">
            <span class="wf-card-title">${htmlEsc(wf.title || wf.workflow_key)}</span>
            <span class="wf-card-status ${stateCls}">${htmlEsc(wf.state)}</span>
          </div>
          ${steps}
        </div>`;
      }).join("");
      el.querySelectorAll(".wf-advance-btn").forEach(b => {
        b.addEventListener("click", async () => {
          b.disabled = true;
          try {
            const r = await fetch(`/api/cases/${activeCaseId}/workflows/${b.dataset.wf}/advance`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ step_id: b.dataset.step }),
            });
            if (!r.ok) {
              const e = await r.json().catch(()=>({}));
              throw new Error(e.error || `HTTP ${r.status}`);
            }
            toast("Hapi u përparua ✓", "ok");
            loadWorkflowActive();
          } catch (e) {
            toast("Gabim: " + e.message, "error");
            b.disabled = false;
          }
        });
      });
    } catch (e) {
      el.innerHTML = `<p class="pro-status error">Gabim: ${htmlEsc(e.message)}</p>`;
    }
  }

  // ── V8.16 TIME-BLOCK RECONSTRUCTION ────────────────────────────
  const reconDateEl   = document.getElementById("recon-date");
  const reconLabelEl  = document.getElementById("recon-label");
  const reconRunBtn   = document.getElementById("recon-run");
  const reconStatusEl = document.getElementById("recon-status");
  const reconBlocksEl = document.getElementById("recon-blocks");
  const reconActionsEl = document.getElementById("recon-actions");
  const reconAcceptBtn = document.getElementById("recon-accept");

  function initTimeRecon() {
    if (!reconDateEl.value) {
      reconDateEl.value = new Date().toISOString().slice(0,10);
    }
    reconStatusEl.textContent = "";
    reconStatusEl.className = "pro-status";
    reconBlocksEl.innerHTML = "";
    reconActionsEl.hidden = true;
  }
  reconRunBtn?.addEventListener("click", async () => {
    const date = reconDateEl.value;
    if (!date) { reconStatusEl.textContent = "Zgjidh datën."; reconStatusEl.className = "pro-status error"; return; }
    reconRunBtn.disabled = true;
    reconStatusEl.textContent = "Po lexon aktivitetet…";
    reconStatusEl.className = "pro-status";
    try {
      const params = new URLSearchParams({ date });
      if (reconLabelEl.checked) params.set("label", "1");
      const r = await fetch(`/api/time/reconstruction?${params}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      renderReconBlocks(d.blocks || []);
      reconStatusEl.textContent = `${(d.blocks||[]).length} blloqe të propozuara`;
      reconStatusEl.className = "pro-status ok";
    } catch (e) {
      reconStatusEl.textContent = "Gabim: " + e.message;
      reconStatusEl.className = "pro-status error";
    } finally {
      reconRunBtn.disabled = false;
    }
  });
  function renderReconBlocks(blocks) {
    if (blocks.length === 0) {
      reconBlocksEl.innerHTML = `<p class="pro-modal-sub">Asnjë aktivitet i regjistruar për këtë datë.</p>`;
      reconActionsEl.hidden = true;
      return;
    }
    reconBlocksEl.innerHTML = blocks.map((b, i) => {
      const start = b.started_at || "";
      const end = b.ended_at || "";
      const desc = b.suggested_description || `${b.kind_label || b.activity_kind} — ${b.evidence_count || 0} sinjale`;
      return `<div class="recon-block is-selected" data-idx="${i}">
        <input type="checkbox" class="recon-block-pick" checked />
        <div class="recon-block-time">${start}–${end}<br><strong>${b.minutes} min</strong></div>
        <div class="recon-block-desc">
          <input type="text" class="recon-desc-input" value="${htmlEsc(desc)}" />
          <div class="recon-block-meta">
            ${htmlEsc(b.case_title||b.case_id||"")} ·
            kind: <strong>${htmlEsc(b.kind_label||b.activity_kind)}</strong> ·
            besimi: ${htmlEsc(b.confidence)} ·
            ${b.already_logged_for_case_minutes ? `<em>(${b.already_logged_for_case_minutes} min në kalendar)</em>` : ""}
          </div>
        </div>
        <div class="recon-block-meta">case: <code>${htmlEsc(b.case_id||"")}</code></div>
      </div>`;
    }).join("");
    reconBlocksEl.querySelectorAll(".recon-block-pick").forEach(cb => {
      cb.addEventListener("change", () => {
        cb.closest(".recon-block").classList.toggle("is-selected", cb.checked);
      });
    });
    reconActionsEl.hidden = false;
    reconActionsEl._blocks = blocks;
  }
  reconAcceptBtn?.addEventListener("click", async () => {
    const blocks = reconActionsEl._blocks || [];
    const picks = [];
    reconBlocksEl.querySelectorAll(".recon-block").forEach(el => {
      const idx = parseInt(el.dataset.idx, 10);
      const cb = el.querySelector(".recon-block-pick");
      if (!cb.checked) return;
      const desc = el.querySelector(".recon-desc-input").value;
      const b = blocks[idx];
      picks.push({
        case_id: b.case_id,
        minutes: b.minutes,
        activity_kind: b.activity_kind,
        description: desc,
      });
    });
    if (picks.length === 0) { toast("Asnjë bllok i zgjedhur", "error"); return; }
    reconAcceptBtn.disabled = true;
    try {
      const r = await fetch(`/api/time/reconstruction/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: reconDateEl.value, blocks: picks }),
      });
      if (!r.ok) {
        const e = await r.json().catch(()=>({}));
        throw new Error(e.error || `HTTP ${r.status}`);
      }
      const d = await r.json();
      toast(`${(d.created||[]).length} blloqe u regjistruan ✓`, "ok");
      reconBlocksEl.innerHTML = "";
      reconActionsEl.hidden = true;
      reconStatusEl.textContent = "U regjistrua ✓";
      reconStatusEl.className = "pro-status ok";
    } catch (e) {
      toast("Gabim: " + e.message, "error");
    } finally {
      reconAcceptBtn.disabled = false;
    }
  });

  // ═══════════════════════════════════════════════════════════════
  // V9.2 — Admin user management (dentro Studio modal)
  // ═══════════════════════════════════════════════════════════════
  const IS_ADMIN = document.body.dataset.admin === "1";
  const usersAdminSection = document.getElementById("users-admin-section");
  const usersAdminBody    = document.getElementById("users-admin-body");
  const newUserBtn        = document.getElementById("new-user-btn");
  const newUserUsername   = document.getElementById("new-user-username");
  const newUserPassword   = document.getElementById("new-user-password");
  const newUserAdminChk   = document.getElementById("new-user-admin");
  const newUserStatus     = document.getElementById("new-user-status");
  const myPasswdBtn       = document.getElementById("my-passwd-btn");
  const myNewPassword     = document.getElementById("my-new-password");
  const myPasswdStatus    = document.getElementById("my-passwd-status");

  function escHtml(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
    }[c]));
  }

  async function loadAdminUsers() {
    if (!IS_ADMIN || !usersAdminBody) return;
    usersAdminSection.hidden = false;
    try {
      const r = await fetch("/api/admin/users");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (!data.items?.length) {
        usersAdminBody.innerHTML = '<tr><td colspan="4" class="studio-empty">Asnjë përdorues.</td></tr>';
        return;
      }
      const meId = parseInt(document.body.dataset.userId || "0", 10);
      usersAdminBody.innerHTML = data.items.map((u) => `
        <tr${u.suspended ? ' style="opacity:.5;"' : ''}>
          <td><strong>${escHtml(u.username)}</strong>${u.suspended ? ' <span class="admin-badge" style="background:#c0392b;color:#fff;">i çaktivizuar</span>' : ''}<div class="u-meta">${moduleChips(u)}${statusChip(u)}</div></td>
          <td>${u.is_admin ? "👑 Admin" : "👤 User"}</td>
          <td>${u.created_at ? new Date(u.created_at).toLocaleDateString("sq-AL") : "—"}</td>
          <td style="text-align: right; white-space: nowrap;">
            <button type="button" class="ghost" data-action="manage" data-uid="${u.id}" data-uname="${escHtml(u.username)}" data-modules="${(u.modules||[]).join(',')}" data-jurisdictions="${(u.jurisdictions||['AL']).join(',')}" data-plan="${u.plan_expires_at||''}" data-admin="${u.is_admin?1:0}" data-status="${u.status||''}" data-days="${u.days_left==null?'':u.days_left}" title="Menaxho modulet & abonimin">⚙️</button>
            <button type="button" class="ghost" data-action="passwd" data-uid="${u.id}" data-uname="${escHtml(u.username)}" title="Ndrysho fjalëkalimin">🔑</button>
            ${u.id === meId ? "" : `<button type="button" class="ghost" data-action="suspend" data-uid="${u.id}" data-uname="${escHtml(u.username)}" data-suspended="${u.suspended ? '1' : '0'}" title="${u.suspended ? 'Riaktivizo aksesin' : 'Çaktivizo aksesin (nuk fshin të dhënat)'}">${u.suspended ? '✅' : '⛔'}</button>`}
            ${u.id === meId ? "" : `<button type="button" class="ghost" data-action="delete" data-uid="${u.id}" data-uname="${escHtml(u.username)}" title="Fshi përfundimisht" style="color:#c66;">🗑</button>`}
          </td>
        </tr>
      `).join("");
    } catch (e) {
      usersAdminBody.innerHTML = `<tr><td colspan="4" class="studio-empty">Gabim: ${escHtml(e.message)}</td></tr>`;
    }
  }

  function moduleChips(u) {
    var m = u.is_admin ? ["avokat", "prokuror", "noter"] : (u.modules || []);
    var ic = { avokat: "⚖️", prokuror: "🏛️", noter: "📜" };
    return m.map(function (x) { return '<span class="u-chip u-' + x + '" title="' + x + '">' + (ic[x] || "") + '</span>'; }).join("");
  }
  function statusChip(u) {
    if (u.is_admin) return '<span class="u-chip u-full">3-in-1</span>';
    if (u.suspended) return "";
    if (u.status === "plan_expired" || u.status === "demo_expired") return '<span class="u-chip u-exp">skaduar</span>';
    if (u.plan_expires_at) {
      var d = u.days_left;
      var cls = (d != null && d <= 7) ? "u-warn" : "u-ok";
      return '<span class="u-chip ' + cls + '">' + (d != null ? d + "d" : "aktiv") + '</span>';
    }
    return '<span class="u-chip u-ok">aktiv</span>';
  }
  function openUserManage(d) {
    var ov = document.createElement("div"); ov.className = "wa-modal-ov";
    var moduleRow = ["avokat", "prokuror", "noter"].map(function (m) {
      var lbl = { avokat: "⚖️ Avokat", prokuror: "🏛️ Prokuror", noter: "📜 Noter" }[m];
      var on = d.modules.indexOf(m) >= 0;
      return '<label class="um-mod"><input type="checkbox" value="' + m + '"' + (on ? " checked" : "") + "> " + lbl + "</label>";
    }).join("");
    var jurRow = ["AL", "IT"].map(function (jj) {
      var lbl = { AL: "🇦🇱 Shqipëri", IT: "🇮🇹 Itali" }[jj];
      var on = (d.jurisdictions || ["AL"]).indexOf(jj) >= 0;
      return '<label class="um-mod"><input type="checkbox" value="' + jj + '"' + (on ? " checked" : "") + "> " + lbl + "</label>";
    }).join("");
    var expTxt = d.isAdmin ? "Admin — i plotë, pa afat"
      : (d.plan ? ("Skadon: " + new Date(d.plan).toLocaleDateString("sq-AL") + (d.days != null ? (" (" + d.days + " ditë)") : ""))
                : "Pa afat (i përhershëm)");
    var okStatus = (d.isAdmin || d.status === "active");
    ov.innerHTML = '<div class="wa-modal"><button class="wa-x" type="button" aria-label="Mbyll">×</button>' +
      "<h3>⚙️ " + escHtml(d.uname) + "</h3>" +
      '<div class="wa-note ' + (okStatus ? "ok" : "warn") + '">Statusi: <b>' + (d.isAdmin ? "admin" : escHtml(d.status || "active")) + "</b> · " + expTxt + "</div>" +
      (d.isAdmin ? '<p class="wa-sub">Admin i ka të gjitha modulet — nuk preket.</p>'
        : '<label class="wa-lab">Modulet e paguara</label><div class="um-mods">' + moduleRow + "</div>" +
          '<div class="wa-row"><button class="um-save-mods wa-save" type="button">Ruaj modulet</button><span class="um-msg1 wa-msg"></span></div>' +
          '<label class="wa-lab" style="margin-top:12px">Juridiksioni (shteti · ligji)</label><div class="um-jurs">' + jurRow + '</div>' +
          '<div class="wa-row"><button class="um-save-jur wa-save" type="button">Ruaj juridiksionin</button><span class="um-msgj wa-msg"></span></div>' +
          '<label class="wa-lab" style="margin-top:12px">Abonimi (zgjat nga fundi aktual)</label>' +
          '<div class="um-plan"><button type="button" data-mo="1">+1 muaj</button><button type="button" data-mo="3">+3 muaj</button><button type="button" data-mo="6">+6 muaj</button><button type="button" data-mo="12">+1 vit</button><button type="button" class="um-clear">♾ Pa afat</button></div>' +
          '<div class="wa-row"><span class="um-msg2 wa-msg"></span></div>') +
      "</div>";
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector(".wa-x").onclick = close;
    if (d.isAdmin) return;
    ov.querySelector(".um-save-mods").onclick = async function () {
      var sel = [].slice.call(ov.querySelectorAll(".um-mods input:checked")).map(function (x) { return x.value; });
      var msg = ov.querySelector(".um-msg1");
      if (!sel.length) { msg.textContent = "Zgjidh të paktën një modul"; return; }
      try {
        var r = await fetch("/api/admin/users/" + d.uid + "/modules", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modules: sel }) });
        if (!r.ok) throw new Error();
        msg.textContent = "✓ Ruajtur"; if (typeof toast === "function") toast("Modulet u ruajtën", "ok"); loadAdminUsers();
      } catch (e) { msg.textContent = "Gabim"; }
    };
    var _jb = ov.querySelector(".um-save-jur");
    if (_jb) _jb.onclick = async function () {
      var js = [].slice.call(ov.querySelectorAll(".um-jurs input:checked")).map(function (x) { return x.value; });
      var msg = ov.querySelector(".um-msgj");
      if (!js.length) { msg.textContent = "Zgjidh të paktën një"; return; }
      try {
        var r = await fetch("/api/admin/users/" + d.uid + "/jurisdictions", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jurisdictions: js }) });
        if (!r.ok) throw new Error();
        msg.textContent = "✓ Ruajtur"; if (typeof toast === "function") toast("Juridiksioni u ruajt", "ok"); loadAdminUsers();
      } catch (e) { msg.textContent = "Gabim"; }
    };
    ov.querySelectorAll(".um-plan button[data-mo]").forEach(function (b) {
      b.onclick = async function () {
        var msg = ov.querySelector(".um-msg2");
        try {
          var r = await fetch("/api/admin/users/" + d.uid + "/plan", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ months: parseInt(b.dataset.mo, 10) }) });
          var j = await r.json(); if (!r.ok) throw new Error();
          msg.textContent = "✓ Deri " + (j.plan_expires_at ? new Date(j.plan_expires_at).toLocaleDateString("sq-AL") : "");
          if (typeof toast === "function") toast("Abonimi u zgjat", "ok"); loadAdminUsers(); setTimeout(close, 1000);
        } catch (e) { msg.textContent = "Gabim"; }
      };
    });
    ov.querySelector(".um-clear").onclick = async function () {
      var msg = ov.querySelector(".um-msg2");
      try {
        var r = await fetch("/api/admin/users/" + d.uid + "/plan", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clear: true }) });
        if (!r.ok) throw new Error();
        msg.textContent = "✓ Pa afat"; if (typeof toast === "function") toast("Bërë i përhershëm", "ok"); loadAdminUsers(); setTimeout(close, 1000);
      } catch (e) { msg.textContent = "Gabim"; }
    };
  }

  // delegated click handler per delete/passwd
  usersAdminBody?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const uid = parseInt(btn.dataset.uid, 10);
    const uname = btn.dataset.uname;

    if (action === "manage") {
      openUserManage({ uid: uid, uname: uname,
        modules: (btn.dataset.modules || "").split(",").filter(Boolean),
        jurisdictions: (btn.dataset.jurisdictions || "AL").split(",").filter(Boolean),
        plan: btn.dataset.plan || "", isAdmin: btn.dataset.admin === "1",
        status: btn.dataset.status || "",
        days: btn.dataset.days === "" ? null : parseInt(btn.dataset.days, 10) });
      return;
    }

    if (action === "delete") {
      if (!confirm(`Të fshish përdoruesin '${uname}'? Veprimi nuk mund të zhbëhet.`)) return;
      const r = await fetch(`/api/admin/users/${uid}`, { method: "DELETE" });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        if (typeof toast === "function") toast(`U fshi përdoruesi '${uname}'`, "success");
        loadAdminUsers();
      } else {
        if (typeof toast === "function") toast("Gabim: " + (data.error || r.status), "error");
      }
    } else if (action === "suspend") {
      const willSuspend = btn.dataset.suspended !== "1";
      const verb = willSuspend ? "çaktivizosh" : "riaktivizosh";
      const note = willSuspend
        ? "Përdoruesi nuk do të mund të hyjë, por të dhënat e tij ruhen. Mund ta riaktivizosh kur të dojë."
        : "Përdoruesi do të rifitojë aksesin menjëherë.";
      if (!confirm(`Të ${verb} përdoruesin '${uname}'?\n\n${note}`)) return;
      const r = await fetch(`/api/admin/users/${uid}/suspend`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suspended: willSuspend }),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        if (typeof toast === "function")
          toast(willSuspend ? `'${uname}' u çaktivizua` : `'${uname}' u riaktivizua`, "success");
        loadAdminUsers();
      } else {
        if (typeof toast === "function") toast("Gabim: " + (data.error || r.status), "error");
      }
    } else if (action === "passwd") {
      const newPw = prompt(`Fjalëkalimi i ri për '${uname}' (min 6 karaktere):`);
      if (!newPw) return;
      if (newPw.length < 6) {
        alert("Fjalëkalimi duhet të jetë të paktën 6 karaktere.");
        return;
      }
      const r = await fetch(`/api/admin/users/${uid}/password`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: newPw }),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok) {
        if (typeof toast === "function") toast(`Fjalëkalimi i '${uname}' u ndryshua`, "success");
      } else {
        if (typeof toast === "function") toast("Gabim: " + (data.error || r.status), "error");
      }
    }
  });

  document.getElementById("new-firm-btn")?.addEventListener("click", async () => {
    var nameEl = document.getElementById("new-firm-name");
    var ownerEl = document.getElementById("new-firm-owner");
    var st = document.getElementById("new-firm-status");
    var name = (nameEl.value || "").trim();
    if (!name) { st.textContent = "Shkruaj emrin e studios."; return; }
    st.textContent = "Duke krijuar\u2026";
    try {
      var r = await fetch("/api/admin/firms", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, owner_username: (ownerEl.value || "").trim() }),
      });
      var d = await r.json();
      if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
      st.textContent = "\u2713 Studio '" + (d.name || name) + "' u krijua (pronar: " + (d.owner || "-") + ")";
      nameEl.value = ""; ownerEl.value = "";
      if (typeof toast === "function") toast("Studio u krijua", "success");
    } catch (e) { st.textContent = "Gabim: " + e.message; }
  });

  newUserBtn?.addEventListener("click", async () => {
    const username = newUserUsername.value.trim().toLowerCase();
    const password = newUserPassword.value;
    const isAdmin  = newUserAdminChk.checked;
    if (!username || password.length < 6) {
      newUserStatus.textContent = "Plotëso username dhe fjalëkalim (min 6 karaktere).";
      newUserStatus.style.color = "#c66";
      return;
    }
    newUserBtn.disabled = true;
    newUserStatus.textContent = "Duke krijuar…";
    newUserStatus.style.color = "#aaa";
    try {
      const r = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, is_admin: isAdmin, profession: (document.getElementById("new-user-profession") || {}).value || "avokat" }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      newUserStatus.textContent = `✓ U krijua '${data.username}'`;
      newUserStatus.style.color = "#6c6";
      newUserUsername.value = "";
      newUserPassword.value = "";
      newUserAdminChk.checked = false;
      loadAdminUsers();
    } catch (e) {
      newUserStatus.textContent = "Gabim: " + e.message;
      newUserStatus.style.color = "#c66";
    } finally {
      newUserBtn.disabled = false;
    }
  });

  myPasswdBtn?.addEventListener("click", async () => {
    const newPw = myNewPassword.value;
    if (newPw.length < 6) {
      myPasswdStatus.textContent = "Min 6 karaktere.";
      myPasswdStatus.style.color = "#c66";
      return;
    }
    // Trovo l'id corrente da /api/me
    const meR = await fetch("/api/me");
    const me = await meR.json().catch(() => ({}));
    const meId = me?.user?.id;
    if (!meId) {
      myPasswdStatus.textContent = "Errore: utente non identificato";
      myPasswdStatus.style.color = "#c66";
      return;
    }
    myPasswdBtn.disabled = true;
    const r = await fetch(`/api/admin/users/${meId}/password`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: newPw }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      myPasswdStatus.textContent = "✓ Fjalëkalimi u ndryshua";
      myPasswdStatus.style.color = "#6c6";
      myNewPassword.value = "";
    } else {
      myPasswdStatus.textContent = "Gabim: " + (data.error || r.status);
      myPasswdStatus.style.color = "#c66";
    }
    myPasswdBtn.disabled = false;
  });

  // V9.2 — usage dashboard (admin only)
  const usagePeriodSel = document.getElementById("usage-period");
  const usageSummary   = document.getElementById("usage-summary");
  const usageBody      = document.getElementById("usage-body");

  function fmtNum(n) {
    if (!n) return "0";
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
    return String(n);
  }
  function fmtCost(cents) {
    if (!cents) return "$0.00";
    return "$" + (cents / 100).toFixed(2);
  }
  function fmtRelative(iso) {
    if (!iso) return "—";
    const then = new Date(iso).getTime();
    const diffSec = Math.floor((Date.now() - then) / 1000);
    if (diffSec < 60) return "ora";
    if (diffSec < 3600) return Math.floor(diffSec / 60) + " min fa";
    if (diffSec < 86400) return Math.floor(diffSec / 3600) + " h fa";
    return Math.floor(diffSec / 86400) + " gg fa";
  }

  async function loadUsageDashboard() {
    if (!IS_ADMIN || !usageBody) return;
    const period = usagePeriodSel?.value || "month";
    usageBody.innerHTML = '<tr><td colspan="6" class="studio-empty">Duke ngarkuar…</td></tr>';
    try {
      const r = await fetch(`/api/admin/usage?period=${period}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const t = data.totals;
      usageSummary.innerHTML = `
        <span>🟢 <strong>${data.online_count}</strong> online</span>
        <span>📞 <strong>${fmtNum(t.calls)}</strong> thirrje</span>
        <span>↗ <strong>${fmtNum(t.tokens_in)}</strong> in</span>
        <span>↘ <strong>${fmtNum(t.tokens_out)}</strong> out</span>
        <span>💰 <strong>${fmtCost(t.cost_cents)}</strong> ~ kosto API</span>
      `;
      if (!data.users.length) {
        usageBody.innerHTML = '<tr><td colspan="6" class="studio-empty">Asnjë e dhënë.</td></tr>';
        return;
      }
      usageBody.innerHTML = data.users.map((u) => `
        <tr>
          <td>
            ${u.online ? '<span style="color:#6c6;">●</span>' : '<span style="color:#555;">○</span>'}
            <strong>${escHtml(u.username)}</strong>
            ${u.is_admin ? ' 👑' : ''}
          </td>
          <td>${fmtNum(u.calls)}</td>
          <td>${fmtNum(u.tokens_in)}</td>
          <td>${fmtNum(u.tokens_out)}</td>
          <td>${fmtCost(u.cost_cents)}</td>
          <td style="color:#888; font-size:12px;">${fmtRelative(u.last_active)}</td>
        </tr>
      `).join("");
    } catch (e) {
      usageBody.innerHTML = `<tr><td colspan="6" class="studio-empty">Gabim: ${escHtml(e.message)}</td></tr>`;
    }
  }
  usagePeriodSel?.addEventListener("change", loadUsageDashboard);

  // hook a openStudioModal — ricarica utenti + usage ogni volta che apre Studio
  const _origOpenStudio = openStudioModal;
  openStudioModal = function() {
    _origOpenStudio();
    loadAdminUsers();
    loadUsageDashboard();
  };
  studioBtn?.removeEventListener("click", _origOpenStudio);
  studioBtn?.addEventListener("click", openStudioModal);

  // ─── init ────────────────────────────────────────────────────────
  renderCaseList();
  loadDailyBrief();
})();

document.getElementById("logout-fab")?.addEventListener("click", async function(){ try{ await fetch("/api/logout", { method: "POST" }); }catch(e){} window.location.href = "/"; });
