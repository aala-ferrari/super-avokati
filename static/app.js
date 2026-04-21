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
      });
    }
    renderDossier(c.documents || []);
    dossierPanel.hidden = true;  // reset to collapsed when switching cases
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
      node.querySelector(".case-meta").textContent = formatWhen(c.updated_at);
      node.querySelector(".case-select").addEventListener("click", () => selectCase(c.id));
      caseList.appendChild(node);
    }
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
    try {
      const resp = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, case_id: activeCaseId }),
      });
      const data = await resp.json();
      typing.remove();
      if (!resp.ok && resp.status === 401) {
        window.location.href = "/login";
        return;
      }
      appendBot(data);
      // After first message the case may have been auto-renamed — refresh list.
      await renderCaseList();
      const resp2 = await fetch(`/api/cases/${activeCaseId}`);
      if (resp2.ok) {
        const c = await resp2.json();
        caseTitleText.textContent = c.title;
      }
    } catch (err) {
      typing.remove();
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

  // ─── init ────────────────────────────────────────────────────────
  renderCaseList();
})();
