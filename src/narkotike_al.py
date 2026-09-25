# -*- coding: utf-8 -*-
"""v9.392 — LE LISTE DELLE SOSTANZE della ligji 7975/1995 (Shqipëri) al senior, al Giudice e alla verifica. Solo AL.

Perché (misurato il 25 set, 35 sostanze, il modello del senior senza web: `tools/eval_narkotike_al.py`): le liste ONU le
conosce, ma sbaglia proprio ciò che è albanese — ketamina, N2O e GBL «jo» (sono lëndë të kontrolluara: Lista A, regime
del gruppo III/b per il neni 4, e per il neni 2 NON narcotici né psicotropi — il KP 283 parla di «substanca narkotike dhe
psikotrope»), HHC e carisoprodol «jo» (in lista con la ligji 17/2026, datë 3.2.2026), e il GRUPPO della 7975 in 12 casi
su 35 (cocaina, cannabis, morfina, fentanil, metadone nel gruppo I: lo schema li mette nel II). Il gruppo decide ricetta
(7/60 giorni, ripetibilità) e controllo; la lista decide se il KP 283-284/c si applica.

Dati: `data/processed/al_lista_narkotike.json` (`tools/ingest_liste_narkotike_al.py`: le 16 figure dell'allegato lette una a
una con la cifra di controllo dei CAS + la parte in testo). Tre usi, come `stupefacenti.py` per l'Italia: `trova`, `blocco`
(dossier del senior e del Giudice), `verifica` / `nota` (gruppo o lista sbagliati, «non controllata» detta di una sostanza
in lista). Mai solleva.
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata

from .config import PROCESSED_DATA_PATH
from .logging_utils import get_logger

log = get_logger(__name__)

FILE = PROCESSED_DATA_PATH / "al_lista_narkotike.json"
_lock = threading.Lock()
_stato: dict = {"mtime": None, "dati": None, "forme": {}, "rx": None}

# Lo SCHEMA DI CLASSIFICAZIONE dell'allegato (figura 16) + neni 4 (Lista A → regime del gruppo III, nëngrupi «b»)
GRUPPO = {"1961-IV": "I", "1971-I": "I", "1961-I": "II", "1961-II": "II", "1971-II": "II",
          "1961-III": "III", "1971-III": "III", "1971-IV": "III", "A": "III"}
_ETICHETTA = {"1961-I": "Lista I e Konventës Unike 1961", "1961-II": "Lista II e Konventës Unike 1961",
              "1961-III": "Lista III e Konventës Unike 1961", "1961-IV": "Lista IV e Konventës Unike 1961",
              "1971-I": "Lista I e Konventës 1971", "1971-II": "Lista II e Konventës 1971",
              "1971-III": "Lista III e Konventës 1971", "1971-IV": "Lista IV e Konventës 1971",
              "A": "Lista A e lëndëve të kontrolluara"}
_ORDINE = ["1961-I", "1961-II", "1961-III", "1961-IV", "1971-I", "1971-II", "1971-III", "1971-IV", "A"]

# forme albanesi (flesse) e nomi correnti → una forma del dizionario. Mai «hashash»: nel neni 9 è Papaver somniferum.
_ALIAS = [
    (r"kokain\w*|crack", "cocaine"), (r"heroin\w*", "heroin"),
    (r"kanabis\w*|cannabis\w*|marijuan\w*|marihuan\w*", "cannabis"), (r"hashish\w*", "cannabis resin"),
    (r"ekstaz\w*|ecstasy", "mdma"), (r"metamfetamin\w*|metaamfetamin\w*|shabu", "metamfetamine"),
    (r"(?<!met)amfetamin\w*", "amfetamine"), (r"ketamin\w*", "ketamine"), (r"karfentanil\w*", "carfentanil"),
    (r"(?<!kar)fentanil\w*|fentanyl", "fentanyl"), (r"metadon\w*", "methadone"), (r"morfin\w*", "morphine"),
    (r"kodein\w*", "codeine"), (r"oksikodon\w*", "oxycodone"), (r"buprenorfin\w*", "buprenorphine"),
    (r"diazepam\w*", "diazepam"), (r"alprazolam\w*", "alprazolam"), (r"klonazepam\w*", "clonazepam"),
    (r"lorazepam\w*", "lorazepam"), (r"zolpidem\w*", "zolpidem"), (r"flunitrazepam\w*", "flunitrazepam"),
    (r"psilocibin\w*", "psilocybine"), (r"meskalin\w*", "mescaline"), (r"mefedron\w*", "mephedrone"),
    (r"katinon\w*", "cathinone"), (r"metilfenidat\w*", "methylphenidate"), (r"fenobarbital\w*", "phenobarbital"),
    (r"karisoprodol\w*", "carisoprodol"), (r"petidin\w*", "pethidine"), (r"opium\w*", "opium"),
    (r"(?:prot)?oksid\w* (?:i |te )?azot\w*|gaz\w* (?:i |te )?qeshj\w*|gaz gazmor\w*|n2o", "nitrous oxide"),
    (r"gama[- ]?butirolakton\w*|gamma[- ]?butyrolacton\w*|gbl", "gamma-butyrolactone"),
    (r"gama[- ]?hidroksibutir\w*|ghb|oksibat\w*", "ghb"),
    (r"tetrahidrokanabinol\w*|delta[- ]?9[- ]?thc|thc", "delta-9-tetrahydro-cannabinol"),
    (r"heksahidrokanabinol\w*|hexahydrocannabinol|hhc", "hexahydrocannabinol"),
]
# nessuna lista della 7975 (verificato sull'allegato il 25 set: se una revisione le aggiunge, vince il dizionario)
_JO = [(r"tramadol\w*", "tramadol"), (r"pregabalin\w*", "pregabalinë"), (r"gabapentin\w*", "gabapentinë"),
       (r"kratom\w*|mitragin\w*", "kratom (mitraginë)"), (r"dekstrometorfan\w*|dextromethorphan", "dekstrometorfan")]
_SHENIME = {"cannabis": "kultivimi me licencë për qëllime mjekësore dhe industriale: ligji nr. 61/2023",
            "dekstrometorfan": "shënim i shtojcës: «Dextromethorphan dhe dextrorphan nuk janë nën kontroll ndërkombëtar»"}
_SIGLE_AMBIGUE = {"dom", "stp", "dob", "mda", "dmt", "det", "dmhp", "tma", "pma", "cps", "and", "etc"}


def _piega(s: str) -> str:
    """Chiave di confronto (per le forme del dizionario): minuscolo, senza diacritici, spazi compattati."""
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("ë", "e").replace("ç", "c"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.replace("³", "").replace("²", "")).strip()


def _piega_testo(text: str) -> str:
    """La stessa piegatura carattere per carattere (stessa lunghezza del testo): le posizioni valgono nell'originale."""
    out = []
    for ch in text or "":
        c = ch.lower()
        if len(c) != 1:
            c = ch
        if c in "ëç":
            c = {"ë": "e", "ç": "c"}[c]
        elif c.isspace() or c in "³²":
            c = " "
        else:
            base = unicodedata.normalize("NFKD", c)
            c = base[0] if base and not unicodedata.combining(base[0]) else c
        out.append(c)
    return "".join(out)


def _forme(r: dict) -> set[str]:
    nome = re.sub(r"^\(\s*[+±-]\s*\)-", "", r.get("emri") or "")
    out = {nome, nome.split(",")[0]}            # «CANNABIS RESIN, EXTRACTS and TINCTURES» → anche «cannabis resin»
    out.update(re.findall(r"\(([^()]{2,60})\)", nome))
    out.add(re.sub(r"\s*\([^()]*\)\s*", " ", nome))
    for x in (r.get("te_tjera") or "").split(","):
        x = re.split(r"\s+and its\b|\s+dhe\b", x.strip(" ()"))[0]
        out.add(x)
    return {_piega(f) for f in out if f}


def _dati() -> dict | None:
    with _lock:
        try:
            mt = os.path.getmtime(FILE)
        except OSError:
            return None
        if _stato["mtime"] == mt:
            return _stato["dati"]
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("narkotike_al: listat nuk lexohen", exc_info=True)
            return None
        forme: dict = {}
        for r in d.get("righe") or []:
            voce = (r["lista"], (r.get("emri") or "").strip(), r.get("shtuar_me") or "", bool(r.get("preparat")))
            for f in _forme(r):
                # «THC» nudo sta negli «altri nomi» degli isomeri (Lista I 1971): in un testo è il delta-9 (Lista II) → alias
                if len(f) < 3 or f in _SIGLE_AMBIGUE or f == "thc" or re.fullmatch(r"[\d\W]+", f):
                    continue
                forme.setdefault(f, [])
                if voce not in forme[f]:
                    forme[f].append(voce)
        chiavi = sorted(forme, key=len, reverse=True)
        rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in chiavi) + r")(?![\w-])") if chiavi else None
        _stato.update(mtime=mt, dati=d, forme=forme, rx=rx)
        return d


def _voci_alias(target: str) -> list:
    return _stato["forme"].get(_piega(target)) or []


def trova(text: str) -> list[dict]:
    """Le sostanze nominate: [{testo, chiave, voci: [(lista, nome ufficiale, shtuar_me, preparat)], jo, pos}]."""
    d = _dati()
    if not d or not text:
        return []
    t = _piega_testo(text)
    out: dict = {}
    presi: list[tuple[int, int]] = []

    def _sigla_ok(a, b):
        # sigle corte solo se scritte come sigle nel testo («GHB», «HHC», «THC», «N2O»), mai dentro una parola comune
        return b - a > 4 or text[a:b] == text[a:b].upper()

    def _aggiungi(k, a, b, voci, jo=False):
        if any(a < y and b > x for x, y in presi) or not _sigla_ok(a, b):
            return
        presi.append((a, b))
        v = out.setdefault(k, {"testo": text[a:b], "chiave": k, "voci": voci, "jo": jo, "pos": []})
        v["pos"].append((a, b))

    for pat, target in _ALIAS:
        for m in re.finditer(r"(?<![\w-])(?:" + pat + r")(?![\w-])", t):
            voci = _voci_alias(target)
            if voci:
                _aggiungi(_piega(target), m.start(), m.end(), voci)
    for pat, nome in _JO:
        for m in re.finditer(r"(?<![\w-])(?:" + pat + r")(?![\w-])", t):
            voci = _stato["forme"].get(_piega(nome.split(" (")[0])) or []
            _aggiungi(_piega(nome.split(" (")[0]), m.start(), m.end(), voci, jo=not voci)
    if _stato["rx"] is not None:
        for m in _stato["rx"].finditer(t):
            _aggiungi(m.group(1), m.start(), m.end(), _stato["forme"][m.group(1)])
    return list(out.values())


def _liste(voci) -> list[str]:
    return sorted({l for l, _, _, p in voci if not p}, key=_ORDINE.index)


def gruppo(voci) -> str:
    ll = _liste(voci) or sorted({l for l, _, _, _ in voci}, key=_ORDINE.index)
    return min((GRUPPO[l] for l in ll), key=["I", "II", "III"].index) if ll else ""


def categoria(voci) -> str:
    ll = _liste(voci)
    if not ll:
        return "përgatesë" if voci else "jo"
    if ll == ["A"]:
        return "e kontrolluar"
    return "narkotike" if any(l.startswith("1961") for l in ll) else "psikotrope"


def _mostra(s: dict) -> str:
    x = (s.get("testo") or s["chiave"]).strip()
    return x.upper() if len(x) <= 4 and x.replace("2", "").isalpha() else x[:1].upper() + x[1:]


def _dove(s: dict) -> str:
    voci = s["voci"]
    if s.get("jo") or not voci:
        return "nuk figuron në asnjë listë të ligjit 7975 (as në Listën A)" + (f"; {_SHENIME[s['chiave']]}" if s["chiave"] in _SHENIME else "")
    ll = _liste(voci)
    kat = categoria(voci)
    if not ll:
        return f"vetëm si përgatesë me dozë të ulët: {_ETICHETTA['1961-III']} → Grupi III"
    if kat == "e kontrolluar":
        pjese = [f"lëndë e kontrolluar: {_ETICHETTA['A']} → regjimi i grupit III, nëngrupi «b» (neni 4); sipas nenit 2 "
                 f"NUK është lëndë narkotike as psikotrope"]
    else:
        pjese = [f"lëndë {kat}: " + " + ".join(_ETICHETTA[l] for l in ll) + f" → Grupi {gruppo(voci)}"]
    if any(p for _, _, _, p in voci):
        pjese.append("përgatesat me dozë të ulët: Lista III e Konventës Unike 1961 → Grupi III")
    sh = sorted({x for _, _, x, _ in voci if x})
    if sh:
        pjese.append(f"shtuar me {sh[0].replace('ligji nr.', 'ligjin nr.')} — për fakte para hyrjes në fuqi të këtij ligji "
                     f"verifiko nëse lënda kontrollohej")
    if s["chiave"] in _SHENIME:
        pjese.append(_SHENIME[s["chiave"]])
    return "; ".join(pjese)


def blocco(text: str, massimo: int = 12) -> str:
    """Per il dossier (senior e Giudice): dove stanno le sostanze nominate, dall'allegato della legge. Vuoto se nessuna."""
    try:
        trovate = trova(text)
    except Exception:  # noqa: BLE001
        return ""
    if not trovate:
        return ""
    r = ["💊 LISTAT E LËNDËVE NARKOTIKE, PSIKOTROPE DHE TË KONTROLLUARA — ligji nr. 7975/1995, shtojca (teksti i konsoliduar "
         "QBZ 2026-02-20: listat e Konventës Unike 1961 dhe të Konventës 1971 të bashkëlidhura, Lista A, shtesat e ligjit "
         "17/2026). Është e dhëna zyrtare: ka përparësi mbi kujtesën. Skema e klasifikimit: Grupi I = Lista IV 1961 + Lista I "
         "1971 · Grupi II = Listat I e II 1961 + Lista II 1971 · Grupi III = Lista III 1961 (përgatesa) + Listat III e IV "
         "1971 · Lista A (lëndë të kontrolluara) = regjimi i grupit III/b (neni 4), dhe sipas nenit 2 nuk janë narkotike as "
         "psikotrope. Neni 283 dhe 284/c i Kodit Penal flasin për «substanca narkotike dhe psikotrope»."]
    for s in trovate[:massimo]:
        r.append(f"- «{_mostra(s)}» → {_dove(s)}")
    return "\n".join(r)


_GRUPI_RX = re.compile(r"\b[Gg]rup(?:i|in|it)?\s+(III|II|I)\b")
_LISTA_RX = re.compile(r"\b[Ll]ist(?:a|ën|ës|e)\s+(IV|III|II|I|A)\b(?:[^.;]{0,70}?\b(1961|1971)\b)?")
_JO_RX = re.compile(r"\bnuk\s+(?:është|eshte|figuron|përfshihet|perfshihet|kontrollohet|bën pjesë|ben pjese)\b[^.;]{0,40}?"
                    r"\b(?:list\w*|kontroll\w*|konvent\w*|nd[ëe]rkomb\w*)", re.I)
_KAT_RX = re.compile(r"\b(?:është|eshte|janë|jane|si)\s+(?:një\s+)?(?:lëndë|lende|substancë|substance|drogë|droge)?\s*"
                     r"(narkotik\w*|psikotrop\w*)", re.I)


def verifica(text: str) -> list[dict]:
    """Le affermazioni sbagliate: gruppo o lista diversi dall'allegato, «non controllata» detta di una sostanza in lista,
    una lëndë e kontrolluar chiamata narcotica/psicotropa. [{sostanza, lloji, detta, vera}]"""
    errori: list[dict] = []
    try:
        trovate = trova(text)
    except Exception:  # noqa: BLE001
        return []
    if not trovate:
        return []
    tutte = sorted(((p, s) for s in trovate for p in s["pos"]), key=lambda x: x[0][0])
    for i, ((a, b), s) in enumerate(tutte):
        fine = tutte[i + 1][0][0] if i + 1 < len(tutte) else len(text)
        fin = text[b: min(fine, b + 110)]
        m_stop = re.search(r"[.;]\s|\n", fin)
        fin = fin[: m_stop.start()] if m_stop else fin
        nome, vera = _mostra(s), _dove(s)

        def _err(lloji, detta):
            if not any(e["sostanza"] == nome and e["lloji"] == lloji for e in errori):
                errori.append({"sostanza": nome, "lloji": lloji, "detta": detta, "vera": vera})
        if s.get("jo") or not s["voci"]:
            # una sostanza in NESSUNA lista (tramadol, pregabalin…) chiamata «lëndë narkotike/psikotrope» o messa in una lista
            m = re.search(r"\b(?:është|eshte|janë|jane|si)\s+(?:një\s+)?(?:lëndë|lende|substancë|substance)\s+(narkotik\w*|psikotrop\w*)", fin, re.I)
            if m and not re.search(r"\bnuk\b", fin[: m.start()]):
                _err("jo_ne_liste", m.group(1))
            elif _LISTA_RX.search(fin) or _GRUPI_RX.search(fin):
                _err("jo_ne_liste", (_LISTA_RX.search(fin) or _GRUPI_RX.search(fin)).group(0))
            continue
        ll, gr, kat = _liste(s["voci"]), gruppo(s["voci"]), categoria(s["voci"])
        m = _GRUPI_RX.search(fin)
        if m and gr and m.group(1) != gr:
            _err("grupi", f"Grupi {m.group(1)}")
        m = _LISTA_RX.search(fin)
        if m:
            det = m.group(1)
            if det == "A" and "A" not in ll:
                _err("lista", "Lista A")
            elif det != "A" and m.group(2) and f"{m.group(2)}-{det}" not in {l for l, _, _, _ in s["voci"]}:
                _err("lista", f"Lista {det} e Konventës {m.group(2)}")
        # «non è nelle Convenzioni / sotto controllo internazionale»: VERO per una sostanza della sola Lista A (ketamina), FALSO
        # per una che nelle liste delle Convenzioni c'è (HHC dal 2026 — prova viva del 25 set: «HHC nuk figuron në Konventat
        # 1961/1971» e la difesa costruita sopra); «non controllata / in nessuna lista» detto di una sostanza in lista: falso
        mj = _JO_RX.search(fin)
        if mj and not re.search(r"\bnuk\s+(?:është|eshte)\s+(?:lëndë|lende)?\s*(?:narkotik|psikotrop)", fin, re.I):
            if not re.search(r"konvent|nd[ëe]rkomb|OKB", fin[mj.start(): mj.end() + 40], re.I) or any(l != "A" for l in ll):
                _err("jo", mj.group(0).strip()[:60])
        m = _KAT_RX.search(fin)
        if m and kat == "e kontrolluar" and not re.search(r"\bnuk\b", fin[: m.start()]):
            _err("kategoria", m.group(1))
    return errori


def _breve(vera: str) -> str:
    """La verità in poche parole per la nota nel testo (il dettaglio completo va al Giudice)."""
    v = vera.split("; përgatesat")[0].split("; kultivimi")[0].split("; shënim")[0]
    v = v.replace(" → regjimi i grupit III, nëngrupi «b» (neni 4); sipas nenit 2 NUK është lëndë narkotike as psikotrope",
                  " (regjimi i grupit III/b), jo narkotike as psikotrope")
    return re.sub(r" — për fakte para hyrjes.*$", "", v)


def nota(text: str) -> str:
    """La correzione da attaccare al testo (idempotente, breve: una voce per sostanza): vuota se non c'è niente."""
    errori = verifica(text)
    testa = "> ⚠️ **Listat e lëndëve narkotike — për t'u korrigjuar** (ligji nr. 7975/1995, shtojca):"
    if not errori or testa in (text or ""):
        return ""
    per: dict = {}
    for e in errori:
        per.setdefault(e["sostanza"], {"vera": e["vera"], "detta": []})["detta"].append(e["detta"])
    voci = []
    for k, v in list(per.items())[:6]:
        b = _breve(v["vera"])
        voci.append(f"«{k}» {b if b.startswith('nuk ') else 'është ' + b} — jo «{'» / «'.join(v['detta'])}»")
    return "\n\n" + testa + " " + " · ".join(voci) + ".\n"
