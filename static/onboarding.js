/* Super Avokati — turne i parë (onboarding).
   Regole di casa: file ESTERNO (CSP script-src 'self'), stili iniettati
   (style-src ha 'unsafe-inline'), zero dipendenze, zero backend: il "visto"
   vive in localStorage. Ogni passo salta da solo se il suo elemento non
   esiste o non si vede; qualunque errore = overlay via, app intatta. */
(function () {
  "use strict";
  var CHIAVE = "sa_tour_v1_done";
  var lang = (document.body && document.body.dataset && document.body.dataset.lang) || "sq";
  var L = lang === "it" ? "it" : "sq";

  var TESTI = {
    sq: {
      benvenuto_t: "Mirë se erdhe në Super Avokati",
      benvenuto_p: "Një turne i shkurtër — 60 sekonda — dhe e di ku është gjithçka.",
      fillo: "Fillo turneun", kalo: "Kaloje", vazhdo: "Vazhdo →", mbaro: "Fillo punën",
      hapa: [
        ["new-case-btn", "Rastet", "Këtu hap një rast të ri: çdo bisedë, dokument dhe kërkim jeton brenda rastit të vet."],
        ["mode-bar", "Mënyrat e punës", "Zgjidh si punon truri: pyetje-përgjigje, analizë e thellë, hartim aktesh…"],
        ["ask-input", "Pyetja", "Shkruaj si njeriu, jo si makina. Tetramorph arsyeton mbi 21 kode shqiptare, 43 italiane dhe mijëra vendime gjyqësore."],
        ["composer-attach", "Dokumentet", "Bashkangjit PDF, foto, Word — analizohen brenda rastit, me citime të verifikuara."],
        ["dosja-btn", "Dosja", "Gjithçka e ruajtur dhe e ngarkuar, nga të gjitha rastet — në një vend."],
        ["calendar-btn", "Kalendari & Sekretarja", "Afatet procedurale futen vetë në kalendar; Sekretarja virtuale mban takimet — edhe me zë."],
        ["menu-btn", "Veglat PRO", "Nga menuja gjen Super Prokurorin, Super Noterin, Modelet e Ekspertizës, provat video…"]
      ],
      fund_t: "Gati.",
      fund_p: "Beteja fitohet para se të nisë."
    },
    it: {
      benvenuto_t: "Benvenuto in Super Avokati",
      benvenuto_p: "Un giro veloce — 60 secondi — e sai dove sta tutto.",
      fillo: "Inizia il giro", kalo: "Salta", vazhdo: "Avanti →", mbaro: "Inizia a lavorare",
      hapa: [
        ["new-case-btn", "I casi", "Qui apri un caso nuovo: ogni conversazione, documento e ricerca vive dentro il suo caso."],
        ["mode-bar", "Le modalità", "Scegli come lavora il cervello: domanda-risposta, analisi profonda, redazione atti…"],
        ["ask-input", "La domanda", "Scrivi da persona, non da macchina. Tetramorph ragiona su 21 codici albanesi, 43 italiani e migliaia di sentenze."],
        ["composer-attach", "I documenti", "Allega PDF, foto, Word — vengono analizzati dentro il caso, con citazioni verificate."],
        ["dosja-btn", "Il dossier", "Tutto ciò che hai salvato e caricato, da tutti i casi — in un posto solo."],
        ["calendar-btn", "Calendario & Segretaria", "I termini processuali entrano da soli in calendario; la Segretaria virtuale tiene gli appuntamenti — anche a voce."],
        ["menu-btn", "Strumenti PRO", "Dal menu trovi Super Prokuror, Super Noteri, i Modelli di Perizia, le prove video…"]
      ],
      fund_t: "Pronto.",
      fund_p: "La battaglia si vince prima di iniziare."
    }
  };
  var T = TESTI[L];

  function vistoGia() {
    try { return localStorage.getItem(CHIAVE) === "1"; } catch (e) { return true; }
  }
  function segnaVisto() {
    try { localStorage.setItem(CHIAVE, "1"); } catch (e) {}
  }
  function visibile(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 4 && r.height > 4 && el.offsetParent !== null;
  }

  var stile = null, anello = null, carta = null, veli = [], passo = -1, tappe = [];

  function css() {
    stile = document.createElement("style");
    stile.textContent =
      ".sa-tour-veil{position:fixed;z-index:99997;background:rgba(6,10,26,.74);" +
      "transition:all .32s cubic-bezier(.4,.1,.2,1)}" +
      ".sa-tour-ring{position:fixed;z-index:99998;border:2px solid #c9a24b;border-radius:12px;" +
      "box-shadow:0 0 22px rgba(201,162,75,.55);" +
      "transition:all .32s cubic-bezier(.4,.1,.2,1);pointer-events:none}" +
      ".sa-tour-card{position:fixed;z-index:99999;max-width:320px;background:#101a33;" +
      "border:1px solid rgba(201,162,75,.5);border-radius:14px;padding:16px 18px;" +
      "color:#e8ecf7;font:14px/1.55 system-ui,-apple-system,sans-serif;" +
      "box-shadow:0 18px 50px rgba(0,0,0,.55);transition:all .32s cubic-bezier(.4,.1,.2,1)}" +
      ".sa-tour-card h3{margin:0 0 6px;font-size:16px;color:#f0dfa8}" +
      ".sa-tour-card p{margin:0 0 14px;color:#b9c2d8}" +
      ".sa-tour-row{display:flex;align-items:center;justify-content:space-between;gap:10px}" +
      ".sa-tour-n{font-size:12px;color:#7f8aa8}" +
      ".sa-tour-btns{display:flex;gap:8px}" +
      ".sa-tour-skip{background:none;border:none;color:#7f8aa8;font-size:13px;cursor:pointer;padding:6px 4px}" +
      ".sa-tour-skip:hover{color:#b9c2d8}" +
      ".sa-tour-go{background:linear-gradient(135deg,#c9a24b,#e7ce8e);border:none;color:#101a33;" +
      "font-weight:700;font-size:13px;padding:8px 16px;border-radius:999px;cursor:pointer}" +
      ".sa-tour-go:hover{filter:brightness(1.08)}" +
      "@media (max-width:520px){.sa-tour-card{max-width:calc(100vw - 28px)}}";
    document.head.appendChild(stile);
  }

  function via() {
    try {
      for (var vi = 0; vi < veli.length; vi++) if (veli[vi].parentNode) veli[vi].parentNode.removeChild(veli[vi]);
      veli = [];
      if (anello && anello.parentNode) anello.parentNode.removeChild(anello);
      if (carta && carta.parentNode) carta.parentNode.removeChild(carta);
      if (stile && stile.parentNode) stile.parentNode.removeChild(stile);
      document.removeEventListener("keydown", suTasto, true);
      window.removeEventListener("resize", riposiziona);
    } catch (e) {}
    anello = carta = stile = null;
  }
  function chiudi() { segnaVisto(); via(); }
  function suTasto(ev) { if (ev.key === "Escape") chiudi(); }

  function cartaHTML(titolo, testo, contatore, primario, ultima) {
    var salta = ultima ? "" : '<button type="button" class="sa-tour-skip">' + T.kalo + "</button>";
    return "<h3></h3><p></p>" +
      '<div class="sa-tour-row"><span class="sa-tour-n">' + contatore + "</span>" +
      '<div class="sa-tour-btns">' + salta +
      '<button type="button" class="sa-tour-go">' + primario + "</button></div></div>";
  }
  function riempi(titolo, testo, contatore, primario, ultima) {
    carta.innerHTML = cartaHTML(titolo, testo, contatore, primario, ultima);
    carta.querySelector("h3").textContent = titolo;
    carta.querySelector("p").textContent = testo;
    var s = carta.querySelector(".sa-tour-skip");
    if (s) s.onclick = chiudi;
    carta.querySelector(".sa-tour-go").onclick = avanti;
  }

  function velo(i, x, y, w, h) {
    var v = veli[i]; if (!v) return;
    v.style.left = Math.max(0, x) + "px";
    v.style.top = Math.max(0, y) + "px";
    v.style.width = Math.max(0, w) + "px";
    v.style.height = Math.max(0, h) + "px";
  }
  function buco(x0, y0, x1, y1) {
    var W = window.innerWidth, Hh = window.innerHeight;
    velo(0, 0, 0, W, y0);            // sopra
    velo(1, 0, y1, W, Hh - y1);      // sotto
    velo(2, 0, y0, x0, y1 - y0);     // sinistra
    velo(3, x1, y0, W - x1, y1 - y0);// destra
  }
  function posiziona(el) {
    var r = el.getBoundingClientRect(), m = 7;
    buco(r.left - m, r.top - m, r.right + m, r.bottom + m);
    anello.style.left = (r.left - m) + "px";
    anello.style.top = (r.top - m) + "px";
    anello.style.width = (r.width + m * 2) + "px";
    anello.style.height = (r.height + m * 2) + "px";
    anello.style.display = "block";
    var ch = carta.offsetHeight || 150, cw = carta.offsetWidth || 300;
    var sotto = r.bottom + 14 + ch < window.innerHeight;
    var top = sotto ? r.bottom + 14 : Math.max(12, r.top - ch - 14);
    var left = Math.min(Math.max(12, r.left), window.innerWidth - cw - 12);
    carta.style.top = top + "px";
    carta.style.left = left + "px";
    carta.style.transform = "none";
  }
  function centra() {
    buco(0, 0, 0, 0); // nessun buco: velo pieno
    anello.style.display = "none";
    carta.style.top = "50%";
    carta.style.left = "50%";
    carta.style.transform = "translate(-50%,-50%)";
  }
  function riposiziona() {
    try {
      if (passo >= 0 && passo < tappe.length && tappe[passo].el) posiziona(tappe[passo].el);
    } catch (e) {}
  }

  function mostra() {
    var t = tappe[passo];
    var contatore = (passo + 1) + "/" + tappe.length;
    var ultima = passo === tappe.length - 1;
    riempi(t.titolo, t.testo, contatore, ultima ? T.mbaro : (passo === 0 ? T.fillo : T.vazhdo), ultima);
    if (t.el) {
      try { t.el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
      requestAnimationFrame(function () { requestAnimationFrame(function () { posiziona(t.el); }); });
    } else {
      centra();
    }
  }
  function avanti() {
    passo++;
    if (passo >= tappe.length) { chiudi(); return; }
    mostra();
  }

  function costruisciTappe() {
    tappe = [{ el: null, titolo: T.benvenuto_t, testo: T.benvenuto_p }];
    for (var i = 0; i < T.hapa.length; i++) {
      var el = document.getElementById(T.hapa[i][0]);
      if (visibile(el)) tappe.push({ el: el, titolo: T.hapa[i][1], testo: T.hapa[i][2] });
    }
    tappe.push({ el: null, titolo: T.fund_t, testo: T.fund_p });
  }

  function parti() {
    try {
      if (document.querySelector(".sa-tour-card")) return;
      costruisciTappe();
      if (tappe.length < 4) { segnaVisto(); return; } // app troppo diversa: meglio niente che rotto
      css();
      veli = [];
      for (var vi = 0; vi < 4; vi++) {
        var v = document.createElement("div");
        v.className = "sa-tour-veil";
        document.body.appendChild(v);
        veli.push(v);
      }
      anello = document.createElement("div"); anello.className = "sa-tour-ring"; anello.style.display = "none";
      carta = document.createElement("div"); carta.className = "sa-tour-card";
      document.body.appendChild(anello); document.body.appendChild(carta);
      document.addEventListener("keydown", suTasto, true);
      window.addEventListener("resize", riposiziona);
      passo = 0; mostra();
    } catch (e) { via(); }
  }

  /* voce nel menu ☰ per rivederlo quando si vuole */
  function vocePerRivedere() {
    try {
      var dosja = document.getElementById("dosja-btn");
      if (!dosja || !dosja.parentNode) return;
      if (document.getElementById("tour-replay-btn")) return;
      var b = document.createElement("button");
      b.id = "tour-replay-btn";
      b.type = "button";
      b.className = dosja.className || "intake-btn";
      b.textContent = L === "it" ? "❔ Come funziona" : "❔ Si funksionon";
      b.onclick = function () { try { localStorage.removeItem(CHIAVE); } catch (e) {} via(); parti(); };
      dosja.parentNode.insertBefore(b, dosja.nextSibling);
    } catch (e) {}
  }

  function gdprAperto() {
    // il modale legale del primo accesso ha SEMPRE il pulsante di
    // accettazione: finché si vede, il turne non deve sovrapporsi
    return visibile(document.getElementById("legal-accetta"));
  }
  function partiQuandoLibero() {
    if (!gdprAperto()) { setTimeout(parti, 900); return; }
    var giri = 0;
    var attesa = setInterval(function () {
      giri++;
      if (!gdprAperto()) { clearInterval(attesa); setTimeout(parti, 900); }
      else if (giri > 400) clearInterval(attesa); // ~6 min: rinuncia in silenzio
    }, 900);
  }
  function pronto() {
    try {
      if (!document.getElementById("ask-input")) return; // non è la pagina dell'app
      vocePerRivedere();
      if (vistoGia()) return;
      setTimeout(partiQuandoLibero, 1400); // l'app si disegna, il GDPR passa, poi il turne
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pronto);
  } else {
    pronto();
  }
})();
