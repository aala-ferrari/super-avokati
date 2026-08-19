# -*- coding: utf-8 -*-
"""Ripara il corpus: confronta ogni atto con il numero di articoli ATTESO
(rilevato dall'albero dell'atto) e ri-scarica quelli incompleti o con errori.
Un solo flusso, delay più alto: niente rate limiting."""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, "/root")
from normattiva_lib import ingest_act
from ingest_it_normattiva import ACTS

OUT = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
OUT.mkdir(parents=True, exist_ok=True)
EXPECTED = {
    "codice_civile": 3217, "codice_penale": 978, "codice_procedura_civile": 982,
    "codice_procedura_penale": 902, "costituzione": 139, "disp_att_cc": 314,
    "disp_att_cpp": 325, "codice_strada": 266, "regolamento_strada": 409,
    "codice_consumo": 249, "codice_crisi_impresa": 415, "ordinamento_polizia": 118,
    "tulps": 234, "statuto_lavoratori": 41, "sicurezza_lavoro": 321,
    "tu_bancario": 346, "tu_finanza": 512, "codice_proprieta_industriale": 291,
    "codice_terzo_settore": 105, "codice_assicurazioni": 610, "responsabilita_enti": 105,
    "procedimento_amministrativo": 51, "codice_processo_amministrativo": 142,
    "codice_amministrazione_digitale": 123, "tu_documentazione_amministrativa": 92,
    "codice_contratti_pubblici": 241, "sanzioni_amministrative": 159,
    "tu_spese_giustizia": 316, "codice_privacy": 221, "codice_ambiente": 447,
    "tu_edilizia": 151, "tu_immigrazione": 77, "codice_antimafia": 136, "tuir": 235,
    "codice_beni_culturali": 194, "codice_navigazione": 1364, "stupefacenti": 145,
    "ordinamento_penitenziario": 137, "codice_pari_opportunita": 74,
    "codice_protezione_civile": 51, "divorzio": 18, "adozione": 92, "equa_riparazione": 15,
}
TOLL = 0.97   # accettiamo un minimo scarto (articoli senza testo)

todo = []
for cid, title, area, urn, wave in ACTS:
    want = EXPECTED.get(cid, 0)
    f = OUT / f"{cid}.json"
    if not f.exists():
        todo.append((cid, title, area, urn, wave, "mancante", 0, want)); continue
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        todo.append((cid, title, area, urn, wave, "illeggibile", 0, want)); continue
    got, fails = len(d["articles"]), len(d.get("failures") or [])
    if fails or (want and got < want * TOLL):
        todo.append((cid, title, area, urn, wave, f"{got}/{want} fail={fails}", got, want))

print(f"da riparare: {len(todo)}/{len(ACTS)}", flush=True)
for cid, *_rest in todo:
    print("   -", cid, ":", _rest[4], flush=True)

for cid, title, area, urn, wave, why, got, want in todo:
    print(f"\n▶ {cid} ({why})", flush=True)
    t0 = time.time()

    def prog(i, tot, ok, bad, _c=cid):
        print(f"    {_c}: {i}/{tot} ok={ok} fail={bad}", flush=True)

    try:
        arts, fails = ingest_act(urn, delay=0.75, progress=prog)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {cid} FALLITO: {type(e).__name__}: {str(e)[:150]}", flush=True)
        continue
    if want and len(arts) < want * TOLL:
        print(f"  ! {cid}: solo {len(arts)}/{want} — riprovo una volta", flush=True)
        arts2, fails2 = ingest_act(urn, delay=1.1, progress=prog)
        if len(arts2) > len(arts):
            arts, fails = arts2, fails2
    (OUT / f"{cid}.json").write_text(json.dumps(
        {"id": cid, "title": title, "area": area, "urn": urn, "wave": wave,
         "articles": arts, "failures": fails}, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ {cid}: {len(arts)}/{want} articoli, {len(fails)} falliti, {time.time()-t0:.0f}s", flush=True)

print("\nRIPARAZIONE COMPLETATA", flush=True)
