# -*- coding: utf-8 -*-
"""v9.409 — IMPOSTE IPOTECARIA E CATASTALE (d.lgs. 347/1990): la Tariffa e la Tabella delle tasse ipotecarie entravano VUOTE
(«TARIFFA ((24))», «[senza testo]»): sono tabelle disegnate a caratteri, la seconda fuori dal contenitore `table-akn` e dentro il
testo modificato «((…))». Si rileggono con `normattiva_lib.tabelle_keep80_in_testo`.

La Tariffa porta le cifre ORIGINARIE: «1,60» per la trascrizione (portata al 2 per cento dalla L. 549/1995) e «100.000» lire per
le misure fisse (oggi 200 euro). Normattiva mette i cambi nelle note di aggiornamento, che il parser toglie dal testo: qui le note
UFFICIALI della pagina entrano in coda al testo, e la misura fissa di oggi — verificata sul testo vigente dell'art. 26, c. 2, D.L.
104/2013 — si dichiara come nota nostra. Backup.

    python3 tools/fix_ipotecaria_it.py [--dry]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402

F = Path("/var/www/apps/super-avvocato/data/processed/it_acts/imposta_ipotecaria_catastale.json")
RUBRICHE = {"tariffa": "Tariffa — imposta ipotecaria (trascrizioni, iscrizioni, annotazioni: aliquote e misure fisse)",
            "tabella": "Tabella delle tasse per i servizi ipotecari e catastali"}
NOTA_FISSA = ("Nota di collegamento (redazionale, non del testo ufficiale): le cifre in lire della Tariffa sono le misure "
              "originarie. Per l'art. 26, comma 2, D.L. 12 settembre 2013, n. 104 (conv. L. 8 novembre 2013, n. 128) «l'importo "
              "di ciascuna delle imposte di registro, ipotecaria e catastale stabilito in misura fissa di euro 168» è di euro 200 "
              "dal 1° gennaio 2014. Le aliquote proporzionali vigenti risultano dalle note di aggiornamento qui sotto (art. 1: "
              "2 per cento, L. 549/1995).")


def main():
    dry = "--dry" in sys.argv
    j = json.loads(F.read_text(encoding="utf-8"))
    arts = {str(a["number"]): a for a in j["articles"]}
    nm = nl.Normattiva(delay=0.6)
    links = nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + time.strftime("%Y-%m-%d")))
    fatte = 0
    for h, lab, _g in links:
        num = lab.strip().lower()
        if num not in RUBRICHE or num not in arts:
            continue
        p = nm.fetch_article(h)
        nuovo = nl.parse_article_page(nl.tabelle_keep80_in_testo(p), fallback_number=num) or {}
        b = re.sub(r"^\s*TARIFFA\s*\n+", "", nuovo.get("body") or "")
        b = re.sub(r"^\s*\(\(\s*Tabella delle tasse[^\n]*\n+", "", b)
        b = re.sub(r"\n*\(\(\s*\d{1,3}\s*\)\)\s*$", "", b).strip()
        if len(b) < 500:
            print(f"  ? {num}: testo riletto troppo corto ({len(b)}), lasciato com'era"); continue
        note = [x for x in (nuovo.get("notes") or []) if re.search(r"(?i)aliquot|per cento|euro|lire", x.get("text") or "")]
        if num == "tariffa" and note:
            b += "\n\nNote di aggiornamento (testo ufficiale di Normattiva):\n" + "\n".join(
                "— " + re.sub(r"\s+", " ", x["text"]).strip() for x in note)
        a = arts[num]
        a["heading"], a["body"], a["repealed"] = RUBRICHE[num], b, False
        if nuovo.get("notes"):
            a["notes"] = nuovo["notes"]
        if num == "tariffa":
            a["note"] = NOTA_FISSA
        fatte += 1
        print(f"  {num}: {len(b)} caratteri, note ufficiali in coda {len(note) if num == 'tariffa' else 0}")
        print("   ", b[:300].replace("\n", " | "))
    if fatte and not dry:
        shutil.copy2(F, F.with_name(F.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-ipotecaria"))
        F.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"riletti {fatte}" + (" (a secco)" if dry else ""))


if __name__ == "__main__":
    main()
