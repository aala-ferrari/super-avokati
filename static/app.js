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
      });
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
      messages.innerHTML = "";
      sendBtn.disabled = true;
      composerHint.textContent = "Hap një rast për të filluar bisedën";
      await renderCaseList();
      // re-insert welcome if still exists in DOM elsewhere, else write static
      messages.innerHTML = `<div class="msg bot welcome"><p><strong>Rasti u fshi.</strong> Kliko "＋ Rast i ri" për të hapur një bisedë të re.</p></div>`;
    }
  });

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

    // Court precedents — shown in a second collapsible block when any exist.
    if (precedents.length) {
      const prec = document.createElement("details");
      prec.className = "precedents";
      const outcomeTag = (o) => o
        ? `<span class="prec-outcome prec-${o}">${escapeHtml(o)}</span>`
        : "";
      const items = precedents.map((d) => `
        <li>
          <span class="art-score">${d.score}</span>
          <div class="prec-cite">
            ${escapeHtml(d.citation)} <span class="prec-date">${escapeHtml(d.date || "")}</span>
            ${outcomeTag(d.outcome)}
          </div>
          ${d.objekti ? `<div class="prec-objekti">${escapeHtml(d.objekti)}</div>` : ""}
          ${d.dispositif ? `<div class="prec-dispositif">${escapeHtml(d.dispositif)}</div>` : ""}
          ${d.source_url ? `<a class="prec-link" href="${encodeURI(d.source_url)}" target="_blank" rel="noopener">Lexo vendimin →</a>` : ""}
        </li>
      `).join("");
      prec.innerHTML = `
        <summary>⚖️ Vendime relevante të gjykatave (${precedents.length})</summary>
        <ul class="precedents-list">${items}</ul>
      `;
      msgEl.insertBefore(prec, null);
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
