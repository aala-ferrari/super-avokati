/* Service worker di Super Avokati.
 *
 * Fa il minimo indispensabile perche' l'app sia installabile, e NIENTE
 * altro. In particolare non mette in cache pagine, script o risposte delle
 * API: un service worker che conserva l'applicazione e' la cosa piu'
 * pericolosa che si possa lasciare su un sito, perche' sopravvive ai deploy
 * e continua a servire il codice vecchio a utenti che non sanno perche'.
 *
 * L'unica cosa conservata e' la paginetta «non c'e' rete». Tutto il resto
 * passa dritto al server, come se questo file non esistesse.
 */
const VERSIONE = "sa-guscio-2";
const GUSCIO = ["/static/offline.html", "/static/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSIONE)
      .then((c) => c.addAll(GUSCIO))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())   // se il guscio non si scarica, pazienza
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomi) => Promise.all(
        nomi.filter((n) => n !== VERSIONE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                       // POST: mai toccare
  let url;
  try { url = new URL(req.url); } catch (_) { return; }
  if (url.origin !== self.location.origin) return;        // altri domini: mai
  if (url.pathname.startsWith("/api/")) return;           // il cervello: mai

  // Solo l'apertura di una pagina ha un ripiego, e solo quando la rete
  // manca davvero. Nessuna risposta viene conservata.
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/static/offline.html")));
  }
});

/* ── Notifiche ────────────────────────────────────────────────────────────
 *
 * Arrivano quando il cervello ha finito. Se pero' l'utente sta gia' guardando
 * l'applicazione non si mostra niente: notificare qualcosa che uno ha davanti
 * agli occhi e' il modo piu' rapido per far disattivare le notifiche.
 */
self.addEventListener("push", (e) => {
  let d = { title: "Super Avokati", body: "", url: "/", tag: "sa" };
  try { if (e.data) d = Object.assign(d, e.data.json()); } catch (_) {}

  e.waitUntil((async () => {
    const finestre = await self.clients.matchAll({
      type: "window", includeUncontrolled: true,
    });
    const guardando = finestre.some((c) => c.visibilityState === "visible" && c.focused);
    if (guardando) return;                     // ce l'ha gia' davanti

    await self.registration.showNotification(d.title, {
      body: d.body,
      tag: d.tag,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url: d.url },
      renotify: false,
    });
  })());
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const meta = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil((async () => {
    const finestre = await self.clients.matchAll({
      type: "window", includeUncontrolled: true,
    });
    // Se l'app e' gia' aperta si va li', invece di aprirne una seconda.
    for (const c of finestre) {
      if ("focus" in c) { await c.focus(); return; }
    }
    if (self.clients.openWindow) await self.clients.openWindow(meta);
  })());
});
