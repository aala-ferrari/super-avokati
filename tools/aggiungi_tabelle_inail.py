# -*- coding: utf-8 -*-
"""v9.593 — le TABELLE DELLE MALATTIE PROFESSIONALI del testo unico INAIL (d.P.R. 1124/1965, allegati 4 e 5) nel corpus italiano.

La wave13 (v9.589) le aveva lasciate fuori: su Normattiva sono tabelle disegnate a caratteri (righe `keep80`) e il parser semplice
leggeva solo il titolo. Sono la norma che decide una malattia professionale: per ogni voce la malattia (col codice ICD-10), le
lavorazioni che la causano e il PERIODO MASSIMO DI INDENNIZZABILITÀ dalla cessazione della lavorazione (art. 3: per le malattie in
tabella la causa professionale si presume; fuori tabella la prova spetta al lavoratore). Si rileggono con
`normattiva_lib.tabelle_keep80_in_testo` (lo stesso lettore della v9.409) e si scrivono nel JSON dell'atto:
  un'unità per VOCE: «allegato-4-voce-71» («Allegato 4, voce 71»), «allegato-5-voce-3», con la riga delle colonne in testa (la
  durata finale «— 10 anni» è il periodo massimo di indennizzabilità) e la malattia nella rubrica. La prima stesura (blocchi di ~9.000
  caratteri, «allegato-4-1» … «-4») non entrava mai nel blocco del senior: la ricerca penalizza i testi lunghi e la voce cercata
  («ipoacusia», «mesotelioma») era una riga fra cento — i blocchi già scritti si sostituiscono.
Si scrive solo se il testo riletto è vero (≥ 2.000 caratteri e almeno 10 voci numerate). Backup del JSON. Sull'host:

    python3 tools/aggiungi_tabelle_inail.py [--dry]      → poi build_it_index.py, build_acts_meta.py, build_dense.py --incremental
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402

SRC = Path(sys.argv[sys.argv.index("--src") + 1]) if "--src" in sys.argv else \
    Path("/var/www/apps/super-avvocato/data/processed/it_acts/tu_infortuni.json")
TABELLE = (
    ("Allegato n. 4", "4", "Allegato 4 — Tabella delle malattie professionali nell'industria (art. 3)"),
    ("Allegato n. 5", "5", "Allegato 5 — Tabella delle malattie professionali nell'agricoltura (art. 211)"),
)
_VOCE = re.compile(r"^(\d{1,3})\)\s", re.M)


def _pulisci(b: str) -> str:
    """Toglie la testata ripetuta («TABELLE / ALLEGATO N. 4 / Tabella») e i segni del testo modificato «(( … ))»."""
    b = re.sub(r"^\s*TABELLE\s*\n+\s*ALLEGATO\s+N\.\s*\d+\s*\n+\s*Tabella\s*\n+", "", b.strip())
    b = re.sub(r"^\(\(\s*|\s*\)\)\s*$", "", b.strip(), flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", b).strip()


def main() -> int:
    dry = "--dry" in sys.argv
    j = json.loads(SRC.read_text(encoding="utf-8"))
    if any("-voce-" in str(a["number"]) for a in j["articles"]):
        print("le voci delle tabelle ci sono già — niente da fare"); return 0
    _vecchi = [a for a in j["articles"] if str(a["number"]).startswith("allegato-4-") or str(a["number"]) == "allegato-5"]
    nm = nl.Normattiva(delay=0.6)
    links = {l.strip(): h for h, l, _g in nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + time.strftime("%Y-%m-%d")))}
    nuovi = []
    for lab, n, rub in TABELLE:
        if lab not in links:
            print(f"  ? {lab}: link non trovato"); continue
        page = nm.fetch_article(links[lab])
        a = nl.parse_article_page(nl.tabelle_keep80_in_testo(page), fallback_number=lab) or {}
        b = _pulisci(a.get("body") or "")
        nvoci = len(_VOCE.findall(b))
        if len(b) < 2000 or nvoci < 10:
            print(f"  ? {lab}: riletto {len(b)} caratteri, {nvoci} voci — lasciato fuori"); continue
        starts = [m.start() for m in _VOCE.finditer(b)]
        testa = b[:starts[0]].strip()      # «MALATTIE (ICD-10) — LAVORAZIONI — Periodo massimo di indennizzabilità …»
        for s0, s1 in zip(starts, starts[1:] + [len(b)]):
            voce = b[s0:s1].strip()
            nv = _VOCE.match(voce).group(1)
            prima = re.sub(r"^\d{1,3}\)\s*", "", voce.split("\n")[0]).split(" — ")[0].strip().rstrip(":")
            num = f"allegato-{n}-voce-{nv}"
            head = f"{rub} — voce {nv}: {prima[:150]}"
            nuovi.append({"number": num, "heading": head, "body": (testa + "\n" if testa else "") + voce, "repealed": False,
                          "in_force_from": "", "group": n, "aggiunto": time.strftime("%Y-%m-%d"), "aggiunto_da": "aggiungi_tabelle_inail"})
        print(f"  {lab}: {nvoci} voci → allegato-{n}-voce-1 … -{_VOCE.match(b[starts[-1]:]).group(1)}")
    if not nuovi:
        print("niente di nuovo"); return 1
    if dry:
        return 0
    shutil.copy2(SRC, SRC.with_name(SRC.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-tabelle-inail"))
    j["articles"] = [a for a in j["articles"] if a not in _vecchi] + nuovi
    if _vecchi:
        print(f"tolti {len(_vecchi)} blocchi della prima stesura: {', '.join(str(a['number']) for a in _vecchi)}")
    j["note_ingest"] = (j.get("note_ingest", "") + " · v9.593: rientrano gli allegati 4 e 5 (tabelle delle malattie professionali, "
                        "rilette dalle righe a caratteri), un'unità per voce").strip(" ·")
    SRC.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    print(f"scritto {SRC} (+{len(nuovi)} unità)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
