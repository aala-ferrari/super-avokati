"""v9.434 — MISURA dei TERMINI DI LEGGE che partono da un evento del documento (`afati.compute`: articoli del corpus → righe
AFAT → data dal motore deterministico), la strada che lo scadenziario usa per sentenze, decreti, licenziamenti. Casi con la risposta
scritta prima e verificata sul codice: la data attesa deve uscire, con la BASE (l'articolo) giusta. Nessun database, nessun avviso.

    docker run --rm --env-file … -v <copia credenziali>:/home/avvocato/.claude super-avvocato:vX python3 tools/eval_afati.py
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CASI = [
    {"id": "al_vendim_civil", "g": "AL", "trigger": "vendim_civil", "data": "18.09.2026",
     "fatti": "Vendim i Gjykatës së Rrethit Gjyqësor Durrës, datë 10.09.2026, njoftuar mbrojtësit të të paditurës më 18.09.2026.",
     "attesa": ("2026-10-05", r"\b443\b")},
    {"id": "al_vendim_penal", "g": "AL", "trigger": "vendim_penal", "data": "10.09.2026",
     "fatti": "Vendim i Gjykatës së Shkallës së Parë, shpallur në seancë më 10.09.2026 në prani të të pandehurit dhe të mbrojtësit.",
     "attesa": ("2026-09-25", r"\b415\b")},
    {"id": "al_ekzekutim", "g": "AL", "trigger": "ekzekutim", "data": "25.09.2026",
     "fatti": "Lajmërim për ekzekutim vullnetar i përmbaruesit gjyqësor, dorëzuar debitorit më 25.09.2026, për një detyrim "
              "kontraktor prej 1.250.000 lekësh (jo pagë, jo detyrim ushqimi).",
     "attesa": ("2026-10-05", r"\b517\b"), "anche": [("2026-10-26", r"\b609\b")]},
    # v9.456 — la lettera di licenziamento e l'atto amministrativo (prima: «tjeter», nessun articolo)
    {"id": "al_pushim", "g": "AL", "trigger": "pushim_nga_puna", "data": "18.09.2026",
     "fatti": "Njoftim me shkrim për zgjidhjen me efekt të menjëhershëm të kontratës së punës me afat të pacaktuar, dorëzuar "
              "punëmarrësit më 18.09.2026, për «shkelje të disiplinës», pa paralajmërim të mëparshëm me shkrim.",
     "attesa": ("2027-03-17", r"\b155\b")},
    {"id": "al_akt_admin", "g": "AL", "trigger": "akt_administrativ", "data": "21.09.2026",
     "fatti": "Vendim i Inspektoratit Shtetëror të Punës për gjobë prej 500.000 lekësh ndaj shoqërisë, njoftuar shoqërisë "
              "më 21.09.2026.",
     "attesa": ("2026-10-21", r"\b132\b")},
    # v9.457 — la multa e l'accertamento fiscale
    {"id": "al_gjobe_rrugore", "g": "AL", "trigger": "kundervajtje", "data": "22.09.2026",
     "fatti": "Procesverbal i Policisë Rrugore për tejkalim shpejtësie, gjobë 10.000 lekë, i dorëzuar drejtuesit të mjetit në "
              "vend më 22.09.2026.",
     "attesa": ("2026-10-07", r"\b203\b")},
    {"id": "al_vleresim_tatimor", "g": "AL", "trigger": "vleresim_tatimor", "data": "21.09.2026",
     "fatti": "Njoftim vlerësimi tatimor dhe kërkesë për pagesë për TVSH të papaguar, 1.800.000 lekë, marrë nga shoqëria më "
              "21.09.2026.",
     "attesa": ("2026-10-21", r"\b106\b|\b69\b")},
    # v9.458 — la domanda ricevuta: AL termine FISSATO DALLA GJYKATA (KPC 158: al massimo 30 giorni) — col termine scritto si usa
    # quello, senza nessuna riga di 30 giorni; IT citazione: i termini del convenuto A RITROSO dall'udienza di comparizione
    {"id": "al_padi_afat", "g": "AL", "trigger": "padi_e_marre", "data": "23.09.2026",
     "fatti": "Kërkesëpadi për detyrim kontraktor, njoftuar të paditurit më 23.09.2026 bashkë me njoftimin e gjykatës që i kërkon "
              "të paraqesë deklaratën e mbrojtjes brenda 20 ditëve nga njoftimi.",
     "attesa": ("2026-10-13", r"\b158\b"), "mai": ["2026-10-23"]},
    {"id": "al_padi_pa_afat", "g": "AL", "trigger": "padi_e_marre", "data": "23.09.2026",
     "fatti": "Kërkesëpadi për detyrim kontraktor, njoftuar të paditurit më 23.09.2026; gjykata nuk ka caktuar ende afatin për "
              "deklaratën e mbrojtjes.",
     "attesa": None, "mai": ["2026-10-23"]},
    {"id": "it_decreto_ingiuntivo", "g": "IT", "trigger": "decreto_ingiuntivo", "data": "15.09.2026",
     "fatti": "Decreto ingiuntivo n. 8812/2026 del Tribunale di Milano, notificato a mezzo PEC il 15.09.2026.",
     "attesa": ("2026-10-26", r"\b641\b")},
    {"id": "it_precetto", "g": "IT", "trigger": "precetto", "data": "15.09.2026",
     "fatti": "Atto di precetto per euro 23.400 fondato su una sentenza del Tribunale di Milano, notificato al debitore il "
              "15.09.2026, con intimazione a pagare entro dieci giorni.",
     # (v9.457: il 481 — entro quando il CREDITORE deve iniziare l'esecuzione — è un termine della controparte del debitore che ha
     # ricevuto il precetto: va nella tabella, non nel calendario; prima era fra le attese)
     "attesa": ("2026-10-05", r"\b617\b"), "anche": [("2026-09-25", r"\b480\b")]},
    {"id": "it_licenziamento", "g": "IT", "trigger": "pushim_nga_puna", "data": "17.09.2026",
     "fatti": "Lettera di licenziamento per giustificato motivo oggettivo datata 15.09.2026, ricevuta dal lavoratore con "
              "raccomandata il 17.09.2026; azienda con 40 dipendenti, lavoratore assunto nel 2019.",
     "attesa": ("2026-11-16", r"604")},
    {"id": "it_provvedimento", "g": "IT", "trigger": "akt_administrativ", "data": "21.09.2026",
     "fatti": "Decreto del Questore di rigetto dell'istanza di rinnovo del permesso di soggiorno, notificato all'interessato "
              "il 21.09.2026.",
     "attesa": ("2026-11-20", r"\b29\b|\b41\b")},
    {"id": "it_verbale_cds", "g": "IT", "trigger": "kundervajtje", "data": "22.09.2026",
     "fatti": "Verbale di accertamento per eccesso di velocità rilevato da autovelox, non contestato immediatamente, notificato "
              "al proprietario del veicolo (residente in Italia) il 22.09.2026; sanzione di euro 173.",
     "attesa": ("2026-10-22", r"\b7\b|204")},
    {"id": "it_accertamento", "g": "IT", "trigger": "vleresim_tatimor", "data": "21.09.2026",
     "fatti": "Avviso di accertamento IRPEF per l'anno 2021, notificato al contribuente il 21.09.2026; nessuna istanza di "
              "accertamento con adesione presentata.",
     "attesa": ("2026-11-20", r"\b21\b")},
    {"id": "it_citazione", "g": "IT", "trigger": "padi_e_marre", "data": "24.09.2026",
     "fatti": "Atto di citazione per risarcimento del danno (inadempimento contrattuale) davanti al Tribunale di Milano, notificato "
              "al convenuto il 24.09.2026, con udienza di comparizione fissata al 2 febbraio 2027.",
     "attesa": ("2026-11-24", r"\b166\b"), "anche": [("2026-12-24", r"171")]},
    {"id": "it_sentenza_appello", "g": "IT", "trigger": "vendim_civil", "data": "15.07.2026",
     "fatti": "Sentenza civile di primo grado del Tribunale di Roma (materia contrattuale, non lavoro), notificata su istanza della "
              "controparte il 15.07.2026.",
     "attesa": ("2026-09-14", r"\b325\b")},
]


def main() -> int:
    from src import web, brain, afati
    web._ensure_loaded()
    ok_tot = 0
    solo = sys.argv[sys.argv.index("--solo") + 1].split(",") if "--solo" in sys.argv else None
    casi = [c for c in CASI if not solo or c["id"] in solo]
    for c in casi:
        brain.set_request_jurisdiction(c["g"])
        idx = web._INDEX_IT if c["g"] == "IT" else web._INDEX
        t0 = time.time()
        try:
            r = afati.compute(web._BRAIN.backend, idx, trigger=c["trigger"], event_date=c["data"], facts=c["fatti"],
                              jurisdiction=c["g"])
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {c['id']}: {type(exc).__name__}: {exc}")
            continue
        data, rx = c["attesa"] or (None, None)
        righe = r.get("afatet") or []
        trovata = [a for a in righe if a.get("date") == data]
        base_ok = data is None or any(re.search(rx, a.get("baza") or "") for a in trovata)
        senza_motore = [a for a in righe if not a.get("passi")]
        ok = (data is None or bool(trovata)) and base_ok
        vietate = [a.get("date") for a in righe if a.get("date") in (c.get("mai") or [])]   # v9.458: date che NON devono uscire
        ok = ok and not vietate
        for d2, rx2 in c.get("anche") or []:             # termini in più che devono esserci (con la loro base)
            ok = ok and any(a.get("date") == d2 and re.search(rx2, a.get("baza") or "") for a in righe)
        ok_tot += ok
        print(f"{'✓' if ok else '✗'} {c['id']:<22} attesa {data} ({rx}) · trovata {bool(trovata)} base {base_ok} · "
              f"righe {len(righe)} · senza motore {len(senza_motore)} · vietate {vietate or '-'} · {time.time() - t0:.0f} s")
        for a in righe:
            print(f"      {a.get('date')}  {a.get('baza') or '-':<28} {a.get('title', '')[:70]}")
    print(f"\nTOTALE: {ok_tot}/{len(casi)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
