// Estratto da templates/in_hearing.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.

(function () {
  const CASE_ID = document.body.dataset.caseId || '';
  // v9.402: bilingue — la lingua arriva da `data-lang` (quella del fascicolo); il marchio «SUPER AVOKATI» non si traduce
  const IT = (document.body.dataset.lang || '') === 'it';
  const M = IT ? {
    empty: 'Nessuna nota. Detta o fai una domanda.', loadErr: 'Errore di caricamento.', delQ: 'Eliminare questa voce?',
    del: 'Elimina', writeSth: 'Scrivi qualcosa.', saved: 'Nota salvata', saveErr: 'Salvataggio non riuscito',
    writeQ: 'Scrivi la domanda.', asking: 'Sto chiedendo…', noAnswer: 'Nessuna risposta', answer: '✓ Risposta',
    noSpeech: 'Il browser non supporta la dettatura.', mic: 'Microfono: ', listening: 'In ascolto…',
    micErr: 'Microfono non avviato', stopped: 'Fermato', q: '❓ DOMANDA', note: '📝 NOTA',
  } : {
    empty: 'Asnjë shënim ende. Dikto ose pyet.', loadErr: 'Gabim në ngarkim.', delQ: 'Heq këtë?',
    del: 'Fshi', writeSth: 'Shkruaj diçka.', saved: 'Shënimi u ruajt', saveErr: 'Ruajtja dështoi',
    writeQ: 'Shkruaj pyetjen.', asking: 'Po pyes…', noAnswer: "S'erdhi përgjigje", answer: '✓ Përgjigja',
    noSpeech: 'Shfletuesi yt nuk e mbështet diktimin.', mic: 'Mikrofon: ', listening: 'Po dëgjoj…',
    micErr: "S'fillova mikrofonin", stopped: 'U ndal', q: '❓ PYETJE', note: '📝 SHËNIM',
  };
  const feed = document.getElementById("hh-feed");
  const input = document.getElementById("hh-input");
  const mic = document.getElementById("hh-mic");
  const btnNote = document.getElementById("hh-note");
  const btnAsk = document.getElementById("hh-ask");
  const btnClear = document.getElementById("hh-clear");
  const statusEl = document.getElementById("hh-status");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function fmtTime(iso) {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function setStatus(msg, kind = "") {
    statusEl.textContent = msg;
    statusEl.className = "hh-status " + kind;
    if (msg) setTimeout(() => { if (statusEl.textContent === msg) { statusEl.textContent = ""; statusEl.className = "hh-status"; } }, 4000);
  }

  function renderNotes(notes) {
    if (!notes.length) {
      feed.innerHTML = '<p class="hh-empty">' + M.empty + '</p>';
      return;
    }
    feed.innerHTML = notes.map(n => {
      const klass = n.kind === "question" ? "hh-question"
                  : n.kind === "ai_reply" ? "hh-ai"
                  : "hh-note";
      const label = n.kind === "question" ? M.q
                  : n.kind === "ai_reply" ? "🤖 SUPER AVOKATI"
                  : M.note;
      return `
        <div class="hh-bubble ${klass}" data-id="${n.id}">
          <div class="hh-meta">
            <span>${label}</span>
            <span>${fmtTime(n.created_at)} <button type="button" class="hh-del" data-del="${n.id}" title="${M.del}">✕</button></span>
          </div>
          <div>${escapeHtml(n.body_sq).replace(/\n/g, "<br>")}</div>
        </div>`;
    }).join("");
    requestAnimationFrame(() => { window.scrollTo(0, document.body.scrollHeight); });
  }

  async function loadNotes() {
    try {
      const r = await fetch(`/api/cases/${CASE_ID}/hearing/notes`);
      if (!r.ok) throw new Error();
      const data = await r.json();
      renderNotes(data.notes || []);
    } catch {
      feed.innerHTML = '<p class="hh-empty">' + M.loadErr + '</p>';
    }
  }

  feed.addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (!del) return;
    const id = del.getAttribute("data-del");
    if (!confirm(M.delQ)) return;
    const r = await fetch(`/api/cases/${CASE_ID}/hearing/notes/${id}`, { method: "DELETE" });
    if (r.ok) await loadNotes();
  });

  function autoresize() {
    input.style.height = "auto";
    input.style.height = Math.min(140, input.scrollHeight) + "px";
  }
  input.addEventListener("input", autoresize);

  btnNote.addEventListener("click", async () => {
    const body = input.value.trim();
    if (!body) { setStatus(M.writeSth); return; }
    btnNote.disabled = true;
    try {
      const r = await fetch(`/api/cases/${CASE_ID}/hearing/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body_sq: body, kind: "note" }),
      });
      if (!r.ok) throw new Error();
      input.value = ""; autoresize();
      setStatus(M.saved, "ok");
      await loadNotes();
    } catch {
      setStatus(M.saveErr, "error");
    } finally {
      btnNote.disabled = false;
    }
  });

  btnAsk.addEventListener("click", async () => {
    const q = input.value.trim();
    if (!q) { setStatus(M.writeQ); return; }
    btnAsk.disabled = true;
    setStatus(M.asking);
    try {
      const r = await fetch(`/api/cases/${CASE_ID}/hearing/quick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.error || M.noAnswer);
      }
      input.value = ""; autoresize();
      setStatus(M.answer, "ok");
      await loadNotes();
    } catch (err) {
      setStatus(err.message, "error");
    } finally {
      btnAsk.disabled = false;
    }
  });

  btnClear.addEventListener("click", () => { input.value = ""; autoresize(); input.focus(); });

  // ── Voice input via Web Speech API (Albanian) ────────────────────
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    mic.disabled = true;
    mic.title = M.noSpeech;
  } else {
    let rec = null;
    let listening = false;

    function startRec() {
      rec = new SR();
      rec.lang = IT ? "it-IT" : "sq-AL";
      rec.interimResults = true;
      rec.continuous = true;
      let baseline = input.value;
      let interim = "";
      rec.onresult = (e) => {
        interim = "";
        let final = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) final += t + " ";
          else interim += t;
        }
        if (final) {
          baseline = (baseline ? baseline.trim() + " " : "") + final.trim();
        }
        input.value = (baseline + (interim ? " " + interim : "")).trim();
        autoresize();
      };
      rec.onerror = (e) => {
        setStatus(M.mic + e.error, "error");
        stopRec();
      };
      rec.onend = () => {
        if (listening) {
          // browser auto-stopped — restart unless user toggled off
          try { rec.start(); } catch {}
        }
      };
      try {
        rec.start();
        listening = true;
        mic.classList.add("listening");
        setStatus(M.listening, "ok");
      } catch (err) {
        setStatus(M.micErr, "error");
      }
    }
    function stopRec() {
      listening = false;
      if (rec) try { rec.stop(); } catch {}
      mic.classList.remove("listening");
    }
    mic.addEventListener("click", () => {
      if (listening) { stopRec(); setStatus(M.stopped, ""); }
      else { startRec(); }
    });
  }

  // Initial load
  loadNotes();
  // Poll every 30s in case other devices add notes
  setInterval(loadNotes, 30000);

  // Keep screen awake during a hearing if supported
  if ("wakeLock" in navigator) {
    navigator.wakeLock.request("screen").catch(() => {});
  }
})();
