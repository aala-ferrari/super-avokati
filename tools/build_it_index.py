# -*- coding: utf-8 -*-
"""Build bm25_it.pkl from the downloaded Normattiva acts.
Writes: all_articles_it.jsonl, it_codes.json (metadata for the UI), bm25_it.pkl.
Keeps a timestamped backup of the previous index so a rollback is trivial.
"""
import json
import os, re, shutil, sys, time
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import Article
from src.retrieval import ArticleIndex

# 16 set 2026 (benchmark lab, v9.332): Normattiva marca con «((…))» il testo modificato da atti
# successivi, e nei CODICI (markup allegato-legacy) la rubrica arriva come «(Capacità giuridica).»
# o resta nel corpo dopo «Art. N.» (c.c. art. 1: rubrica VUOTA e corpo «CODICE CIVILE / Art. 1. /
# (Capacità giuridica). / La capacità…»). Misurato: 1.700+ rubriche IT che cominciano con «(»,
# 457 nel solo c.c.; «( (Maggiore età…» finiva nel badge delle citazioni e nel prompt. Qui si
# puliscono rubrica e corpo SENZA toccare i JSON scaricati (fonte grezza).
_RUB_IN_BODY = re.compile(r"^\s*(?:[A-ZÀ-Ü'’ ,.]{6,}\n+)?Art\.\s*[\dA-Za-z\-]+(?:\.\d+)?\.?\s*\n+\s*\(\(?\s*([^\n]{3,160}?)\s*\)?\)\.?\s*\n+")


# v9.383 — LA RUBRICA RIMASTA NEL CORPO. 4.848 articoli IT vivi (22 %) senza rubrica, fra cui c.c. 45, 89, 128, 158, 230-bis,
# 316 «Responsabilità genitoriale», 536 «Legittimari», 565, 581, 583, 737, c.p. 280, 635 «Danneggiamento», c.p.p. 11, 33-bis…:
# negli articoli SOSTITUITI da leggi successive Normattiva stampa la rubrica senza parentesi («Domicilio dei coniugi…».) come
# prima riga del testo, e nei decreti AKN «(Rubrica)» resta nel corpo quando manca il div della rubrica. Si sposta nella
# rubrica SOLO una prima riga corta (≤100 chr), che finisce con «.» o «)», seguita da una riga vuota e dal testo, che comincia
# con una parola piena (mai «Il/La/Chi/Se/Nei…», mai un verbo finito: una frase normativa breve resta nel corpo — c.c. 147
# non ha rubrica su Normattiva e non gliene si inventa una). Misurato su 1.078 candidate, 115 lette a mano: tutte rubriche.
_RUB_PRIMA_RIGA = re.compile(r"^\s*([^\n]{3,140}?)\s*(?:\n\s*[.;]\s*)?\n\s*\n+(?=\s*[A-ZÀ-Ü0-9(«\"])")
_RUB_STOP = {"il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una", "chi", "quando", "se", "qualora", "nei", "nel", "nella",
             "nelle", "negli", "nello", "per", "salvo", "ai", "al", "alla", "alle", "agli", "allo", "dal", "dalla", "dai", "dalle",
             "in", "con", "tra", "fra", "ogni", "ciascun", "ciascuno", "ciascuna", "è", "sono", "non", "oltre", "fuori", "fermo",
             "ferma", "restano", "resta", "sulla", "sul", "sui", "sulle", "presso", "entro", "anche", "tutti", "tutte", "nessuno",
             "questo", "questa", "tale", "tali", "detto", "detta", "a", "e", "o", "ove", "dove", "chiunque", "coloro", "colui",
             "nessun", "qualunque", "qualsiasi", "ad", "ed", "od", "sino", "fino", "dopo", "prima", "durante", "mediante",
             "decorso", "trascorso", "all", "dell", "nell", "sull", "dall"}
_RUB_VERBI = re.compile(r"\b(?:è|sono|può|possono|deve|devono|ha|hanno|non|si|viene|vengono|era|erano|sia|siano|fosse|sarà|saranno|"
                        r"spetta|spettano|costituisce|costituiscono|comporta|provvede|provvedono|dispone|stabilisce|prevede|applica|"
                        r"applicano|determina|entra|cessa|decorre|appartiene|appartengono|abbia|abbiano|occorre|basta|vale|valgono)\b", re.I)
# non sono rubriche (misurato sul campione del v9.384): il nome di un allegato o di una tabella, il titolo dell'atto,
# una nota redazionale («COMMA ABROGATO DALLA L. COSTITUZIONALE 18 OTTOBRE 2001, N. 3»)
_RUB_NON_RUBRICA = re.compile(r"^(?:ALLEGAT|Allegat|TABELL|Tabell|TESTO UNICO|Testo unico|CONVENZIONE|CODICE|REGOLAMENTO|DECRETO|"
                              r"LEGGE|TARIFFA|PROSPETTO)|ABROGAT|SOPPRESS")
_RUB_FONTE = re.compile(r"^(.*?\S)\s*(\(\s*(?:articol[oi]|art\.|legge|decreto|d\.\s?lgs|regio)\b[^()]*\))\s*$", re.I)


# v9.384 — le altre forme della rubrica rimasta nel corpo (misurate: Roma I 29 su 29, c.c. 263, 330, 332, 337-ter, 2250…):
#   B «Libertà di scelta» + a capo + «1.  Il contratto…»        (regolamenti UE consolidati: il comma numerato sotto)
#   C «Decadenza dalla responsabilità genitoriale» + «sui figli.»  (rubrica su DUE righe, la seconda minuscola col punto)
#   D «Provvedimenti riguardo ai figli» + riga vuota + «Il figlio…» (senza punto; sotto comincia il testo, maiuscolo)
# Stessi filtri della forma A: ≤100 chr, parola piena in testa, nessun verbo finito, niente «:».
_RUB_RIGA_COMMA = re.compile(r"^\s*([^\n]{3,100}?)[ \t\xa0]*\n(?=[ \t\xa0]*(?:1\.|1\)|\(1\))[\s\xa0])")
_RUB_DUE_RIGHE = re.compile(r"^\s*([^\n]{3,90}?)[ \t\xa0]*\n[ \t\xa0]*([a-zà-ü][^\n]{0,60}?\.)[ \t\xa0]*\n\s*\n+(?=\s*[A-ZÀ-Ü0-9(«\"])")
_RUB_NUDA = re.compile(r"^\s*([^\n]{3,100}?)[ \t\xa0]*\n(?:[ \t\xa0]*\n)*(?=[ \t\xa0]*[A-ZÀ-Ü«\"])")


def _rubrica_prima_riga(body: str):
    """(rubrica, corpo) se la prima riga del corpo è la rubrica dell'articolo, altrimenti None."""
    body = body or ""
    m = _RUB_PRIMA_RIGA.match(body)
    if m:
        riga = m.group(1).strip()
        punto_sotto = bool(re.match(r"\s*\n\s*[.;]", body[m.end(1):]))     # «Reintegrazione …\n.\n\n» (c.c. 332)
        if not (riga.endswith((".", ")")) or riga.endswith("...") or punto_sotto):
            m = None
    if not m:
        m = _RUB_DUE_RIGHE.match(body)
        if m:
            riga = (m.group(1).strip() + " " + m.group(2).strip())
    if not m:
        m = _RUB_RIGA_COMMA.match(body) or _RUB_NUDA.match(body)
        if not m or re.search(r"[.;:,]$", m.group(1).strip()):
            return None
        riga = m.group(1).strip()
    fonte = ""
    f = _RUB_FONTE.match(riga)                          # «Prova del pagamento delle imposte ( articolo 14 d.lgs. 347/1990 )»
    if f and not f.group(1).startswith("("):
        riga, fonte = f.group(1), f.group(2)
    r = riga.rstrip(" .").strip()
    if r.startswith("(") and r.endswith(")") and r.count("(") == 1:
        r = r[1:-1].strip()
    r = re.sub(r"(?:\s*\(\d{1,4}\))+$", "", r).rstrip(" .").strip()   # «Legittimazione ad agire (321)(322)»: note
    if not r or len(r) > 100 or ":" in r or r.count(",") > 3 or not re.match(r"^[A-ZÀ-Ü]", r):
        return None
    w = re.sub(r"[^\wÀ-ÿ']", " ", r.split()[0]).strip().lower().rstrip("'")
    if w in _RUB_STOP or _RUB_VERBI.search(r) or _RUB_NON_RUBRICA.search(r):
        return None
    resto = body[m.end():]
    return r, ((fonte + "\n\n") if fonte else "") + resto.lstrip("\n")


# v9.403 — LE RUBRICHE CHE LE FORME DEL v9.383-384 NON VEDEVANO (misurato: 5.313 articoli IT senza rubrica, ~1.800 con la
# rubrica nella prima riga del testo). Tre forme nuove, provate SOLO quando le altre non trovano nulla:
#   E  i TESTI UNICI della riforma fiscale 2024-2026 (TUIR, accertamento, riscossione, IVA, registro, sanzioni tributarie,
#      giustizia tributaria: ~1.290 articoli): «Dichiarazione fraudolenta mediante uso di fatture…» + riga vuota + la FONTE
#      «( articolo 2 del decreto legislativo n. 74 del 2000 )» (a volte sulla stessa riga, a volte spezzata). La riga della
#      fonte è testo ufficiale del testo unico e resta nel corpo (dice all'avvocato da quale articolo abrogato viene);
#   F  rubrica + riga vuota + comma «1.» (c.p.a., codice doganale nazionale, processo minorile, convenzione Italia-Albania,
#      allegati del codice dei contratti) — la forma «nuda» c'era, ma voleva la maiuscola, non la cifra del comma;
#      anche su DUE righe separate da una riga vuota, la seconda minuscola («Espropriazione od occupazione temporanea» /
#      «di locali per la tutela degli interessi doganali»);
#   H  rubrica FRA PARENTESI spezzata su più righe (regolamento del C.d.S., spese di giustizia): «(Verifiche e prove» /
#      «per l'omologazione delle macchine agricole)».
# In E e H la fonte fra parentesi e le parentesi stesse sono il segnale forte: non si applica il filtro dei verbi («Casi di
# non punibilità» è una rubrica). In F valgono tutti i filtri della forma A.
_RUB_TU_FONTE = re.compile(r"\(\s*(?:articol[oi]|art\.)\s", re.I)
# v9.547 — la riga della FONTE in senso largo: «( articolo …», «( art. …», «( legge 28 febbraio 1985 …», «( Legge 6 marzo 1998 …»,
# «( decreto legislativo …», «( d.lgs. …», «( d.P.R. …», «( R.D. …»
_RUB_FONTE_RIGA = re.compile(r"\(\s*(?:articol[oi]|artt?\.|legge\b|l\.\s|decreto\b|d\.\s?lgs|d\.\s?l\.|d\.\s?p\.\s?r|r\.\s?d\.?\s|regio\s+decreto)",
                             re.I)
_RUB_COMMA_DOPO_VUOTA = re.compile(r"^\s*([^\n]{3,140}?)[ \t\xa0]*\n(?:[ \t\xa0]*\n)+(?=[ \t\xa0]*(?:1\.|1\)|\(1\))[\s\xa0])")
_RUB_DUE_RIGHE_VUOTA = re.compile(r"^\s*([^\n]{3,110}?)[ \t\xa0]*\n(?:[ \t\xa0]*\n)+[ \t\xa0]*([a-zà-ü][^\n]{0,110}?)[ \t\xa0]*\n"
                                  r"(?:[ \t\xa0]*\n)+(?=[ \t\xa0]*(?:1\.|1\)|\(1\))[\s\xa0])")
_RUB_PAREN_RIGHE = re.compile(r"^\s*\(\s*([^()]{3,260}?)\s*\)[ \t\xa0]*\.?[ \t\xa0]*\n(?:[ \t\xa0]*\n)*"
                              r"(?=[ \t\xa0]*(?:1\.|1\)|\(1\)|[A-ZÀ-Ü«\"]))")


# una FONTE fra parentesi in testa al testo non è una rubrica («(Legge 26 giugno 1990, n. 162, artt. 5…)» nel d.P.R. 309/1990)
_RUB_FONTE_NON_RUBRICA = re.compile(r"(?:Legge|Decreto|Regio\s+decreto|D\.\s?[Ll]gs|D\.\s?L\.|d\.\s?l\.|R\.\s?D\.|D\.P\.R|d\.P\.R|"
                                    r"Articol[oi]|Artt?\.|Circolare|Nota|Vedi)\b|[LR](?:\s|$)")   # «(L comma 3 e 4 - R …)» del TU edilizia


_RUB_FONTE_DAVANTI = re.compile(r"^\(?\s*(?P<f>(?:Legge|L\.|D\.\s?L\.|d\.l\.|Decreto|D\.\s?Lgs|d\.lgs|D\.P\.R|d\.P\.R|R\.\s?D|Regio|"
                                r"Artt?\.|articol[oi])\b[^)]{3,300})\)\s*(?P<r>\S.*)$", re.I)


def _prima_parola(r: str) -> str:
    return re.sub(r"[^\wÀ-ÿ']", " ", (r or " ").split()[0] if (r or "").split() else "").strip().lower().rstrip("'")


def _rubrica_ok(r: str, filtri_verbi: bool = True) -> bool:
    if not r or len(r) > 260 or ":" in r or not re.match(r"^[A-ZÀ-Ü]", r):
        return False
    if _RUB_NON_RUBRICA.search(r) or _RUB_FONTE_NON_RUBRICA.match(r):
        return False
    if filtri_verbi:
        w = re.sub(r"[^\wÀ-ÿ']", " ", r.split()[0]).strip().lower().rstrip("'")
        if w in _RUB_STOP or _RUB_VERBI.search(r) or len(r) > 140:
            return False
    return True


def _rubrica_forme_nuove(body: str):
    """(rubrica, corpo) per le forme E, F, H del v9.403, altrimenti None. Si chiama solo se `_rubrica_prima_riga` fallisce."""
    b = (body or "").lstrip()
    righe = b.split("\n")
    # E — testi unici: la fonte «( articolo … )» sulla riga dopo la rubrica (dopo eventuali righe vuote) o sulla stessa riga
    if righe:
        r1 = righe[0].strip()
        j = 1
        while j < len(righe) and not righe[j].strip():
            j += 1
        r2 = righe[j].strip() if j < len(righe) else ""
        # la riga della fonte è SOLO la parentesi (chiusa lì o sulla riga dopo): «(art. 106, n. 8 della legge), è eseguito…» del
        # regolamento notarile è il seguito di una frase, non una fonte
        chiusa = r2.endswith(")") or (j + 1 < len(righe) and righe[j + 1].strip() == ")")
        if r1 and not r1.startswith("(") and _RUB_TU_FONTE.match(r2) and chiusa:
            r = r1.rstrip(" .").strip()
            if _rubrica_ok(r, filtri_verbi=False) and _prima_parola(r) not in _RUB_STOP:
                return r, "\n".join(righe[j:]).strip()
        # v9.547 — le forme della FONTE che la regola sopra non vedeva (92 articoli italiani con la rubrica rimasta nel testo, fra cui
        # la sanatoria edilizia, art. 36 d.P.R. 380/2001): (a) la fonte che comincia con «( legge / ( Legge / ( decreto / ( d.lgs. /
        # ( d.P.R. / ( R.D.» (TU edilizia 36, TU immigrazione 49); (b) la fonte SPEZZATA su più righe, chiusa entro tre righe e solo
        # alla fine di una riga (TUIR 39, TU riscossione 40); (c) la rubrica su DUE righe, la seconda minuscola, sopra la fonte
        # (giustizia tributaria 39: «Ufficio di segreteria …» / «di primo e secondo grado»); (d) la rubrica che comincia con un
        # articolo («La composizione delle corti…»): ammessa solo SENZA verbi. La parentesi della fonte resta il segnale forte.
        def _fonte_chiusa(k):
            # fino a otto righe, anche vuote in mezzo («(Artt. 3, comma 1, … 12,» / «» / «comma 1, 14 …)» delle accise)
            if k >= len(righe) or not _RUB_FONTE_RIGA.match(righe[k].strip()):
                return None
            prof = 0
            for kk in range(k, min(len(righe), k + 8)):
                t = righe[kk].strip()
                # le lettere d'elenco («lettera a)», «lettere b), c)») chiudono una parentesi mai aperta: non contano
                prof += t.count("(") - (t.count(")") - len(re.findall(r"(?<![\w(])[a-z]{1,2}\)", t)))
                if prof <= 0:
                    return kk if t.endswith((")", ").")) else None
            return None
        def _ok_e(r):
            r = r.rstrip(" .").strip()
            if r.startswith("(") and r.endswith(")") and r.count("(") == 1:
                r = r[1:-1].strip()                       # «(Assistenza sanitaria per gli stranieri non iscritti …)»
            if not r or re.search(r"[.;:,]$", r) or len(r) > 160:
                return None
            w = _prima_parola(r)
            if w in _RUB_STOP:
                # l'ARTICOLO in testa («Il ricorso», «Le parti», «La giurisdizione tributaria» — giustizia tributaria): sì, se
                # nella rubrica non c'è un verbo; «Non» solo davanti a un sostantivo («Non imponibilità», «Non riproponibilità»)
                if w in ("il", "lo", "la", "i", "gli", "le", "l") and not _RUB_VERBI.search(r) and len(r) <= 140:
                    return r if _rubrica_ok(r, filtri_verbi=False) else None
                return r if _rubrica_ok(r) else None
            if w == "non" and re.match(r"(?i)non\s+\w+(?:ità|enza|anza|zione|sione|mento)\b", r) and not _RUB_VERBI.search(r[4:]):
                return r if _rubrica_ok(r, filtri_verbi=False) else None
            return r if _rubrica_ok(r, filtri_verbi=False) else None
        # il titolo dell'ATTO e la riga «ART. 1» / «Art. 1.» / il solo numero sopra la rubrica (TUIR 1, TU IVA 1, TU accertamento 1 e 103)
        _salta = 0
        while _salta < len(righe) and (not righe[_salta].strip() or re.fullmatch(
                r"(?i)testo unico\b[^()\n]{0,160}|art\.?\s*\d+[a-z-]*\.?|\d{1,4}(?:-[a-z]+)?", righe[_salta].strip())):
            _salta += 1
        if 0 < _salta < len(righe) and _salta <= 6:
            _sotto = _rubrica_forme_nuove("\n".join(righe[_salta:]))
            if _sotto and _RUB_FONTE_RIGA.match(_sotto[1].lstrip()):
                return _sotto
        if r1 and (not r1.startswith("(") or (r1.endswith(")") and r1.count("(") == 1)):
            if _fonte_chiusa(j) is not None and (_r := _ok_e(r1)):
                return _r, "\n".join(righe[j:]).strip()
            j2 = j + 1
            while j2 < len(righe) and not righe[j2].strip():
                j2 += 1
            if (re.match(r"^[a-zà-ü]", r2) and len(r2) <= 110 and not re.search(r"[.;:,]$", r1)
                    and _fonte_chiusa(j2) is not None and (_r := _ok_e(r1 + " " + r2))):
                return _r, "\n".join(righe[j2:]).strip()
        m = re.match(r"^([^()\n]{3,260}?)\s*(\(\s*(?:articol[oi]|art\.)\s.*)$", r1, re.I)
        if (m and _rubrica_ok(m.group(1).rstrip(" .").strip(), filtri_verbi=False)
                and _prima_parola(m.group(1)) not in _RUB_STOP
                and (m.group(2).rstrip().endswith(")") or (len(righe) > 1 and righe[1].strip().endswith(")")))):
            fonte = m.group(2)
            k = 1
            if ")" not in fonte and len(righe) > 1 and righe[1].strip().endswith(")") and len(righe[1].strip()) <= 60:
                fonte, k = fonte + " " + righe[1].strip(), 2       # «… n. 131 …» / «)» (fonte spezzata, tu_registro 50)
            return m.group(1).rstrip(" .").strip(), (fonte + "\n\n" + "\n".join(righe[k:]).lstrip("\n")).strip()
    # H — rubrica fra parentesi su più righe
    m = _RUB_PAREN_RIGHE.match(b)      # (anche su una riga oltre i 140 caratteri: spese di giustizia 115-bis)
    if m:
        r = " ".join(m.group(1).split()).rstrip(" .")
        if _rubrica_ok(r, filtri_verbi=False):
            return r, b[m.end():].strip()
    # F — rubrica su due righe separate da una riga vuota, poi il comma «1.»
    m = _RUB_DUE_RIGHE_VUOTA.match(b)
    if m and not re.search(r"[.;:,]$", m.group(1).strip()):
        r = (m.group(1).strip() + " " + m.group(2).strip()).rstrip(" .")
        if _rubrica_ok(r):
            return r, b[m.end():].strip()
    # F — rubrica su una riga, riga vuota, comma «1.»
    m = _RUB_COMMA_DOPO_VUOTA.match(b)
    if m and not re.search(r"[.;:,]$", m.group(1).strip()):
        r = m.group(1).strip()
        if _rubrica_ok(r):
            return r, b[m.end():].strip()
    return None


# v9.405 — nel testo unico delle successioni (d.lgs. 346/1990) ogni articolo porta SOPRA la rubrica la sua fonte nel vecchio
# d.P.R. 637/1972 («Art. 2 D.P.R. n. 637/1972», «Artt. 13, commi 1 e 2, e 14 D.P.R. n. 637/1972 - Art. 7 legge n. 880/1986»,
# «Disposizione nuova»), e l'ingest la leggeva come rubrica: la vera rubrica («Territorialità dell'imposta») restava prima riga
# del testo. Col testo vigente riallineato (fino a v9.404 c'era solo la nota «ARTICOLO ABROGATO…») il caso è comparso.
_FONTE_SOPRA = re.compile(r"^(?:Artt?\.\s*\d.*?(?:D\.\s?P\.\s?R\.|[Ll]egge|D\.\s?L\.|D\.\s?[Ll]gs\.?)\s*(?:n\.\s*)?\d+\s*/\s*\d{2,4}\b.*"
                          r"|Disposizione nuova\.?)$")


def _pulisci(heading: str, body: str) -> tuple[str, str]:
    h, b = heading or "", body or ""
    # v9.540 — il TRATTINO MORBIDO (U+00AD) di Normattiva: «comma 3­bis» (TU riscossione, CAD) — fra un numero e il suffisso vale
    # «-», altrove si toglie; e i caratteri a larghezza zero
    h, b = (re.sub(r"[​-‍⁠﻿]", "", re.sub(r"(?<=\d)­(?=[a-z])", "-", x).replace("­", ""))
            for x in (h, b))
    # v9.551 — l'A CAPO davanti a una virgola o a un punto e virgola: lo lascia l'ingest dove toglie i segni del testo modificato
    # («figli ((legittimi))\n, il coniuge…», «ascendenti ((...))\n, fratelli e sorelle»): 1.357 articoli IT, 54 senza rubrica per
    # questo (c.c. 582 «Concorso del coniuge con ascendenti, fratelli e sorelle»). Si riunisce la riga; l'omissione «((...))» subito
    # prima della virgola si toglie (è il testo soppresso, non c'è più)
    # (anche col DOPPIO a capo: «… materiale analogo di natura sessuale\n\n, all'accattonaggio» — c.p. 600, reg. C.d.S.)
    # (e col segno che si RIAPRE prima della virgola: «sessuale))\n\n((, all'accattonaggio»)
    b = re.sub(r"[ \t]*(?:\(\(\s*)?\.\.\.(?:\s*\)\))?[ \t]*(?=(?:\n[ \t]*)+(?:\(\(\s*)?[,;])", "", b)
    b = re.sub(r"[ \t]*(?:\n[ \t]*)+(?=(?:\(\(\s*)?[,;])", "", b)
    _hs = re.sub(r"\s+", " ", re.sub(r"\(\(|\)\)", " ", h)).strip()
    _fonte_fatta = False
    if _hs and _FONTE_SOPRA.match(_hs):
        _fonte_fatta = True             # la fonte messa in testa al testo non va poi riletta come rubrica fra parentesi
        # nel testo unico delle accise (d.lgs. 504/1995) la rubrica sta nella stessa riga DOPO la fonte: «Artt. 22 e 23 D.L. n.
        # 271/1957 ) Obbligazione civile dell'esercente…» → la rubrica è dopo l'ultima parentesi chiusa
        _mr = re.match(r"^(?P<f>.+\d)\s*\)\s*\.?\s*(?P<r>[A-ZÀ-Ü][^()]{2,})$", _hs)
        if _mr and _rubrica_ok(_mr.group("r").strip(" ."), filtri_verbi=False):
            h, b = _mr.group("r").strip(" ."), "(" + _mr.group("f").strip(" (") + ")\n\n" + b
        else:
            _b2 = re.sub(r"\(\(|\)\)", "", b).strip()
            rp = _rubrica_prima_riga(_b2) or _rubrica_forme_nuove(_b2)
            if rp and not _FONTE_SOPRA.match(rp[0].strip()):
                h, b = rp[0], "(" + _hs + ")\n\n" + rp[1]
            else:
                h, b = "", "(" + _hs + ")\n\n" + b
    if not h.strip():
        m = _RUB_IN_BODY.match(b)
        if m:
            h, b = m.group(1), b[m.end():]
    h = re.sub(r"\(\(|\)\)", " ", h)
    h = re.sub(r"\s+", " ", h).strip().strip(" ()").rstrip(".").strip(" ()")
    # v9.384 — TFUE/TUE: la «rubrica» è la nota di corrispondenza «(ex articolo 234 del TCE)», non un titolo: va in testa al
    # testo (ai giuristi serve la vecchia numerazione) e la rubrica resta vuota, come nel trattato
    if re.fullmatch(r"ex\s+articol[oi]\b.*", h, re.I):
        b, h = "(" + h + ")\n" + b, ""
    # «((13))» = numero della nota di aggiornamento, non testo normativo: nel corpus restava un
    # «13» a sé su una riga (e faceva risultare «diverso» un testo storico identico — v9.336)
    b = re.sub(r"\(\(\s*\d{1,3}\s*\)\)", " ", b)
    b = re.sub(r"\(\(\s*", "", b)
    b = re.sub(r"\s*\)\)", "", b)
    b = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", b)
    # v9.384 — «… della presente Convenzione. TITOLO I DIRITTI E LIBERTÀ»: l'intestazione del titolo SEGUENTE incollata in
    # coda all'articolo (CEDU artt. 1, 18, 51; nel corpus IT non succede altrove — misurato): non è testo dell'articolo
    b = re.sub(r"(?<=[.;:])\s+(?:PARTE|TITOLO|CAPO|SEZIONE|SOTTOSEZIONE)\s+(?:[IVXLC]+|\d+)\b(?:\s+[A-ZÀ-Ü’'«»,\-]+)+\s*$", "", b)
    if not h.strip() and not _fonte_fatta:              # dopo la pulizia dei «((…))»: «(( (Competenza …).» c.p.p. 11
        rp = _rubrica_prima_riga(b.strip()) or _rubrica_forme_nuove(b.strip())
        if rp:
            h, b = rp
    # v9.404 — nel testo unico degli stupefacenti (d.P.R. 309/1990) la rubrica porta DAVANTI la fonte: «Legge 26 giugno 1990,
    # n. 162 , articoli 14, comma 1, e 38, comma 2) Associazione finalizzata al traffico illecito…» (107 articoli): la rubrica è
    # dopo la parentesi, la fonte va in testa al testo come nei testi unici fiscali
    # v9.404 — i marcatori «(L)»/«(R)» (norma di legge / di regolamento) dei testi unici del 2000-2002 finivano in testa alla
    # rubrica: «L) Condizioni per l'ammissione» (spese di giustizia 76)
    h = re.sub(r"^\(?[LR]\)\s+(?=[A-ZÀ-Ü])", "", h)
    mf = _RUB_FONTE_DAVANTI.match(h)
    if mf and len(mf.group("r").strip()) >= 3 and _rubrica_ok(mf.group("r").strip(" ."), filtri_verbi=False):
        b = "(" + mf.group("f").strip() + ")\n\n" + b.strip()
        h = mf.group("r").strip(" .")
    # v9.409 — il testo MODIFICATO per intero comincia con «((»: il riconoscimento della rubrica fra parentesi del formato
    # «allegato» (c.c., disp. att., C.N.) prendeva TUTTO il testo come rubrica e il corpo restava «)» (c.c. 148 «I coniugi devono
    # adempiere…», disp. att. c.c. 32, 33, 60-bis, 60-ter). Corpo senza testo + rubrica lunga che non è il nome di un allegato →
    # il testo torna nel corpo; «Rubrica). 1. Testo…» si divide. Solo se nel corpo non resta NESSUNA lettera: un corpo corto
    # vero («1. L'Agenzia…») sotto una rubrica lunga resta com'è.
    if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", b)) < 3 and len(h) > 60 and not re.match(r"(?i)(allegat|tabell|tariff|prospett)", h):
        mm = re.match(r"^(?P<r>[^()]{3,120}?)\)\.?\s+(?P<t>(?:\d+\.\s+)?[A-ZÀ-Ü].+)$", h, re.S)
        if mm and _rubrica_ok(mm.group("r").strip(" ."), filtri_verbi=False):
            h, b = mm.group("r").strip(" ."), mm.group("t").strip()
        else:
            h, b = "", h.rstrip(" .") + "."
    # v9.546 — i RESIDUI della rubrica fra parentesi in testa al corpo: «) Il coniuge dell'assente…» (c.c. 51), «) . I minori di età…»
    # (c.c. 84), «. La riduzione della donazione…» (c.c. 563), «) ). Chiunque…» (c.p. 316-bis): 537 articoli italiani su 24.871, e il
    # blocco del cervello li mostrava così. Solo parentesi chiuse e punti SINGOLI in testa: «...» (un'omissione del testo ufficiale)
    # e «, e 2436…» (un taglio vero) restano come sono
    b = re.sub(r"^\s*(?:[)\]]\s*)+(?:\.(?!\.)\s*)*", "", b)
    b = re.sub(r"^\s*\.(?!\.)\s+(?=[A-ZÀ-Ü0-9«(\"])", "", b)
    return h, b.strip()

# v9.413 — IMPORTI IN LIRE ancora nel testo vigente (339 articoli di 48 atti: c.p. 103, codice della navigazione 62, L. 689/1981 19,
# armi, TULPS, imposta di registro…): Normattiva lascia la cifra originaria. Valgono in euro al tasso fisso (verificati sulle fonti
# ufficiali il 30 set 2026: 1 euro = 1.936,27 lire, Reg. (CE) 2866/98; art. 14 Reg. (CE) 974/98 per ogni riferimento alla lira;
# art. 51 d.lgs. 213/1998 per le sanzioni penali e amministrative, dal 1° gennaio 2002, «eliminando i decimali»). La nota la scrive il
# CODICE con gli importi convertiti, dichiarata come nostra: il modello non converte a memoria e non cita «lire» come se valessero.
_LIRE_RX = re.compile(r"(?i)\blire\s+(\d{1,3}(?:\.\d{3})+|\d{4,})(?![,.]\d|\s*/)"
                      r"|\bL\.\s*(\d{1,3}(?:\.\d{3})+)(?![,.]?\d|\s*/)"
                      r"|\b(\d{1,3}(?:\.\d{3})+)\s+lire\b"
                      r"|\blire\s+([a-zàèéìòù]*(?:mila|mille|cento|milioni|milione)[a-zàèéìòù]*)\b")
_TASSO_LIRA = 1936.27
# una PENA o una SANZIONE in lire non si converte direttamente (art. 113-114 L. 689/1981, artt. 24 e 26 c.p.): lo si riconosce dalle
# parole vicine all'importo
_FINE_FRASE_RX = re.compile(r"[.;:]\s+(?=[A-ZÀ-Ü0-9(«\"])|\n")
_SANZIONE_RX = re.compile(r"(?i)multa|ammenda|pena pecuniaria|pene pecuniarie|sanzion|punit|oblazione|cauzione|somma di denaro")
_UNITA_IT = {"zero": 0, "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8,
             "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15, "sedici": 16,
             "diciassette": 17, "diciotto": 18, "diciannove": 19, "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50,
             "sessanta": 60, "settanta": 70, "ottanta": 80, "novanta": 90}
_DECINE_IT = {k: v for k, v in _UNITA_IT.items() if v >= 20}


def _sotto_mille(t: str):
    if not t:
        return 0
    n = 0
    if "cento" in t:
        a, _, t = t.partition("cento")
        c = _UNITA_IT.get(a, None) if a else 1
        if c is None or c > 9:
            return None
        n += c * 100
    if not t:
        return n
    if t in _UNITA_IT:
        return n + _UNITA_IT[t]
    for d in sorted(_DECINE_IT, key=len, reverse=True):
        for rad in (d, d[:-1]):                      # «ventuno», «trentotto»: la vocale cade
            if t.startswith(rad) and (t[len(rad):] in _UNITA_IT and _UNITA_IT[t[len(rad):]] < 10):
                return n + _DECINE_IT[d] + _UNITA_IT[t[len(rad):]]
    return None


def numero_in_lettere(t: str):
    """«trentamila» → 30000, «duecentocinquantamila» → 250000, «un milione» → None (parole separate: si lascia)."""
    t = (t or "").lower().strip()
    n = 0
    for sep, mult in (("milioni", 10 ** 6), ("milione", 10 ** 6)):
        if sep in t:
            a, _, t = t.partition(sep)
            v = _sotto_mille(a) if a not in ("un", "") else 1
            if v is None:
                return None
            n += v * mult
    if "mila" in t:
        a, _, t = t.partition("mila")
        v = _sotto_mille(a)
        if v is None:
            return None
        n += v * 1000
    elif t.startswith("mille"):
        n += 1000
        t = t[5:]
    v = _sotto_mille(t)
    return None if v is None else n + v


def _euro(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s[:-3] if s.endswith(",00") else s


def _nota_lire(body: str) -> str:
    importi, sanzioni = [], False
    for m in _LIRE_RX.finditer(body or ""):
        raw = m.group(1) or m.group(2) or m.group(3)
        n = int(raw.replace(".", "")) if raw and raw.replace(".", "").isdigit() else numero_in_lettere(m.group(4) or "")
        if not n or n < 100:
            continue
        # la FRASE che contiene l'importo: «è punito con l'ammenda da lire …» → sanzione. Il punto delle migliaia («300.000»)
        # non chiude la frase: solo «. Maiuscola», «;» o l'a capo
        _b = body or ""
        inizio = max([x.end() for x in _FINE_FRASE_RX.finditer(_b, 0, m.start())] or [0])
        fine_m = _FINE_FRASE_RX.search(_b, m.end())
        fine = fine_m.start() if fine_m else len(_b)
        if _SANZIONE_RX.search(_b[max(inizio, m.start() - 220):min(fine, m.end() + 60)]):
            sanzioni = True
            continue
        if n not in [x for x, _ in importi]:
            importi.append((n, n / _TASSO_LIRA))
    parti = []
    if sanzioni:
        parti.append("le PENE e le SANZIONI pecuniarie in lire di questo articolo NON si convertono direttamente: prima si applicano "
                     "gli aumenti dell'art. 113 L. 24 novembre 1981, n. 689 (per il codice penale e le leggi speciali: per cinque gli "
                     "importi già aumentati dalla L. 12 luglio 1961, n. 603 e quelli delle leggi 1947-1961, per tre 1961-1970, per due "
                     "1971-1975; per le sanzioni amministrative art. 114) e i minimi (multa non inferiore a euro 50 e ammenda a euro 20, "
                     "artt. 24 e 26 c.p.), poi la conversione al tasso di 1 euro = 1.936,27 lire eliminando i decimali (art. 51 d.lgs. "
                     "24 giugno 1998, n. 213). Calcola l'importo vigente con queste norme; verifica se una legge successiva lo ha fissato "
                     "in euro")
    if importi:
        righe = "; ".join(f"lire {n:,}".replace(",", ".") + f" = euro {_euro(e)}" for n, e in importi[:8])
        parti.append(("gli altri importi" if sanzioni else "gli importi") + " in lire valgono in euro al tasso fisso di 1 euro = 1.936,27 lire (art. 14 Reg. (CE) n. "
                     "974/1998): " + righe + ". Verifica che una legge successiva non li abbia aggiornati o fissati in euro")
    if not parti:
        return ""
    return "Nota di collegamento (redazionale, non del testo ufficiale): " + ". Inoltre, ".join(parti) + "."


def _nota_con_lire(nota: str, body: str, abrogato: bool) -> str:
    """La nota dell'atto (se c'è) e, per un articolo vigente con importi in lire, la conversione. Una nota che già parla della
    conversione (tariffe del bollo e delle imposte ipotecarie, v9.409) resta sola."""
    if abrogato or re.search(r"(?i)1\.936,27|euro\s+(?:2,00|16,00|200)\b", nota or ""):
        return nota
    nl_ = _nota_lire(body)
    return (nota + "\n" + nl_).strip() if nl_ else nota


SRC = Path("/app/data/processed/it_acts")
JSONL = Path("/app/data/processed/all_articles_it.jsonl")
CODES_META = Path("/app/data/processed/it_codes.json")
INDEX = Path("/app/data/index/bm25_it.pkl")

# display order: fundamentals first, then by area
ORDER = ["costituzione", "codice_civile", "preleggi", "disp_att_cc", "codice_procedura_civile", "disp_att_cpc",
         "codice_penale", "codice_procedura_penale", "disp_att_cpp",
         "codice_strada", "regolamento_strada", "codice_consumo", "codice_crisi_impresa",
         "ordinamento_polizia", "tulps", "statuto_lavoratori", "sicurezza_lavoro",
         "tu_bancario", "tu_finanza", "codice_proprieta_industriale", "codice_terzo_settore",
         "codice_assicurazioni", "responsabilita_enti", "procedimento_amministrativo",
         "codice_processo_amministrativo", "codice_amministrazione_digitale",
         "tu_documentazione_amministrativa", "codice_contratti_pubblici",
         "sanzioni_amministrative", "tu_spese_giustizia", "codice_privacy",
         "codice_ambiente", "tu_edilizia", "tu_immigrazione", "codice_antimafia",
         "tuir", "codice_beni_culturali", "codice_navigazione", "stupefacenti",
         "ordinamento_penitenziario", "codice_pari_opportunita", "codice_protezione_civile",
         "divorzio", "adozione", "equa_riparazione", "antiriciclaggio",
         # wave5 (16 set 2026) — dogana/tributario, notarile, procedura, lavoro, altro
         "codice_doganale_nazionale", "codice_doganale_ue", "reg_ue_2015_2446", "reg_ue_2015_2447",
         "accise", "iva", "imposta_registro", "imposta_successioni", "sanzioni_tributarie",
         "giustizia_tributaria", "statuto_contribuente", "accertamento_imposte", "riscossione",
         "reati_tributari", "legge_notarile", "legge_52_1985", "condono_edilizio",
         "immobili_da_costruire", "successioni_ue", "locazioni_abitative", "locazioni_immobili_urbani",
         "mediazione_civile", "riti_civili_semplificati", "bruxelles_i_bis", "roma_i", "roma_ii",
         "bruxelles_ii_ter", "ordinamento_forense", "licenziamenti_individuali", "tutele_crescenti",
         "responsabilita_sanitaria", "regolamento_immigrazione", "tuel", "processo_penale_minorile",
         "codice_nautica_diporto", "gdpr",
         # wave6 (16 set 2026) — testi unici della riforma fiscale (sostituiscono gli atti abrogati)
         "tu_sanzioni_tributarie", "tu_riscossione", "tu_registro", "tu_iva", "tu_accertamento",
         # wave7 «blocco A» (16 set 2026)
         "diritto_internazionale_privato", "cittadinanza", "regolamento_cittadinanza", "cittadini_ue",
         "protezione_internazionale", "contratti_lavoro", "orario_lavoro", "maternita_paternita",
         "legge_biagi", "pubblico_impiego", "negoziazione_assistita", "giudice_pace_penale",
         "mandato_arresto_europeo", "casellario", "unioni_civili", "consenso_informato_dat",
         "regolamento_notarile", "prestazione_energetica", "legge_urbanistica", "armi",
         "regolamento_penitenziario",
         "tfue", "tue", "carta_diritti_ue", "codice_frontiere_schengen", "reg_ue_2018_1806",
         "codice_visti", "roma_iii", "alimenti_ue", "regimi_patrimoniali_ue", "ingiunzione_europea",
         "small_claims_ue", "notifiche_ue",
         # wave8 «blocco B»: trattati
         "convenzione_it_al_fisco", "protocollo_it_al_migranti", "cedu", "cedu_protocollo_1",
         "cedu_protocollo_4", "cedu_protocollo_6", "cedu_protocollo_7", "cedu_protocollo_12",
         "cedu_protocollo_13", "cedu_protocollo_16"]


def _as_bool(v) -> bool:
    # La prima ingestione EUR-Lex (16 set 2026) scriveva str(bool): bool("False")
    # e' True -> 1.342 articoli UE «abrogati» e invisibili al BM25 (search() li
    # salta). Qui una stringa vale solo se dice davvero «true».
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "si", "sì")
    return bool(v)


GER = Path("/app/data/processed/it_gerarchia")


def _gerarchia(cid: str):
    """v9.383 — Libro / Titolo / Capo / Sezione di ogni articolo, raccolti dall'albero di Normattiva da tools/it_gerarchia.py
    (una mappa per atto). Ritorna l'indice pronto per `it_gerarchia.voce` (stessa regola del controllo di copertura), o None."""
    f = GER / f"{cid}.json"
    if not f.exists():
        return None
    try:
        m = json.loads(f.read_text(encoding="utf-8")).get("map") or {}
    except Exception:  # noqa: BLE001
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from it_gerarchia import prepara
    return prepara({tuple(k.split("|", 1)): v for k, v in m.items()})


def main():
    files = sorted(SRC.glob("*.json"))
    if not files:
        print("nessun atto scaricato — esco")
        return 1
    acts = {}
    for f in files:
        try:
            acts[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! {f.name} illeggibile: {e}")
    ordered = [c for c in ORDER if c in acts] + [c for c in sorted(acts) if c not in ORDER]

    all_articles, meta = [], []
    vigenze: dict = {}            # v9.405: code -> number -> {fino, dal, futuro_abrogato, futuro_rubrica, futuro_testo, non_in_vigore_dal}
    notes_map: dict = {}          # code -> number -> [note] (per src/temporal.py: storia + transitori)
    ger_ok = ger_tot = 0
    senza_testo = 0
    for cid in ordered:
        a = acts[cid]
        arts = a.get("articles") or []
        _ger = _gerarchia(cid)
        if not arts:
            print(f"  ! {cid}: 0 articoli — escluso")
            continue
        for art in arts:
            # v9.405 — VIGENZA: il JSON riallineato (tools/riallinea_vigenti_it.py) porta il testo di OGGI e, in `futuro`, la
            # versione che entra in vigore più avanti con la sua data. Al build si usa quella giusta per la data di oggi; le date
            # vanno nella mappa (`_vigenze`) perché verificatore e blocco degli articoli ragionino anche prima di un nuovo build.
            _fu = art.get("futuro") if isinstance(art.get("futuro"), dict) else None
            _oggi_iso = time.strftime("%Y-%m-%d")
            if _fu and (_fu.get("dal") or "9999") <= _oggi_iso:
                art = dict(art, heading=_fu.get("heading") or "", body=_fu.get("body") or "", repealed=_fu.get("repealed"))
                _fu = None
            _nv = art.get("non_in_vigore_dal")
            if _fu and _as_bool(art.get("repealed")) and _as_bool(_fu.get("repealed")):
                _fu = None          # abrogato oggi e abrogato dopo (d.lgs. 74/2000 art. 7, dal 2015): nessuna vigenza da dire
            if _fu or (_nv and _nv > _oggi_iso):
                _hf, _bf = _pulisci((_fu or {}).get("heading") or "", (_fu or {}).get("body") or "")
                vigenze.setdefault(cid, {})[str(art["number"])] = {
                    "fino": art.get("vigente_fino") or "", "dal": (_fu or {}).get("dal") or "",
                    "futuro_abrogato": bool((_fu or {}).get("repealed")), "futuro_rubrica": _hf[:120],
                    "futuro_testo": ("" if (_fu or {}).get("repealed") else _bf[:600]),
                    "non_in_vigore_dal": _nv if (_nv and _nv > _oggi_iso) else ""}
            _h, _b = _pulisci(art.get("heading") or "", art.get("body") or "")
            # v9.409 — pagine che sono solo un'etichetta («Tabella 1», «Allegato III-bis», «[senza testo]»: il contenuto è
            # un'immagine): nell'indice rispondevano alle ricerche su «tabella/allegato» senza dire niente
            if not _as_bool(art.get("repealed")) and re.fullmatch(
                    r"(?i)\[senza testo\]|(?:tabella|allegato|tariffa|prospetto)(?:\s+[\w.\-]{1,12})?\.?", _b.strip()):
                senza_testo += 1
                continue
            # P3b-IT (16 set 2026): la data dell'ultima modifica per articolo dalle note di
            # aggiornamento Normattiva (vedi normattiva_lib.parse_notes), quando l'atto le ha
            _notes = [n for n in (art.get("notes") or []) if isinstance(n, dict)]
            _lad = max((n.get("date") or "" for n in _notes), default="")
            if _notes:
                notes_map.setdefault(cid, {})[str(art["number"])] = [
                    {"n": n.get("n"), "date": n.get("date") or "", "acts": [x.get("label") for x in (n.get("acts") or [])][:3],
                     "text": (n.get("text") or "")[:600]} for n in _notes[:6]]
            _gv = ["", "", ""]
            if _ger is not None:
                from it_gerarchia import voce as _ger_voce
                _gv = _ger_voce(_ger, art["number"], art.get("group")) or ["", "", ""]
            ger_tot += 1; ger_ok += 1 if any(_gv) else 0
            all_articles.append(Article(
                code=cid, title_sq=a["title"], area=a.get("area") or "",
                number=art["number"], heading=_h, body=_b,
                pjesa=_gv[0], kreu=_gv[1], seksioni=_gv[2],
                repealed=_as_bool(art.get("repealed")), volatility="STABLE",
                last_amendment_date=_lad,
                # v9.401: una nota di collegamento NOSTRA (dichiarata come tale) viaggia col testo ufficiale — es. l'art. 3
                # L. 742/1969 richiama gli artt. 429 e 459 c.p.c. nella numerazione anteriore al 1973
                note=_nota_con_lire(art.get("note") or "", _b, _as_bool(art.get("repealed")))))
        meta.append({"code": cid, "title": a["title"], "area": a.get("area") or "",
                     "count": len(arts)})
        print(f"  {cid:34s} {len(arts):>5} art   {a['title'][:46]}")

    print(f"\nTOTALE: {len(all_articles)} articoli su {len(meta)} corpora · con capitolo (Titolo/Capo/Sezione): {ger_ok}/{ger_tot}"
          f" · pagine senza testo escluse: {senza_testo}")
    # v9.403 — le CORRISPONDENZE vecchio articolo → articolo del testo unico, dalle righe di fonte dei testi unici fiscali
    # («( articolo 8 del decreto legislativo n. 74 del 2000 )»): il verificatore dice dove sta oggi una norma abrogata
    from src import corrispondenze_tu as _ctu
    _corr = _ctu.costruisci(all_articles, urns={cid: (acts[cid].get("urn") or "") for cid in acts})
    _corr["_vigenze"] = vigenze
    print(f"vigenze (testo che cambia o si abroga più avanti): {sum(len(v) for v in vigenze.values())} articoli in {len(vigenze)} atti")
    _atti_corr = {k: v for k, v in _corr.items() if not k.startswith("_")}
    _n_corr = sum(len(v) for v in _atti_corr.values())
    print(f"corrispondenze dei testi unici: {len(_atti_corr)} atti di origine, {_n_corr} articoli vecchi → "
          + ", ".join(f"{_ctu.etichetta_atto(k)} {len(v)}" for k, v in sorted(_atti_corr.items(), key=lambda kv: -len(kv[1]))[:8]))
    print(f"decorrenza dei testi unici: {_corr.get('_decorrenza')} · atti: {_corr.get('_atto_tu')}")
    # v9.383 — indice di PROVA: IT_INDEX_OUT=/percorso scrive SOLO il pickle lì (niente jsonl, meta, note: la produzione non si tocca)
    _test_out = os.environ.get("IT_INDEX_OUT", "").strip()
    if _test_out:
        ArticleIndex.build(all_articles, lang="it").save(Path(_test_out))
        _co = Path(_test_out).with_name("it_corrispondenze.json")
        _co.write_text(json.dumps(_corr, ensure_ascii=False), encoding="utf-8")
        print(f"indice di PROVA scritto in {_test_out} (+ {_co.name}; produzione intatta)")
        return 0

    # backup previous index before overwriting
    if INDEX.exists():
        bak = INDEX.with_suffix(f".pkl.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(INDEX, bak)
        print(f"backup indice precedente -> {bak.name}")

    with JSONL.open("w", encoding="utf-8") as fh:
        for a in all_articles:
            fh.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    CODES_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    _ctu.FILE.write_text(json.dumps(_corr, ensure_ascii=False), encoding="utf-8")
    NOTES = CODES_META.parent / "it_notes.json"
    NOTES.write_text(json.dumps(notes_map, ensure_ascii=False), encoding="utf-8")
    n_notes = sum(len(v) for v in notes_map.values())
    ArticleIndex.build(all_articles, lang="it").save(INDEX)
    print(f"scritto: {JSONL.name}, {CODES_META.name}, {INDEX.name}, {NOTES.name} ({n_notes} articoli con note)")

    # sanity: reload and spot-check
    idx = ArticleIndex.load(INDEX)
    print(f"reload OK: {len(idx.articles)} articoli, lang={getattr(idx, 'lang', '?')}")
    by = {(a.code, a.number): a for a in idx.articles}
    checks = [("codice_civile", "2043"), ("codice_penale", "575"),
              ("codice_procedura_civile", "163"), ("codice_procedura_penale", "273"),
              ("costituzione", "21"), ("codice_strada", "186"), ("codice_strada", "142"),
              ("codice_consumo", "33"), ("codice_crisi_impresa", "2"),
              ("statuto_lavoratori", "18"), ("codice_privacy", "1")]
    for code, n in checks:
        a = by.get((code, n))
        print(f"  {code} art.{n}: " + (f"{(a.heading or a.body[:44])[:50]!r}" if a else "MANCANTE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
