# -*- coding: utf-8 -*-
"""QA del corpus italiano scaricato: completezza, pulizia, rubriche, spot-check
su articoli noti. Da eseguire PRIMA di costruire/pubblicare l'indice."""
import json, glob, re, sys
from pathlib import Path

D = Path("/var/www/apps/super-avvocato/data/processed/it_acts")
CHROME = ["articolo precedente", "articolo successivo", "Approfondimenti e Funzioni",
          "Testo in vigore dal", "flagTipoArticolo", "descrizione:", "tipoArticolo:"]

# articoli notissimi: (atto, numero, parola attesa nel testo)
SPOT = [
    ("codice_civile", "2043", "danno ingiusto"),
    ("codice_civile", "1418", "norme imperative"),
    ("codice_civile", "832", "godere"),
    ("codice_penale", "575", "morte di un uomo"),
    ("codice_penale", "624", "impossessa"),
    ("codice_procedura_civile", "163", "citazione"),
    ("codice_procedura_penale", "273", "gravi indizi"),
    ("costituzione", "21", "manifestare liberamente"),
    ("codice_strada", "186", "stato di ebbrezza"),
    ("codice_strada", "142", "velocit"),
    ("codice_consumo", "33", "vessator"),
    ("codice_crisi_impresa", "2", "crisi"),
    ("statuto_lavoratori", "18", "licenzia"),
    ("tulps", "1", ""),
    ("codice_privacy", "1", ""),
    ("tu_bancario", "10", "attività bancaria"),
]

acts, problems = {}, []
files = sorted(D.glob("*.json"))
print(f"ATTI PRESENTI: {len(files)}/43\n")
print(f"{'ATTO':34s} {'ART':>5} {'SPORCHI':>7} {'NO-RUB':>7} {'CORTI':>6} {'MEDIA':>7}")
tot = 0
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    arts = d["articles"]
    acts[d["id"]] = {a["number"]: a for a in arts}
    tot += len(arts)
    dirty = sum(1 for a in arts if any(c in a["body"] for c in CHROME))
    norub = sum(1 for a in arts if not a["heading"])
    short = sum(1 for a in arts if len(a["body"]) < 25 and not a["repealed"])
    avg = sum(len(a["body"]) for a in arts) / max(1, len(arts))
    flag = ""
    if dirty: flag += f"  SPORCO({dirty})"; problems.append((d["id"], "chrome", dirty))
    if d.get("failures"): flag += f"  FALLITI({len(d['failures'])})"; problems.append((d["id"], "fail", len(d["failures"])))
    print(f"{d['id']:34s} {len(arts):>5} {dirty:>7} {norub:>7} {short:>6} {avg:>7.0f}{flag}")

print(f"\nTOTALE ARTICOLI: {tot}")

print("\n=== SPOT-CHECK ARTICOLI NOTI ===")
missing = 0
for code, num, want in SPOT:
    a = acts.get(code, {}).get(num)
    if not a:
        print(f"  MANCA   {code} art.{num}")
        missing += 1
        continue
    hit = (want.lower() in a["body"].lower()) if want else True
    status = "OK " if hit else "TESTO-INATTESO"
    if not hit: missing += 1
    print(f"  {status:14s} {code:28s} art.{num:<6s} {a['heading'][:38]!r:42s} [{len(a['body'])}ch]")

print("\n=== ESITO ===")
print(f"atti: {len(files)}/43 | articoli: {tot} | problemi: {len(problems)} | spot-check falliti: {missing}")
sys.exit(0 if (len(files) == 43 and not problems and not missing) else 1)
