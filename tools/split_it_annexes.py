# -*- coding: utf-8 -*-
"""ALLEGATI INCOLLATI (v9.363, 22 set 2026): negli atti EUR-Lex gli allegati (moduli, certificati, elenchi) finivano
DENTRO l'ultimo articolo — bruxelles_ii_ter art. 105 = 88.924 chr, alimenti_ue 76, codice_frontiere_schengen 45,
codice_visti 9 e 58, notifiche_ue 37, reg_ue_2018_1806 15, bruxelles_i_bis 81, small_claims_ue 29 (9 atti). Qui si
separano: l'articolo si ferma alla prima intestazione «ALLEGATO N» a sé stante; il resto diventa unità
`allegato-<n>` (una per intestazione), come già fanno gli allegati Normattiva (v9.348).

    docker exec super-avvocato python3 tools/split_it_annexes.py            # rapporto a secco
    docker exec super-avvocato python3 tools/split_it_annexes.py --apply    # riscrive i JSON (backup) → poi build_it_index.py
"""
import argparse, glob, json, re, shutil, sys, time
from pathlib import Path

ACTS = Path("/app/data/processed/it_acts")
_HEAD = re.compile(r"(?m)^[ \t]*(ALLEGATO|ANNEX|ANNESSO)[ \t]+([IVXLC]+|\d+)([A-Za-z\-]*)[ \t]*$")
MIN_POS = 200          # un'intestazione nei primi 200 chr è l'inizio dell'unità stessa, non una coda incollata
MIN_UNIT = 40          # unità più corte (l'elenco dei titoli «ALLEGATO I ALLEGATO II …») si scartano


def _num(m) -> str:
    return "allegato-" + (m.group(2) + m.group(3)).lower()


def split_annexes(arts: list[dict]) -> tuple[list[dict], list[str]]:
    """Torna (articoli nuovi, note). Solo articoli NON già «allegato/tabella»; il testo prima della prima
    intestazione resta nell'articolo; ogni «ALLEGATO N» a sé stante apre un'unità nuova (saltata se esiste già)."""
    have = {str(a.get("number", "")).lower() for a in arts}
    out, note = [], []
    for a in arts:
        n = str(a.get("number", "")); body = a.get("body", "") or ""
        if n.lower().startswith(("allegato", "annex", "annesso", "tabell")):
            out.append(a); continue
        heads = [m for m in _HEAD.finditer(body) if m.start() > MIN_POS]
        if not heads:
            out.append(a); continue
        cut = heads[0].start()
        a2 = dict(a); a2["body"] = body[:cut].rstrip()
        out.append(a2)
        added = 0
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            unit = body[m.start():end].strip()
            num = _num(m)
            if len(unit) < MIN_UNIT or num in have:
                continue
            titolo = next((ln.strip() for ln in unit.splitlines()[1:] if ln.strip()), "")[:120]
            out.append({"number": num, "heading": (m.group(0).strip() + (" — " + titolo if titolo else ""))[:300],
                        "body": unit, "repealed": False, "in_force_from": a.get("in_force_from", "")})
            have.add(num); added += 1
        note.append(f"art. {n}: {len(body)} → {len(a2['body'])} chr, +{added} allegati")
    return out, note


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    tot = 0
    for p in sorted(glob.glob(str(ACTS / "*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        arts = d.get("articles") if isinstance(d, dict) else None
        if not isinstance(arts, list):
            continue
        new, note = split_annexes(arts)
        if not note:
            continue
        tot += 1
        print(f"[{Path(p).stem}] {'; '.join(note)} → articoli {len(arts)} → {len(new)}")
        if a.apply:
            bak = Path(p + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"); shutil.copy2(p, bak)
            d["articles"] = new
            Path(p).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    print(f"{tot} atti con allegati incollati{' — RISCRITTI (backup .bak-*), ora: python3 tools/build_it_index.py' if a.apply else ' (prova a secco: --apply per riscrivere)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
