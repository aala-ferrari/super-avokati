#!/usr/bin/env python3
"""v9.391 — ligji 7975/1995 «Për lëndët narkotike, psikotrope dhe të kontrolluara» (consolidato QBZ 2026-02-20): tre
difetti del .docx sorgente che il parser generale non vede, riparati SOLO su questo atto.

1. Le intestazioni dei capi hanno maiuscole miste («KLASIFIKIMI I lëndëve NARKOTIKE … dhe lëndëve të kontrolluara»,
   «… PËRGATESAT E GrupEVE II DHE III»): il parser le riconosce in testa al capo ma le lascia anche in CODA all'articolo
   precedente (6 articoli: 2, 10/1, 11, 40, 61, 80) e ne tronca il titolo alla prima riga non maiuscola → coda tolta, e
   il titolo intero del capo (letto dalla coda) torna nel campo `kreu` degli articoli del capo.
2. L'allegato «Skema e klasifikimit» (Lista A delle sostanze controllate e le aggiunte della ligji 17/2026 alle liste
   delle Convenzioni; il resto degli elenchi è in immagini) finiva nel corpo del neni 105 («Ky ligj hyn në fuqi…») →
   un'unità sua, `shtojca`.
3. Il neni 9 vieta OGNI coltivazione di cannabis, ma la ligji 61/2023 la permette con licenza (uso medico, neni 14) o
   permesso (uso industriale, neni 22) e al neni 44 abroga le disposizioni della 7975 contrarie: il consolidato QBZ non
   lo riflette (abrogazione implicita) → nota di collegamento nel campo `note` del neni 9, dichiarata come nostra.
4. (v9.392) Lo SCHEMA DI CLASSIFICAZIONE (gruppi I-III, sottogruppi A/B: ricette per 7 o 60 giorni, ripetibilità) è
   un'immagine dell'allegato: trascritto parola per parola in un'unità sua, `skema` (la nota ricorda che il KP 283 vigente
   esclude «përveç rastit të përdorimit vetjak dhe në doza të vogla», mentre lo schema scrive «Ndiqet penalisht mbajtja për konsum
   vetjak»).
Idempotente, con backup del jsonl; poi `ArticleIndex.from_jsonl()` ricostruisce bm25.pkl. Nel container:

    python3 /app/tools/repair_lendet_narkotike.py [--apply]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
from src.config import INDEX_PATH, PROCESSED_DATA_PATH  # noqa: E402

JSONL = PROCESSED_DATA_PATH / "all_articles.jsonl"
CODE = "ligji_lendet_narkotike"
_CODA = re.compile(r"\s*\bKREU\s+([IVXLC]+)\s+(.{8,260}?)\s*$", re.S)
_ALLEGATO = re.compile(r"\s*KLASIFIKIMI\s+I\s+l[ëe]nd[ëe]ve\s+NARKOTIKE\s+DHE\s+L[ËE]ND[ËE]VE\s+PSIKOTROPE\*.*$", re.S | re.I)
_NOTA_9 = ("Lidhje (shënim i Super Avokatit, jo i QBZ): ligji nr. 61/2023 «Për kontrollin e kultivimit dhe përpunimit të bimës "
           "së cannabis-it…» lejon kultivimin e cannabis-it vetëm për qëllime mjekësore, me licencë (neni 14), dhe industriale "
           "(≤0,8% THC), me leje (neni 22); shitja, shpërndarja dhe konsumi në Shqipëri i produkteve mjekësore mbeten të ndaluara "
           "(neni 5/d). Neni 44 i tij: «dispozitat e ligjit nr. 7975, datë 26.7.1995 … që bien ndesh me parashikimet e këtij "
           "ligji, shfuqizohen».")


_SKEMA = """KLASIFIKIMI PËR LËNDËT NARKOTIKE, PSIKOTROPE DHE TË KONTROLLUARA
GRUPI I
Lëndët e përfshira në këtë grup kanë: rrezikshmëri shumë të lartë për shëndetin e njeriut; përdorim mjekësor shumë të limituar; potencial të lartë abuzimi dhe varësie.
1. Lëndë narkotike të listës IV të Konventës për Lëndët Narkotike 1961.
2. Lëndë psikotrope të Listës I të Konventës për Lëndët Psikotrope 1971.
GRUPI II
Lëndët e përfshira në këtë grup kanë: rrezikshmëri të lartë për shëndetin e njeriut; përdorim mjekësor të miratuar; potencial të moderuar abuzimi dhe varësie.
1. Lëndë narkotike të listës I (me përjashtim të lëndëve të listës IV të Konventës për Lëndët Narkotike 1961) dhe II të Konventës për Lëndët Narkotike 1961.
2. Lëndë psikotrope të Listës II të Konventës për Lëndët Psikotrope 1971.
Nëngrupi A: barna që mund të përshkruhen për jo më shumë se 7 ditë.
Nëngrupi B: barna që mund të përshkruhen për jo më shumë se 60 ditë.
GRUPI III
Lëndët e përfshira në këtë grup kanë: rrezikshmëri të ulët për shëndetin e njeriut; përdorim mjekësor të miratuar; potencial të ulët abuzimi dhe varësie.
1. Lëndë narkotike të listës III të Konventës për Lëndët Narkotike 1961.
2. Lëndë psikotrope të Listës III dhe IV të Konventës për Lëndët Psikotrope 1971.
Nëngrupi A: barna për të cilat ndalohet ripërsëritja e recetës pa autorizim me shkrim të përshkruesit të saj.
Nëngrupi B: barna për të cilat lejohet ripërsëritja e recetës me përjashtim të rastit kur përshkruesi i saj mendon ndryshe.
Grupi I dhe Grupi II: kontroll i rreptë i trafikut të paligjshëm. Grupi III: kontroll i trafikut të paligjshëm.
Ndiqet penalisht mbajtja për konsum vetjak."""
_NOTA_SKEMA = ("Lidhje (shënim i Super Avokatit, jo i QBZ): transkriptim fjalë për fjalë i figurës së skemës në shtojcën e ligjit "
               "(teksti i konsoliduar QBZ 2026-02-20). Lëndët e kontrolluara (Lista A) ndjekin regjimin e grupit III, nëngrupi «b» "
               "(neni 4). Për mbajtjen: neni 283 i Kodit Penal në fuqi e dënon mbajtjen «përveç rastit të përdorimit vetjak dhe në doza të vogla».")


def main() -> int:
    apply = "--apply" in sys.argv
    righe = JSONL.read_text(encoding="utf-8").splitlines()
    arts = [(i, json.loads(r)) for i, r in enumerate(righe) if f'"code": "{CODE}"' in r]
    if not arts:
        print(f"✗ {CODE} non è nel corpus"); return 1
    titoli: dict = {}
    cambiati = 0
    for i, a in arts:
        corpo = a.get("body") or ""
        m = _CODA.search(corpo[-320:])
        if m:
            # la coda può portare anche il titolo della prima SEZIONE del capo («… ME PAKICË A. Përdorimi në klinikë…»):
            # nel capo va solo il titolo del capo; la sezione il parser la assegna già agli articoli che seguono
            titoli[m.group(1)] = re.split(r"\s+[A-D]\.\s+(?=[A-ZÇË])", re.sub(r"\s+", " ", m.group(2)).strip())[0].strip()
            a["body"] = corpo[: len(corpo) - len(corpo[-320:]) + m.start()].rstrip()
            cambiati += 1
    for i, a in arts:
        km = re.match(r"^KREU\s+([IVXLC]+)\s+—\s+(.*)$", a.get("kreu") or "")
        if km and km.group(1) in titoli and len(titoli[km.group(1)]) > len(km.group(2)):
            a["kreu"] = f"KREU {km.group(1)} — {titoli[km.group(1)]}"
    ult = next((x for x in arts if str(x[1]["number"]) == "105"), None)
    nuova = None
    if ult:
        corpo = ult[1].get("body") or ""
        m = _ALLEGATO.search(corpo)
        if m:
            allegato = re.sub(r"[ \t]+", " ", corpo[m.start():]).strip()
            ult[1]["body"] = corpo[: m.start()].rstrip()
            nuova = dict(ult[1], number="shtojca", body=allegato,
                         heading="Skema e klasifikimit — pjesët në tekst: Lista A (lëndë të kontrolluara, grupi III/b) dhe "
                                 "shtesat e ligjit 17/2026 në listat e konventave (pjesa tjetër e listave është në figura)")
    gia = any(str(a["number"]) == "shtojca" for _, a in arts)
    nove = next((x for x in arts if str(x[1]["number"]) == "9"), None)
    nota9 = bool(nove) and "ligji nr. 61/2023" not in (nove[1].get("note") or "")
    if nota9:
        nove[1]["note"] = ((nove[1].get("note") or "").strip() + " " + _NOTA_9).strip()
    base_sh = nuova or next((x[1] for x in arts if str(x[1]["number"]) == "shtojca"), None)
    skema = None
    if base_sh is not None and not any(str(a["number"]) == "skema" for _, a in arts):
        skema = dict(base_sh, number="skema", body=_SKEMA, note=_NOTA_SKEMA, paragrafet=[], heading_kind="rubrike",
                     heading="Skema e klasifikimit — grupet I, II dhe III (transkriptim i figurës së shtojcës)")
    print(f"code tolte: {cambiati} · titoli di capo completati: {len(titoli)} · allegato separato: {bool(nuova)} (già presente: {gia})"
          f" · nota 61/2023 sul neni 9: {'aggiunta' if nota9 else 'già presente'} · schema: {'aggiunto' if skema else 'già presente'}")
    for k, v in titoli.items():
        print(f"   KREU {k} — {v[:110]}")
    if not apply:
        return 0
    bak = JSONL.with_name(JSONL.name + time.strftime(".bak-7975-%Y%m%d-%H%M"))
    shutil.copy2(JSONL, bak)
    for i, a in arts:
        righe[i] = json.dumps(a, ensure_ascii=False)
    if nuova and not gia:
        dopo = ult[0]
        righe.insert(dopo + 1, json.dumps(nuova, ensure_ascii=False))
        if skema:
            righe.insert(dopo + 2, json.dumps(skema, ensure_ascii=False))
    elif skema:
        sh_i = next(i for i, r in enumerate(righe) if f'"code": "{CODE}"' in r and '"number": "shtojca"' in r)
        righe.insert(sh_i + 1, json.dumps(skema, ensure_ascii=False))
    JSONL.write_text("\n".join(righe) + "\n", encoding="utf-8")
    from src.retrieval import ArticleIndex
    idx = ArticleIndex.from_jsonl(JSONL, lang="sq")          # fold dei diacritici come la produzione
    idx.save(INDEX_PATH / "bm25.pkl")
    try:
        import os
        os.chown(INDEX_PATH / "bm25.pkl", 1000, 1000); os.chown(JSONL, 1000, 1000)
    except Exception:  # noqa: BLE001
        pass
    print(f"✓ jsonl riscritto (backup {bak.name}) · indice AL: {len(idx.articles)} articoli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
