# -*- coding: utf-8 -*-
"""Metadati dell'ATTO per ogni codice del corpus → data/index/acts_meta.json (roadmap v4, punto 6, 20 set 2026).

    docker exec super-avvocato python3 tools/build_acts_meta.py

AL: dalla tabella QBZ (tools/al_sources.json): l'URL WebDAV porta data e numero
(«…/ligj/kuvendi-i-shqiperise/2021/06/24/79/cons-2025-07-14/…»), `consolidated` la data del testo
consolidato e le leggi modificanti; il tipo (ligj/vendim) dal percorso. IT: dalla URN Normattiva
(«decreto.legislativo:1992-04-30;285») in it_acts/*.json + `fetched`; gli atti EUR-Lex/CEDU dal loro
campo `urn`/`source`. Il cervello riceve la riga «📜 Ligji nr. 79/2021, datë 24.6.2021 — teksti i
konsoliduar 2025-07-14 (ndryshuar nga ligji 43/2025)» sotto ogni articolo (src/acts_meta.py).
"""
import json, os, re, sys
from pathlib import Path

ROOT = Path(os.environ.get("APP_ROOT", "/app"))
SRC_AL = Path(os.environ.get("AL_SOURCES", str(ROOT / "tools" / "al_sources.json")))
IT_ACTS = Path(os.environ.get("IT_ACTS_DIR", str(ROOT / "data" / "processed" / "it_acts")))
OUT = Path(os.environ.get("ACTS_META", str(ROOT / "data" / "index" / "acts_meta.json")))

_TIPO_IT = {"decreto.legislativo": "D.Lgs.", "legge": "L.", "decreto.legge": "D.L.", "decreto.del.presidente.della.repubblica": "D.P.R.",
            "decreto.presidente.repubblica": "D.P.R.", "regio.decreto": "R.D.", "costituzione": "Cost.", "legge.costituzionale": "L. cost.",
            "decreto.ministeriale": "D.M.", "regolamento": "Reg."}
_MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _al() -> dict:
    out = {}
    try:
        d = json.loads(SRC_AL.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("al_sources.json illeggibile:", exc); return out
    for l in d.get("laws") or []:
        code = l.get("code") or l.get("replace")
        if not code:
            continue
        url = l.get("url") or ""
        m = re.search(r"/Aktet/(ligj|vendim|dekret|urdh[eë]r|rregullore)/[^/]+/(\d{4})/(\d{2})/(\d{2})/([^/]+)/", url)
        tipo = {"ligj": "Ligji", "vendim": "VKM", "dekret": "Dekreti"}.get(m.group(1), "Akti") if m else ("Ligji" if "ligj" in (l.get("title_sq") or "").lower() else "Akti")
        num = m.group(5) if m else None
        year, mo, day = (m.group(2), m.group(3), m.group(4)) if m else (None, None, None)
        cons = l.get("consolidated") or ""
        mc = re.search(r"cons\s+(\d{4}-\d{2}-\d{2})", cons)
        mod = re.search(r"\(([^)]*)\)", cons)
        out[code] = {
            "jur": "AL", "tipo": tipo, "numero": num, "anno": year,
            "data": f"{int(day)}.{int(mo)}.{year}" if m else None, "data_iso": f"{year}-{mo}-{day}" if m else None,
            "titolo": l.get("title_sq") or "", "consolidato": mc.group(1) if mc else ("base" if cons.startswith("base") else None),
            "modificato_da": (mod.group(1) if mod and "ligj" in mod.group(1).lower() or (mod and re.search(r"\d+/\d{4}", mod.group(1))) else None),
            "fonte": "QBZ",
        }
    return out


def _it() -> dict:
    out = {}
    for f in sorted(IT_ACTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        code = d.get("id") or f.stem
        urn = d.get("urn") or ""
        m = re.match(r"([a-z.]+):(\d{4})-(\d{2})-(\d{2});(\d+)", urn)
        if m:
            tipo = _TIPO_IT.get(m.group(1), m.group(1))
            y, mo, day, num = m.group(2), m.group(3), m.group(4), m.group(5)
            out[code] = {"jur": "IT", "tipo": tipo, "numero": num, "anno": y, "data": f"{int(day)} {_MESI_IT[int(mo)-1]} {y}",
                         "data_iso": f"{y}-{mo}-{day}", "titolo": d.get("title") or "", "consolidato": d.get("fetched"),
                         "modificato_da": None, "fonte": "Normattiva"}
        else:
            out[code] = {"jur": "IT", "tipo": None, "numero": None, "anno": None, "data": None, "data_iso": None,
                         "titolo": d.get("title") or "", "consolidato": d.get("fetched"), "modificato_da": None,
                         "fonte": ("Corte EDU (PDF ufficiale)" if code.startswith("cedu") else
                                   "EUR-Lex" if (code.startswith(("reg_ue", "bruxelles", "roma_", "codice_doganale_ue", "codice_frontiere", "codice_visti", "gdpr", "tfue", "tue", "carta_diritti", "alimenti_ue", "ingiunzione_europea", "notifiche_ue", "small_claims", "regimi_patrimoniali", "successioni_ue")) or "celex" in urn.lower() or "eur-lex" in (d.get("source") or "").lower())
                                   else "Normattiva")}
    return out


def main() -> int:
    meta = {}
    meta.update(_al()); meta.update(_it())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    al = [k for k, v in meta.items() if v["jur"] == "AL"]; it = [k for k, v in meta.items() if v["jur"] == "IT"]
    print(f"acts_meta.json: {len(meta)} atti (AL {len(al)}: {sum(1 for k in al if meta[k]['numero'])} con numero/data; "
          f"IT {len(it)}: {sum(1 for k in it if meta[k]['numero'])} con numero/data) → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
