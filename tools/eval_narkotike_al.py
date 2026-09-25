#!/usr/bin/env python3
"""v9.392 — il cervello conosce le LISTE ALBANESI delle sostanze? Misura PRIMA di cablare `src/narkotike_al.py`.

35 sostanze (quelle che un avvocato albanese incontra davvero: droghe di strada, farmaci, nuove sostanze, e quelle che NON
sono in nessuna lista) → UNA chiamata al modello del senior, senza web, in sessione AL: per ciascuna la categoria
(narkotike = liste 1961 · psikotrope = liste 1971 · e kontrolluar = Lista A · jo), le liste e il GRUPPO della 7975
(schema di classificazione: 1961-IV e 1971-I → I; 1961-I/II e 1971-II → II; 1961-III, 1971-III/IV → III; Lista A →
regime del III/b, neni 4). Verità: `data/processed/al_lista_narkotike.json` (tools/ingest_liste_narkotike_al.py).

    python3 /app/tools/eval_narkotike_al.py            # nel container, con le credenziali del cervello (a memoria)
    python3 /app/tools/eval_narkotike_al.py --con-blocco   # con il dossier delle liste davanti, come in produzione
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

LISTE = Path("/app/data/processed/al_lista_narkotike.json")
GRUPPO = {"1961-IV": "I", "1971-I": "I", "1961-I": "II", "1961-II": "II", "1971-II": "II",
          "1961-III": "III", "1971-III": "III", "1971-IV": "III", "A": "III"}

# (nome come lo scrive l'avvocato, chiave nel dizionario: nome esatto o «~prefisso» negli altri nomi; None = in nessuna lista)
CASI = [
    ("kokainë", "COCAINE"), ("heroinë", "HEROIN"), ("kanabis (marijuanë)", "CANNABIS"),
    ("rrëshirë kanabisi (hashish)", "CANNABIS RESIN, EXTRACTS and TINCTURES"), ("THC (delta-9-tetrahidrokanabinol)", "~delta-9-tetrahydro-cannabinol"),
    ("MDMA (ekstazi)", "MDMA"), ("LSD", "(+)-LYSERGIDE"), ("amfetaminë", "AMFETAMINE"), ("metamfetaminë", "METAMFETAMINE"),
    ("ketaminë", "Ketamine"), ("GHB", "~GHB"), ("tramadol", None), ("fentanil", "FENTANYL"), ("karfentanil", "CARFENTANIL"),
    ("metadon", "METHADONE"), ("buprenorfinë", "BUPRENORPHINE"), ("diazepam", "DIAZEPAM"), ("alprazolam", "ALPRAZOLAM"),
    ("kodeinë", "CODEINE"), ("pregabalinë", None), ("mefedron", "~mephedrone"), ("HHC (heksahidrokanabinol)", "Hexahydrocannabinol (HHC)"),
    ("karisoprodol", "Carisoprodol"), ("oksid azoti (N2O, «gaz gazmor»)", "Nitrous oxide"), ("psilocibinë", "PSILOCYBINE"),
    ("zolpidem", "ZOLPIDEM"), ("kratom (mitraginë)", None), ("morfinë", "MORPHINE"), ("oksikodon", "OXYCODONE"),
    ("flunitrazepam", "FLUNITRAZEPAM"), ("dekstrometorfan", None), ("GBL (gama-butirolakton)", "Gamma-butyrolactone"),
    ("katinonë (khat)", "CATHINONE"), ("metilfenidat", "METHYLPHENIDATE"), ("fenobarbital", "PHENOBARBITAL"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def verita(righe: list[dict], chiave: str | None) -> dict:
    if chiave is None:
        return {"liste": [], "grupi": "—", "kategoria": "jo"}
    k = _norm(chiave.lstrip("~"))
    trov = []
    for r in righe:
        if r.get("preparat"):
            continue
        altri = [_norm(x) for x in (r.get("te_tjera") or "").split(",")]
        if (chiave.startswith("~") and (any(a.startswith(k) for a in altri) or _norm(r["emri"]).startswith(k))) \
                or _norm(r["emri"]) == k or k in altri:
            trov.append(r["lista"])
    liste = sorted(set(trov))
    if not liste:
        return {"liste": [], "grupi": "?", "kategoria": "?"}
    grupi = min((GRUPPO[l] for l in liste), key=["I", "II", "III"].index)
    kat = "e kontrolluar" if liste == ["A"] else ("narkotike" if any(l.startswith("1961") for l in liste) else "psikotrope")
    return {"liste": liste, "grupi": grupi, "kategoria": kat}


PROMPT = """Për secilën lëndë më poshtë, sipas ligjit shqiptar nr. 7975/1995 «Për lëndët narkotike, psikotrope dhe të
kontrolluara» (me shtojcat e tij në fuqi sot: listat e Konventës Unike 1961 dhe të Konventës 1971 të bashkëlidhura, Lista A
e lëndëve të kontrolluara, skema e klasifikimit në grupet I, II, III), thuaj:
- "kategoria": "narkotike" (në një listë të Konventës 1961), "psikotrope" (në një listë të Konventës 1971),
  "e kontrolluar" (Lista A) ose "jo" (në asnjë listë të këtij ligji);
- "liste": listat, p.sh. ["1961-I", "1961-IV"], ["1971-II"], ["A"], [];
- "grupi": grupi i ligjit 7975 ("I", "II", "III") ose "—".
Përgjigju VETËM me një objekt JSON {"<emri i lëndës siç e shkrova>": {"kategoria": …, "liste": […], "grupi": …}, …}, pa
tekst tjetër. Mos kërko në internet: përgjigju nga njohuritë e tua, siç do t'i përgjigjeshe një avokati.

Lëndët:
""" + "\n".join(f"- {n}" for n, _ in CASI)


def main() -> int:
    righe = json.loads(LISTE.read_text(encoding="utf-8"))["righe"]
    ver = {n: verita(righe, k) for n, k in CASI}
    dubbi = [n for n, v in ver.items() if v["grupi"] == "?"]
    if dubbi:
        print("✗ sostanze non trovate nel dizionario (chiave sbagliata?):", dubbi); return 1
    if "--verita" in sys.argv:                           # solo la tabella della legge, senza chiamare il modello
        for n, v in ver.items():
            print(f"{n:38s} {v['kategoria']:13s} {'/'.join(v['liste']) or '—':16s} gr. {v['grupi']}")
        return 0
    from src import brain as B
    B.set_request_jurisdiction("AL")
    sa = B.SuperAvvocato()
    t0 = time.time()
    prompt = PROMPT
    if "--con-blocco" in sys.argv:                      # come in produzione: il dossier con le liste della legge davanti
        from src import narkotike_al
        prompt = narkotike_al.blocco(" · ".join(n for n, _ in CASI), massimo=60) + "\n\n" + PROMPT
    raw = sa.backend.complete("Je jurist ekspert i së drejtës penale shqiptare dhe i ligjit për lëndët narkotike.",
                              [{"role": "user", "content": prompt}], max_tokens=8000, no_web=True, callsite="eval_narkotike_al")
    m = re.search(r"\{.*\}", raw, re.S)
    got = json.loads(m.group(0)) if m else {}
    print(f"risposta in {time.time() - t0:.0f}s\n")
    err_cat = err_grp = err_lst = 0
    for n, _ in CASI:
        v, g = ver[n], got.get(n) or {}
        gl = sorted({re.sub(r"\s+", "", str(x)).upper().replace("LISTA", "") for x in (g.get("liste") or [])})
        ok_c = _norm(g.get("kategoria")) == v["kategoria"]
        ok_g = str(g.get("grupi") or "—").strip().upper() in (v["grupi"], v["grupi"].upper())
        ok_l = gl == [x.upper() for x in v["liste"]]
        err_cat += not ok_c; err_grp += not ok_g; err_lst += not ok_l
        segno = "✓" if ok_c and ok_g else "✗"
        print(f"{segno} {n:38s} legge: {v['kategoria']:13s} {'/'.join(v['liste']) or '—':16s} gr. {v['grupi']:4s} | "
              f"modello: {g.get('kategoria')!s:13s} {'/'.join(gl) or '—':16s} gr. {g.get('grupi')}"
              + ("" if ok_l else "  (liste diverse)"))
    n = len(CASI)
    print(f"\ncategoria sbagliata {err_cat}/{n} · gruppo sbagliato {err_grp}/{n} · liste diverse {err_lst}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
