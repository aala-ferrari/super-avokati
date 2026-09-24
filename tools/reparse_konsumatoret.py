#!/usr/bin/env python3
"""v9.378 — il Ligji 9902/2008 «Për mbrojtjen e konsumatorëve» (unico consolidato disponibile: erru.al 2018, CON note a piè di
pagina; QBZ ha solo l'atto base) ha i numeri delle note ATTACCATI ai numeri degli articoli: «Neni 6³» → «Neni 63», «Neni 45²⁵»
→ «Neni 4525», «Neni 56/1³²» → «Neni 56/132». Il parser saltava gli articoli e il loro testo finiva nel precedente (il 45 dentro
il 44, il 57 e il 59 persi). Qui: si leggono i numeri delle note presenti a fondo pagina; un'intestazione fuori sequenza si
separa in (articolo, nota) SOLO se la nota esiste davvero e l'articolo è quello atteso; poi il parser normale. Gli articoli
senza testo la cui nota dice «Shfuqizuar …» diventano abrogati con la nota come fonte.

    python3 tools/reparse_konsumatoret.py            # rapporto
    python3 tools/reparse_konsumatoret.py --apply    # sostituisce il codice nel jsonl (backup) + indice
"""
import json, re, shutil, sys, time
sys.path.insert(0, "/app")
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from src import parser as P
from src.config import PROCESSED_DATA_PATH, RAW_DATA_PATH

CODE = "ligji_konsumatoret"
PDF = RAW_DATA_PATH / "ligji_konsumatoret.pdf"
JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
_NOTA_RX = re.compile(r"(?m)^(\d{1,3})\s+(?=[A-ZÇËa-zëç«“(])(.{0,200})$")
_HDR_RX = re.compile(r"(?m)^[ \t]*Neni[ \t]*(\d+)(?:[ \t]*/[ \t]*(\d+))?[ \t]*$")


def normalizza(text: str) -> tuple[str, dict, list]:
    note = {}
    for m in _NOTA_RX.finditer(text):
        if re.match(r"(Shtuar|Ndryshuar|Shfuqizuar|Hequr|Riformuluar|Kjo|Ky|Nen|Pika|Fjal|Shkronj|Paragraf|Titull|Kre|Seksion|Pjes|Emërtim|Zëvendësuar)", m.group(2)):
            note[m.group(1)] = m.group(2).strip()
    out, last, cambi = [], 0, []
    last_sub: dict[int, int] = {}
    pos = 0
    for m in _HDR_RX.finditer(text):
        a, sub = m.group(1), m.group(2)
        nuovo = None
        if sub is None:
            n = int(a)
            if not (last <= n <= last + 3):
                for k in (1, 2, 3):                       # «4525» → 45 + nota 25 (l'articolo atteso + una nota vera)
                    art = str(last + k)
                    if a.startswith(art) and a[len(art):] in note:
                        nuovo = f"Neni {art}"; last = last + k; break
                if nuovo is None and last and a.startswith(str(last)) and a[len(str(last)):] in note:
                    nuovo = f"Neni {last}"               # l'intestazione ripetuta con nota
            else:
                last = n
        else:
            # «56/132» → 56/1 + nota 32 — SOLO se «132» non è il sotto-articolo atteso in sequenza (37/11 dopo 37/10 è vero)
            b_ = int(a); atteso = last_sub.get(b_, 0) + 1
            if int(sub) == atteso or int(sub) <= atteso + 1:
                last_sub[b_] = int(sub)
            else:
                for k in range(1, len(sub)):
                    s_, fn_ = sub[:k], sub[k:]
                    if int(s_) in (atteso, atteso + 1) and fn_ in note:
                        nuovo = f"Neni {a}/{s_}"; last_sub[b_] = int(s_); break
            if b_ > last:
                last = b_
        if nuovo:
            out.append(text[pos:m.start()]); out.append(nuovo); pos = m.end()
            cambi.append((m.group(0).strip(), nuovo))
    out.append(text[pos:])
    return "".join(out), note, cambi


def main() -> int:
    raw = P.extract_full_text(PDF)
    testo, note, cambi = normalizza(raw)
    doc = SimpleNamespace(code=CODE, title_sq="Ligji nr. 9902/2008 «Për mbrojtjen e konsumatorëve»", area="Konsumator",
                          volatility="STABLE", last_amendment_date="2018-10-18")
    arts = P.split_into_articles(testo, doc)
    base = sorted({int(re.match(r"\d+", a.number).group()) for a in arts if re.match(r"\d+", a.number)})
    mancanti = [n for n in range(1, max(base) + 1) if n not in base]
    print(f"note trovate: {len(note)} · intestazioni corrette: {len(cambi)} · articoli: {len(arts)} · mancanti: {mancanti}")
    for c in cambi:
        print("   ", c)
    # un «articolo» che contiene SOLO l'intestazione del capitolo seguente («Neni 21» + «KREU II / PUBLICITETI») è vuoto:
    # il capitolo appartiene all'articolo dopo (che lo ha già nel suo `kreu`)
    for x in arts:
        righe = [ln.strip() for ln in ((x.heading or "") + "\n" + (x.body or "")).split("\n") if ln.strip()]
        if righe and P.HIERARCHY_RE.match(righe[0]) and all(P.HIERARCHY_RE.match(r) or P._riga_titolo(r) for r in righe):
            x.heading, x.body, x.paragrafet = "", "", []
    # abrogati: testo vuoto e nota «Shfuqizuar» sull'intestazione originale
    abrog = []
    for orig, nuovo in cambi:
        fn = re.sub(r"^Neni\s*", "", orig).replace(" ", "")
        num = nuovo.replace("Neni ", "")
        foot = fn[len(num.replace("/", "")):] if "/" not in num else fn.split("/")[1][1:]
        txt = note.get(foot, "")
        a = next((x for x in arts if x.number == num), None)
        if a is not None and not (a.body or "").strip() and re.match(r"(Shfuqizuar|Hequr)", txt):
            a.repealed = True; a.note = "(" + txt.rstrip(".") + ")"; abrog.append(num)
    print("abrogati dalla nota:", abrog)
    for n in ("21", "37/11", "37/15", "44", "45", "57", "59", "56/1"):
        a = next((x for x in arts if x.number == n), None)
        print(f"   {n:5s} →", (a.heading[:50], (a.body or "")[:90].replace("\n", " ")) if a else None)
    if "--apply" not in sys.argv:
        print("(a secco: niente scritto; --apply per applicare)")
        return 0
    rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
    i0 = next(i for i, r in enumerate(rows) if r["code"] == CODE)
    rows = [r for r in rows if r["code"] != CODE]
    nuovi = [asdict(a) for a in arts]
    rows[i0:i0] = nuovi
    bak = JSONL.with_suffix(f".jsonl.bak-kons-{time.strftime('%Y%m%d%H%M')}")
    shutil.copy2(JSONL, bak)
    with JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from src.retrieval import ArticleIndex, INDEX_FILE
    shutil.copy2(INDEX_FILE, INDEX_FILE.with_suffix(f".pkl.bak-kons-{time.strftime('%Y%m%d%H%M')}"))
    ix = ArticleIndex.from_jsonl(JSONL)
    ix.save(INDEX_FILE)
    print("scritto", JSONL.name, "(backup", bak.name + ") · indice", len(ix.articles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
