#!/usr/bin/env python3
"""v9.474 — AGGIORNA articolo per articolo un atto italiano già nel corpus col ri-download di Normattiva (al testo in vigore OGGI,
`VIGENTE_OGGI=1 IT_ACTS_DIR=…/it_acts_refreshN python3 tools/ingest_it_normattiva.py <id>`), senza perdere ciò che è stato
aggiunto a mano dopo il primo ingest (allegati rifatti, versioni future in `futuro`, note redazionali in `note`, articoli
recuperati). Il controllo di freschezza (`tools/freshness_check.py`) dice quali atti sono cambiati alla fonte.

    aggiorna_atti_it.py report --new it_acts_refresh3        → per atto: articoli cambiati / nuovi / spariti alla fonte
    aggiorna_atti_it.py apply  --new it_acts_refresh3 [ids…] → riscrive gli atti (backup .bak-<data>-aggiorna)

Regole: un articolo che c'è in tutti e due prende testo, rubrica, note e stato di abrogazione dal nuovo, e TIENE i campi che il
nuovo non ha (`futuro`, `note`, `vigente_fino`, …); uno nuovo alla fonte entra; uno che il nuovo non ha resta com'era (non si
cancella niente). Si aggiorna `fetched` (la freschezza). Solo stdlib, sull'host.
"""
import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path("/var/www/apps/super-avvocato/data/processed")
OLD = BASE / "it_acts"
CAMPI_DAL_NUOVO = ("body", "heading", "notes", "repealed")


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def confronta(o: dict, n: dict) -> tuple[list, list, list, dict]:
    oa = {a["number"]: a for a in o.get("articles") or []}
    na = {a["number"]: a for a in n.get("articles") or []}
    cambiati = [k for k in oa if k in na and (_norm(oa[k].get("body")) != _norm(na[k].get("body"))
                                              or bool(oa[k].get("repealed")) != bool(na[k].get("repealed")))]
    # un testo nuovo molto più CORTO del vecchio non sostituisce: di solito il vecchio è una tabella riletta a mano (v9.406-409:
    # tariffe, allegati) che il parser semplice perde — si segnala e si lascia
    corti = [k for k in cambiati if not na[k].get("repealed") and len(_norm(na[k].get("body"))) < 0.7 * len(_norm(oa[k].get("body")))]
    # HTML rimasto nel testo («class="bodyTesto">»): il parser ha preso un'altra pagina (codice dell'ambiente, allegato I)
    corti += [k for k in cambiati if 'class="' in (na[k].get("body") or "") and k not in corti]
    nuovi_sporchi = [k for k in na if k not in oa and 'class="' in (na[k].get("body") or "")]
    for k in nuovi_sporchi:
        na.pop(k)
    if corti:
        print(f"    ⚠ non sostituiti (testo nuovo molto più corto, probabilmente una tabella riletta): {', '.join(corti[:10])}")
    cambiati = [k for k in cambiati if k not in corti]
    nuovi = [k for k in na if k not in oa]
    spariti = [k for k in oa if k not in na]
    return cambiati, nuovi, spariti, na


def main() -> int:
    modo = sys.argv[1] if len(sys.argv) > 1 else "report"
    nuova = BASE / (sys.argv[sys.argv.index("--new") + 1] if "--new" in sys.argv else "it_acts_refresh3")
    salta = set((sys.argv[sys.argv.index("--salta") + 1].split(",")) if "--salta" in sys.argv else [])
    ids = [a for a in sys.argv[2:] if not a.startswith("--") and a != nuova.name and a not in salta
           and not ("--salta" in sys.argv and a == sys.argv[sys.argv.index("--salta") + 1])]
    stamp = time.strftime("%Y%m%d-%H%M")
    for f in sorted(nuova.glob("*.json")):
        if ids and f.stem not in ids:
            continue
        n = json.loads(f.read_text(encoding="utf-8"))
        o_path = OLD / f.name
        if not o_path.exists():
            print(f"  ? {f.stem}: non è nel corpus — salto (atto nuovo: si aggiunge con l'ingest normale)")
            continue
        o = json.loads(o_path.read_text(encoding="utf-8"))
        if len(n.get("failures") or []) > len(o.get("failures") or []):
            print(f"  ✗ {f.stem}: il ri-download ha più fallimenti ({len(n.get('failures') or [])}) — salto")
            continue
        cambiati, nuovi, spariti, na = confronta(o, n)
        cambiati = [k for k in cambiati if f"{f.stem}:{k}" not in salta]       # --salta atto:numero,… (letti a mano: solo note)
        nuovi = [k for k in nuovi if f"{f.stem}:{k}" not in salta]
        print(f"  {f.stem:28s} cambiati {len(cambiati):4d} · nuovi {len(nuovi):3d} · spariti alla fonte {len(spariti):3d} (restano)"
              + (f" · es. {', '.join(cambiati[:6])}" if cambiati else ""))
        if modo != "apply":
            continue
        if not (cambiati or nuovi):
            # v9.475: niente di sostanziale (solo note o tabelle tenute) — la data del controllo si aggiorna lo stesso, altrimenti il
            # controllo di freschezza continua a segnalarlo «da aggiornare»
            if n.get("fetched") and n["fetched"] > (o.get("fetched") or ""):
                o["fetched"] = n["fetched"]
                o_path.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
                print(f"    ✓ solo la data di controllo ({n['fetched']})")
            continue
        shutil.copy2(o_path, str(o_path) + f".bak-{stamp}-aggiorna")
        for a in o["articles"]:
            if a["number"] in cambiati:
                for k in CAMPI_DAL_NUOVO:
                    if k in na[a["number"]] and not (k == "heading" and not na[a["number"]][k] and a.get(k)):
                        a[k] = na[a["number"]][k]      # una rubrica vuota nel nuovo non cancella quella che c'è
        o["articles"].extend(na[k] for k in nuovi)
        o["fetched"] = n.get("fetched") or time.strftime("%Y-%m-%d")
        if n.get("vigente_al"):
            o["vigente_al"] = n["vigente_al"]
        o_path.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
        print(f"    ✓ aggiornato (backup .bak-{stamp}-aggiorna)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
