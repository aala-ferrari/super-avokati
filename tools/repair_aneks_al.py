"""v9.576 — gli ALLEGATI incollati all'ULTIMO articolo delle leggi albanesi, e la formula di promulgazione.

Nel testo consolidato, dopo l'ultimo articolo («Hyrja në fuqi») vengono la formula («Miratuar në datën …», «Shpallur me
dekretin nr. … të Presidentit…», «KRYETARI ⏎ Gramoz Ruçi») e poi gli ALLEGATI (SHTOJCA / ANEKSI): il parser li lasciava nel
corpo dell'ultimo articolo. La Costituzione aveva l'ANEKS sulla rivalutazione transitoria dei giudici e dei procuratori (il
vetting: neni A-G, 20.000 caratteri) dentro l'art. 183 — oltre il tetto del prompt (12.000) i neni D-G non arrivavano mai al
modello —; la legge sull'IVA i suoi tre allegati nell'art. 161; quella sulle imposte sul reddito la dichiarazione del
lavoratore autonomo nell'art. 72; i consumatori il modello del recesso nell'art. 63; il Codice elettorale tre allegati
abrogati nell'art. 186.

Qui, solo sull'ULTIMO articolo di ogni atto: (1) la formula di promulgazione esce dal corpo (numero e data della legge sono
già nella riga dell'atto, `acts_meta`); (2) ogni allegato diventa un'unità sua («aneks-I», «shtojca-1»; nella Costituzione
un'unità per neni: «aneks-neni-A»), col titolo dell'allegato come rubrica e come titolo del capitolo (cercabile), la nota
«(Shtuar/Ndryshuar/Shfuqizuar me ligjin …)» nel campo `note`, abrogata se la nota dice «Shfuqizuar» e non resta testo;
(3) le note a piè di pagina dopo la formula («* Ligji nr. … botuar në Fletoren Zyrtare …», «‡ Shiko …») vanno nel campo `note`
dell'articolo. Fuori di proposito il VKM doganale (gli allegati sono moduli e modifiche annidate «{ VKM nr. 872 … }»).
Una formula lunga o con verbi normativi non si tocca (la si riporta). jsonl E pickle, backup, idempotente.
Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.
    python3 tools/repair_aneks_al.py [--apply]     → poi build_dense.py --only al --kreu [--flat] --suffix _flat3|_ck3
                                                      --incremental --rifai <pkl>.aneks.json"""
import json, os, re, shutil, sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import Article, _paragrafet, _is_italian_code  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
ESCLUSI = {"vkm_dispozita_doganore"}

FORMULA = re.compile(r"^(?:Miratuar\s+(?:në\s+datën|më|me\s+ligjin|me\s+referendum)\b|Shpallur\s+me\s+dekretin\b|KRYETAR(?:I)?$|"
                     r"KRYEMINISTRI$)")
ANEKS = re.compile(r"^(?P<k>SHTOJC[AË]|ANEKS(?:I)?|Aneksi|Shtojca)(?:\s+(?:NR\.?|Nr\.?)?\s*(?P<n>[IVXLC]+|\d+))?$")
NOTA_FONDO = re.compile(r"^[*‡†]")
NOTA_ALL = re.compile(r"^\((?:[Ss]htuar|[Nn]dryshuar|[Ss]hfuqizuar|[Pp]arashikuar)\b")
NENI_LETTERA = re.compile(r"^Neni\s+(?P<l>[A-ZËÇ]{1,3})$")
# una riga di STRUTTURA dentro l'allegato non è il suo titolo: «PJESA A», «I. LISTA E …» (l'allegato III dell'IVA ha due liste)
STRUTT = re.compile(r"^(?:[IVX]+\.\s|PJESA\b|KREU\b|SEKSIONI\b|\d|\(|[a-zë]{1,2}\)|Neni\b)")
VERBI = re.compile(r"\b(?:hyn në fuqi|zbatohet|zbatohen|shfuqizohet|ngarkohet|detyrohet|duhet|mund të|përcaktohet)\b", re.I)


def _num(n) -> int:
    m = re.match(r"\d+", str(n))
    return int(m.group(0)) if m else -1


def _maiuscola(s: str) -> bool:
    let = [c for c in s if c.isalpha()]
    return len(let) >= 3 and sum(c.isupper() for c in let) / len(let) >= 0.8


def _titolo_e_nota(righe: list[str]):
    """Le prime righe di un allegato: il titolo (maiuscolo, fino a 3 righe; o una riga breve senza punto finale) e la nota
    «(Shtuar/Ndryshuar/Shfuqizuar … )» che può andare a capo. Restituisce (titolo, nota, resto)."""
    i, tit = 0, []
    while i < len(righe) and not righe[i].strip():
        i += 1
    while i < len(righe) and len(tit) < 3 and _maiuscola(righe[i]) and len(righe[i].strip()) <= 120 \
            and not STRUTT.match(righe[i].strip()):
        tit.append(righe[i].strip()); i += 1
    if not tit and i < len(righe):
        r = righe[i].strip()
        if r and len(r) <= 120 and not re.search(r"[.:;]$", r) and not STRUTT.match(r):
            tit.append(r); i += 1
    nota = []
    if i < len(righe) and NOTA_ALL.match(righe[i].strip()):
        while i < len(righe):
            nota.append(righe[i].strip()); i += 1
            if nota[-1].endswith(")"):
                break
    return " ".join(tit), " ".join(nota), righe[i:]


def seziona(body: str):
    """→ None (niente da fare) | dict(testo, formula, fondo, annessi[{k, n, titolo, nota, righe}], motivo)."""
    righe = body.split("\n")
    i0 = next((i for i, r in enumerate(righe) if FORMULA.match(r.strip()) or ANEKS.match(r.strip())), None)
    if i0 is None:
        return None
    formula, fondo, annessi, nota_pend = [], [], [], ""
    stato, i = "formula", i0
    while i < len(righe):
        s = righe[i].strip()
        m = ANEKS.match(s)
        if m:
            annessi.append({"k": m.group("k"), "n": m.group("n") or "", "righe": [], "nota_prima": nota_pend})
            nota_pend, stato = "", "aneks"
        elif stato == "aneks":
            annessi[-1]["righe"].append(righe[i])
        elif s and NOTA_ALL.match(s) and next((ANEKS.match(x.strip()) for x in righe[i + 1:i + 4] if x.strip()), None):
            nota_pend = s
        elif s and (stato == "fondo" or NOTA_FONDO.match(s)):
            fondo.append(s); stato = "fondo"
        elif s:
            formula.append(s)
        i += 1
    ftxt = " ".join(formula)
    if len(ftxt) > 500 or VERBI.search(ftxt):
        return {"motivo": f"formula sospetta ({len(ftxt)} chr): {ftxt[:120]}"}
    out = []
    for a in annessi:
        tit, nota, resto = _titolo_e_nota(a["righe"])
        nota = " ".join(x for x in (a["nota_prima"], nota) if x)
        out.append({"k": a["k"], "n": a["n"], "titolo": tit, "nota": nota, "resto": resto})
    return {"testo": "\n".join(righe[:i0]).rstrip(), "formula": ftxt, "fondo": " ".join(fondo), "annessi": out}


def _unita(base: dict, numero: str, rubrica: str, kreu: str, corpo: str, nota: str) -> dict:
    corpo = corpo.strip()
    d = dict(base)
    d.update({"number": numero, "heading": rubrica, "body": corpo, "pjesa": "", "kreu": kreu, "seksioni": "",
              "note": nota, "paragrafet": _paragrafet(corpo) if corpo else [], "heading_kind": "rubrike",
              "repealed": (not corpo) and bool(re.search(r"shfuqizuar", nota, re.I))})
    return d


def unita_da_annessi(base: dict, annessi: list) -> list[dict]:
    nuove = []
    for a in annessi:
        num = ("shtojca" if a["k"].upper().startswith("SHTOJC") else "aneks") + (f"-{a['n']}" if a["n"] else "")
        etichetta = (a["k"].upper() + (f" {a['n']}" if a["n"] else "")).strip()
        kreu = f"{etichetta} — {a['titolo']}" if a["titolo"] else etichetta
        righe = a["resto"]
        posiz = [j for j, r in enumerate(righe) if NENI_LETTERA.match(r.strip())]
        if len(posiz) >= 2:                                   # l'allegato ha i suoi neni (Kushtetuta: A … G)
            intro = " ".join(r.strip() for r in righe[:posiz[0]] if r.strip())
            nota = " ".join(x for x in (a["nota"], intro) if x)
            for j, p in enumerate(posiz):
                lett = NENI_LETTERA.match(righe[p].strip()).group("l")
                pezzo = righe[p + 1:(posiz[j + 1] if j + 1 < len(posiz) else len(righe))]
                rub = pezzo[0].strip() if pezzo and len(pezzo[0].strip()) <= 120 and not pezzo[0].strip().endswith(".") else ""
                corpo = "\n".join(pezzo[1:] if rub else pezzo)
                nuove.append(_unita(base, f"{num}-neni-{lett}", rub, kreu, corpo, nota))
        else:
            nuove.append(_unita(base, num, a["titolo"] or etichetta, kreu, "\n".join(righe), a["nota"]))
    return nuove


def main() -> int:
    apply = "--apply" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    ultimo = {}
    for d in dati:
        if not _is_italian_code(d["code"]) and _num(d["number"]) >= _num(ultimo.get(d["code"], {}).get("number", -1)):
            ultimo[d["code"]] = d
    gia = {(d["code"], str(d["number"])) for d in dati}
    cambiati, nuove_tutte = [], []
    for code, d in sorted(ultimo.items()):
        if code in ESCLUSI:
            continue
        s = seziona(d.get("body") or "")
        if not s:
            continue
        if "motivo" in s:
            print(f"SALTATO {code} {d['number']}: {s['motivo']}"); continue
        nuove = unita_da_annessi(d, s["annessi"])
        nuove = [u for u in nuove if (code, u["number"]) not in gia]
        if len({u["number"] for u in nuove}) != len(nuove):
            print(f"SALTATO {code} {d['number']}: numeri d'allegato doppi {[u['number'] for u in nuove]}"); continue
        print(f"{code} {d['number']}: corpo {len(d['body'])} → {len(s['testo'])} | formula «{s['formula'][:90]}»"
              + (f" | nota a piè «{s['fondo'][:90]}»" if s["fondo"] else ""))
        for u in nuove:
            print(f"    + {u['number']:18s} «{u['heading'][:60]}» corpo {len(u['body'])}" + (" ABROGATO" if u["repealed"] else "")
                  + (f" | nota «{u['note'][:70]}»" if u["note"] else "") + f" | kreu «{u['kreu'][:60]}»")
        d["body"] = s["testo"]
        d["paragrafet"] = _paragrafet(s["testo"]) if s["testo"] else []
        if s["fondo"] and s["fondo"] not in (d.get("note") or ""):
            d["note"] = " ".join(x for x in ((d.get("note") or "").strip(), s["fondo"]) if x)
        cambiati.append((code, str(d["number"]), d))
        nuove_tutte.append((code, str(d["number"]), nuove))
    print(f"articoli cambiati {len(cambiati)}, unità nuove {sum(len(n) for _, _, n in nuove_tutte)}")
    if not apply or not cambiati:
        return 0
    # le unità nuove subito DOPO l'ultimo articolo del loro atto
    dopo = {(c, n): nu for c, n, nu in nuove_tutte}
    out = []
    for d in dati:
        out.append(d)
        out.extend(dopo.get((d["code"], str(d["number"])), []))
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-aneks")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in out) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-aneks")
    per_chiave = {(c, n): d for c, n, d in cambiati}
    arts = []
    campi = set(Article.__dataclass_fields__)
    for a in idx.articles:
        k = (a.code, str(a.number))
        if k in per_chiave:
            a.body, a.paragrafet, a.note = per_chiave[k]["body"], per_chiave[k]["paragrafet"], per_chiave[k].get("note") or ""
        arts.append(a)
        for u in dopo.get(k, []):
            arts.append(Article(**{f: v for f, v in u.items() if f in campi}))
    ArticleIndex.build(arts, lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    chiavi = [[c, n] for c, n, _ in cambiati] + [[c, u["number"]] for c, _, nu in nuove_tutte for u in nu]
    Path(str(PKL) + ".aneks.json").write_text(json.dumps(chiavi, ensure_ascii=False), encoding="utf-8")
    print(f"scritti: {JSONL} ({len(out)} righe), {PKL} ({len(arts)} articoli), {len(chiavi)} chiavi per l'embedding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
