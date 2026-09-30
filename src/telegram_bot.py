# -*- coding: utf-8 -*-
"""v9.410 — il BOT TELEGRAM di Super Avokati: collegamento a un tocco e comandi minimi.

Prima il collegamento chiedeva all'avvocato il proprio «chat_id» numerico (scrivere a @userinfobot, copiare un numero,
incollarlo): nessuno dei 17 utenti l'aveva fatto, e sul server il bot non esisteva nemmeno. Ora:
  1. l'app crea un CODICE personale monouso (2 giorni, `storage.crea_token_telegram`) e apre
     `https://t.me/<bot>?start=<codice>`;
  2. l'avvocato preme «Avvia»: Telegram manda al nostro webhook «/start <codice>» con il suo chat_id;
  3. il codice diventa l'utente, il chat_id si salva, il bot risponde nella lingua dell'avvocato.
`/stop` scollega. Il webhook vive su una rotta segreta (derivata dal token del bot) e Telegram firma ogni chiamata con
l'intestazione `X-Telegram-Bot-Api-Secret-Token`: una chiamata senza firma giusta non tocca niente.
Senza `TELEGRAM_BOT_TOKEN` tutto è spento e l'interfaccia lo dice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from .config import TELEGRAM_BOT_TOKEN
from .logging_utils import get_logger

log = get_logger(__name__)

TG_API = "https://api.telegram.org"
PUBBLICO = os.getenv("SUPERAVOKATI_PUBLIC_URL", "https://superavokati.ai").rstrip("/")
_cache: dict = {}


def attivo() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def segreto() -> str:
    """Parte della rotta del webhook e firma attesa da Telegram: derivata dal token, mai scritta da nessuna parte."""
    return hmac.new(TELEGRAM_BOT_TOKEN.encode(), b"superavokati-webhook-v1", hashlib.sha256).hexdigest()[:48]


def _api(metodo: str, **param) -> dict:
    url = f"{TG_API}/bot{TELEGRAM_BOT_TOKEN}/{metodo}"
    dati = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                   for k, v in param.items()}).encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(url, data=dati, method="POST"), timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def nome_bot() -> str:
    """Lo username del bot (getMe), in cache un'ora: serve a costruire il link t.me."""
    if not attivo():
        return ""
    c = _cache.get("me")
    if c and time.time() - c[1] < 3600:
        return c[0]
    try:
        u = (_api("getMe").get("result") or {}).get("username") or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram getMe: %s", exc)
        return (c or ("", 0))[0]
    _cache["me"] = (u, time.time())
    return u


def link_collegamento(user_id: int) -> str:
    from . import storage
    bot = nome_bot()
    if not bot:
        return ""
    return f"https://t.me/{bot}?start={storage.crea_token_telegram(user_id)}"


def invia(chat_id: str, testo: str) -> bool:
    try:
        return bool(_api("sendMessage", chat_id=chat_id, text=testo, disable_web_page_preview="true").get("ok"))
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram sendMessage: %s", exc)
        return False


def _lingua_utente(user_id: int | None) -> str:
    """L'italiano solo per chi lavora SOLO in Italia; altrimenti albanese (con la riga italiana sotto, se ha anche l'IT)."""
    try:
        from . import storage
        u = storage.get_user_by_id(user_id) if user_id else None
        giur = [g.strip().upper() for g in (getattr(u, "jurisdictions", "") or "AL").split(",") if g.strip()]
        return "it" if giur == ["IT"] else "sq"
    except Exception:  # noqa: BLE001
        return "sq"


_T = {
    "ok": {"sq": "✅ U lidh me Super Avokati. Këtu do të marrësh kujtesat e seancave dhe të afateve të dosjeve.\n"
                 "/sot — agjenda e sotme · /java — 7 ditët · /afatet — për t'u konfirmuar · /stop — shkëput",
           "it": "✅ Collegato a Super Avokati. Qui riceverai gli avvisi di udienze e scadenze dei fascicoli.\n"
                 "/oggi — agenda di oggi · /settimana — 7 giorni · /scadenze — da confermare · /stop — scollega"},
    "ko": {"sq": "⚠️ Kodi nuk vlen ose ka skaduar. Hap Super Avokati → Kalendari → «Lidh Telegram» dhe provo sërish.\n"
                 "⚠️ Codice non valido o scaduto: apri Super Avokati → Calendario → «Collega Telegram» e riprova.",
           "it": "⚠️ Codice non valido o scaduto: apri Super Avokati → Calendario → «Collega Telegram» e riprova."},
    "info": {"sq": "Ky është bot-i i Super Avokati (superavokati.ai). Lidhu nga aplikacioni: Kalendari → «Lidh Telegram».\n"
                   "Questo è il bot di Super Avokati: collegati dall'app → Calendario → «Collega Telegram».",
             "it": "Questo è il bot di Super Avokati: collegati dall'app → Calendario → «Collega Telegram»."},
    "stop": {"sq": "U shkëpute. Nuk do të marrësh më kujtesa këtu.",
             "it": "Scollegato. Non riceverai più avvisi qui."},
    "comandi": {"sq": "Komandat: /sot — seancat dhe afatet e sotme dhe të nesërme · /java — 7 ditët e ardhshme · "
                      "/afatet — afatet nga dokumentet për t'u konfirmuar · /stop — shkëput. Ose më shkruaj (ose më dërgo një mesazh zanor): "
                      "«çfarë kam javën tjetër?», «regjistro seancë më 4 nëntor ora 10 për Kolën»",
                "it": "Comandi: /oggi — udienze e scadenze di oggi e domani · /settimana — i prossimi 7 giorni · "
                      "/scadenze — scadenze dai documenti da confermare · /stop — scollega. Oppure scrivimi (o mandami un vocale): "
                      "«cosa ho la settimana prossima?», «registra udienza il 4 novembre alle 10 per Rossi»"},
}


# v9.416 — COMANDI dell'avvocato collegato: l'agenda e le scadenze da confermare, nella sua lingua e in ORA LOCALE (Tirana/Roma).
# Solo in chat privata e solo per il Telegram collegato a un account (`utente_da_chat_telegram`): nessun dato a chi non è collegato.
_ICONA = {"seance": "⚖️", "afat": "⏰", "dorëzim": "📤", "takim": "🤝", "tjetër": "📌"}
_CMD_OGGI, _CMD_SETT, _CMD_SCAD = {"/oggi", "/sot"}, {"/settimana", "/java"}, {"/scadenze", "/afatet"}


def _titoli_casi(case_ids) -> dict:
    from . import storage
    ids = [c for c in set(case_ids) if c]
    if not ids:
        return {}
    with storage.db() as conn:
        rows = conn.execute("SELECT id, title FROM cases WHERE id IN (" + ",".join("?" * len(ids)) + ")", ids).fetchall()
    return {r["id"]: (r["title"] or "").strip()[:60] for r in rows}


def agenda(uid: int, giorni: int, lang: str) -> str:
    from datetime import datetime, timedelta, timezone
    from . import storage
    it = lang == "it"
    fuso = storage.fuso_di("IT" if it else "AL")
    inizio_loc = datetime.now(fuso).replace(hour=0, minute=0, second=0, microsecond=0)
    da = inizio_loc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = (inizio_loc + timedelta(days=giorni)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    eventi = [e for e in storage.list_events(uid, start=da, end=a) if not e.done]
    titoli = _titoli_casi(e.case_id for e in eventi)
    quando = (("oggi e domani" if giorni == 2 else f"i prossimi {giorni} giorni") if it else
              ("sot dhe nesër" if giorni == 2 else f"{giorni} ditët e ardhshme"))
    if not eventi:
        testo = (f"Nessuna udienza o scadenza per {quando}." if it else f"Asnjë seancë apo afat për {quando}.")
    else:
        righe = []
        for e in eventi[:25]:
            g = storage.giurisdizione_evento(e)
            fmt = "%d/%m" if e.all_day else "%d/%m %H:%M"
            caso = titoli.get(e.case_id or "", "")
            righe.append(f"{_ICONA.get(e.kind, '📌')} {storage.ora_locale(e.starts_at, g, fmt)} · {e.title}"
                         + (f" — «{caso}»" if caso else "") + (f" · {e.location}" if e.location else ""))
        testo = (f"📅 Agenda — {quando} ({len(eventi)}):\n" if it else f"📅 Agjenda — {quando} ({len(eventi)}):\n") + "\n".join(righe)
        if len(eventi) > 25:
            testo += f"\n… +{len(eventi) - 25}"
    n = len(storage.lista_scadenze_proposte(user_id=uid, stati=("proposta",)))
    if n:
        testo += (f"\n\n🟡 {n} scadenz{'a' if n == 1 else 'e'} dai documenti da confermare: /scadenze" if it else
                  f"\n\n🟡 {n} afat{'' if n == 1 else 'e'} nga dokumentet për t'u konfirmuar: /afatet")
    return testo


def da_confermare(uid: int, lang: str) -> str:
    from . import storage
    it = lang == "it"
    pr = storage.lista_scadenze_proposte(user_id=uid, stati=("proposta",))
    if not pr:
        return ("Nessuna scadenza da confermare." if it else "Asnjë afat për t'u konfirmuar.")
    titoli = _titoli_casi(p["case_id"] for p in pr)
    per_caso: dict = {}
    for p in pr:
        per_caso.setdefault(p["case_id"], []).append(p)
    righe = []
    for cid, lista in list(per_caso.items())[:8]:
        righe.append(f"\n📁 {titoli.get(cid) or '—'}")
        for p in lista[:6]:
            d = "/".join(reversed(p["data"].split("-"))) if p.get("data") else ("senza data" if it else "pa datë")
            righe.append(f"  {_ICONA.get(p['kind'], '📌')} {d} · {p['titolo'][:90]}" + ("" if p.get("verificato") else " ⚠️"))
    return ((f"🟡 Da confermare ({len(pr)}) — aprili nel fascicolo su superavokati.ai:" if it else
             f"🟡 Për t'u konfirmuar ({len(pr)}) — hapi në dosje te superavokati.ai:") + "\n".join(righe))


# v9.420 — la SEGRETARIA TETRAMORPH su Telegram (richiesta del titolare: «stesso lavoro che fa dal portale»): testo libero o
# VOCALE → `secretary.handle_message` (la stessa del portale: agenda dell'avvocato, azioni proposte); un'azione di scrittura
# (registra / sposta / cancella) si esegue SOLO col pulsante ✅ (callback), come la conferma del portale. Gira in un thread: il
# webhook risponde subito (Telegram ritenta le risposte lente). Memoria delle ultime battute per chat, azioni in attesa 30 min,
# tetto di messaggi all'ora per avvocato (l'abbonamento è condiviso).
_CERVELLO = {"get": None}
_STORIA: dict = {}                 # chat_id -> (ultimo_ts, [messaggi])
_AZIONI: dict = {}                 # token -> {uid, chat, action, lang, ts}
_USO: dict = {}                    # uid -> [timestamp]
MAX_ORA = int(os.getenv("TELEGRAM_SEGRETARIA_MAX_ORA", "40"))
_MAX_VOCALE_S = 120


def imposta_cervello(getter) -> None:
    _CERVELLO["get"] = getter


def _limite_ok(uid: int) -> bool:
    ora = time.time()
    lista = [t for t in _USO.get(uid, []) if ora - t < 3600]
    if len(lista) >= MAX_ORA:
        _USO[uid] = lista
        return False
    lista.append(ora)
    _USO[uid] = lista
    return True


def _storia(chat_id: str) -> list:
    ts, lista = _STORIA.get(chat_id, (0, []))
    if time.time() - ts > 7200:            # dopo 2 ore di silenzio si riparte da capo
        lista = []
    return lista


def _vocale_in_testo(voice: dict, lang: str) -> str:
    """Il vocale di Telegram → testo, con il trascrittore LOCALE (`audio.trascrivi`: la voce non esce dal server)."""
    import tempfile
    from pathlib import Path as _P
    from . import audio as _audio
    if int(voice.get("duration") or 0) > _MAX_VOCALE_S:
        return ""
    info = _api("getFile", file_id=voice.get("file_id") or "").get("result") or {}
    fp = info.get("file_path") or ""
    if not fp:
        return ""
    with tempfile.TemporaryDirectory() as d:
        dest = _P(d) / ("voce" + (_P(fp).suffix or ".ogg"))
        with urllib.request.urlopen(f"{TG_API}/file/bot{TELEGRAM_BOT_TOKEN}/{fp}", timeout=30) as r:
            dest.write_bytes(r.read())
        segmenti, _lg, _conf = _audio.trascrivi(dest)
    return " ".join(t for _a, _b, t in segmenti).strip()


def _tastiera(token: str, lang: str) -> dict:
    return {"inline_keyboard": [[{"text": "✅ " + ("Conferma" if lang == "it" else "Konfirmo"), "callback_data": "ok:" + token},
                                 {"text": "❌ " + ("Annulla" if lang == "it" else "Anulo"), "callback_data": "no:" + token}]]}


def _segretaria(uid: int, chat_id: str, testo: str, voice: dict | None) -> None:
    from . import brain as _brain, secretary as _sec
    lang = _lingua_utente(uid)
    it = lang == "it"
    try:
        _brain.set_request_user(uid)
        _brain.set_request_jurisdiction("IT" if it else "AL")   # lingua e agenda della giurisdizione dell'avvocato
    except Exception:  # noqa: BLE001
        pass
    try:
        _api("sendChatAction", chat_id=chat_id, action="typing")
    except Exception:  # noqa: BLE001
        pass
    if voice:
        try:
            testo = _vocale_in_testo(voice, lang)
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram: vocale non trascritto: %s", exc)
            testo = ""
        if not testo:
            invia(chat_id, "Non sono riuscita a capire il vocale (massimo 2 minuti): riprova o scrivi." if it else
                  "Nuk e kuptova mesazhin zanor (maksimumi 2 minuta): provo sërish ose shkruaj.")
            return
        invia(chat_id, "🎙️ «" + testo[:300] + "»")
    cervello = _CERVELLO["get"]() if _CERVELLO["get"] else None
    if cervello is None:
        invia(chat_id, "Il servizio è momentaneamente occupato: riprova tra poco." if it else
              "Shërbimi është i zënë për momentin: provo pak më vonë.")
        return
    storia = _storia(chat_id) + [{"role": "user", "content": testo[:2000]}]
    try:
        r = _sec.handle_message(cervello, uid, storia[-10:])
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram segretaria: %s", exc)
        invia(chat_id, "Non sono riuscita a rispondere: riprova tra poco." if it else "Nuk arrita të përgjigjem: provo pak më vonë.")
        return
    risposta = (r.get("reply") or "").strip()
    storia.append({"role": "assistant", "content": risposta[:2000]})
    _STORIA[chat_id] = (time.time(), storia[-10:])
    azione = r.get("action") if isinstance(r.get("action"), dict) else None
    if not azione:
        invia(chat_id, risposta or ("Fatto." if it else "Në rregull."))
        return
    import secrets as _secrets
    tok = _secrets.token_urlsafe(9)
    for k in [k for k, v in _AZIONI.items() if time.time() - v["ts"] > 1800]:
        _AZIONI.pop(k, None)
    _AZIONI[tok] = {"uid": uid, "chat": chat_id, "action": azione, "lang": lang, "ts": time.time()}
    riepilogo = (azione.get("confirm") or "").strip()
    testo_conf = (risposta + ("\n\n📝 " + riepilogo if riepilogo and riepilogo not in risposta else "")).strip()
    try:
        _api("sendMessage", chat_id=chat_id, text=testo_conf[:3900], reply_markup=_tastiera(tok, lang),
             disable_web_page_preview="true")
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram: conferma non inviata: %s", exc)


# v9.422 — DOCUMENTI MANDATI AL BOT (PDF, foto, Word): l'avvocato fotografa la notifica e la manda; il bot chiede con i pulsanti a
# quale fascicolo allegarla (prima quelli che corrispondono alla didascalia, poi i recenti, e «➕ Nuovo fascicolo» col nome della
# didascalia); dopo il clic il documento entra nel fascicolo come dal portale (`web.avvia_elaborazione_documento`: OCR, riassunto,
# scadenziario automatico, che avvisa qui con le scadenze trovate). Il file resta sul server in attesa della scelta (30 minuti).
_DOC_ATTESA: dict = {}              # token -> {uid, chat, path, nome, casi:[(id, titolo)], nuovo, ts}
_MAX_DOC_MB = 20                    # limite dei bot Telegram per scaricare un file


def _parole(t: str) -> set:
    import re as _re
    return {w for w in _re.findall(r"[a-zà-ÿëç]{3,}", (t or "").lower())} - {"per", "del", "della", "dei", "con", "për", "nga", "dhe"}


def _stessa_radice(a: str, b: str) -> bool:
    """«kolës» ~ «kola», «hoxhës» ~ «hoxha»: dieresi piegate, radice comune di almeno 3 lettere e fino alla penultima lettera
    della parola più corta (le desinenze albanesi cambiano la coda)."""
    f = lambda w: w.replace("ë", "e").replace("ç", "c")
    a, b = f(a), f(b)
    if a == b:
        return True
    corta = min(len(a), len(b))
    comune = 0
    while comune < corta and a[comune] == b[comune]:
        comune += 1
    return comune >= 3 and comune >= corta - 1


def _documento(uid: int, chat_id: str, msg: dict) -> None:
    import secrets as _secrets
    import tempfile
    from pathlib import Path as _P
    from . import brain as _brain, secretary as _sec, documents as _docs
    lang = _lingua_utente(uid)
    it = lang == "it"
    try:
        _brain.set_request_user(uid)
        _brain.set_request_jurisdiction("IT" if it else "AL")
    except Exception:  # noqa: BLE001
        pass
    if msg.get("photo"):
        info_f = max(msg["photo"], key=lambda x: int(x.get("file_size") or 0))
        nome = "foto_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg"
    else:
        info_f = msg.get("document") or {}
        nome = (info_f.get("file_name") or "documento").strip()[:120]
    if int(info_f.get("file_size") or 0) > _MAX_DOC_MB * 1024 * 1024:
        invia(chat_id, f"Il file supera i {_MAX_DOC_MB} MB che Telegram permette ai bot: caricalo dal portale." if it else
              f"Skedari kalon {_MAX_DOC_MB} MB që Telegram lejon për bot-et: ngarkoje nga portali.")
        return
    v = _docs.validate_upload(nome, int(info_f.get("file_size") or 1))
    if not v.ok:
        invia(chat_id, ("Questo tipo di file non si può allegare: " if it else "Ky lloj skedari nuk mund të bashkëngjitet: ") + str(v.error))
        return
    try:
        fp = (_api("getFile", file_id=info_f.get("file_id") or "").get("result") or {}).get("file_path") or ""
        d = _P(tempfile.mkdtemp(prefix="tgdoc-"))
        dest = d / ("file" + v.ext)
        with urllib.request.urlopen(f"{TG_API}/file/bot{TELEGRAM_BOT_TOKEN}/{fp}", timeout=60) as r:
            dest.write_bytes(r.read())
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram: documento non scaricato: %s", exc)
        invia(chat_id, "Non sono riuscita a scaricare il file: riprova." if it else "Nuk arrita ta shkarkoj skedarin: provo sërish.")
        return
    didascalia = (msg.get("caption") or "").strip()
    casi = _sec.casi_visibili(uid)
    p_dida = _parole(didascalia)

    def punteggio(c) -> int:
        # le forme flesse albanesi («Kolës», «Kolën» per «Kola»; «Hoxhës» per «Hoxha»): conta la RADICE di 4 lettere
        pt = _parole(c.title or "")
        return sum(1 for a in p_dida if any(_stessa_radice(a, b) for b in pt))
    corrispondenti = sorted([c for c in casi if p_dida and punteggio(c) > 0], key=punteggio, reverse=True)
    scelti = (corrispondenti + [c for c in casi if c not in corrispondenti])[:6]
    tok = _secrets.token_urlsafe(6)
    for k in [k for k, x in _DOC_ATTESA.items() if time.time() - x["ts"] > 1800]:
        vecchio = _DOC_ATTESA.pop(k, None)
        try:
            _P(vecchio["path"]).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    nuovo = didascalia[:80] if (didascalia and not corrispondenti) else ""
    _DOC_ATTESA[tok] = {"uid": uid, "chat": chat_id, "path": str(dest), "nome": nome, "ts": time.time(),
                        "casi": [(c.id, c.title or "—") for c in scelti], "nuovo": nuovo, "lang": lang}
    righe = [[{"text": "📁 " + (t[:40] or "—"), "callback_data": f"d:{tok}:{i}"}] for i, (_cid, t) in enumerate(_DOC_ATTESA[tok]["casi"])]
    if nuovo:
        righe.append([{"text": "➕ " + ("Nuovo fascicolo: " if it else "Dosje e re: ") + nuovo[:30], "callback_data": f"d:{tok}:n"}])
    righe.append([{"text": "❌ " + ("Annulla" if it else "Anulo"), "callback_data": f"d:{tok}:x"}])
    testo = ((f"📎 «{nome}» — a quale fascicolo lo allego? Poi lo leggo e ti scrivo qui le scadenze che trovo."
              + ("" if didascalia else "\nSuggerimento: scrivi il nome del cliente nella didascalia della foto.")) if it else
             (f"📎 «{nome}» — në cilën dosje ta bashkëngjit? Pastaj e lexoj dhe të shkruaj këtu afatet që gjej."
              + ("" if didascalia else "\nKëshillë: shkruaj emrin e klientit te përshkrimi i fotos.")))
    if not casi and not nuovo:
        testo += ("\n\nNon hai ancora fascicoli: rimanda il file scrivendo il nome del cliente nella didascalia." if it else
                  "\n\nNuk ke ende dosje: ridërgoje skedarin me emrin e klientit te përshkrimi.")
    try:
        _api("sendMessage", chat_id=chat_id, text=testo, reply_markup={"inline_keyboard": righe})
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram: scelta del fascicolo non inviata: %s", exc)


def _allega_documento(cb_chat: str, tok: str, scelta: str, uid: int | None) -> None:
    import shutil as _sh
    from pathlib import Path as _P
    from . import storage, brain as _brain, documents as _docs, web as _web
    att = _DOC_ATTESA.pop(tok, None)
    if not att or not uid or att["uid"] != uid or att["chat"] != cb_chat:
        invia(cb_chat, "Richiesta scaduta: rimanda il file." if _lingua_utente(uid) == "it" else "Kërkesa ka skaduar: ridërgoje skedarin.")
        return
    it = att["lang"] == "it"
    src = _P(att["path"])
    try:
        if scelta == "x":
            invia(cb_chat, "Annullato: il file non è stato allegato." if it else "U anulua: skedari nuk u bashkëngjit.")
            return
        _brain.set_request_user(uid)
        _brain.set_request_jurisdiction("IT" if it else "AL")
        if scelta == "n" and att.get("nuovo"):
            caso = storage.create_case(uid, att["nuovo"], jurisdiction="IT" if it else "AL")
            cid, titolo = caso.id, caso.title
        else:
            try:
                cid, titolo = att["casi"][int(scelta)]
            except (ValueError, IndexError):
                return
            from . import secretary as _sec
            if not _sec._caso_valido(uid, cid):         # il fascicolo deve essere ancora visibile a chi allega
                invia(cb_chat, "Fascicolo non trovato." if it else "Dosja nuk u gjet.")
                return
        if storage.count_documents(cid) >= _web.MAX_DOCUMENTS_PER_CASE:
            invia(cb_chat, "Il fascicolo ha già il numero massimo di documenti." if it else "Dosja ka numrin maksimal të dokumenteve.")
            return
        v = _docs.validate_upload(att["nome"], src.stat().st_size)
        dest = _docs.storage_path_for(cid, v.ext)
        _sh.move(str(src), str(dest))
        doc = storage.create_document(case_id=cid, filename=att["nome"], ext=v.ext, mimetype=v.mimetype,
                                      size_bytes=dest.stat().st_size, storage_path=str(dest))
        _web.avvia_elaborazione_documento(doc, cid, uid, "IT" if it else "AL", dest, att["nome"])
        invia(cb_chat, (f"✅ Allegato al fascicolo «{titolo}». Lo sto leggendo: se trovo scadenze te le scrivo qui "
                        "(da confermare nel portale o con /scadenze).") if it else
              (f"✅ U bashkëngjit te dosja «{titolo}». Po e lexoj: nëse gjej afate t'i shkruaj këtu "
               "(për t'u konfirmuar në portal ose me /afatet)."))
    except Exception as exc:  # noqa: BLE001
        log.exception("telegram: documento non allegato")
        invia(cb_chat, ("Non sono riuscita ad allegare il file: caricalo dal portale (" if it else
                        "Nuk arrita ta bashkëngjit skedarin: ngarkoje nga portali (") + type(exc).__name__ + ").")
    finally:
        try:
            if src.exists():
                src.unlink()
            src.parent.rmdir()
        except Exception:  # noqa: BLE001
            pass


def _esito_in_lingua(uid: int, azione: dict, res: dict, lang: str) -> str:
    """Il testo dell'esito nella lingua dell'avvocato (quello di `secretary.execute_action` è solo albanese)."""
    from . import storage
    if lang != "it" or not res.get("ok") or (res.get("reply") or "").startswith(("✅ Registrato", "✅ Aggiornato", "🗑 Eliminato")):
        return res.get("reply") or ""
    t = azione.get("type")
    if t == "create_event" and res.get("event_id"):
        ev = storage.get_event(res["event_id"], uid)
        if ev:
            return (f"✅ Registrato: «{ev.title}» — {storage.ora_locale(ev.starts_at, storage.giurisdizione_evento(ev))}"
                    + (f" — fascicolo «{res['case_title']}»." if res.get("case_title") else "."))
    if t == "update_event":
        return "✅ Aggiornato."
    if t == "delete_event":
        return "🗑 Eliminato."
    return res.get("reply") or "✅"


def _gestisci_callback(cb: dict) -> None:
    from . import storage, secretary as _sec, brain as _brain
    dati = cb.get("data") or ""
    chat_id = str(((cb.get("message") or {}).get("chat") or {}).get("id") or "")
    msg_id = (cb.get("message") or {}).get("message_id")
    try:
        _api("answerCallbackQuery", callback_query_id=cb.get("id") or "")
    except Exception:  # noqa: BLE001
        pass
    uid = storage.utente_da_chat_telegram(chat_id) if chat_id else None
    if dati.startswith("d:"):                         # v9.422: scelta del fascicolo per un documento mandato al bot
        _p, tok_d, sc = (dati.split(":") + ["", ""])[:3]
        try:
            if msg_id:
                _api("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id, reply_markup={"inline_keyboard": []})
        except Exception:  # noqa: BLE001
            pass
        _allega_documento(chat_id, tok_d, sc, uid)
        return
    scelta, _, tok = dati.partition(":")
    az = _AZIONI.pop(tok, None)
    try:
        if msg_id:
            _api("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id, reply_markup={"inline_keyboard": []})
    except Exception:  # noqa: BLE001
        pass
    if not az or not uid or az["uid"] != uid or az["chat"] != chat_id:
        invia(chat_id, "Richiesta scaduta: riscrivila." if _lingua_utente(uid) == "it" else "Kërkesa ka skaduar: rishkruaje.")
        return
    lang = az["lang"]
    if scelta != "ok":
        invia(chat_id, "Annullato: non ho cambiato niente." if lang == "it" else "U anulua: nuk ndryshova asgjë.")
        return
    try:
        _brain.set_request_user(uid)
        _brain.set_request_jurisdiction("IT" if lang == "it" else "AL")
    except Exception:  # noqa: BLE001
        pass
    res = _sec.execute_action(uid, az["action"])
    invia(chat_id, _esito_in_lingua(uid, az["action"], res, lang))


def gestisci_update(upd: dict) -> None:
    """Un messaggio arrivato al bot. Mai solleva: il webhook risponde sempre 200 a Telegram (altrimenti ritenta all'infinito)."""
    from . import storage
    try:
        if upd.get("callback_query"):
            threading.Thread(target=_gestisci_callback, args=(upd["callback_query"],), name="tg-cb", daemon=True).start()
            return
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return                                    # mai nei gruppi: gli avvisi sono dati riservati del fascicolo
        chat_id = str(chat.get("id") or "")
        testo = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")
        if chat_id and (msg.get("document") or msg.get("photo")):
            uid_d = storage.utente_da_chat_telegram(chat_id)
            if not uid_d:
                invia(chat_id, _T["info"]["sq"])
                return
            if not _limite_ok(uid_d):
                return
            threading.Thread(target=_documento, args=(uid_d, chat_id, msg), name="tg-doc", daemon=True).start()
            return
        if not chat_id or not (testo or voice):
            return
        if testo.startswith("/start"):
            codice = testo.split(maxsplit=1)[1].strip() if len(testo.split(maxsplit=1)) > 1 else ""
            uid = storage.usa_token_telegram(codice) if codice else None
            if uid:
                vecchio = storage.utente_da_chat_telegram(chat_id)
                if vecchio and vecchio != uid:
                    storage.set_user_telegram_chat(vecchio, None)     # un telefono = un avvocato
                storage.set_user_telegram_chat(uid, chat_id)
                invia(chat_id, _T["ok"][_lingua_utente(uid)])
                log.info("telegram: collegato l'utente %s", uid)
            else:
                invia(chat_id, _T["ko"]["sq"] if codice else _T["info"]["sq"])
            return
        if testo.startswith("/stop"):
            uid = storage.utente_da_chat_telegram(chat_id)
            if uid:
                storage.set_user_telegram_chat(uid, None)
            invia(chat_id, _T["stop"][_lingua_utente(uid)])
            return
        uid = storage.utente_da_chat_telegram(chat_id)
        comando = testo.split()[0].split("@")[0].lower() if testo else ""
        if uid and comando in _CMD_OGGI | _CMD_SETT | _CMD_SCAD:
            lg = _lingua_utente(uid)
            if comando in _CMD_SCAD:
                invia(chat_id, da_confermare(uid, lg))
            else:
                invia(chat_id, agenda(uid, 2 if comando in _CMD_OGGI else 7, lg))
            return
        if uid and not comando.startswith("/"):
            if not _limite_ok(uid):
                invia(chat_id, "Troppi messaggi nell'ultima ora: riprova più tardi." if _lingua_utente(uid) == "it" else
                      "Shumë mesazhe në orën e fundit: provo më vonë.")
                return
            threading.Thread(target=_segretaria, args=(uid, chat_id, testo, voice), name="tg-seg", daemon=True).start()
            return
        invia(chat_id, (_T["comandi"][_lingua_utente(uid)] if uid else _T["info"]["sq"]))
    except Exception:  # noqa: BLE001
        log.exception("telegram: update non gestito")


def registra_webhook() -> None:
    """Dice a Telegram dove mandare i messaggi (idempotente). Gira in un thread all'avvio: se Telegram non risponde, l'app
    parte lo stesso e si riprova al prossimo avvio."""
    if not attivo():
        return

    def _fai():
        try:
            url = f"{PUBBLICO}/telegram/webhook/{segreto()}"
            r = _api("setWebhook", url=url, secret_token=segreto(), allowed_updates=["message", "callback_query"],
                     drop_pending_updates="true")
            log.info("telegram setWebhook: %s", "ok" if r.get("ok") else r.get("description"))
            try:
                _api("setMyCommands", commands=[
                    {"command": "sot", "description": "Agjenda e sotme dhe e nesërme"},
                    {"command": "java", "description": "7 ditët e ardhshme"},
                    {"command": "afatet", "description": "Afatet për t'u konfirmuar"},
                    {"command": "stop", "description": "Shkëput"}])
                _api("setMyCommands", language_code="it", commands=[
                    {"command": "oggi", "description": "Agenda di oggi e domani"},
                    {"command": "settimana", "description": "I prossimi 7 giorni"},
                    {"command": "scadenze", "description": "Scadenze da confermare"},
                    {"command": "stop", "description": "Scollega"}])
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram setWebhook: %s", exc)

    threading.Thread(target=_fai, name="tg-webhook", daemon=True).start()
