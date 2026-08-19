# -*- coding: utf-8 -*-
"""Ingest the Italian legal corpus from NORMATTIVA (official consolidated texts).
Italian statutes carry no copyright (Art. 5 L. 633/1941).

Resume-safe: each act is written to /app/data/processed/it_acts/<id>.json as
soon as it completes, so an interrupted run continues where it stopped.
Building the index is a separate step (build_it_index.py) — this script only
downloads, so it never touches the live index.

  python3 /tmp/ingest_it_normattiva.py            # all acts (resume)
  python3 /tmp/ingest_it_normattiva.py wave1      # only a wave
"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, "/tmp")
sys.path.insert(0, "/app")
from normattiva_lib import ingest_act

OUT = Path(os.environ.get("IT_ACTS_DIR", "/app/data/processed/it_acts"))
OUT.mkdir(parents=True, exist_ok=True)

# (id, titolo, area, urn, wave)
ACTS = [
    # ── base: i codici fondamentali (versione ufficiale, più completa di Wikisource) ──
    ("codice_civile", "Codice Civile", "Civile", "regio.decreto:1942-03-16;262", "base"),
    ("codice_penale", "Codice Penale", "Penale", "regio.decreto:1930-10-19;1398", "base"),
    ("codice_procedura_civile", "Codice di Procedura Civile", "Procedura Civile", "regio.decreto:1940-10-28;1443", "base"),
    ("codice_procedura_penale", "Codice di Procedura Penale", "Procedura Penale", "decreto.presidente.repubblica:1988-09-22;447", "base"),
    ("costituzione", "Costituzione della Repubblica Italiana", "Costituzionale", "costituzione:1947-12-27", "base"),
    ("disp_att_cc", "Disposizioni di attuazione del Codice Civile", "Civile", "regio.decreto:1942-03-30;318", "base"),
    ("disp_att_cpp", "Disposizioni di attuazione del Codice di Procedura Penale", "Procedura Penale", "decreto.legislativo:1989-07-28;271", "base"),
    # ── wave1: strada, consumo, crisi d'impresa, polizia ──
    ("codice_strada", "Codice della Strada", "Strada", "decreto.legislativo:1992-04-30;285", "wave1"),
    ("regolamento_strada", "Regolamento di esecuzione del Codice della Strada", "Strada", "decreto.presidente.repubblica:1992-12-16;495", "wave1"),
    ("codice_consumo", "Codice del Consumo", "Consumo", "decreto.legislativo:2005-09-06;206", "wave1"),
    ("codice_crisi_impresa", "Codice della Crisi d'Impresa e dell'Insolvenza", "Impresa", "decreto.legislativo:2019-01-12;14", "wave1"),
    ("ordinamento_polizia", "Ordinamento dell'Amministrazione della Pubblica Sicurezza", "Sicurezza", "legge:1981-04-01;121", "wave1"),
    ("tulps", "Testo Unico delle Leggi di Pubblica Sicurezza (TULPS)", "Sicurezza", "regio.decreto:1931-06-18;773", "wave1"),
    # ── wave2: imprese e lavoro ──
    ("statuto_lavoratori", "Statuto dei Lavoratori", "Lavoro", "legge:1970-05-20;300", "wave2"),
    ("sicurezza_lavoro", "Testo Unico Sicurezza sul Lavoro", "Lavoro", "decreto.legislativo:2008-04-09;81", "wave2"),
    ("tu_bancario", "Testo Unico Bancario", "Bancario", "decreto.legislativo:1993-09-01;385", "wave2"),
    ("tu_finanza", "Testo Unico della Finanza", "Finanza", "decreto.legislativo:1998-02-24;58", "wave2"),
    ("codice_proprieta_industriale", "Codice della Proprietà Industriale", "Impresa", "decreto.legislativo:2005-02-10;30", "wave2"),
    ("codice_terzo_settore", "Codice del Terzo Settore", "Impresa", "decreto.legislativo:2017-07-03;117", "wave2"),
    ("codice_assicurazioni", "Codice delle Assicurazioni Private", "Assicurazioni", "decreto.legislativo:2005-09-07;209", "wave2"),
    ("responsabilita_enti", "Responsabilità amministrativa degli enti (D.Lgs 231/2001)", "Impresa", "decreto.legislativo:2001-06-08;231", "wave2"),
    # ── wave3: procedure e amministrativo ──
    ("procedimento_amministrativo", "Legge sul Procedimento Amministrativo (L. 241/1990)", "Amministrativo", "legge:1990-08-07;241", "wave3"),
    ("codice_processo_amministrativo", "Codice del Processo Amministrativo", "Amministrativo", "decreto.legislativo:2010-07-02;104", "wave3"),
    ("codice_amministrazione_digitale", "Codice dell'Amministrazione Digitale", "Amministrativo", "decreto.legislativo:2005-03-07;82", "wave3"),
    ("tu_documentazione_amministrativa", "Testo Unico Documentazione Amministrativa", "Amministrativo", "decreto.presidente.repubblica:2000-12-28;445", "wave3"),
    ("codice_contratti_pubblici", "Codice dei Contratti Pubblici", "Amministrativo", "decreto.legislativo:2023-03-31;36", "wave3"),
    ("sanzioni_amministrative", "Sanzioni amministrative (L. 689/1981)", "Amministrativo", "legge:1981-11-24;689", "wave3"),
    ("tu_spese_giustizia", "Testo Unico Spese di Giustizia", "Procedura Civile", "decreto.presidente.repubblica:2002-05-30;115", "wave3"),
    # ── wave4: altri fondamentali ──
    ("codice_privacy", "Codice in materia di protezione dei dati personali (Privacy)", "Privacy", "decreto.legislativo:2003-06-30;196", "wave4"),
    ("codice_ambiente", "Codice dell'Ambiente", "Ambiente", "decreto.legislativo:2006-04-03;152", "wave4"),
    ("tu_edilizia", "Testo Unico dell'Edilizia", "Edilizia", "decreto.presidente.repubblica:2001-06-06;380", "wave4"),
    ("tu_immigrazione", "Testo Unico sull'Immigrazione", "Immigrazione", "decreto.legislativo:1998-07-25;286", "wave4"),
    ("codice_antimafia", "Codice Antimafia", "Penale", "decreto.legislativo:2011-09-06;159", "wave4"),
    ("tuir", "Testo Unico delle Imposte sui Redditi", "Tributario", "decreto.legislativo:2026-06-19;117", "wave4"),
    ("codice_beni_culturali", "Codice dei Beni Culturali e del Paesaggio", "Beni Culturali", "decreto.legislativo:2004-01-22;42", "wave4"),
    ("codice_navigazione", "Codice della Navigazione", "Navigazione", "regio.decreto:1942-03-30;327", "wave4"),
    ("stupefacenti", "Testo Unico Stupefacenti", "Penale", "decreto.presidente.repubblica:1990-10-09;309", "wave4"),
    ("ordinamento_penitenziario", "Ordinamento Penitenziario", "Penale", "legge:1975-07-26;354", "wave4"),
    ("codice_pari_opportunita", "Codice delle Pari Opportunità", "Civile", "decreto.legislativo:2006-04-11;198", "wave4"),
    ("codice_protezione_civile", "Codice della Protezione Civile", "Amministrativo", "decreto.legislativo:2018-01-02;1", "wave4"),
    ("divorzio", "Legge sul Divorzio (L. 898/1970)", "Famiglia", "legge:1970-12-01;898", "wave4"),
    ("adozione", "Legge sull'Adozione (L. 184/1983)", "Famiglia", "legge:1983-05-04;184", "wave4"),
    ("equa_riparazione", "Legge Pinto — equa riparazione (L. 89/2001)", "Procedura Civile", "legge:2001-03-24;89", "wave4"),
]


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    todo = [a for a in ACTS if not want or a[4] == want]
    print(f"acts to process: {len(todo)}" + (f" (wave={want})" if want else ""), flush=True)
    for cid, title, area, urn, wave in todo:
        dest = OUT / f"{cid}.json"
        if dest.exists():
            try:
                n = len(json.loads(dest.read_text(encoding="utf-8"))["articles"])
                print(f"= {cid:32s} già scaricato ({n} art) — salto", flush=True)
                continue
            except Exception:  # noqa: BLE001
                pass
        t0 = time.time()
        print(f"\n▶ {cid}  ({title})", flush=True)

        def prog(i, tot, ok, bad, _c=cid):
            print(f"    {_c}: {i}/{tot} ok={ok} fail={bad}", flush=True)

        try:
            arts, fails = ingest_act(urn, delay=0.4, progress=prog)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {cid} FALLITO: {type(e).__name__}: {str(e)[:120]}", flush=True)
            continue
        payload = {"id": cid, "title": title, "area": area, "urn": urn, "wave": wave,
                   "articles": arts, "failures": fails}
        dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ {cid}: {len(arts)} articoli, {len(fails)} falliti, "
              f"{time.time()-t0:.0f}s -> {dest.name}", flush=True)

    done = sorted(OUT.glob("*.json"))
    tot = 0
    for f in done:
        try:
            tot += len(json.loads(f.read_text(encoding="utf-8"))["articles"])
        except Exception:  # noqa: BLE001
            pass
    print(f"\n\nSTATO: {len(done)} atti scaricati, {tot} articoli totali", flush=True)


if __name__ == "__main__":
    main()
