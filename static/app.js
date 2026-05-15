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
    window.location.href = "/login";
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
  exportJsonBtn.addEventListener("click", () => {
    if (!activeCaseId) return;
    window.location.href = `/api/cases/${activeCaseId}/export?format=json`;
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

  function renderDossier(documents) {
    dossierList.innerHTML = "";
    updateDossierBadge(documents.length);
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

  // ─── submit ──────────────────────────────────────────────────────
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
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
    let streamBuffer = "";
    const ensureStreamEl = () => {
      if (streamEl) return;
      typing.remove();
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
            // keep typing indicator while in pre-stream phases
          } else if (evt.type === "final") {
            finalPayload = evt.data || evt;
          } else if (evt.type === "error") {
            sawError = evt.message || "Gabim i panjohur";
          } else if (evt.type === "done") {
            break outer;
          }
        }
      }
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
  function appendUser(text) {
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
    highlightNeni(body);
    linkCaseMarkers(body, data.precedents || []);

    // Citation trust badge — provenance lock. Always at the very top of
    // the answer (before urgency/action-plan) so the lawyer's eye lands on
    // it first: "are these citations real or hallucinated?"
    if (data.citations && data.citations.stats && data.citations.stats.total > 0) {
      msgEl.insertBefore(renderCitationsBadge(data.citations), body);
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
        </li>
      `).join("");
      prec.innerHTML = `
        <summary>⚖️ Vendime relevante të gjykatave (${precedents.length})</summary>
        <ul class="precedents-list">${items}</ul>
      `;
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
  function highlightNeni(root) {
    const re = /\bNeni\s*\d+(?:\s*[\/-]\s*[a-zçëA-ZÇË0-9]+)?/g;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const toReplace = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && node.parentElement.closest(".neni-cite, code")) continue;
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
        const span = document.createElement("span");
        span.className = "neni-cite";
        span.textContent = m[0];
        frag.appendChild(span);
        last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      n.parentNode.replaceChild(frag, n);
    }
  }

  // ─── convert [[case:ID]] markers → clickable pin-to-row links ───
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
      "qytetari": "qytetari (ti)",
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
  function renderCitationsBadge(payload) {
    const stats = payload.stats || {};
    const items = payload.items || [];
    const total = stats.total || 0;
    const verified = stats.verified || 0;
    const fake = stats.fake || 0;
    const needs = stats.needs_code || 0;

    let level, label, icon;
    if (fake > 0) {
      level = "danger";
      icon = "⚠";
      label = `${verified}/${total} të verifikuara · ${fake} fantazmë`;
    } else if (needs > 0) {
      level = "partial";
      icon = "ℹ";
      label = `${verified}/${total} të verifikuara · ${needs} pa kod të qartë`;
    } else {
      level = "ok";
      icon = "✓";
      label = `${verified}/${total} citime të verifikuara`;
    }

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
            return `<li class="cit-row cit-row-ok">
              <span class="cit-status">✓</span>
              <code>${escapeHtml(c.raw)}</code>
              <span class="cit-meta">${escapeHtml(c.code_label || "")}${head}</span>
            </li>`;
          }
          if (c.status === "fake") {
            return `<li class="cit-row cit-row-fake">
              <span class="cit-status">✗</span>
              <code>${escapeHtml(c.raw)}</code>
              <span class="cit-meta">nuk u gjet ${c.code_label ? `në ${escapeHtml(c.code_label)}` : "në asnjë kod"}</span>
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
      const resp = await fetch(`/api/events?from=${now.toISOString()}&to=${in48.toISOString()}`);
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
  }

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
  const stressModal = document.getElementById("stress-modal");
  const auditModal = document.getElementById("audit-modal");
  const draftModal = document.getElementById("draft-modal");
  const cascadeModal = document.getElementById("cascade-modal");
  const timelineModal = document.getElementById("timeline-modal");
  const adversarialModal = document.getElementById("adversarial-modal");
  const strategyModal = document.getElementById("strategy-modal");
  const draftSubmitModal = document.getElementById("draft-submit-modal");
  const PRO_MODALS = {
    stress: stressModal, audit: auditModal,
    draft: draftModal, cascade: cascadeModal,
    timeline: timelineModal, adversarial: adversarialModal,
    strategy: strategyModal,
    "submit-draft": draftSubmitModal,
    "intake": document.getElementById("intake-modal"),
    "clients": document.getElementById("clients-modal"),
    "jargon": document.getElementById("jargon-modal"),
    "contract": document.getElementById("contract-modal"),
    "money": document.getElementById("money-modal"),
    "agent": document.getElementById("agent-modal"),
    "rehearsal": document.getElementById("rehearsal-modal"),
    "inbox": document.getElementById("inbox-modal"),
    "genio": document.getElementById("genio-modal"),
    "precedent": document.getElementById("precedent-modal"),
    "settlement": document.getElementById("settlement-modal"),
    "financial": document.getElementById("financial-modal"),
    "workflow": document.getElementById("workflow-modal"),
    "time-recon": document.getElementById("time-recon-modal"),
  };

  function openProModal(key) {
    const m = PRO_MODALS[key];
    if (!m) return;
    m.hidden = false;
    document.body.style.overflow = "hidden";
    if (key === "draft") ensureDraftTypes();
    if (key === "cascade") ensureCascadeTypes();
    if (key === "timeline") loadTimelineForCase();
    if (key === "submit-draft") prepareDraftSubmit();
    if (key === "clients") loadClientsForCase();
    if (key === "contract") loadContractHistory();
    if (key === "money") loadMoneyForCase();
    if (key === "agent") loadAgentForCase();
    if (key === "rehearsal") initRehearsal();
    if (key === "inbox") loadInbox();
    if (key === "genio") initGenio();
    if (key === "precedent") initPrecedent();
    if (key === "settlement") initSettlement();
    if (key === "financial") initFinancial();
    if (key === "workflow") initWorkflow();
    if (key === "time-recon") initTimeRecon();
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
    proMenu.hidden = expanded;
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
      if (key === "in-hearing") {
        if (!activeCaseId) { toast("Hap një rast së pari", "error"); return; }
        window.location.href = `/case/${activeCaseId}/in-hearing`;
        return;
      }
      openProModal(key);
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

  // ── ① STRESS-TEST ────────────────────────────────────────────────
  const stressInput = document.getElementById("stress-hypothesis");
  const stressRun = document.getElementById("stress-run");
  const stressStatus = document.getElementById("stress-status");
  const stressResult = document.getElementById("stress-result");

  stressRun?.addEventListener("click", async () => {
    if (!activeCaseId) {
      stressStatus.textContent = "Hap një rast së pari.";
      stressStatus.className = "pro-status error";
      return;
    }
    const text = (stressInput.value || "").trim();
    if (text.length < 20) {
      stressStatus.textContent = "Shkruaj të paktën 20 karaktere.";
      stressStatus.className = "pro-status error";
      return;
    }
    stressRun.disabled = true;
    stressStatus.textContent = "Po stres-teston… (~60s)";
    stressStatus.className = "pro-status";
    stressResult.hidden = true;
    try {
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

    adversarialResult.innerHTML = `
      ${summaryHtml}
      <div class="pro-section">
        <h4>🥊 Raundet (${rounds.length})</h4>
        <div class="adv-rounds">${roundsHtml || "<p>Asnjë raund.</p>"}</div>
      </div>
    `;
    adversarialResult.hidden = false;
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
    contractStatus.textContent = "Po analizon kontratën… (~60-90s, full Opus)";
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
    precStatusEl.textContent = "Po kërkon precedentët, po lexon ratio decidendi, po sintetizon… (~40s)";
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
      const data = await r.json();
      renderPrecedentBrief(data.brief || {});
      const sec = (data.elapsed_ms / 1000).toFixed(1);
      precStatusEl.textContent = `Gati në ${sec}s ✓ (#${data.brief_id})`;
      precStatusEl.className = "pro-status ok";
      loadPrecedentHistory();
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
                ${link}
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

  // ─── init ────────────────────────────────────────────────────────
  renderCaseList();
  loadDailyBrief();
})();
