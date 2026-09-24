#!/usr/bin/env python3
"""v9.383 — I TITOLI DEI CAPITOLI PER L'ITALIANO: Libro / Titolo / Capo / Sezione di ogni articolo, letti dall'ALBERO
della pagina dell'atto su Normattiva (la stessa che l'ingest apre per i link agli articoli). Una richiesta per atto, in
sequenza, con pausa (Normattiva strozza i flussi paralleli). Il risultato si SALVA a parte, atto per atto, in
`data/processed/it_gerarchia/<id>.json` (i JSON sorgente in it_acts/ non si toccano) e `build_it_index.py` lo unisce.

L'albero è una sequenza piatta: intestazioni («CAPO I» + titolo «PRINCIPI») e link agli articoli («art. 2946», «art. 42
bis», «1»). Un'intestazione può portare più livelli insieme («TITOLO V» → «DELLA PRESCRIZIONE…<br/>CAPO I<br/>Della
prescrizione<br/>Sezione I<br/>…»): si scompone riga per riga. Livelli: PARTE > LIBRO > TITOLO > CAPO > SEZIONE > §;
una nuova intestazione azzera SOLO i livelli sotto di sé; un'intestazione senza parola di livello («Disposizioni sulla
legge in generale») vale come un LIBRO; «ALLEGATO» azzera tutto. Chiave dell'articolo = (gruppo, numero normalizzato come
l'ingest: «art. 42 bis» → «42-bis»); una chiave ripetuta nello stesso gruppo è AMBIGUA e non si assegna (mai a caso).

    python3 tools/it_gerarchia.py probe codice_civile     # un atto: statistiche + esempi, nulla scritto
    python3 tools/it_gerarchia.py run [--only a,b] [--delay 3]
    python3 tools/it_gerarchia.py file <id> <pagina.html> # prova su una pagina già scaricata
    --cache DIR   le pagine degli atti si salvano (gzip, per URN) e si rileggono da lì: rifare l'albero senza riscaricare
"""
import gzip, hashlib, html as _html, json, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = Path(os.environ.get("SA_DATA", "/var/www/apps/super-avvocato/data"))
ACTS = DATA / "processed" / "it_acts"
OUT = DATA / "processed" / "it_gerarchia"

# ⚠️ l'etichetta può contenere dei tag: le intestazioni del testo MODIFICATO sono «<em><strong>((TITOLO IV</a>…» — il primo
# regex ([^<]+) le saltava in silenzio (288 intestazioni su 3.235, fra cui il Titolo IV «controversie di lavoro» e il
# Titolo IV-bis «famiglia» del c.p.c.: gli artt. 409-473-bis finivano sotto «Dell'opposizione di terzo»)
_HDR = re.compile(r'data-toggle="collapse"[^>]*>(.*?)</a></div><span class="snippets"><div id="coll_\d+"[^>]*>(.*?)</div>', re.S)
_LNK = re.compile(r"showArticle\('([^']+)',\s*this\);\"[^>]*class=\"numero_articolo\">([^<]*)</a>")

# livelli: ALLEGATO (-1) sopra tutto · PARTE 0 · ancora senza parola di livello 0.5 · LIBRO 1 · TITOLO 2 · CAPO 3 ·
# SEZIONE 4 · § 5 · lettera «D) Segnali di indicazione» 6
_LIV = {"PARTE": 0, "LIBRO": 1, "TITOLO": 2, "CAPO": 3, "SEZIONE": 4, "SEZ.": 4, "SEZ": 4, "§": 5, "PARAGRAFO": 5, "PAR.": 5}
_ROM = r"(?=[IVXL])(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"          # 1-89: «DI», «CIVILE», «MI» NON sono numeri romani
_SUFF = (r"(?:BIS|TER|QUATER|QUINQUIES|SEXIES|SEPTIES|OCTIES|NOVIES|DECIES|UNDECIES|DUODECIES|TERDECIES|QUATERDECIES|"
         r"QUINQUIESDECIES|SEXIESDECIES|SEPTIESDECIES|OCTIESDECIES|NOVIESDECIES|VICIES)")
_PAROLA_ORD = (r"(?:UNIC[OA]|PRIM[OA]|SECOND[OA]|TERZ[OA]|QUART[OA]|QUINT[OA]|SEST[OA]|SETTIM[OA]|OTTAV[OA]|NON[OA]|"
               r"(?:UN|DUO)?DECIM[OA]|[A-Z]{3,}ESIM[OA]|PRELIMINARE|GENERALE|SPECIALE)")
_ORD = (r"(?:" + _ROM + r"(?:\.\d+)?|\d+\." + _ROM + r"|\d+(?:\.\d+)*(?:-" + _ROM + r")?|" + _PAROLA_ORD + r")"
        r"(?:\s*-\s*" + _SUFF + r"|\s+" + _SUFF + r"|(?<=\d)[A-Zªº°]|-[A-Z])?(?![A-Z0-9])")   # «Sezione 1ª», «1a»
_LW = r"(§|PARTE|LIBRO|TITOLO|CAPO|SEZIONE|SEZ\.|PARAGRAFO|PAR\.)"          # «Par. 1» del c.p.c. (rito del lavoro)
_TESTA_RX = re.compile(r"^\s*" + _LW + r"\s*(" + _ORD + r")", re.I)      # la parola di livello + l'ordinale, a inizio riga
_ALL_ID = r"(?:[IVXL]+|\d+|[A-Z])(?:[.\-](?:[IVXL]+|\d+|[A-Z]|BIS|TER|QUATER|QUINQUIES|SEXIES|SEPTIES|OCTIES))*(?![A-Z0-9])"
_ALLEGATO_RX = re.compile(r"^\s*ALLEGATO\b\s*(" + _ALL_ID + r")?\s*[.:\-–—]?\s*(.*)$", re.I)
_ABROGATO_RX = re.compile(r"^\s*(?:PARTE|LIBRO|TITOLO|CAPO|SEZIONE|PARAGRAFO)\s+ABROGAT[OA]\b", re.I)
_LETTERA_RX = re.compile(r"^\s*[A-Z]\)\s+\S")
# un'intestazione FUSA nel titolo precedente («DOCUMENTAZIONE AMMINISTRATIVA SEZIONE I», «SANZIONI Capo I ABUSIVISMO…»):
# si spezza SOLO se la parola prima non è una preposizione/articolo («MODIFICHE AL TITOLO VIII», «DEL LIBRO I» restano)
_DENTRO_RX = re.compile(r"(?<=\S)\s+(?=" + _LW + r"\s*" + _ORD + r")", re.I)
_PREP = {"DI", "DEL", "DELLO", "DELLA", "DEI", "DEGLI", "DELLE", "A", "AL", "ALLO", "ALLA", "AI", "AGLI", "ALLE", "DA", "DAL",
         "DALLO", "DALLA", "DAI", "DAGLI", "DALLE", "IN", "NEL", "NELLO", "NELLA", "NEI", "NEGLI", "NELLE", "SU", "SUL", "SULLO",
         "SULLA", "SUI", "SUGLI", "SULLE", "CON", "PER", "TRA", "FRA", "E", "ED", "O", "IL", "LO", "LA", "I", "GLI", "LE", "UN",
         "UNO", "UNA", "CUI", "COME", "ALL'", "DELL'", "DALL'", "NELL'", "SULL'", "ALTRO", "ALTRA", "PRESENTE", "MEDESIMO"}


# i suffissi latini si scrivono in più modi anche dentro Normattiva (l'albero «1519 novies», la pagina «1519-nonies»;
# «quindecies» = «quinquiesdecies», «duodevicies» = «octiesdecies»): per CONFRONTARE si riducono al numero
_LAT = {"tricies": 30, "bis": 2, "ter": 3, "quater": 4, "quinquies": 5, "sexies": 6, "septies": 7, "octies": 8, "novies": 9, "nonies": 9,
        "decies": 10, "undecies": 11, "duodecies": 12, "terdecies": 13, "tredecies": 13, "quaterdecies": 14,
        "quinquiesdecies": 15, "quindecies": 15, "sexiesdecies": 16, "sexdecies": 16, "sedecies": 16, "septiesdecies": 17,
        "octiesdecies": 18, "duodevicies": 18, "noviesdecies": 19, "undevicies": 19, "vicies": 20, "viciessemel": 21,
        "unvicies": 21, "viciesbis": 22, "duovicies": 22, "viciester": 23, "viciesquater": 24, "viciesquinquies": 25,
        "viciessexies": 26, "viciessepties": 27, "viciesocties": 28, "viciesnovies": 29}


def canon(numero: str) -> str:
    """«2-sex-decies» / «2-sexdecies» / «2-sexiesdecies» → «2-16»; «473-bis.2» → «473-2.2»; «2506.1» resta «2506.1»."""
    t = str(numero or "").lower().split("-")
    out, i = [t[0]], 1
    while i < len(t):
        for j in (3, 2):                                 # due-tre pezzi che insieme fanno un ordinale («vicies-semel»)
            if i + j <= len(t) and "".join(t[i:i + j]) in _LAT and all(x.isalpha() for x in t[i:i + j]):
                out.append(str(_LAT["".join(t[i:i + j])])); i += j
                break
        else:
            m = re.match(r"^([a-z]+)(\..*)?$", t[i])
            out.append((str(_LAT[m.group(1)]) + (m.group(2) or "")) if m and m.group(1) in _LAT else t[i]); i += 1
    return "-".join(out)


def ordina(numero: str) -> tuple:
    """Ordine vero degli articoli: 518, 518.1, 518.2, 518-bis, 518-ter … 473-bis, 473-bis.1 … 473-ter."""
    c = canon(numero)
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:-(\d+)(?:\.(\d+))?)?(.*)$", c)
    if not m:
        return (10 ** 9, 0, 0, 0, c)
    return (int(m.group(1)), int(m.group(3) or 0), int(m.group(2) or 0) + int(m.group(4) or 0), 0, m.group(5) or "")


def _norm_num(label: str) -> str:
    n = re.sub(r"^art(?:icolo)?\.?\s*", "", (label or "").strip(), flags=re.I)
    return re.sub(r"[\s\-]+", "-", n).lower().rstrip("-.")


def _pulito(s: str) -> str:
    t = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = re.sub(r"\(\(\s*\d+\s*\)\)", " ", t)                 # rimandi alle note «((178))»
    t = t.replace("((", " ").replace("))", " ")              # marcatori del testo modificato di Normattiva
    t = re.sub(r"^[\s.…]+", "", t)                          # «... ... CAPO IV» (c.c.): i puntini di un'omissione
    return " ".join(t.split())


def _livello(riga: str):
    """{livello, etichetta, titolo} se la riga è un'intestazione («CAPO I», «Sezione IV-bis», «§ 2. DISPOSIZIONI…»,
    «TITOLO DODICESIMO», «ALLEGATO I.7 …»), altrimenti None. Il titolo sulla stessa riga dopo la punteggiatura o lo spazio."""
    m = _ALLEGATO_RX.match(riga)
    if m:
        return {"liv": -1, "tipo": "ALLEGATO", "stile": "M", "etichetta": ("ALLEGATO " + (m.group(1) or "")).strip(),
                "titolo": m.group(2).strip(" .:-–—")}
    if _LETTERA_RX.match(riga):                            # «A) Segnali verticali in generale» (reg. CdS, sotto il §)
        return {"liv": 6, "tipo": "LETTERA", "stile": "M", "etichetta": "", "titolo": riga.strip()}
    m = _TESTA_RX.match(riga)
    if not m:
        return None
    resto = riga[m.end():]
    if resto and not re.match(r"^[\s.:\-–—]", resto):        # «CAPOVERSO», «Sezione Ia» fuori standard: non è un'etichetta
        return None
    parola = m.group(1).upper()
    if parola == "§":
        etichetta = "§ " + m.group(2).strip()
    elif parola in ("SEZ.", "SEZ"):
        etichetta = "Sezione " + m.group(2).strip()
    else:
        etichetta = m.group(1) + " " + m.group(2).strip()
    tipo = {"SEZ.": "SEZIONE", "SEZ": "SEZIONE", "PARAGRAFO": "§", "PAR.": "§"}.get(parola, parola)
    stile = "M" if m.group(1).isupper() else "m"         # «SEZIONE II» (sopra i titoli, cod. ambiente) ≠ «Sezione I» (dentro i capi)
    return {"liv": _LIV[parola], "tipo": tipo, "stile": stile, "etichetta": " ".join(etichetta.split()),
            "titolo": resto.strip(" .:-–—")}


def _spezza(riga: str) -> list[str]:
    """Una riga con dentro un'altra intestazione («… E CONTABILE TITOLO I DISPOSIZIONI GENERALI») → due righe."""
    for m in _DENTRO_RX.finditer(riga):
        prima = riga[:m.start()].rstrip()
        ultima = (prima.split() or [""])[-1].upper()
        if ultima in _PREP or ultima.endswith("'"):
            continue
        return [prima] + _spezza(riga[m.end():])
    return [riga]


def _righe_blocco(etichetta_html: str, corpo_html: str, titolo_atto: str) -> list[str]:
    righe = [_pulito(etichetta_html)] + [_pulito(x) for x in re.split(r"<br\s*/?>", corpo_html or "", flags=re.I)]
    righe = [r for r in righe if r]
    # «PARTE» | «II ORDINAMENTO FINANZIARIO…» (TUEL): la parola di livello da sola si unisce all'ordinale della riga dopo
    uniti = []
    for r in righe:
        if uniti and re.fullmatch(r"(?:§|PARTE|LIBRO|TITOLO|CAPO|SEZIONE|PARAGRAFO)", uniti[-1], re.I) and \
                re.match(r"^\s*" + _ORD, r, re.I):
            uniti[-1] = uniti[-1] + " " + r
        else:
            uniti.append(r)
    out = []
    for r in uniti:
        out.extend(x for x in _spezza(r) if x)
    # l'intestazione dell'atto stesso («COSTITUZIONE DELLA REPUBBLICA ITALIANA») non è un capitolo
    if out and titolo_atto and _livello(out[0]) is None and \
            re.sub(r"\W+", " ", out[0]).strip().lower() == re.sub(r"\W+", " ", titolo_atto).strip().lower():
        out = out[1:]
    return out


_PJESA_TIPI = ("ALLEGATO", "PARTE", "ANCORA", "LIBRO")
_KREU_TIPI = ("TITOLO", "CAPO")


def _applica(pila: list, e: dict, primo: bool) -> list:
    """Mette l'intestazione `e` nella pila dei livelli aperti. La gerarchia NON è fissa fra gli atti (nel codice
    dell'ambiente la «SEZIONE II» sta SOPRA i «TITOLO»): (1) un'intestazione dello stesso tipo e stile già aperta viene
    sostituita (e con lei tutto ciò che le stava sotto) — dal secondo elemento di un blocco in poi, solo se è del blocco
    stesso: le intestazioni di un blocco si aprono l'una dentro l'altra; (2) altrimenti si chiudono i livelli più profondi
    per ordine canonico (PARTE > LIBRO > TITOLO > CAPO > SEZIONE > § > lettera), ma MAI un'intestazione ancora senza
    articoli (è il genitore di questa)."""
    tipo = e["tipo"]
    if tipo == "ALLEGATO":
        return [e]
    if tipo == "ANCORA":
        return [x for x in pila if x["tipo"] == "ALLEGATO"] + [e]
    for k in range(len(pila) - 1, -1, -1):
        x = pila[k]
        if x["tipo"] == tipo and (x["stile"] == e["stile"] or tipo in ("PARTE", "LIBRO")):
            if primo or x.get("blocco") == e["blocco"]:
                if x["etichetta"] == e["etichetta"] and not e["titolo_proprio"]:
                    e = dict(e, testo=x["testo"])       # «TITOLO I» ripetuto senza titolo (disp. att. c.p.p.): resta il suo titolo
                return pila[:k] + [e]
            break
    if tipo in ("PARTE", "LIBRO"):
        pila = [x for x in pila if x["tipo"] != "ANCORA"]
    if primo:
        while pila and pila[-1]["tipo"] != "ALLEGATO" and pila[-1]["liv"] >= e["liv"] and pila[-1].get("art"):
            pila = pila[:-1]
    return pila + [e]


def _voce_da_pila(pila: list) -> tuple[str, str, str]:
    primo_kreu = next((k for k, x in enumerate(pila) if x["tipo"] in _KREU_TIPI), None)
    pj, kr, sk = [], [], []
    for k, x in enumerate(pila):
        if x["tipo"] == "LETTERA":
            # «A) Segnali verticali in generale»: nell'albero del reg. CdS mancano B) e C) → gli artt. 84-123 finirebbero
            # sotto la A). Si tiene nella pila (non sporca i titoli) ma non si scrive: meglio il § giusto che la lettera sbagliata
            continue
        if x["tipo"] in _PJESA_TIPI or (primo_kreu is not None and k < primo_kreu):
            pj.append(x["testo"])
        elif x["tipo"] in _KREU_TIPI:
            kr.append(x["testo"])
        else:
            sk.append(x["testo"])
    return " · ".join(pj), " · ".join(kr), " · ".join(sk)


def albero(page: str, titolo_atto: str = "") -> tuple[dict, dict]:
    """Ritorna ({(gruppo, numero): (pjesa, kreu, seksioni)}, statistiche).
    pjesa = ALLEGATO · PARTE · ancora · LIBRO (e una SEZIONE che sta sopra i titoli); kreu = TITOLO · CAPO;
    seksioni = SEZIONE · § · lettera."""
    ev = [(m.start(), "H", m.group(1), m.group(2)) for m in _HDR.finditer(page)]
    ev += [(m.start(), "A", m.group(2).strip(), m.group(1)) for m in _LNK.finditer(page) if "imUpdate=true" not in m.group(1)]
    ev.sort(key=lambda e: e[0])
    pila: list = []                                  # i livelli aperti, dal più alto al più profondo
    out: dict = {}
    visti: dict = {}
    n_hdr = 0
    ultimo_gruppo, intestazione_dopo = None, False
    for _pos, kind, a, b in ev:
        if kind == "H":
            n_hdr += 1
            intestazione_dopo = True
            righe = _righe_blocco(a, b, titolo_atto)
            i, primo = 0, True
            while i < len(righe):
                lv = _livello(righe[i])
                if lv is None:
                    if i > 0 or not re.search(r"[A-Za-zÀ-ÿ]", righe[i]):   # riga orfana o senza lettere: non è un capitolo
                        i += 1; continue
                    lv = {"liv": 0.5, "tipo": "ANCORA", "stile": "M", "etichetta": "", "titolo": righe[0]}
                i += 1
                parti = [lv["titolo"]] if lv["titolo"] else []
                while i < len(righe) and _livello(righe[i]) is None:
                    r = righe[i]
                    parti.append(f"({r})" if _ABROGATO_RX.match(r) else r)   # «(CAPO ABROGATO DALLA L. …)»
                    i += 1
                titolo = re.sub(r"(?<=[a-zà-ÿ]{2})\.$", "", " ".join(parti), flags=re.I)   # «Le Camere.» → «Le Camere»
                # «… dei figli naturali SEZIONE ABROGATA DALLA L. 10 DICEMBRE 2012, N. 219» → «… (SEZIONE ABROGATA …)»
                titolo = re.sub(r"(?<=\S)\s+((?:PARTE|LIBRO|TITOLO|CAPO|SEZIONE|PARAGRAFO)\s+ABROGAT[OA]\b[^()]*)$", r" (\1)", titolo)
                e = dict(lv, blocco=n_hdr, titolo_proprio=bool(titolo),
                         testo=" — ".join(x for x in (lv["etichetta"], titolo) if x)[:220])
                pila = _applica(pila, e, primo)
                primo = False
        else:
            mf = re.search(r"flagTipoArticolo=(\d+)", b)
            flag = mf.group(1) if mf else "0"          # come l'ingest (article_links_all): senza flag = gruppo 0
            num = _norm_num(a)
            if not num or not re.match(r"^\d", num):
                continue
            if ultimo_gruppo is not None and flag != ultimo_gruppo and not intestazione_dopo:
                pila = []                              # un altro gruppo (decreto ↔ allegato) senza intestazione: i capitoli non passano
            ultimo_gruppo, intestazione_dopo = flag, False
            for x in pila:
                x["art"] = True
            key = (flag, num)
            ck = (flag, canon(num))
            visti.setdefault(ck, []).append(key)
            out[key] = _voce_da_pila(pila)
    ambigui = [ck for ck, ks in visti.items() if len(ks) > 1]
    for ck in ambigui:                               # la stessa chiave due volte nello stesso gruppo: mai a caso
        for k in visti[ck]:
            out.pop(k, None)
    return out, {"intestazioni": n_hdr, "collapse": page.count('data-toggle="collapse"'), "link": sum(len(v) for v in visti.values()),
                 "chiavi": len(out), "ambigui": len(ambigui)}


def _base(numero: str) -> str:
    return re.sub(r"-(?:legge|all\d+)$", "", str(numero or ""))


def prepara(mappa: dict) -> dict:
    """L'indice per cercare gli articoli del corpus nell'albero: chiavi (gruppo, numero canonico), i gruppi presenti, il gruppo
    del TESTO (quello con più articoli: nel corpus tiene i numeri senza suffisso) e le voci per numero."""
    from collections import Counter
    k = {(g, canon(n)): v for (g, n), v in mappa.items()}
    per_num: dict = {}
    for (g, n), v in k.items():
        per_num.setdefault(n, []).append(v)
    c = Counter(g for g, _n in mappa)
    return {"k": k, "gruppi": set(c), "principale": c.most_common(1)[0][0] if c else "0", "per_num": per_num}


def voce(prep: dict, numero: str, gruppo=None):
    """La voce (pjesa, kreu, seksioni) di un articolo del corpus. Il gruppo è quello scritto nell'articolo; se manca (atti
    scaricati prima della numerazione per gruppi) si ricava dal numero come fa normattiva_lib.assign_numbers: «N-legge» =
    gruppo 0, «N-allK» = gruppo K, senza suffisso = il testo principale. Poi la chiave ESATTA (gruppo, numero); il solo
    numero (se unico) vale SOLO quando quel gruppo non compare affatto nell'albero — mai quando il gruppo c'è ma la chiave
    è ambigua o manca (sarebbe il capitolo di un ALTRO testo: l'art. 5 dell'allegato col capo dell'art. 5 del codice)."""
    numero = str(numero or "")
    base = canon(_base(numero))
    if gruppo in (None, ""):
        m = re.search(r"-all(\d+)$", numero)
        gruppo = m.group(1) if m else ("0" if numero.endswith("-legge") else prep["principale"])
    gruppo = str(gruppo)
    v = prep["k"].get((gruppo, base))
    if v is not None:
        return v
    if gruppo in prep["gruppi"]:
        return None
    uno = prep["per_num"].get(base) or []
    return uno[0] if len(uno) == 1 else None


def copertura(atto: dict, mappa: dict, mancanti: list | None = None) -> tuple[int, int]:
    arts = atto.get("articles") or []
    prep = prepara(mappa)
    ok = 0
    for a in arts:
        if voce(prep, a.get("number"), a.get("group")) is not None:
            ok += 1
        elif mancanti is not None:
            mancanti.append(f"{a.get('number')}[g{a.get('group', '-')}]")
    return ok, len(arts)


def salva(cid: str, urn: str, mappa: dict, stats: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{cid}.json"
    f.write_text(json.dumps({"urn": urn, "fetched": time.strftime("%Y-%m-%d"), "stats": stats,
                             "map": {f"{g}|{n}": list(v) for (g, n), v in mappa.items()}}, ensure_ascii=False), encoding="utf-8")
    return f


def _atti() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(ACTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        urn = (d.get("urn") or "").strip()
        if f.stem == "cedu" or f.stem.startswith("cedu_"):   # dal PDF della Corte EDU, non da Normattiva
            continue
        if urn and ":" in urn and not urn.upper().startswith(("CELEX", "EUR", "3")) and "eur-lex" not in urn.lower():
            out.append((f.stem, d))
    return out


def _mostra(cid, atto, mappa, stats):
    mancanti: list = []
    ok, tot = copertura(atto, mappa, mancanti)
    # «collapse» − 4 = intestazioni vere (la pagina ha sempre 4 pannelli collassabili che non sono capitoli)
    persi = stats.get("collapse", 4) - 4 - stats["intestazioni"]
    print(f"{cid:34s} intestazioni {stats['intestazioni']:4d}{f' (PERSE {persi})' if persi else ''} · link {stats['link']:5d} · "
          f"ambigui {stats['ambigui']:3d} · articoli coperti {ok}/{tot} ({100 * ok / max(tot, 1):.0f}%)"
          + (f"  senza: {', '.join(mancanti[:8])}{' …' if len(mancanti) > 8 else ''}" if mancanti and "-v" in sys.argv else ""), flush=True)
    return ok, tot


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "file":
        cid, page = sys.argv[2], Path(sys.argv[3]).read_text(encoding="utf-8")
        atto = json.loads((ACTS / f"{cid}.json").read_text(encoding="utf-8"))
        mappa, stats = albero(page, atto.get("title") or "")
        _mostra(cid, atto, mappa, stats)
        for n in sys.argv[4:]:
            hits = [(k, v) for k, v in mappa.items() if k[1] == n]
            print(f"   {n}: {hits}")
        return 0
    from normattiva_lib import Normattiva
    solo = set()
    if "--only" in sys.argv:
        solo = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    delay = float(sys.argv[sys.argv.index("--delay") + 1]) if "--delay" in sys.argv else 3.0
    if cmd == "probe":
        solo = {sys.argv[2]} if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else solo
    atti = [(c, d) for c, d in _atti() if not solo or c in solo]
    cache = Path(sys.argv[sys.argv.index("--cache") + 1]) if "--cache" in sys.argv else None
    tot_ok = tot_all = 0; falliti = []
    for cid, atto in atti:
        try:
            cf = cache / (hashlib.sha1(atto["urn"].encode()).hexdigest()[:16] + ".html.gz") if cache else None
            if cf is not None and cf.exists():
                page = gzip.decompress(cf.read_bytes()).decode("utf-8")
            else:
                nm = Normattiva(delay=delay)
                page = nm.open_act(atto["urn"])
                if cf is not None:
                    cache.mkdir(parents=True, exist_ok=True)
                    cf.write_bytes(gzip.compress(page.encode("utf-8")))
                time.sleep(delay)
            mappa, stats = albero(page, atto.get("title") or "")
            ok, tot = _mostra(cid, atto, mappa, stats)
            tot_ok += ok; tot_all += tot
            if cmd == "run":
                salva(cid, atto["urn"], mappa, stats)
        except Exception as e:  # noqa: BLE001
            falliti.append(cid); print(f"{cid:34s} ERRORE {type(e).__name__}: {str(e)[:90]}", flush=True)
    print(f"\ntotale: {tot_ok}/{tot_all} articoli con capitolo · atti {len(atti)} · falliti {falliti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
