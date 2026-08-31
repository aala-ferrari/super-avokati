# -*- coding: utf-8 -*-
"""L'impalcatura forense: impronta, registro di lavorazione, metadati profondi.

Nasce dalla lettura dello standard vero — **SWGDE, Best Practices for Digital
Forensic Video Analysis**, che è ciò su cui sono costruiti Amped FIVE e gli
altri. I suoi quattro requisiti non riguardano l'intelligenza artificiale:

1. **integrità** — impronta del file, copia di lavoro, l'originale non si tocca;
2. **riproducibilità** — ogni passaggio documentato con i suoi parametri, così
   un altro esaminatore ottiene lo stesso risultato;
3. **il miglioramento non può aggiungere informazione** che non c'era;
4. **nel referto i rilievi vanno separati dalle interpretazioni**.

La nostra analisi era filosoficamente l'opposto: un modello che descrive è
interpretazione pura, e nel documento era mescolata alle misure. Questo modulo
mette attorno l'impalcatura che mancava.

⚠️ **Cosa NON facciamo, e va detto nel documento**: nessun miglioramento
d'immagine, nessuna super-risoluzione, nessun riconoscimento facciale. Il
primo perché migliorare male vuol dire *aggiungere informazione che non
c'era*, cioè produrre una prova inammissibile; il terzo perché è la riga rossa
che il prodotto non attraversa.

## Sui nomi degli strumenti, e una tensione risolta

La riproducibilità chiede di dire **quale** strumento hai usato. La regola di
riservatezza del prodotto dice di non nominare mai il modello del cervello.
Non è una contraddizione se si guarda a cosa serve ciascuna cosa:

- gli strumenti **deterministici** (ffmpeg, exiftool, il trascrittore) si
  nominano con la loro versione: sono programmi liberi, non un nostro
  vantaggio, e sono la parte che un altro **può** rifare;
- il motore di descrizione resta **«Tetramorph»**, e accanto c'è scritto che
  quella parte **non è riproducibile per natura** — è interpretazione, non
  misura. Dirlo è più onesto che dare un nome e lasciar credere il contrario.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_TIMEOUT = 120


# ── integrità ──────────────────────────────────────────────────────────
def impronta(path: Path) -> tuple[str, int]:
    """SHA-256 e dimensione del file, a blocchi.

    È la cosa più economica e più importante di tutto il modulo: permette di
    scrivere in un atto «il file che ho analizzato è questo», e a chiunque di
    verificarlo con un comando. Senza, l'analisi parla di un file che nessuno
    può identificare.

    A blocchi da 1 MB perché un video da mezzo giga non deve entrare in memoria.
    """
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


# ── il registro di lavorazione ─────────────────────────────────────────
@dataclass
class Registro:
    """Ogni passaggio, con i suoi parametri.

    È quello che fa il referto di Amped FIVE, ed è ciò che rende un'analisi
    ripetibile: un altro esaminatore legge i parametri e rifà lo stesso lavoro.
    Per noi costa nulla, perché i parametri li conosciamo già — bastava
    scriverli.
    """
    passi: list[str] = field(default_factory=list)

    def aggiungi(self, cosa: str) -> None:
        self.passi.append(cosa)

    def comando(self, cmd: list[str]) -> None:
        """Il comando esatto, così com'è stato eseguito."""
        self.passi.append("`" + " ".join(str(c) for c in cmd) + "`")


def versione(programma: str) -> str:
    """Versione di uno strumento, per il registro. Vuoto se non c'è."""
    exe = shutil.which(programma)
    if not exe:
        return ""
    # ⚠️ Non tutti usano lo stesso argomento: exiftool vuole `-ver` e con
    # `-version` risponde «No file specified», che finirebbe nel registro
    # spacciato per una versione.
    for arg in ("-version", "-ver", "--version"):
        try:
            r = subprocess.run([exe, arg], capture_output=True, text=True,
                               timeout=20)
        except (OSError, subprocess.SubprocessError):
            return ""
        prima = (r.stdout or r.stderr or "").strip().split("\n")[0]
        if not prima or "no file" in prima.lower() or "unknown" in prima.lower():
            continue
        # una versione nuda («12.57») si accompagna al nome del programma
        if prima.replace(".", "").isdigit():
            prima = f"{Path(exe).name} {prima}"
        return prima[:80]
    return ""


# ── metadati profondi del contenitore ──────────────────────────────────
def exiftool_disponibile() -> bool:
    return bool(shutil.which("exiftool"))


def metadati_estesi(path: Path) -> dict:
    """Tutti i tag del contenitore, via exiftool.

    `ffprobe` mostra i flussi; **exiftool mostra gli atomi**: i tag del
    produttore, le date per traccia, il marchio del contenitore, le tracce
    lasciate dai programmi di montaggio. È da lì che si capisce se un file è
    uscito da una telecamera o da un editor.
    """
    if not exiftool_disponibile():
        return {}
    try:
        r = subprocess.run(
            ["exiftool", "-json", "-a", "-G1", "-api", "largefilesupport=1",
             str(path)],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {}
        dati = json.loads(r.stdout)
        return dati[0] if isinstance(dati, list) and dati else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError):
        return {}


# Firme dei programmi che riscrivono un file. Il campo `encoder` è la traccia
# più parlante: ogni uscita di ffmpeg scrive «Lavf…», Premiere scrive il suo,
# e così via. Fonte: Xiang et al., «Forensic Analysis of Video Files Using
# Metadata» (Purdue) — con i soli metadati del contenitore si distingue un
# originale da un file rielaborato, e si riconosce il programma.
_FIRME = (
    ("Lavf", "ffmpeg / libavformat"),
    ("HandBrake", "HandBrake"),
    ("Adobe", "Adobe (Premiere / Media Encoder)"),
    ("Premiere", "Adobe Premiere"),
    ("DaVinci", "DaVinci Resolve"),
    ("Vegas", "Vegas Pro"),
    ("Shotcut", "Shotcut"),
    ("Kdenlive", "Kdenlive"),
    ("Avidemux", "Avidemux"),
    ("iMovie", "iMovie"),
    ("Final Cut", "Final Cut"),
    ("CapCut", "CapCut"),
    ("InShot", "InShot"),
    ("WhatsApp", "WhatsApp"),
    ("ExifTool", "ExifTool (metadati riscritti a mano)"),
)

_TESTI = {
    "sq": {
        "orig": ("Skedari **nuk deklaron asnjë gjurmë programi montazhi**: kjo "
                 "përputhet me një skedar që vjen drejtpërdrejt nga pajisja. "
                 "Nuk e provon — thjesht nuk e kundërshton."),
        "riel": ("Skedari mban gjurmën e **{p}**: është kaluar nga ai program. "
                 "Nuk do të thotë ndryshim i përmbajtjes — dërgimi në WhatsApp e "
                 "rikompreson — por **nuk është origjinali i pajisjes**."),
        "date_div": ("Datat e brendshme **nuk përputhen midis tyre** ({d}). Në një "
                     "skedar të pandryshuar zakonisht përputhen; ndryshimi lind "
                     "shpesh nga një rishkrim."),
        "marca": "Prodhuesi i deklaruar në metadata: **{m}**.",
        "gps": ("Skedari përmban **koordinata GPS** ({g}) — krahaso me vendin e "
                "deklaruar të ngjarjes."),
        "no_exif": ("exiftool nuk është i disponueshëm: analiza e thellë e "
                    "kontejnerit nuk u krye."),
    },
    "it": {
        "orig": ("Il file **non dichiara nessuna traccia di programmi di "
                 "montaggio**: è compatibile con un file uscito direttamente dal "
                 "dispositivo. Non lo prova — semplicemente non lo contraddice."),
        "riel": ("Il file porta la firma di **{p}**: è passato da quel programma. "
                 "Non significa alterazione del contenuto — inviarlo su WhatsApp "
                 "lo ricomprime — ma **non è l'originale del dispositivo**."),
        "date_div": ("Le date interne **non coincidono fra loro** ({d}). In un file "
                     "non rimaneggiato di norma coincidono; la differenza nasce "
                     "spesso da una riscrittura."),
        "marca": "Produttore dichiarato nei metadati: **{m}**.",
        "gps": ("Il file contiene **coordinate GPS** ({g}) — da confrontare con il "
                "luogo dichiarato del fatto."),
        "no_exif": ("exiftool non disponibile: l'analisi profonda del contenitore "
                    "non è stata eseguita."),
    },
}


def rilievi_contenitore(exif: dict, lingua: str = "sq") -> list[str]:
    """Rilievi dedotti dagli atomi del contenitore. Regole, non modelli.

    Deterministico di proposito: un perito rifà lo stesso controllo e ottiene
    lo stesso risultato. È la differenza fra un rilievo e un'opinione.
    """
    T = _TESTI.get(lingua, _TESTI["sq"])
    if not exif:
        return [T["no_exif"]]

    fuori: list[str] = []

    # 1) firme di programmi che hanno riscritto il file
    testo = " ".join(str(v) for k, v in exif.items()
                     if any(x in k for x in ("Encoder", "Software", "Writing",
                                             "HandlerDescription", "Comment",
                                             "CreatorTool", "Model")))
    trovate = sorted({nome for firma, nome in _FIRME if firma.lower() in testo.lower()})
    if trovate:
        fuori.append(T["riel"].format(p=" · ".join(trovate)))
    else:
        fuori.append(T["orig"])

    # 2) marca/modello del dispositivo, se dichiarati
    marca = next((str(v) for k, v in exif.items()
                  if k.endswith(":Make") or k.endswith(":Model")), "")
    if marca:
        fuori.append(T["marca"].format(m=marca))

    # 3) date interne che non coincidono
    date = {str(v)[:19] for k, v in exif.items()
            if ("CreateDate" in k or "ModifyDate" in k) and v
            and not str(v).startswith("0000")}
    if len(date) > 1:
        fuori.append(T["date_div"].format(d=" · ".join(sorted(date)[:3])))

    # 4) coordinate
    gps = next((str(v) for k, v in exif.items()
                if "GPSPosition" in k or "GPSCoordinates" in k), "")
    if gps:
        fuori.append(T["gps"].format(g=gps[:48]))

    return fuori


# ── il blocco da stampare in fondo al documento ────────────────────────
_REG = {
    "sq": {
        "titolo": "REGJISTRI I PËRPUNIMIT (për riprodhueshmëri)",
        "intro": ("Çdo hap, me parametrat e vet, që një ekspert tjetër të mund "
                  "ta përsërisë. Kërkesë e standardit SWGDE për analizën "
                  "mjeko-ligjore të videos."),
        "impronta": "Gjurma e skedarit (SHA-256)",
        "strumenti": "Mjetet",
        "passi": "Hapat",
        "limite": ("⚠️ **Përshkrimet e fotogramave nuk janë të riprodhueshme.** "
                   "I prodhon motori **Tetramorph**: janë **interpretim**, jo "
                   "matje. Matjet janë metadatat, gjurma, minutazhet dhe "
                   "transkripti. Kjo analizë **nuk përmirëson pamjen** (as "
                   "super-rezolucion, as pastrim zhurme) dhe **nuk identifikon "
                   "persona**: për këto duhet ekspert i certifikuar me mjete të "
                   "validuara."),
    },
    "it": {
        "titolo": "REGISTRO DI LAVORAZIONE (per la riproducibilità)",
        "intro": ("Ogni passaggio, con i suoi parametri, perché un altro perito "
                  "possa ripeterlo. È il requisito dello standard SWGDE per "
                  "l'analisi forense del video."),
        "impronta": "Impronta del file (SHA-256)",
        "strumenti": "Strumenti",
        "passi": "Passaggi",
        "limite": ("⚠️ **Le descrizioni dei fotogrammi non sono riproducibili.** "
                   "Le produce il motore **Tetramorph**: sono **interpretazione**, "
                   "non misura. Le misure sono i metadati, l'impronta, i "
                   "minutaggi e la trascrizione. Questa analisi **non migliora "
                   "l'immagine** (né super-risoluzione né riduzione del rumore) e "
                   "**non identifica persone**: per queste serve un perito "
                   "certificato con strumenti validati."),
    },
}


def blocco_registro(sha: str, byte: int, registro: Registro,
                    strumenti: list[str], lingua: str = "sq") -> list[str]:
    L = _REG.get(lingua, _REG["sq"])
    righe = ["---", "", f"## {L['titolo']}", "", L["intro"], ""]
    righe += [f"**{L['impronta']}**", "", f"`{sha}`", "",
              f"({byte:,} byte)".replace(",", "."), ""]
    if strumenti:
        righe += [f"**{L['strumenti']}**", ""]
        righe += [f"- {s}" for s in strumenti if s]
        righe.append("")
    if registro.passi:
        righe += [f"**{L['passi']}**", ""]
        righe += [f"{i}. {p}" for i, p in enumerate(registro.passi, 1)]
        righe.append("")
    righe += [L["limite"], ""]
    return righe

# ── le frasi dei passaggi, nelle due lingue ────────────────────────────
# ⚠️ Stanno QUI e non in video.py: sparse in due file, il prossimo che le
# tocca ne traduce una sola. Le chiavi devono restare identiche fra sq e it —
# il set aureo lo verifica.
PASSI = {
    "sq": {
        "impronta": "Gjurma SHA-256 e llogaritur mbi skedarin origjinal ({n} bajt).",
        "exif": ("Metadatat e kontejnerit u lexuan me exiftool "
                 "(`exiftool -json -a -G1`)."),
        "fotogrammi": ("Fotogramat u nxorën me ffmpeg: dallim i ndryshimit të skenës "
                       "`select='gt(scene,{soglia})'` me rikthim te intervali i "
                       "rregullt, shkallë maks 1280px, cilësi JPEG 4, tavan {tetto}. "
                       "Të nxjerra: {n}."),
        "minutaggi": ("Minutazhet e fotogramave (lexuar nga `showinfo`, jo të "
                      "vlerësuara): {lista}"),
        "audio": ("Pista audio u nxor: 16 kHz, mono, PCM 16 bit "
                  "(`ffmpeg -vn -ac 1 -ar 16000`)."),
        "trascrizione": ("Transkriptim me faster-whisper, modeli `{modello}`, int8, "
                         "VAD aktiv. Gjuha e dalluar: {lingua} ({conf})."),
        "motore": "Tetramorph — motori i përshkrimit (interpretim)",
    },
    "it": {
        "impronta": "Impronta SHA-256 calcolata sul file originale ({n} byte).",
        "exif": ("Metadati del contenitore letti con exiftool "
                 "(`exiftool -json -a -G1`)."),
        "fotogrammi": ("Fotogrammi estratti con ffmpeg: rilevamento cambio scena "
                       "`select='gt(scene,{soglia})'` con ripiego a intervallo "
                       "regolare, scala max 1280px, qualità JPEG 4, tetto {tetto}. "
                       "Estratti: {n}."),
        "minutaggi": ("Minutaggi dei fotogrammi (letti da `showinfo`, non "
                      "stimati): {lista}"),
        "audio": ("Traccia audio estratta: 16 kHz, mono, PCM 16 bit "
                  "(`ffmpeg -vn -ac 1 -ar 16000`)."),
        "trascrizione": ("Trascrizione con faster-whisper, modello `{modello}`, int8, "
                         "VAD attivo. Lingua riconosciuta: {lingua} ({conf})."),
        "motore": "Tetramorph — motore di descrizione (interpretazione)",
    },
}


def passo(chiave: str, lang: str = "sq", **campi) -> str:
    """Una frase del registro, nella lingua del documento.

    ⚠️ Il parametro si chiama `lang` e non `lingua` di proposito: uno dei testi
    ha un campo `{lingua}` (quella riconosciuta nell'audio), e con lo stesso
    nome Python direbbe «got multiple values for argument».
    """
    tab = PASSI.get(lang, PASSI["sq"])
    return tab[chiave].format(**campi)
