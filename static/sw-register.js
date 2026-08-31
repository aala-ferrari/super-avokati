// Estratto da templates/index.html il 31 ago 2026.
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
