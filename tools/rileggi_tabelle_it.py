# -*- coding: utf-8 -*-
"""v9.409 — pagine di allegato entrate col SOLO nome («Tabella 1», «Allegato III-bis», «[senza testo]») perché il testo è una
tabella (HTML o disegnata a caratteri) che il parser scartava: si rileggono con `normattiva_lib.tabelle_keep80_in_testo`. Si
scrive solo se il testo riletto è vero (≥300 caratteri). Backup per atto.

    python3 tools/rileggi_tabelle_it.py [--dry]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402

SRC = Path("/var/www/apps/super-avvocato/data/processed/it_acts")
# (atto, numero nel JSON, etichetta del link su Normattiva, rubrica)
DA_RILEGGERE = [
    ("codice_contratti_pubblici", "tabella-1-all7", "Tabella 1", "Tabella 1 — tipologie di opere e soglie dimensionali"),
    ("tuir", "allegato-c", "Allegato C", "Allegato C — Imposizione minima globale: riduzione da attività economica sostanziale"),
    ("stupefacenti", "allegato-iii-bis", "Allegato III bis",
     "Allegato III-bis — Medicinali che usufruiscono delle modalità prescrittive semplificate (terapia del dolore)"),
]


def main():
    dry = "--dry" in sys.argv
    per_atto = {}
    for cid, num, lab, rub in DA_RILEGGERE:
        per_atto.setdefault(cid, []).append((num, lab, rub))
    for cid, voci in per_atto.items():
        f = SRC / f"{cid}.json"
        j = json.loads(f.read_text(encoding="utf-8"))
        arts = {str(a["number"]): a for a in j["articles"]}
        nm = nl.Normattiva(delay=0.6)
        links = {l.strip(): h for h, l, _g in nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + time.strftime("%Y-%m-%d")))}
        cambiati = 0
        for num, lab, rub in voci:
            if num not in arts or lab not in links:
                print(f"  ? {cid} {num}: {'non nel JSON' if num not in arts else 'link non trovato'}"); continue
            nuovo = nl.parse_article_page(nl.tabelle_keep80_in_testo(nm.fetch_article(links[lab])), fallback_number=num) or {}
            b = re.sub(r"\n{3,}", "\n\n", (nuovo.get("body") or "").strip())
            if len(b) < 300:
                print(f"  ? {cid} {num}: riletto {len(b)} caratteri, lasciato com'era ({b[:80]!r})"); continue
            a = arts[num]
            a["body"] = b
            if rub:
                a["heading"] = rub
            elif not (a.get("heading") or "").strip():
                prima = next((r.strip() for r in b.split("\n") if len(r.strip()) > 12), "")
                a["heading"] = (lab + " — " + prima[:110]) if prima else lab
            cambiati += 1
            print(f"  {cid} {num}: {len(b)} caratteri · {a['heading'][:90]}")
        if cambiati and not dry:
            shutil.copy2(f, f.with_name(f.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-tabelle"))
            f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
