#!/usr/bin/env python3
"""v9.392 — LE LISTE DELLE SOSTANZE della ligji 7975/1995 (Shqipëri) → data/processed/al_lista_narkotike.json.

Perché: il KP 283-284/c punisce le «substanca narkotike dhe psikotrope» e la 7975 (neni 4, 7, 103) dice quali sono: quelle
delle liste della Convenzione unica del 1961 (narkotike) e della Convenzione del 1971 (psikotrope), allegate alla legge; le
«lëndë të kontrolluara» (neni 2: NON narkotike né psikotrope) stanno nella Lista A. Nel .docx consolidato di QBZ quelle
liste sono 16 IMMAGINI (tabelle: Kodi IDS · Numri CAS · nome · altri nomi · nome chimico); in testo ci sono solo la Lista A
e le aggiunte della ligji 17/2026 (l'unità «shtojca» del corpus).

Come: le immagini si estraggono dal .docx nell'ordine del documento, ognuna si legge col lettore di immagini del prodotto
(`backend.ocr_image`, righe «TITLE:» / «ROW: IDS | CAS | nome | altri nomi»; la colonna del nome chimico NON si trascrive:
non serve a riconoscere una sostanza ed è dove si sbaglia), la lista corrente passa da una pagina all'altra finché un nuovo
titolo non la cambia, e ogni numero CAS si controlla con la sua cifra di controllo (una cifra letta male non passa). Le
letture restano in cache (`data/cache/ocr_liste_al/<sha1>.txt`): rilanciare non rilegge. Poi la parte in testo dallo
«shtojca» del corpus (Lista A + aggiunte 17/2026 con la data). Cancello: ≥ 4 liste, ≥ 200 sostanze, CAS sbagliati < 3 %.
Da rilanciare quando QBZ pubblica un consolidato nuovo della 7975 (la freschezza lo segnala). Nel container:

    python3 /app/tools/ingest_liste_narkotike_al.py [--docx PATH] [--out PATH] [--only N] [--dry]
"""
import hashlib
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, "/app")

DOCX = Path("/app/data/raw/al_qbz/ligji_lendet_narkotike.docx")
OUT = Path("/app/data/processed/al_lista_narkotike.json")
CACHE = Path("/app/data/cache/ocr_liste_al")
JSONL = Path("/app/data/processed/all_articles.jsonl")

PROMPT = (
    "This image is a page of the annex to Albanian Law no. 7975/1995 on narcotic, psychotropic and controlled substances: "
    "one or more tables of substances (the lists of the UN 1961 Single Convention on Narcotic Drugs, of the 1971 Convention "
    "on Psychotropic Substances, or national lists).\n"
    "Transcribe it EXACTLY, using ONLY these line formats:\n"
    "TITLE: <every table/list title printed on the page, exactly as printed, e.g. «Lista I e Konventës Unike për Lëndët "
    "Narkotike e vitit 1961»>\n"
    "ROW: <Kodi IDS> | <Numri CAS> | <substance name column> | <other names column>\n"
    "NOTE: <a footnote or note printed under or between the tables>\n"
    "Rules for ROW: copy codes, CAS numbers and names character by character (hyphens, digits, commas, parentheses, "
    "letters written as words like ALPHA, BETA, and lowercase prefixes like N-, α- as printed); an empty cell or a dash is "
    "written -; if the table has no 'other names' column write - in that position; NEVER transcribe the chemical-name / "
    "description column; a row whose name wraps on two lines is ONE row; skip the header row of the table. "
    "Keep the order of the page. No commentary, no markdown."
)
CODA = "Read this file and return ONLY the TITLE/ROW/NOTE lines described above."

_ROMANI = {"I": "I", "II": "II", "III": "III", "IV": "IV"}
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_IDS = re.compile(r"^[A-Z]{2}\s?\d{3}$")


def cas_ok(cas: str) -> bool:
    """La cifra di controllo del numero CAS: somma delle cifre (esclusa l'ultima) pesate 1, 2, 3… da destra, modulo 10."""
    if not _CAS.match(cas or ""):
        return False
    d = cas.replace("-", "")
    corpo, ctrl = d[:-1], int(d[-1])
    return sum(int(c) * (i + 1) for i, c in enumerate(reversed(corpo))) % 10 == ctrl


def chiave_lista(titolo: str) -> str | None:
    t = re.sub(r"\s+", " ", titolo or "")
    if re.search(r"\b(?i:List(?:a|ës|ën))\s+A\b", t):
        return "A"
    m = re.search(r"\b(?i:List(?:a|ës|ën)|Tabel(?:a|ës|ën))\s+(IV|III|II|I)\b", t)
    if not m:
        return None
    r = m.group(1)
    if re.search(r"1988|Prekursor|Tabel", t, re.I):          # la Convenzione del 1988 nomina narcotici E psicotropi
        return f"1988-{r}"
    if re.search(r"1971|Psikotrop", t, re.I) and not re.search(r"1961|Unike", t, re.I):
        return f"1971-{r}"
    if re.search(r"1961|Unike|Narkotik", t, re.I):
        return f"1961-{r}"
    return None


def immagini(docx: Path) -> list[tuple[str, bytes]]:
    """Le immagini nell'ordine in cui compaiono nel documento (rId → media)."""
    with zipfile.ZipFile(docx) as z:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        mappa = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="(media/[^"]+)"', rels))
        mappa.update({k: v for v, k in re.findall(r'Target="(media/[^"]+)"[^>]*Id="(rId\d+)"', rels)})
        doc = z.read("word/document.xml").decode("utf-8")
        ordine = []
        for rid in re.findall(r'r:embed="(rId\d+)"', doc):
            if rid in mappa and mappa[rid] not in [o for o, _ in ordine]:
                ordine.append((mappa[rid], z.read("word/" + mappa[rid])))
        return ordine


def leggi(backend, nome: str, dati: bytes) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha1(dati).hexdigest()
    f = CACHE / f"{sha}.txt"
    if f.exists() and f.stat().st_size > 50:
        return f.read_text(encoding="utf-8")
    img = CACHE / f"{sha}{Path(nome).suffix or '.jpg'}"
    img.write_bytes(dati)
    ultimo = ""
    for tentativo in range(3):
        try:
            testo = backend.ocr_image(img, "image/jpeg", PROMPT, istruzione_finale=CODA)
            if testo.count("ROW:") >= 3 or re.search(r"GRUPI\s+I", testo):
                f.write_text(testo, encoding="utf-8")
                return testo
            ultimo = testo or ultimo
            print(f"  {nome}: lettura povera ({testo.count('ROW:')} righe), riprovo", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  {nome}: lettura fallita ({exc}), riprovo", flush=True)
        time.sleep(10 * (tentativo + 1))
    # una pagina SENZA tabelle di sostanze (lo schema dei gruppi I-III, trascritto nell'unità «skema» del corpus e in
    # `src/narkotike_al.py`): tre letture concordi → si tiene, così un nuovo giro non la rilegge
    if ultimo.strip():
        f.write_text(ultimo, encoding="utf-8")
    return ultimo


def righe_da_ocr(testo: str, lista: str | None, pagina: int) -> tuple[list[dict], str | None, list[str]]:
    out, titoli = [], []
    for riga in (testo or "").splitlines():
        riga = riga.strip()
        if riga.startswith("TITLE:"):
            t = riga[6:].strip()
            titoli.append(t)
            k = chiave_lista(t)
            if k:
                lista = k
            continue
        if not riga.startswith("ROW:"):
            continue
        celle = [c.strip() for c in riga[4:].split("|")]
        celle = (celle + ["-", "-", "-", "-"])[:4]
        ids, cas, nome, altri = celle
        ids = re.sub(r"\s+", " ", ids).upper()
        cas = cas.replace(" ", "")
        if cas.lower() in ("n/a", "na", "–", "—"):
            cas = "-"
        if nome in ("", "-") and altri not in ("", "-"):
            nome, altri = altri.split(",")[0].strip(), altri
        if nome in ("", "-") or re.match(r"(?i)^(kodi|emri|lënda|numri)\b", nome):
            continue
        out.append({"lista": lista or "?", "ids": ids if ids != "-" else "", "cas": cas if cas != "-" else "",
                    "emri": re.sub(r"\s+", " ", nome), "te_tjera": "" if altri == "-" else re.sub(r"\s+", " ", altri),
                    "cas_ok": cas_ok(cas) if cas not in ("", "-") else None, "faqja": pagina, "burimi": "figurë",
                    # la Lista III del 1961 elenca PREPARATI a basso dosaggio (codeina ≤ 100 mg per dose, cocaina ≤ 0,1 %…),
                    # non la sostanza: chi la cita la trova anche nella Lista I/II
                    "preparat": (lista or "") == "1961-III"})
    return out, lista, titoli


def righe_da_testo() -> list[dict]:
    """La parte in testo dello «shtojca» del corpus: Lista A e le aggiunte della ligji 17/2026 (con la data)."""
    corpo = ""
    for l in JSONL.read_text(encoding="utf-8").splitlines():
        if '"ligji_lendet_narkotike"' in l and '"shtojca"' in l:
            a = json.loads(l)
            if str(a.get("number")) == "shtojca":
                corpo = a.get("body") or ""
    out, lista, shtuar = [], None, ""
    for riga in corpo.splitlines():
        r = riga.strip()
        m = re.search(r"\(Shtuar Shtojca \d+ List[ëe]s s[ëe] (IV|III|II|I) t[ëe] Konvent[ëe]s (Unike )?p[ëe]r L[ëe]nd[ëe]t (Narkotike|Psikotrope) "
                      r"t[ëe] vitit (1961|1971) me ligjin nr\. (\d+/\d{4}), dat[ëe] ([\d.]+)\)", r)
        if m:
            lista, shtuar = f"{m.group(4)}-{m.group(1)}", f"ligji nr. {m.group(5)}, datë {m.group(6)}"
            continue
        if re.fullmatch(r"LISTA A", r):
            lista, shtuar = "A", ""
            continue
        if "|" not in r or lista is None or re.match(r"(?i)^(numeri|kodi)\b", r):
            continue
        celle = [c.strip() for c in r.split("|")]
        ids = celle[0] if _IDS.match(celle[0]) else ""
        resto = celle[1:] if ids else celle
        cas = next((c for c in resto if _CAS.match(c.replace(" ", ""))), "")
        nomi = [c for c in resto if c != cas and c not in ("", "-")]
        if lista == "A":           # Lista A: CAS | INN | altri nomi | chimico
            inn = resto[1] if len(resto) > 1 else ""
            altri = resto[2] if len(resto) > 2 else ""
            nome = inn if inn not in ("", "-") else altri.split(",")[0].strip()
            altri = altri if inn not in ("", "-") else altri
        else:
            nome, altri = (nomi[0] if nomi else ""), ""
        if not nome:
            continue
        out.append({"lista": lista, "ids": ids, "cas": cas, "emri": nome, "te_tjera": altri,
                    "cas_ok": cas_ok(cas) if cas else None, "faqja": 0, "burimi": "tekst", "shtuar_me": shtuar})
    return out


def main() -> int:
    a = sys.argv[1:]
    docx = Path(a[a.index("--docx") + 1]) if "--docx" in a else DOCX
    out_p = Path(a[a.index("--out") + 1]) if "--out" in a else OUT
    solo = int(a[a.index("--only") + 1]) if "--only" in a else None
    from src.backends import build_backend
    backend = build_backend()
    imgs = immagini(docx)
    print(f"{len(imgs)} immagini nel documento", flush=True)
    righe, lista, titoli_tutti = [], None, []
    for i, (nome, dati) in enumerate(imgs, 1):
        if solo and i != solo:
            continue
        t0 = time.time()
        testo = leggi(backend, nome, dati)
        rr, lista, titoli = righe_da_ocr(testo, lista, i)
        titoli_tutti += [(i, t) for t in titoli]
        cattivi = [r for r in rr if r["cas_ok"] is False]
        print(f"  [{i:2d}] {nome}: {len(rr)} righe · lista {lista} · titoli {titoli} · CAS non validi {len(cattivi)} "
              f"· {time.time() - t0:.0f}s", flush=True)
        for r in cattivi:
            print(f"        ✗ CAS {r['cas']} — {r['emri']}", flush=True)
        righe += rr
    righe += righe_da_testo()
    per = {}
    for r in righe:
        per[r["lista"]] = per.get(r["lista"], 0) + 1
    con_cas = [r for r in righe if r["cas_ok"] is not None]
    male = [r for r in con_cas if not r["cas_ok"]]
    print(f"sostanze {len(righe)} · per lista {per} · CAS letti {len(con_cas)}, non validi {len(male)}")
    if "--dry" in a or solo:
        return 0
    if len([k for k in per if k != "?"]) < 4 or len(righe) < 200 or len(male) > 0.03 * max(len(con_cas), 1) or per.get("?"):
        print("✗ cancello non superato (liste < 4, sostanze < 200, CAS non validi ≥ 3 % o righe senza lista): non scrivo nulla")
        return 1
    out_p.write_text(json.dumps({
        "fonte": "Ligji nr. 7975/1995, shtojca (teksti i konsoliduar QBZ 2026-02-20): listat e Konventave 1961/1971 (figura) + Lista A dhe shtesat e ligjit 17/2026 (tekst)",
        "docx_sha1": hashlib.sha1(docx.read_bytes()).hexdigest(), "lexuar": time.strftime("%Y-%m-%d"),
        "titujt": titoli_tutti, "righe": righe}, ensure_ascii=False, indent=0), encoding="utf-8")
    try:
        os.chown(out_p, 1000, 1000)
    except Exception:  # noqa: BLE001
        pass
    print(f"✓ {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
