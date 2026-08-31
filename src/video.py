# -*- coding: utf-8 -*-
"""Il video come prova: metadati, fotogrammi, linea temporale, integrità.

⚠️ **PRIMA DI TUTTO, IL LIMITE CHE DECIDE COSA POSSIAMO PROMETTERE.**
Il cervello **non guarda i video**: prende immagini e testo. Quindi qui non
«analizziamo un video» — estraiamo dei fotogrammi e li facciamo leggere uno per
uno. Ne consegue una cosa che va detta all'avvocato dentro l'output, non
nascosta nella documentazione: **l'istante decisivo può cadere fra due
fotogrammi** e non essere visto da nessuno. In un fascicolo penale è la
differenza fra uno strumento serio e uno pericoloso.

**Cosa fa e cosa NON fa.** Ricostruisce, mette in fila, misura, e soprattutto
guarda il *file*: come è stato prodotto, se è stato ricodificato, se i tempi
sono continui. Non dice chi è la persona inquadrata. Riconoscere qualcuno dai
tratti fisici è identificazione biometrica — la linea rossa dell'AI Act — ed è
anche il punto in cui un errore non è più recuperabile: un «è lui» sbagliato
una volta sola brucia il prodotto. Il valore vero, per un difensore, non è
*«cosa mostra»* (lo vede anche lui) ma **«possono usarlo, e mostra davvero
quello che l'accusa dice che mostra?»**.

Il risultato è **testo con i minutaggi**. È scelto: `documents.extract_text`
lo restituisce come per un PDF, e da lì in poi il video è un documento come
gli altri — entra nell'analisi, nel fascicolo, nelle contraddizioni, nel Q&A,
senza che nessuno di quei moduli sappia che è un video.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import VIDEO_EXTENSIONS, VIDEO_MAX_FRAMES, VIDEO_SCENE_THRESHOLD

log = logging.getLogger(__name__)

# ffmpeg su un file corrotto (o su un .dav che non digerisce) può restare
# appeso: senza tetto, un caricamento sbagliato terrebbe occupato un thread
# per sempre.
_TIMEOUT_PROBE = 60
_TIMEOUT_ESTRAZIONE = 900


def is_video(ext: str) -> bool:
    return (ext or "").lower() in VIDEO_EXTENSIONS


def strumenti_presenti() -> bool:
    """ffmpeg c'è? Serve dirlo con chiarezza invece di fallire a metà."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# ── metadati ───────────────────────────────────────────────────────────
@dataclass
class MetaVideo:
    durata_s: float = 0.0
    codec: str = ""
    larghezza: int = 0
    altezza: int = 0
    fps: float = 0.0
    creato: str = ""          # data dichiarata dentro il file
    bitrate: int = 0
    formato: str = ""
    n_tracce_audio: int = 0
    encoder: str = ""
    rotazione: int = 0
    grezzo: dict = field(default_factory=dict)

    @property
    def durata_leggibile(self) -> str:
        return _mmss(self.durata_s)


def _mmss(secondi: float) -> str:
    s = max(0, int(secondi))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _frazione(v: str) -> float:
    """ffprobe dà gli fps come '25/1' — e a volte come '0/0'."""
    try:
        if "/" in str(v):
            a, b = str(v).split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(v)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> MetaVideo:
    """Metadati del file. Non è burocrazia: in un processo la data di
    creazione, il codec e le tracce d'origine sono ciò su cui si discute
    quando si contesta l'acquisizione della prova."""
    if not strumenti_presenti():
        raise RuntimeError("ffprobe non disponibile nell'immagine")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=_TIMEOUT_PROBE,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"il file non è apribile come video: {(out.stderr or '').strip()[:200]}"
        )
    dati = json.loads(out.stdout or "{}")
    fmt = dati.get("format") or {}
    flussi = dati.get("streams") or []
    video = next((s for s in flussi if s.get("codec_type") == "video"), {})
    audio = [s for s in flussi if s.get("codec_type") == "audio"]
    tag = {**(fmt.get("tags") or {}), **(video.get("tags") or {})}

    rot = 0
    for sd in video.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass

    return MetaVideo(
        durata_s=float(fmt.get("duration") or video.get("duration") or 0) or 0.0,
        codec=str(video.get("codec_name") or ""),
        larghezza=int(video.get("width") or 0),
        altezza=int(video.get("height") or 0),
        fps=_frazione(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/0"),
        creato=str(tag.get("creation_time") or ""),
        bitrate=int(float(fmt.get("bit_rate") or 0) or 0),
        formato=str(fmt.get("format_name") or ""),
        n_tracce_audio=len(audio),
        encoder=str(tag.get("encoder") or tag.get("handler_name") or ""),
        rotazione=rot,
        grezzo=dati,
    )


# ── integrità: si guarda il FILE, non le persone ───────────────────────
_ENCODER_RIELABORAZIONE = re.compile(
    r"lavf|libav|ffmpeg|handbrake|imovie|premiere|vegas|shotcut|kdenlive|"
    r"whatsapp|telegram|capcut|inshot",
    re.I,
)


def rilievi_integrita(meta: MetaVideo, nome_file: str = "",
                      lingua: str = "sq") -> list[str]:
    """Osservazioni sul file, in una lingua che un giudice capisce.

    **Osservazioni, non accuse.** «Questo file è stato prodotto da un programma
    di montaggio» è un fatto verificabile; «il video è stato manomesso» è una
    conclusione che non spetta a noi. La differenza è tutta la differenza:
    la prima si può scrivere in un atto, la seconda fa perdere una causa.

    ⚠️ **Bilingue davvero.** La prima versione le scriveva solo in italiano:
    in sessione albanese uscivano intestazioni in shqip e osservazioni in
    italiano, dentro lo stesso documento. Sembra tradotto finché non lo leggi.
    """
    M = _RILIEVI.get(lingua, _RILIEVI["sq"])
    r: list[str] = []

    if not meta.creato:
        r.append(M["no_data"])
    else:
        r.append(M["data"].format(d=meta.creato))

    if meta.encoder and _ENCODER_RIELABORAZIONE.search(meta.encoder):
        r.append(M["encoder"].format(e=meta.encoder))

    if meta.fps and meta.fps < 5:
        r.append(M["fps"].format(f=meta.fps))

    if meta.larghezza and meta.larghezza < 640:
        r.append(M["ris"].format(w=meta.larghezza, h=meta.altezza))

    if meta.n_tracce_audio == 0:
        r.append(M["audio"])

    if meta.durata_s and meta.durata_s < 5:
        r.append(M["breve"].format(d=meta.durata_leggibile))

    if (nome_file or "").lower().endswith(".dav"):
        r.append(M["dav"])

    return r


_RILIEVI = {
    "sq": {
        "no_data": (
            "Skedari **nuk deklaron datë krijimi**. Vetëm kjo nuk do të thotë "
            "asgjë (shumë sisteme mbikëqyrjeje nuk e shkruajnë), por do të thotë "
            "se data duhet provuar **ndryshe**: procesverbal marrjeje, regjistri "
            "i kamerës, dëshmitar."
        ),
        "data": ("Data e deklaruar brenda skedarit: **{d}** — krahasoje me orën "
                 "e ngjarjes dhe me orën e kamerës, që shpesh është e zhvendosur."),
        "encoder": (
            "Skedari rezulton i prodhuar ose **i ripërpunuar** nga «{e}». Nuk "
            "është në vetvete ndryshim — dërgimi në WhatsApp e rikompreson — por "
            "**nuk është origjinali i kamerës**: kërko origjinalin dhe zinxhirin "
            "e ruajtjes."
        ),
        "fps": ("Frekuencë shumë e ulët (**{f:.1f} fotograme në sekondë**): tipike "
                "e sistemeve të mbikëqyrjes. Midis një fotogrami dhe tjetrit kalojnë "
                "pjesë sekonde **të paregjistruara**: një lëvizje e shpejtë mund të "
                "mos jetë aty."),
        "ris": ("Rezolucion i ulët (**{w}×{h}**): i pamjaftueshëm për çdo pohim "
                "mbi fytyra ose targa."),
        "audio": ("**Asnjë pistë audio**: nëse akuza përmend fjalë të thëna, ato "
                  "nuk vijnë nga ky skedar."),
        "breve": ("Kohëzgjatje shumë e shkurtër (**{d}**): verifiko nëse është "
                  "shkëputje dhe kush e zgjodhi prerjen."),
        "dav": (
            "Format **.dav** (kamera Dahua): është kontejneri pronësor i "
            "regjistruesit. Nëse gjykata duhet ta hapë, bashkëngjit edhe një kopje "
            "në format të zakonshëm — **dhe deklaro që është konvertim**, duke "
            "treguar mjetin e përdorur."
        ),
    },
    "it": {
        "no_data": (
            "Il file **non dichiara una data di creazione**. Da solo non vuol "
            "dire nulla (molti sistemi di sorveglianza non la scrivono), ma "
            "significa che la data va provata **altrimenti**: verbale di "
            "acquisizione, registro della telecamera, testimone."
        ),
        "data": ("Data dichiarata dentro il file: **{d}** — da confrontare con "
                 "l'orario del fatto e con l'orologio della telecamera, che "
                 "spesso è sfasato."),
        "encoder": (
            "Il file risulta prodotto o **ri-elaborato** da «{e}». Non è di per "
            "sé un'alterazione — inviare un video su WhatsApp lo ricomprime — ma "
            "**non è l'originale della telecamera**: chiedere l'originale e la "
            "catena di custodia."
        ),
        "fps": ("Frequenza molto bassa (**{f:.1f} fotogrammi al secondo**): tipica "
                "dei sistemi di sorveglianza. Fra un fotogramma e l'altro passano "
                "frazioni di secondo **non registrate**: un gesto rapido può non "
                "esserci."),
        "ris": ("Risoluzione bassa (**{w}×{h}**): insufficiente per qualunque "
                "affermazione su volti o targhe."),
        "audio": ("**Nessuna traccia audio**: se l'accusa riferisce frasi "
                  "pronunciate, non vengono da questo file."),
        "breve": ("Durata molto breve (**{d}**): verificare se è un estratto e "
                  "chi ha scelto il ritaglio."),
        "dav": (
            "Formato **.dav** (telecamere Dahua): è il contenitore proprietario "
            "del registratore. Se il tribunale deve poterlo aprire, va allegata "
            "anche una copia in formato comune — **e va detto che è una "
            "conversione**, indicando lo strumento usato."
        ),
    },
}


# ── fotogrammi ─────────────────────────────────────────────────────────
def estrai_fotogrammi(path: Path, cartella: Path, meta: MetaVideo,
                      massimo: int = 0) -> list[tuple[float, Path]]:
    """Fotogrammi sui cambi di scena, con ripiego a intervallo regolare.

    Perché sui cambi di scena e non a intervallo fisso: in un video di
    sorveglianza il 90% del tempo non succede niente, e l'intervallo fisso
    spende il budget sul nulla. Il rilevamento di scena spende dove **cambia
    qualcosa**, che è dove si guarda.

    Il ripiego a intervallo c'è perché un video con un'inquadratura sola e
    poco movimento non produce cambi di scena: senza ripiego non tornerebbe
    **nessun** fotogramma e l'analisi risulterebbe vuota senza errore — il
    modo peggiore di fallire.
    """
    massimo = massimo or VIDEO_MAX_FRAMES
    cartella.mkdir(parents=True, exist_ok=True)

    scelti = _estrai(path, cartella / "scena", massimo,
                     f"select='gt(scene,{VIDEO_SCENE_THRESHOLD})'", meta)
    if len(scelti) >= max(3, massimo // 4):
        return scelti[:massimo]

    # poco o niente movimento: si torna all'intervallo regolare
    log.info("video: pochi cambi di scena (%d), passo all'intervallo", len(scelti))
    passo = max(1.0, (meta.durata_s or 60) / massimo)
    a_intervallo = _estrai(path, cartella / "int", massimo,
                           f"fps=1/{passo:.3f}", meta)
    # si tengono entrambi: i cambi di scena restano i momenti interessanti
    tutti = {round(t, 1): p for t, p in a_intervallo}
    tutti.update({round(t, 1): p for t, p in scelti})
    return [(t, tutti[t]) for t in sorted(tutti)][:massimo]


def _estrai(path: Path, dove: Path, massimo: int, filtro: str,
            meta: MetaVideo) -> list[tuple[float, Path]]:
    dove.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        # scale: il cervello non guadagna niente dal 4K e il contesto sì
        "-vf", f"{filtro},scale='min(1280,iw)':-2,showinfo",
        "-vsync", "vfr", "-frames:v", str(massimo),
        "-q:v", "4",
        str(dove / "f_%04d.jpg"),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=_TIMEOUT_ESTRAZIONE)
    file = sorted(dove.glob("f_*.jpg"))
    if not file:
        if out.returncode != 0:
            log.warning("ffmpeg: %s", (out.stderr or "")[:300])
        return []
    # showinfo scrive su stderr il tempo di ogni fotogramma tenuto: è l'unico
    # modo di sapere il minutaggio VERO invece di stimarlo dal numero d'ordine
    tempi = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", out.stderr or "")]
    coppie: list[tuple[float, Path]] = []
    for i, f in enumerate(file):
        t = tempi[i] if i < len(tempi) else (
            (meta.durata_s / max(1, len(file))) * i
        )
        coppie.append((t, f))
    return coppie


# ── la linea temporale ─────────────────────────────────────────────────
_PROMPT_FOTOGRAMMA_SQ = """Ti je asistent i një avokati/prokurori. Ky është NJË fotogram i nxjerrë nga një video e depozituar si provë.

Përshkruaj VETËM atë që shihet, në 1-3 fjali të shkurtra:
- sa persona, ku janë, çfarë bëjnë me duart, drejtimi i lëvizjes;
- objekte që kanë rëndësi (çanta, armë e dukshme, mjet, derë, arkë);
- mjedisi, ndriçimi, orë ose data e mbishkruar në pamje nëse duket.

RREGULLA TË PRERA:
- MOS identifiko persona dhe MOS përshkruaj tipare fizike që i individualizojnë (fytyrë, racë, moshë e saktë). Thuaj "personi A", "personi B" sipas pozicionit.
- MOS nxirr përfundime për qëllimin, fajin apo veprën penale. Vetëm çfarë duket.
- Nëse pamja është e paqartë, thuaj "e paqartë" — mos plotëso me hamendje.
"""

_PROMPT_FOTOGRAMMA_IT = """Sei l'assistente di un avvocato o di un pubblico ministero. Questo è UN fotogramma estratto da un video depositato come prova.

Descrivi SOLO quello che si vede, in 1-3 frasi brevi:
- quante persone, dove sono, cosa fanno con le mani, direzione del movimento;
- oggetti rilevanti (borse, arma visibile, veicolo, porta, cassa);
- ambiente, illuminazione, ora o data sovraimpressa se visibile.

REGOLE FERREE:
- NON identificare le persone e NON descrivere tratti fisici individualizzanti (viso, etnia, età precisa). Chiamale "persona A", "persona B" secondo la posizione.
- NON trarre conclusioni su intenzioni, colpa o reato. Solo ciò che si vede.
- Se l'immagine è poco chiara, scrivi "non chiaro" — non riempire con ipotesi.
"""


_CODA_SQ = ("Lexo këtë fotogram dhe përshkruaje sipas rregullave më sipër. "
            "Kthe VETËM përshkrimin, pa parathënie dhe pa koment mbi detyrën.")
_CODA_IT = ("Leggi questo fotogramma e descrivilo secondo le regole sopra. "
            "Restituisci SOLO la descrizione, senza premesse e senza commenti "
            "sul compito.")


def descrivi_fotogrammi(fotogrammi: list[tuple[float, Path]], backend,
                        lingua: str = "sq") -> list[tuple[float, str]]:
    """Ogni fotogramma passa dal cervello con un prompt forense.

    Uno per uno e non tutti insieme: un provino a contatto fa risparmiare
    chiamate ma il modello confonde le posizioni fra i riquadri, e un
    minutaggio sbagliato in un atto è peggio di un minutaggio mancante.
    """
    prompt = _PROMPT_FOTOGRAMMA_IT if lingua == "it" else _PROMPT_FOTOGRAMMA_SQ
    fuori: list[tuple[float, str]] = []
    for t, f in fotogrammi:
        try:
            # ⚠️ La coda predefinita di `ocr_image` dice «restituisci SOLO il
            # testo estratto, nessun commento»: qui vogliamo l'opposto — una
            # descrizione. Con le due istruzioni insieme il modello si accorge
            # del conflitto e scrive un paragrafo su di esso invece della scena.
            testo = backend.ocr_image(
                f, "image/jpeg", prompt,
                istruzione_finale=_CODA_IT if lingua == "it" else _CODA_SQ,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("fotogramma %s non letto: %s", f.name, exc)
            testo = ""
        fuori.append((t, (testo or "").strip()))
    return fuori


_INTESTAZIONE = {
    "sq": {
        "titolo": "ANALIZË VIDEOJE",
        "skeda": "Të dhënat e skedarit",
        "kohore": "Rrjedha kohore (nga fotogramat)",
        "integritet": "Vërejtje mbi skedarin",
        "kufi": "KUFIJTË E KËSAJ ANALIZE — LEXOJI",
        "kufi_testo": (
            "Modeli **nuk e sheh videon**: sheh {n} fotograme të nxjerra prej saj. "
            "Momenti vendimtar mund të bjerë **midis dy fotogramave** dhe të mos "
            "shfaqet askund. Kjo analizë **nuk identifikon persona** dhe nuk nxjerr "
            "përfundime për fajësinë: shërben për të lexuar, renditur dhe krahasuar. "
            "Për çdo pretendim vendimtar shihet videoja e plotë, dhe kur duhet, "
            "caktohet ekspert."
        ),
        "durata": "Kohëzgjatja", "codec": "Kodeku", "ris": "Rezolucioni",
        "fps": "Fotograme/sek", "audio": "Pista audio", "creato": "Data në skedar",
        "peso": "Madhësia", "nessuna": "asnjë",
    },
    "it": {
        "titolo": "ANALISI VIDEO",
        "skeda": "Dati del file",
        "kohore": "Linea temporale (dai fotogrammi)",
        "integritet": "Rilievi sul file",
        "kufi": "LIMITI DI QUESTA ANALISI — DA LEGGERE",
        "kufi_testo": (
            "Il modello **non guarda il video**: guarda {n} fotogrammi estratti da "
            "esso. L'istante decisivo può cadere **fra due fotogrammi** e non "
            "comparire da nessuna parte. Questa analisi **non identifica persone** "
            "e non trae conclusioni sulla colpevolezza: serve a leggere, mettere in "
            "fila e confrontare. Per ogni affermazione decisiva si guarda il video "
            "intero e, quando serve, si nomina un perito."
        ),
        "durata": "Durata", "codec": "Codec", "ris": "Risoluzione",
        "fps": "Fotogrammi/sec", "audio": "Tracce audio", "creato": "Data nel file",
        "peso": "Dimensione", "nessuna": "nessuna",
    },
}


def analizza(path: Path, nome_file: str, backend, lingua: str = "sq") -> str:
    """Da un file video a un testo con i minutaggi.

    È quello che `documents.extract_text` restituisce: da lì in poi il video è
    un documento come gli altri e attraversa analisi, fascicolo,
    contraddizioni e Q&A senza che nessuno di quei moduli sappia che è un video.
    """
    L = _INTESTAZIONE.get(lingua, _INTESTAZIONE["sq"])
    meta = probe(path)

    righe: list[str] = [f"# {L['titolo']} — {nome_file}", ""]

    # scheda
    righe += [f"## {L['skeda']}", ""]
    peso = path.stat().st_size / (1024 * 1024) if path.exists() else 0
    righe += [
        f"- **{L['durata']}**: {meta.durata_leggibile}",
        f"- **{L['codec']}**: {meta.codec or '—'} ({meta.formato or '—'})",
        f"- **{L['ris']}**: {meta.larghezza}×{meta.altezza}" if meta.larghezza else f"- **{L['ris']}**: —",
        f"- **{L['fps']}**: {meta.fps:.2f}" if meta.fps else f"- **{L['fps']}**: —",
        f"- **{L['audio']}**: {meta.n_tracce_audio or L['nessuna']}",
        f"- **{L['creato']}**: {meta.creato or '—'}",
        f"- **{L['peso']}**: {peso:.1f} MB",
        "",
    ]

    # rilievi sul file
    rilievi = rilievi_integrita(meta, nome_file, lingua)
    if rilievi:
        righe += [f"## {L['integritet']}", ""]
        righe += [f"- {r}" for r in rilievi]
        righe.append("")

    # fotogrammi → linea temporale
    descrizioni: list[tuple[float, str]] = []
    n_estratti = 0
    with tempfile.TemporaryDirectory(prefix="video-") as tmp:
        # la cartella temporanea sparisce all'uscita: i fotogrammi sono un
        # mezzo, non una prova da conservare — e sono volti di persone
        fotogrammi = estrai_fotogrammi(path, Path(tmp), meta)
        n_estratti = len(fotogrammi)
        if fotogrammi and backend is not None:
            descrizioni = descrivi_fotogrammi(fotogrammi, backend, lingua)

    utili = [(t, d) for t, d in descrizioni if d]
    if utili:
        righe += [f"## {L['kohore']}", ""]
        for t, d in utili:
            righe += [f"**[{_mmss(t)}]** {d}", ""]

    # il limite, dichiarato dentro il testo che l'avvocato legge e copia —
    # non in fondo alla documentazione, dove non lo leggerebbe nessuno
    righe += [
        "---",
        "",
        f"⚠️ **{L['kufi']}**",
        "",
        L["kufi_testo"].format(n=len(utili) or n_estratti),
        "",
    ]
    return "\n".join(righe)

# ── il confronto: dove il video incontra le carte ──────────────────────
_CONFRONTO_SQ = """Ti je asistent i një avokati mbrojtës. Ke përpara DY burime për të njëjtin fakt:
(A) rrjedhën kohore të nxjerrë nga një ose disa video të depozituara;
(B) dokumentet e tjera të fashikullit (procesverbale, dëshmi, raporte).

Detyra jote është TË KRAHASOSH, jo të gjykosh. Nxirr:

## 1. PËRPUTHJET
Çfarë e mbështet videoja te dokumentet. Cito minutazhin [mm:ss] dhe dokumentin.

## 2. MOSPËRPUTHJET
Ku dokumenti thotë diçka që videoja NUK e tregon, ose e tregon ndryshe.
Për secilën: çfarë thotë dokumenti · çfarë duket në [mm:ss] · pse ka rëndësi.
Kjo është pjesa më e vlefshme: mos e zbut.

## 3. HESHTJET
Çfarë pretendon dokumenti dhe videoja nuk mund as ta konfirmojë as ta përgënjeshtrojë
(jashtë kuadrit, jashtë kohës, cilësi e pamjaftueshme). Thuaje qartë.

## 4. ÇFARË TË KËRKOHET
Veprime konkrete: videoja e plotë, origjinali nga regjistruesi, akti i marrjes në dorëzim,
ora e kamerës, ekspertizë teknike — vetëm ato që kanë kuptim për këtë rast.

RREGULLA:
- MOS identifiko persona dhe mos përshkruaj tipare fizike individualizuese.
- MOS nxirr përfundim për fajësinë. Ti krahason burime, nuk gjykon.
- Nëse videoja nuk mbulon një pretendim, thuaj "nuk mbulohet" — mos hamendëso.
- Çdo pohim yti duhet të mbështetet ose te një minutazh ose te një dokument.
"""

_CONFRONTO_IT = """Sei l'assistente di un avvocato difensore. Hai davanti DUE fonti sullo stesso fatto:
(A) la linea temporale estratta da uno o più video depositati;
(B) gli altri documenti del fascicolo (verbali, dichiarazioni, relazioni).

Il tuo compito è CONFRONTARE, non giudicare. Produci:

## 1. CONFERME
Cosa il video conferma dei documenti. Cita il minutaggio [mm:ss] e il documento.

## 2. DISCORDANZE
Dove il documento afferma qualcosa che il video NON mostra, o mostra diversamente.
Per ciascuna: cosa dice il documento · cosa si vede a [mm:ss] · perché conta.
È la parte più preziosa: non addolcirla.

## 3. SILENZI
Cosa il documento afferma e il video non può né confermare né smentire
(fuori inquadratura, fuori orario, qualità insufficiente). Dillo chiaramente.

## 4. COSA CHIEDERE
Azioni concrete: il video integrale, l'originale dal registratore, il verbale di
acquisizione, l'orario della telecamera, una perizia — solo quelle che hanno senso qui.

REGOLE:
- NON identificare persone e non descrivere tratti fisici individualizzanti.
- NON concludere sulla colpevolezza. Confronti fonti, non giudichi.
- Se il video non copre un'affermazione, scrivi "non coperto" — non ipotizzare.
- Ogni tua affermazione deve poggiare o su un minutaggio o su un documento.
"""


def confronta(testi_video: list[str], contesto_fascicolo: str, backend,
              lingua: str = "sq", case_id: str = "") -> str:
    """Mette il video contro le carte e restituisce conferme, crepe e silenzi.

    Ritorna markdown. Non sostituisce la lettura del video: dice **dove
    guardare**, che su tre ore di registrazione e' quasi tutto il lavoro.
    """
    if not testi_video:
        raise ValueError("nessuna analisi video nel fascicolo")

    sistema = _CONFRONTO_IT if lingua == "it" else _CONFRONTO_SQ
    parti = ["## (A) " + ("RRJEDHA KOHORE NGA VIDEOT" if lingua != "it"
                          else "LINEA TEMPORALE DAI VIDEO"), ""]
    parti += testi_video
    parti += ["", "## (B) " + ("DOKUMENTET E TJERA" if lingua != "it"
                               else "GLI ALTRI DOCUMENTI"), ""]
    parti.append(contesto_fascicolo or ("(asnjë dokument tjetër)" if lingua != "it"
                                        else "(nessun altro documento)"))

    # `Message` e' un alias di dict, non una classe: il dizionario esplicito
    # dice cosa succede davvero.
    return backend.complete(
        system=sistema,
        messages=[{"role": "user", "content": "\n".join(parti)}],
        max_tokens=4000,
    )
