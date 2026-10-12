// Estratto da templates/login.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.
//
// ⚠️ IL BLOCCO QUI SOTTO (invio del modulo di accesso) ESISTEVA GIA' in questo
// file dal 19 agosto, e il 31 agosto l'ho sovrascritto estraendo gli script
// inline dell'HTML: il pulsante «Hyr» ha smesso di funzionare, perche' il
// modulo non ha ne' `action` ne' `method` e dipende solo da qui.
// Recuperato dall'immagine v9.215. Prima di scrivere un file, guardare se c'e'.

(() => {
  const form = document.getElementById("login-form");
  const usernameEl = document.getElementById("login-username");
  const passwordEl = document.getElementById("login-password");
  const btn = document.getElementById("login-btn");
  const errEl = document.getElementById("login-error");

  // v9.509 — LINGUA = SESSIONE anche qui: con la pagina in italiano il clic su «Entra» mostrava «Po verifikoj…», gli
  // errori in albanese («Demo ka skaduar», «Kredencialet janë të gabuara») e il pulsante tornava «Hyr»
  const _it = () => document.documentElement.lang === "it";
  const _M = {
    sq: { wait: "Po verifikoj…", login: "Hyr", bad: "⚠️ Kredencialet janë të gabuara.", net: "⚠️ Gabim rrjeti: ",
          err: "⚠️ Gabim gjatë hyrjes: ", many: (m) => "⚠️ Shumë përpjekje. Provo përsëri pas " + m + " minutash.",
          suspended: "⚠️ Llogaria juaj është pezulluar. Kontaktoni studion.",
          demo_expired: "⚠️ Prova falas ka skaduar. Për të vazhduar: info@aala.global · +355 69 955 5777",
          plan_expired: "⚠️ Abonimi juaj ka skaduar. Për ta rinovuar: info@aala.global · +355 69 955 5777" },
    it: { wait: "Verifico…", login: "Entra", bad: "⚠️ Credenziali errate.", net: "⚠️ Errore di rete: ",
          err: "⚠️ Errore durante l'accesso: ", many: (m) => "⚠️ Troppi tentativi. Riprova tra " + m + " minuti.",
          suspended: "⚠️ Il tuo account è sospeso. Contatta lo studio.",
          demo_expired: "⚠️ La prova gratuita è scaduta. Per continuare: info@aala.global · +39 380 635 8654",
          plan_expired: "⚠️ Il tuo abbonamento è scaduto. Per rinnovarlo: info@aala.global · +39 380 635 8654" },
  };
  const M = () => _M[_it() ? "it" : "sq"];

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.hidden = true;
    btn.disabled = true;
    btn.textContent = M().wait;
    try {
      const resp = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: usernameEl.value.trim(),
          password: passwordEl.value,
          // la lingua che la pagina mostra (scelta col pulsante, o dal paese e dal browser): decide anche la sessione
          lang: document.documentElement.lang || "",
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        errEl.textContent = data.error === "invalid credentials" ? M().bad
          : (data.blocked && M()[data.blocked]) ? M()[data.blocked]
          : resp.status === 429 ? M().many(Math.max(1, Math.round((data.retry_after || 60) / 60)))
          : M().err + (data.error || resp.status);
        errEl.hidden = false;
        passwordEl.value = "";
        passwordEl.focus();
        return;
      }
      // v9.426: dal link di un avviso («/s/<fascicolo>») si torna lì dopo il login — solo quel percorso, mai altri indirizzi
      var nxt = "";
      try { nxt = new URLSearchParams(window.location.search).get("next") || ""; } catch (e2) {}
      window.location.href = /^\/s(\/[0-9a-f-]{8,64})?$/.test(nxt) ? nxt : "/";
    } catch (err) {
      errEl.textContent = M().net + err.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = M().login;
    }
  });
})();

/* Registrazione silenziosa: se fallisce, il sito funziona esattamente
     come prima. Non e' una funzione da cui dipende niente. */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" })
        .catch(function () {});
    });
  }

// L'occhio della password — delega sul documento.
// ⚠️ NON tornare all'aggancio diretto (`getElementById(...).addEventListener`):
// era li' e non funzionava, e la diagnosi non e' mai arrivata in fondo. La
// delega non dipende da QUANDO gira lo script ne' dal fatto che l'elemento
// esista in quel momento — una condizione di guasto in meno.
(function () {
  var EYE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  var OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  document.addEventListener('click', function (e) {
    // `closest` perche' il bersaglio del click e' l'<svg> dentro il pulsante
    var b = e.target && e.target.closest ? e.target.closest('#toggle-pw') : null;
    if (!b) return;
    e.preventDefault();          // il pulsante sta dentro un <label>
    var i = document.getElementById('login-password');
    if (!i) return;
    var nascosta = i.getAttribute('type') === 'password';
    i.setAttribute('type', nascosta ? 'text' : 'password');
    b.innerHTML = nascosta ? OFF : EYE;
  });
})();

// v9.623 — la password dimenticata, da soli: prima «Harrova fjalëkalimin?» creava solo una richiesta per l'amministratore, che
// doveva reimpostarla a mano. Ora: l'email → un codice di 6 cifre (15 minuti) → il codice e la nuova password due volte. La
// risposta del server alla richiesta è sempre la stessa, che l'email esista o no.
(function(){
  var link=document.getElementById('forgot-link'),form=document.getElementById('forgot-form'),msg=document.getElementById('forgot-msg');
  if(!link||!form)return;
  var emailEl=document.getElementById('forgot-email'),btn=document.getElementById('forgot-btn'),step2=document.getElementById('forgot-step2');
  var codeEl=document.getElementById('forgot-code'),n1=document.getElementById('forgot-new'),n2=document.getElementById('forgot-new2'),setBtn=document.getElementById('forgot-set');
  var T={
    sq:{sent:"✓ Nëse email-i është i regjistruar, ju dërguam një kod me 6 shifra (shikoni edhe te «Spam»). Shkruajeni më poshtë.",
        again:"Dërgo përsëri kodin",err:"Gabim, provo sërish.",code6:"Shkruaj kodin me 6 shifra nga email-i.",
        short:"Fjalëkalimi i ri duhet të ketë të paktën 8 karaktere.",mismatch:"Dy fjalëkalimet e reja nuk përputhen.",
        done:"✓ Fjalëkalimi u ndryshua. Tani hyni me fjalëkalimin e ri."},
    it:{sent:"✓ Se l'email è registrata, ti abbiamo mandato un codice di 6 cifre (guarda anche nello «Spam»). Scrivilo qui sotto.",
        again:"Invia di nuovo il codice",err:"Errore, riprova.",code6:"Scrivi il codice di 6 cifre ricevuto per email.",
        short:"La nuova password deve avere almeno 8 caratteri.",mismatch:"Le due password nuove non coincidono.",
        done:"✓ Password cambiata. Ora entra con la nuova password."}
  };
  function it(){return document.documentElement.lang==='it';}
  function tr(k){return T[it()?'it':'sq'][k];}
  function mostra(testo,ok){msg.hidden=false;msg.style.color=ok?'#3aa981':'#e57373';msg.textContent=testo;}
  link.addEventListener('click',function(e){e.preventDefault();form.hidden=!form.hidden;if(!form.hidden)emailEl.focus();});
  form.addEventListener('submit',function(e){e.preventDefault();
    var em=emailEl.value.trim();if(!em)return;
    btn.disabled=true;
    fetch('/api/password-reset/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:em,lang:it()?'it':'sq'})})
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(){btn.disabled=false;btn.textContent=tr('again');step2.hidden=false;mostra(tr('sent'),true);codeEl.focus();})
    .catch(function(){btn.disabled=false;mostra(tr('err'),false);});
  });
  setBtn.addEventListener('click',function(){
    var code=(codeEl.value||'').replace(/\D/g,'');
    if(code.length!==6){mostra(tr('code6'),false);codeEl.focus();return;}
    if(n1.value.length<8){mostra(tr('short'),false);n1.focus();return;}
    if(n1.value!==n2.value){mostra(tr('mismatch'),false);n2.focus();return;}
    setBtn.disabled=true;
    fetch('/api/password-reset/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:emailEl.value.trim(),code:code,new:n1.value,lang:it()?'it':'sq'})})
    .then(function(r){return r.json().catch(function(){return {};}).then(function(d){if(!r.ok)throw new Error(d.error||tr('err'));return d;});})
    .then(function(d){
      step2.hidden=true;emailEl.style.display='none';btn.style.display='none';mostra(tr('done'),true);
      var u=document.getElementById('login-username'),p=document.getElementById('login-password');
      if(u&&d.username){u.value=d.username;} if(p){p.value='';p.focus();}
    })
    .catch(function(e){setBtn.disabled=false;mostra(e.message||tr('err'),false);});
  });
  [codeEl,n1,n2].forEach(function(el){el.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();setBtn.click();}});});
})();

(function(){
  var I18N={
    sq:{pw_toggle:"Shfaq/fshih fjalëkalimin",tagline:"Beteja fitohet para se të nisë.",username:"Përdoruesi",password:"Fjalëkalimi",login:"Hyr",forgot:"Harrova fjalëkalimin?",forgot_label:"Email-i yt (i regjistruar)",forgot_btn:"Dërgo kodin",forgot_code_label:"Kodi nga email-i (6 shifra)",forgot_new_label:"Fjalëkalimi i ri (të paktën 8 karaktere)",forgot_new2_label:"Përsërite fjalëkalimin e ri",forgot_set_btn:"Vendos fjalëkalimin e ri"},
    it:{pw_toggle:"Mostra/nascondi la password",tagline:"La battaglia si vince prima che inizi.",username:"Nome utente",password:"Password",login:"Entra",forgot:"Password dimenticata?",forgot_label:"La tua email (registrata)",forgot_btn:"Invia il codice",forgot_code_label:"Il codice dell'email (6 cifre)",forgot_new_label:"Nuova password (almeno 8 caratteri)",forgot_new2_label:"Ripeti la nuova password",forgot_set_btn:"Imposta la nuova password"}
  };
  function apply(lang,scelta){
    var d=I18N[lang]||I18N.sq;
    document.documentElement.lang=lang;
    document.querySelectorAll("[data-i18n]").forEach(function(el){var k=el.getAttribute("data-i18n");if(d[k])el.textContent=d[k];});
    document.querySelectorAll("[data-i18n-aria]").forEach(function(el){var k=el.getAttribute("data-i18n-aria");if(d[k])el.setAttribute("aria-label",d[k]);});
    document.querySelectorAll("[data-i18n-title]").forEach(function(el){var k=el.getAttribute("data-i18n-title");if(d[k])el.setAttribute("title",d[k]);});
    document.querySelectorAll(".ll-btn").forEach(function(b){b.classList.toggle("active",b.getAttribute("data-lang")===lang);});
    if(scelta){try{localStorage.setItem("sa_ui_lang",lang);}catch(e){}}
  }
  // 12 ott 2026 — si ricorda solo la lingua SCELTA col pulsante; senza scelta: quella scelta sulla pagina iniziale, poi il
  // paese dell'IP (nginx → data-paese: AL / IT), poi la lingua del browser, poi l'albanese
  function linguaIniziale(){
    var x=null;try{x=localStorage.getItem("sa_ui_lang");}catch(e){}
    if(x==="sq"||x==="it")return x;
    try{x=localStorage.getItem("sa_lang_scelta");}catch(e){x=null;}
    if(x==="sq"||x==="it")return x;
    var p=String(document.documentElement.getAttribute("data-paese")||"").toUpperCase();
    if(p==="IT")return "it";
    if(p==="AL")return "sq";
    var n=String((navigator.languages&&navigator.languages[0])||navigator.language||"").toLowerCase();
    return n.indexOf("it")===0?"it":"sq";
  }
  document.querySelectorAll(".ll-btn").forEach(function(b){b.addEventListener("click",function(){apply(b.getAttribute("data-lang"),true);});});
  apply(linguaIniziale(),false);
})();
