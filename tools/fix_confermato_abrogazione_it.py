# -*- coding: utf-8 -*-
"""v9.405 — gli articoli la cui unica «versione» è la nota «IL D.LGS. … HA CONFERMATO L'ABROGAZIONE DEL PRESENTE ARTICOLO» erano
nel corpus come VIVI (`normattiva_lib.is_repealed` non riconosceva la frase): c.c. 91, 292, 342, 2623, codice dell'ambiente 49, codice
della navigazione 840… e, nella versione futura, gli articoli dei vecchi atti fiscali abrogati da anni (d.lgs. 74/2000 art. 7,
d.P.R. 633/1972 art. 47, d.P.R. 600/1973 artt. 7 e 51). Qui si segnano abrogati SOLO quelli che portano quella nota nei primi 400
caratteri (non si ricalcola nient'altro: la regola del «moncone» ha falsi positivi noti sugli articoli «Abrogazione»). Backup.

    python3 tools/fix_confermato_abrogazione_it.py [--dry]
"""
import glob
import json
import re
import shutil
import sys
import time
from pathlib import Path

SRC = Path("/var/www/apps/super-avvocato/data/processed/it_acts")
# solo «DEL PRESENTE ARTICOLO»: «… DEL PRESENTE COMMA/PERIODO» (c.c. 1, d.P.R. 633/1972 art. 60, TUB 125-ter) è un pezzo, l'articolo vive
_RX = re.compile(r"CONFERMATO\s+L['’]\s*ABROGAZIONE\s+DEL\s+PRESENTE\s+ARTICOLO")


def main():
    dry = "--dry" in sys.argv
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tot_v = tot_f = 0
    for f in sorted(SRC.glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n_v = n_f = 0
        for a in j.get("articles") or []:
            if not a.get("repealed") and _RX.search(((a.get("heading") or "") + "\n" + (a.get("body") or ""))[:400]):
                a["repealed"] = True
                n_v += 1
                print(f"  {f.stem} art. {a.get('number')}: abrogato (era vivo)", flush=True)
            fu = a.get("futuro")
            if isinstance(fu, dict) and not fu.get("repealed") and _RX.search(((fu.get("heading") or "") + "\n" + (fu.get("body") or ""))[:400]):
                fu["repealed"] = True
                n_f += 1
        if (n_v or n_f) and not dry:
            shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-confermato"))
            f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
        tot_v += n_v; tot_f += n_f
    print(f"TOTALE: {tot_v} articoli vivi → abrogati · {tot_f} versioni future → abrogate{' (a secco)' if dry else ''}")


if __name__ == "__main__":
    main()
