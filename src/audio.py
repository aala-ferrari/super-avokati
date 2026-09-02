# -*- coding: utf-8 -*-
"""Trascrizione dell'audio: registrazioni depositate e la traccia dei video.

Una telefonata registrata, un vocale WhatsApp, l'audio di una telecamera: sono
prove che oggi l'avvocato riascolta a mano con il dito sulla barra, cercando il
minuto in cui è stata detta *quella* frase. La trascrizione con i minutaggi
trasforma tre ore di ascolto in una ricerca di testo.

## ⚠️ QUANTO SI FIDA — MISURATO, NON STIMATO (31 ago 2026)

Provato su una dichiarazione di testimone, 6 core, 4 thread:

| lingua | `small` | `medium` |
|---|---|---|
| **italiano** | **parola per parola**, 0,73× | uguale, 1,56× |
| **albanese** | impreciso, 0,81× | **non migliora**, 2,13× |

Il modello grande costa 2,6 volte tanto e in albanese non guadagna niente:
`small` è la scelta. **In italiano la trascrizione è affidabile; in albanese è
una bozza per orientarsi** — l'avvocato deve riascoltare prima di citare una
frase in un atto, e il testo lo dice.

⚠️ **Un onesto dubbio sulla misura albanese**: l'audio di prova era sintetico,
prodotto dal TTS locale che non è di qualità alta. Può darsi che il problema
fosse la voce e non la lingua. Prima di dichiarare «Whisper non sa l'albanese»
andrebbe rifatta la prova su una registrazione **vera**.

## Perché una alla volta

La trascrizione è l'unica cosa qui dentro che occupa la CPU per minuti interi,
e la macchina ne ha sei core con sopra altri cinque siti. Tre avvocati che
caricano un video insieme prenderebbero dodici thread su sei core e
metterebbero in ginocchio tutto. Un semaforo a uno: si aspetta, non si affoga.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path

from .config import (AUDIO_EXTENSIONS, WHISPER_MODEL, WHISPER_THREADS,
                     WHISPER_DIR)

log = logging.getLogger(__name__)

# Una trascrizione alla volta in tutto il sistema — vedi il perché in testa.
_semaforo = threading.Semaphore(1)
# Il modello si carica una volta sola: 5-18 secondi che non ha senso ripagare
# a ogni file.
_modello = None
_lock_modello = threading.Lock()

_TIMEOUT_ESTRAZIONE = 600


def is_audio(ext: str) -> bool:
    return (ext or "").lower() in AUDIO_EXTENSIONS


def disponibile() -> bool:
    """Il trascrittore c'è? Meglio dirlo che fallire a metà."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return bool(shutil.which("ffmpeg"))


def _carica():
    global _modello
    if _modello is not None:
        return _modello
    with _lock_modello:
        if _modello is not None:
            return _modello
        from faster_whisper import WhisperModel
        d = Path(WHISPER_DIR)
        d.mkdir(parents=True, exist_ok=True)
        log.info("carico il trascrittore %s (cartella %s)", WHISPER_MODEL, d)
        _modello = WhisperModel(
            WHISPER_MODEL, device="cpu", compute_type="int8",
            cpu_threads=WHISPER_THREADS, download_root=str(d),
        )
        return _modello


def estrai_traccia(video: Path, dove: Path) -> Path | None:
    """Tira fuori l'audio da un video, nel formato che il trascrittore vuole.

    16 kHz mono: è quello che Whisper usa internamente. Dargli altro significa
    farglielo riconvertire, più lentamente.
    """
    fuori = dove / "audio.wav"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(fuori)],
        capture_output=True, text=True, timeout=_TIMEOUT_ESTRAZIONE,
    )
    if r.returncode != 0 or not fuori.exists() or fuori.stat().st_size < 1000:
        log.info("nessuna traccia audio utile: %s", (r.stderr or "")[:200])
        return None
    return fuori


def trascrivi(path: Path, lingua: str | None = None
              ) -> tuple[list[tuple[float, float, str]], str, float]:
    """Restituisce ([(inizio, fine, testo)], lingua_riconosciuta, fiducia).

    ⚠️ **La lingua si riconosce, non si impone.** Imporla dalla sessione era il
    difetto piu' grave di questo modulo: un avvocato che lavora in albanese ha
    spessissimo una registrazione in italiano, e forzando lo shqip la stessa
    dichiarazione usciva «una giakka skura … kvalkosa im mano» — la fonetica
    italiana scritta in ortografia albanese. Sbagliato **e** plausibile, che e'
    la combinazione peggiore.

    `lingua` resta come forzatura esplicita quando l'avvocato la conosce.

    `vad_filter` salta i silenzi: in una registrazione di sorveglianza sono la
    maggior parte del file, e trascriverli costa tempo per produrre nulla.
    """
    if not disponibile():
        raise RuntimeError("trascrittore non disponibile")
    m = _carica()
    with _semaforo:
        segmenti, info = m.transcribe(
            str(path), language=lingua, beam_size=1, vad_filter=True,
        )
        fuori = [(s.start, s.end, (s.text or "").strip())
                 for s in segmenti if (s.text or "").strip()]
        return (fuori,
                getattr(info, "language", "") or (lingua or ""),
                float(getattr(info, "language_probability", 0.0) or 0.0))


# I nomi delle lingue nelle due lingue dell'interfaccia: «det: it» non dice
# niente a un avvocato.
_NOMI_LINGUA = {
    "sq": {"sq": "shqip", "it": "italisht", "en": "anglisht", "sr": "serbisht",
           "el": "greqisht", "de": "gjermanisht", "fr": "frëngjisht",
           "es": "spanjisht", "tr": "turqisht", "mk": "maqedonisht"},
    "it": {"sq": "albanese", "it": "italiano", "en": "inglese", "sr": "serbo",
           "el": "greco", "de": "tedesco", "fr": "francese",
           "es": "spagnolo", "tr": "turco", "mk": "macedone"},
}


def nome_lingua(codice: str, in_lingua: str = "sq") -> str:
    return _NOMI_LINGUA.get(in_lingua, _NOMI_LINGUA["sq"]).get(
        codice, codice or "?")


_INTESTAZIONE = {
    "sq": {
        "titolo": "TRANSKRIPT I AUDIOS",
        "lingua_dubbia": "⚠️ Siguria e njohjes së gjuhës është e ulët: nëse transkripti duket i pakuptimtë, ka gjasa që gjuha të jetë dalluar gabim.",
        "lingua": "**Gjuha e dalluar automatikisht: {l}** (siguri {p}%).",
        "sezione": "Fjalët e regjistruara (me minutazhe)",
        "vuoto": "Nuk u dallua asnjë fjalë e kuptueshme në këtë regjistrim.",
        "avviso": (
            "⚠️ **Transkripti është BOZË, jo procesverbal.** E prodhon një sistem "
            "automatik: në italisht del i saktë, **në shqip është vetëm për t'u "
            "orientuar** — para se të citosh një fjali në një akt, dëgjoje "
            "regjistrimin. Emrat e përveçëm dhe shifrat gabohen më shpesh se pjesa "
            "tjetër. Heshtjet janë hequr, prandaj minutazhet nuk janë të vazhdueshme."
        ),
    },
    "it": {
        "titolo": "TRASCRIZIONE DELL'AUDIO",
        "lingua_dubbia": "⚠️ La confidenza sul riconoscimento della lingua è bassa: se la trascrizione sembra priva di senso, è probabile che la lingua sia stata riconosciuta male.",
        "lingua": "**Lingua riconosciuta automaticamente: {l}** (confidenza {p}%).",
        "sezione": "Le parole registrate (con i minutaggi)",
        "vuoto": "Non è stata riconosciuta nessuna parola comprensibile in questa registrazione.",
        "avviso": (
            "⚠️ **La trascrizione è una BOZZA, non un verbale.** La produce un "
            "sistema automatico: **in italiano risulta accurata, in albanese serve "
            "solo a orientarsi** — prima di citare una frase in un atto, riascolta "
            "la registrazione. Nomi propri e cifre sbagliano più del resto. I "
            "silenzi sono stati saltati, quindi i minutaggi non sono continui."
        ),
    },
}


def _mmss(s: float) -> str:
    s = max(0, int(s))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def analizza(path: Path, nome_file: str, lingua: str = "sq") -> str:
    """Da un file audio a un testo con i minutaggi.

    Stessa scelta fatta per il video: il risultato è **testo**, quindi da qui
    in poi la registrazione è un documento come gli altri e attraversa analisi,
    fascicolo, contraddizioni e Q&A senza che nessuno di quei moduli lo sappia.
    """
    L = _INTESTAZIONE.get(lingua, _INTESTAZIONE["sq"])
    # lingua NON imposta: la si riconosce e la si dichiara
    segmenti, gjuha_dalluar, fiducia = trascrivi(path, None)

    righe = [f"# {L['titolo']} — {nome_file}", ""]
    if not segmenti:
        righe += [L["vuoto"], "", "---", "", L["avviso"], ""]
        return "\n".join(righe)

    # Dichiarata sempre: se il riconoscimento ha sbagliato, l'avvocato lo legge
    # invece di dedurlo dalle parole storte.
    righe += [L["lingua"].format(l=nome_lingua(gjuha_dalluar, lingua),
                                 p=int(fiducia * 100)), ""]
    if fiducia < 0.6:
        righe += [L["lingua_dubbia"], ""]
    righe += [f"## {L['sezione']}", ""]
    for inizio, _fine, testo in segmenti:
        righe.append(f"**[{_mmss(inizio)}]** {testo}")
    righe += ["", "---", "", L["avviso"], ""]
    return "\n".join(righe)


def blocco_per_video(segmenti: list[tuple[float, float, str]],
                     lingua: str = "sq") -> list[str]:
    """Le battute pronte da mescolare alla linea temporale del video.

    Vanno **intrecciate** con le descrizioni dei fotogrammi in ordine di tempo,
    non appese in fondo: quello che conta, in una rapina, è che a `[00:14]` si
    veda una mano nella tasca **e** si senta «dammi i soldi». Separati sono due
    elenchi; insieme sono un racconto.
    """
    etichetta = "🔊" if segmenti else ""
    return [f"**[{_mmss(a)}]** {etichetta} «{t}»" for a, _b, t in segmenti]
