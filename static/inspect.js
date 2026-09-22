// Inspector (v9.365) — pagina admin di sola lettura: ricerca/sfoglia il corpus e i precedenti e mostra il record
// esattamente com'è salvato. Nessuna scrittura. Tutto passa da /api/inspect/*.
(function () {
  "use strict";
  var META = null, PAGE = { laws: 1, cases: 1 }, LAST = { laws: null, cases: null };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  function api(path) { return fetch(path, { credentials: "same-origin" }).then(function (r) { return r.json().then(function (d) { if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status)); return d; }); }); }
  function fill(sel, items, keyFn, labelFn, keep) {
    var cur = sel.value; sel.innerHTML = keep + items.map(function (it) { return '<option value="' + esc(keyFn(it)) + '">' + esc(labelFn(it)) + "</option>"; }).join("");
    if (cur) sel.value = cur;
  }
  function renderMeta() {
    $("#rev").textContent = META.revision ? ("corpus " + META.revision) : "";
    fillLawCodes(); fillCaseFilters();
  }
  function fillLawCodes() {
    var lang = $("#f-laws [name=lang]").value, codes = lang === "it" ? (META.it_codes || []) : (META.al_codes || []);
    fill($("#f-laws [name=code]"), codes, function (c) { return c.code; }, function (c) {
      var p = []; if (c.corpo_vuoto) p.push(c.corpo_vuoto + " corpi vuoti"); if (c.rubrica_lunga) p.push(c.rubrica_lunga + " rubriche lunghe");
      return c.code + " · " + c.n + " art." + (c.abrogati ? " · " + c.abrogati + " abr." : "") + (p.length ? " · ⚠ " + p.join(", ") : "");
    }, '<option value="">— tutti —</option>');
  }
  function fillCaseFilters() {
    var src = $("#f-cases [name=src]").value;
    var courts = src === "it" ? (META.it_courts || []) : (META.al_courts || []);
    fill($("#f-cases [name=court]"), courts, function (c) { return c.code; }, function (c) { return c.name + " · " + c.n; }, '<option value="">— tutte —</option>');
    var outs = src === "it" ? {} : (META.al_outcomes || {}), types = src === "it" ? {} : (META.al_types || {});
    fill($("#f-cases [name=outcome]"), Object.keys(outs), function (k) { return k === "—" ? "" : k; }, function (k) { return k + " · " + outs[k]; }, '<option value="">— tutti —</option>');
    fill($("#f-cases [name=type]"), Object.keys(types), function (k) { return k === "—" ? "" : k; }, function (k) { return k + " · " + types[k]; }, '<option value="">— tutti —</option>');
    var ys = src === "it" ? META.it_years : META.al_years;
    $("#s-cases").textContent = (src === "it" ? (META.it_total || 0) : (META.al_total || 0)) + " decisioni" + (ys && ys[0] ? " · " + ys[0] + "–" + ys[1] : "");
    $("#f-cases [name=outcome]").disabled = src === "it"; $("#f-cases [name=type]").disabled = src === "it";
    $("#f-cases [name=cited_code]").disabled = src === "it"; $("#f-cases [name=cited_number]").disabled = src === "it";
  }
  function qs(form, extra) {
    var p = new URLSearchParams();
    Array.prototype.forEach.call(form.elements, function (el) { if (el.name && el.value !== "" && !el.disabled) p.set(el.name, el.value); });
    Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
    return p.toString();
  }
  // ── leggi ──
  function searchLaws(page, browse) {
    PAGE.laws = page || 1;
    var form = $("#f-laws"), extra = { page: PAGE.laws, per_page: 25 };
    if (browse) { extra.q = ""; extra.number = ""; if (!form.code.value) { $("#s-laws").textContent = "scegli un codice da sfogliare"; return; } }
    $("#s-laws").textContent = "…";
    api("/api/inspect/laws?" + qs(form, extra)).then(function (d) {
      LAST.laws = d;
      $("#s-laws").textContent = d.total + " risultati · " + (d.mode === "browse" ? "sfoglio in ordine" : d.mode === "exact" ? "riferimento esatto" : "ricerca BM25");
      var g = $("#gaps-laws"); if (d.gaps && d.gaps.length) { g.hidden = false; g.textContent = "Numeri mancanti nella sequenza (" + d.gaps.length + (d.gaps.length >= 80 ? "+" : "") + "): " + d.gaps.join(", ") + " — normali se abrogati senza stub, sospetti se in mezzo a un capitolo."; } else { g.hidden = true; }
      $("#r-laws").innerHTML = d.items.length ? d.items.map(function (a) {
        var b = a.problemi.map(function (x) { return '<span class="badge bad">' + esc(x) + "</span>"; }).join(" ");
        if (a.repealed) b += ' <span class="badge warn">abrogato</span>';
        if (a.heading_kind === "rubrike") b += ' <span class="badge ok">rubrica</span>';
        if (a.note) b += ' <span class="badge">nota</span>';
        return '<li data-lang="' + esc(d.lang) + '" data-code="' + esc(a.code) + '" data-number="' + esc(a.number) + '"><div class="t">' + esc(a.citation) + '</div><div>' + esc(a.heading.slice(0, 140)) + '</div><div class="m"><span>' + a.body_len + " chr · " + a.n_paragrafet + " par." + (a.segmenti != null ? " · " + a.segmenti + " seg." : " · nessun vettore") + (a.score != null ? " · BM25 " + a.score : "") + (a.last_amendment_date ? " · mod. " + a.last_amendment_date : "") + "</span>" + b + "</div></li>";
      }).join("") : '<li class="empty">nessun risultato</li>';
      pager("laws", d);
    }).catch(function (e) { $("#s-laws").textContent = "errore: " + e.message; });
  }
  function showLaw(lang, code, number) {
    $("#detail").innerHTML = '<div class="empty">…</div>';
    api("/api/inspect/law/" + lang + "/" + encodeURIComponent(code) + "/" + encodeURIComponent(number)).then(function (d) {
      var r = d.record, rows = [["citation", d.citation], ["code", r.code], ["title_sq", r.title_sq], ["area", r.area], ["number", r.number],
        ["heading (rubrica)", r.heading], ["heading_kind", r.heading_kind], ["note", r.note], ["body", r.body], ["paragrafet", (r.paragrafet || []).map(function (p, i) { return "[" + (i + 1) + "] " + p; }).join("\n\n")],
        ["pjesa / kreu / seksioni", [r.pjesa, r.kreu, r.seksioni].filter(Boolean).join(" / ")], ["repealed", String(r.repealed)], ["volatility", r.volatility], ["last_amendment_date", r.last_amendment_date],
        ["acts_meta", d.acts_meta], ["vettori densi", d.segmenti == null ? "nessuno" : (d.segmenti + " segmenti + articolo intero")], ["verificatore (autocitazione)", JSON.stringify(d.verificatore)],
        ["incostituzionalità (grafo)", d.incostituzionalita ? (d.incostituzionalita.stato + " — " + d.incostituzionalita.vendimi) : "—"]];
      var html = "<h2>" + esc(d.citation) + "</h2>" + (d.problemi.length ? d.problemi.map(function (x) { return '<span class="badge bad">' + esc(x) + "</span> "; }).join("") : '<span class="badge ok">nessun segnale di parsing</span>');
      html += '<h3>Record salvato (all_articles.jsonl → bm25.pkl)</h3><table class="rec">' + rows.map(function (kv) { return "<tr><th>" + esc(kv[0]) + "</th><td>" + esc(kv[1] || "—") + "</td></tr>"; }).join("") + "</table>";
      html += "<h3>Come lo legge il cervello (blocco nel prompt)</h3><pre>" + esc(d.prompt_block) + "</pre>";
      html += "<details><summary>Testo indicizzato (BM25 · primi 3000 caratteri)</summary><pre>" + esc(d.searchable_text) + "</pre></details>";
      html += "<details><summary>JSON grezzo</summary><pre>" + esc(JSON.stringify(r, null, 2)) + "</pre></details>";
      $("#detail").innerHTML = html;
    }).catch(function (e) { $("#detail").innerHTML = '<div class="empty">errore: ' + esc(e.message) + "</div>"; });
  }
  // ── sentenze ──
  function searchCases(page) {
    PAGE.cases = page || 1;
    var form = $("#f-cases"); $("#s-cases").textContent = "…";
    api("/api/inspect/cases?" + qs(form, { page: PAGE.cases, per_page: 25 })).then(function (d) {
      LAST.cases = d;
      $("#s-cases").textContent = d.total + " decisioni trovate";
      $("#r-cases").innerHTML = d.items.length ? d.items.map(function (c) {
        var t = esc(c.court) + " · nr. " + esc(c.number) + (c.year ? "/" + c.year : "");
        var b = (c.outcome ? ' <span class="badge">' + esc(c.outcome) + "</span>" : "") + (c.type ? ' <span class="badge">' + esc(c.type) + "</span>" : "") + (d.src === "al" && !c.raw ? ' <span class="badge warn">record grezzo non trovato</span>' : "");
        return '<li data-src="' + esc(d.src) + '" data-id="' + esc(c.id) + '"><div class="t">' + t + "</div><div>" + esc((c.objekti || c.summary || "").slice(0, 220)) + '</div><div class="m"><span>' + esc(c.date || "") + (c.n_articles != null ? " · " + c.n_articles + " nene cit." : "") + (c.score != null ? " · BM25 " + c.score : "") + "</span>" + b + "</div></li>";
      }).join("") : '<li class="empty">nessun risultato</li>';
      pager("cases", d);
    }).catch(function (e) { $("#s-cases").textContent = "errore: " + e.message; });
  }
  function showCase(src, id) {
    $("#detail").innerHTML = '<div class="empty">…</div>';
    api("/api/inspect/case/" + src + "/" + id).then(function (d) {
      var html = "";
      if (src === "al") {
        var p = d.precedent;
        html += "<h2>" + esc(p.citation) + "</h2>" + (d.annullata_da ? '<span class="badge bad">annullata dalla Gjykata Kushtetuese: ' + esc(d.annullata_da) + "</span>" : '<span class="badge ok">non risulta annullata</span>');
        html += '<h3>Come la vede il cervello (CasePrecedent)</h3><table class="rec">' + [["id", p.id], ["court", p.court + " (" + p.court_code + ")"], ["number / year / date", p.number + " / " + p.year + " / " + (p.date || "—")], ["type", p.type], ["outcome", p.outcome], ["summary", d.summary], ["excerpt", d.excerpt], ["judges", (d.judges || []).join(", ")], ["articles_cited", (d.articles_cited || []).map(function (x) { return x[0] + " " + x[1]; }).join(", ")], ["source", (d.source_url || "") + " " + (d.source_file || "")]].map(function (kv) { return "<tr><th>" + esc(kv[0]) + "</th><td>" + esc(kv[1] || "—") + "</td></tr>"; }).join("") + "</table>";
        if (d.raw) {
          var r = d.raw;
          html += '<h3>Record grezzo (bm25_decisions.pkl)</h3><table class="rec">' + [["court_code / title", r.court_code + " · " + r.court_title_sq], ["year / number / date", r.year + " / " + r.number + " / " + r.date], ["citation / short_id", r.citation + " · " + r.short_id], ["objekti", r.objekti], ["kerkues", r.kerkues], ["subjekte_interesuara", r.subjekte_interesuara], ["baza_ligjore", r.baza_ligjore], ["cited_articles", (r.cited_articles || []).join(", ")], ["outcome", r.outcome], ["dispositif", r.dispositif], ["reasoning (" + (r.reasoning || "").length + " chr)", r.reasoning], ["source_file / url", r.source_file + " " + r.source_url]].map(function (kv) { return "<tr><th>" + esc(kv[0]) + "</th><td>" + esc(kv[1] || "—") + "</td></tr>"; }).join("") + "</table>";
          html += "<details><summary>JSON grezzo</summary><pre>" + esc(JSON.stringify(r, null, 2)) + "</pre></details>";
        } else { html += '<p class="badge warn">nessun record grezzo nel pickle per questa chiave</p>'; }
      } else {
        var q = d.raw;
        html += "<h2>" + esc(q.court_name) + " · nr. " + esc(q.number) + "/" + esc(q.year) + "</h2>";
        html += '<h3>Record (it_decisions_fts.db)</h3><table class="rec">' + [["rowid", q.rowid], ["court / tipo", q.court + " / " + q.tipo], ["number / year / data", q.number + " / " + q.year + " / " + q.data], ["url", q.url], ["text (" + q.text_len + " chr)", q.text]].map(function (kv) { return "<tr><th>" + esc(kv[0]) + "</th><td>" + esc(kv[1] || "—") + "</td></tr>"; }).join("") + "</table>";
      }
      $("#detail").innerHTML = html;
    }).catch(function (e) { $("#detail").innerHTML = '<div class="empty">errore: ' + esc(e.message) + "</div>"; });
  }
  function pager(kind, d) {
    var p = $("#p-" + kind), pages = Math.max(1, Math.ceil(d.total / d.per_page));
    p.hidden = pages <= 1; p.querySelector("span").textContent = "pagina " + d.page + " di " + pages;
    p.querySelector("[data-dir='-1']").disabled = d.page <= 1; p.querySelector("[data-dir='1']").disabled = d.page >= pages;
  }
  // ── eventi ──
  document.querySelectorAll(".tabs button").forEach(function (b) { b.addEventListener("click", function () {
    document.querySelectorAll(".tabs button").forEach(function (x) { x.classList.toggle("on", x === b); });
    $("#tab-laws").hidden = b.dataset.tab !== "laws"; $("#tab-cases").hidden = b.dataset.tab !== "cases";
  }); });
  $("#f-laws").addEventListener("submit", function (e) { e.preventDefault(); searchLaws(1, false); });
  $("#browse").addEventListener("click", function () { searchLaws(1, true); });
  $("#f-laws [name=lang]").addEventListener("change", fillLawCodes);
  $("#f-cases").addEventListener("submit", function (e) { e.preventDefault(); searchCases(1); });
  $("#f-cases [name=src]").addEventListener("change", fillCaseFilters);
  $("#r-laws").addEventListener("click", function (e) { var li = e.target.closest("li[data-code]"); if (!li) return; document.querySelectorAll("#r-laws li").forEach(function (x) { x.classList.toggle("sel", x === li); }); showLaw(li.dataset.lang, li.dataset.code, li.dataset.number); });
  $("#r-cases").addEventListener("click", function (e) { var li = e.target.closest("li[data-id]"); if (!li) return; document.querySelectorAll("#r-cases li").forEach(function (x) { x.classList.toggle("sel", x === li); }); showCase(li.dataset.src, li.dataset.id); });
  ["laws", "cases"].forEach(function (kind) { $("#p-" + kind).addEventListener("click", function (e) { var b = e.target.closest("button[data-dir]"); if (!b) return; var np = PAGE[kind] + parseInt(b.dataset.dir, 10); if (kind === "laws") searchLaws(np, LAST.laws && LAST.laws.mode === "browse"); else searchCases(np); }); });
  api("/api/inspect/meta").then(function (m) { META = m; renderMeta(); }).catch(function (e) { $("#s-laws").textContent = "errore: " + e.message; });
})();
