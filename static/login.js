// Estratto da templates/login.html il 31 ago 2026.
// ⚠️ NON rimetterlo dentro l'HTML: la Content-Security-Policy
// (`script-src 'self'`) blocca gli script inline, e il browser lo fa
// in SILENZIO — nessun errore, la pagina sembra a posto e non funziona.
// Se serve un valore dal server, passalo con un attributo `data-`.

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

(function(){
      var link=document.getElementById('forgot-link'),form=document.getElementById('forgot-form'),msg=document.getElementById('forgot-msg');
      if(!link)return;
      link.addEventListener('click',function(e){e.preventDefault();form.hidden=!form.hidden;});
      form.addEventListener('submit',function(e){e.preventDefault();
        var em=document.getElementById('forgot-email').value.trim();if(!em)return;
        var btn=document.getElementById('forgot-btn');btn.disabled=true;btn.textContent='...';
        fetch('/api/leads/intake',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({contact_name:'Reset fjalekalimi',contact_email:em,source:'web',
            problem_text:'KERKESE RESET FJALEKALIMI per Super Avokati (superavokati.ai). Perdoruesi me email '+em+' kerkon rivendosjen e fjalekalimit. Ju lutem kontaktoni perdoruesin dhe rivendosni fjalekalimin.'})})
        .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}).then(function(){
          document.getElementById('forgot-email').style.display='none';btn.style.display='none';
          msg.hidden=false;msg.textContent='\u2713 Kerkesa u dergua. Do te kontaktohesh me email nga administratori.';
        }).catch(function(){btn.disabled=false;btn.textContent='Dergo kerkesen';msg.hidden=false;msg.style.color='#e57373';msg.textContent='Gabim, provo serish.';});
      });
    })();

(function(){
  var I18N={
    sq:{pw_toggle:"Shfaq/fshih fjalëkalimin",tagline:"Beteja fitohet para se të nisë.",username:"Përdoruesi",password:"Fjalëkalimi",login:"Hyr",forgot:"Harrova fjalëkalimin?",forgot_label:"Email-i yt (i regjistruar)",forgot_btn:"Dërgo kërkesën"},
    it:{pw_toggle:"Mostra/nascondi la password",tagline:"La battaglia si vince prima che inizi.",username:"Nome utente",password:"Password",login:"Entra",forgot:"Password dimenticata?",forgot_label:"La tua email (registrata)",forgot_btn:"Invia richiesta"}
  };
  function apply(lang){
    var d=I18N[lang]||I18N.sq;
    document.documentElement.lang=lang;
    document.querySelectorAll("[data-i18n]").forEach(function(el){var k=el.getAttribute("data-i18n");if(d[k])el.textContent=d[k];});
    document.querySelectorAll("[data-i18n-aria]").forEach(function(el){var k=el.getAttribute("data-i18n-aria");if(d[k])el.setAttribute("aria-label",d[k]);});
    document.querySelectorAll("[data-i18n-title]").forEach(function(el){var k=el.getAttribute("data-i18n-title");if(d[k])el.setAttribute("title",d[k]);});
    document.querySelectorAll(".ll-btn").forEach(function(b){b.classList.toggle("active",b.getAttribute("data-lang")===lang);});
    try{localStorage.setItem("sa_ui_lang",lang);}catch(e){}
  }
  var lang="sq";try{lang=localStorage.getItem("sa_ui_lang")||"sq";}catch(e){}
  document.querySelectorAll(".ll-btn").forEach(function(b){b.addEventListener("click",function(){apply(b.getAttribute("data-lang"));});});
  apply(lang);
})();
