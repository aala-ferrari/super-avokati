# v9.645 — uso: bash tools/prova_pro.sh blk tools/diag_blocchi_avok.py [immagine] [cartella_src]
# Quali articoli darebbe il recupero del cervello (triage + _retrieve, come `web._nenet_per_djallin`) agli strumenti
# dell'avvocato che oggi lavorano senza corpus: la mappa delle pretese, il Red Team sul contratto, la revisione del contratto.
# Per ogni caso: gli articoli del blocco e le norme ATTESE che mancano (lette sul corpus il 17 ott 2026).
import sys, time
sys.path.insert(0, "/app")
from src import web, brain

web._ensure_loaded()
B = web._BRAIN

FAKTET_HARTA = (
    "Klienti ynë Gent Shembulli bleu më 10.3.2026, me kontratë noteriale, një apartament 86 m² në Tiranë nga shoqëria ndërtuese "
    "«Ndërtimi Shembull» sh.p.k. për 85.000 euro, të paguara me transfertë bankare. Në shtator 2026 zbuloi lagështirë të rëndë në "
    "muret e jashtme; raporti i një eksperti privat (25.9.2026) thotë se është defekt ndërtimi i izolimit të fasadës. Matja e "
    "ekspertit jep 78 m². Klienti i dërgoi shoqërisë dy mesazhe WhatsApp (28.9 dhe 5.10) pa përgjigje. Duam padi për ulje çmimi "
    "dhe dëmshpërblim.")
KONTRATA = (
    "KONTRATË QIRAJE\nE lidhur më 1.9.2026 në Tiranë midis «Prona Shembull» sh.p.k. (qiradhënësi) dhe Arben Prova (qiramarrësi).\n"
    "Neni 1. Qiradhënësi i jep me qira qiramarrësit apartamentin në rrugën «Shembulli» 5, Tiranë, për banim.\n"
    "Neni 2. Qiraja është 600 euro në muaj, e pagueshme deri më datën 5 të çdo muaji. Për çdo ditë vonesë qiramarrësi paguan "
    "penalitet 50 euro.\n"
    "Neni 3. Kontrata lidhet për 3 vjet. Qiramarrësi nuk mund ta zgjidhë kontratën para afatit; nëse largohet, paguan qiranë e "
    "gjithë periudhës së mbetur.\n"
    "Neni 4. Qiradhënësi mund ta zgjidhë kontratën në çdo kohë me njoftim 7 ditë.\n"
    "Neni 5. Depozita është 3.000 euro dhe nuk kthehet në asnjë rast.\n"
    "Neni 6. Qiradhënësi nuk përgjigjet për asnjë dëm që i vjen qiramarrësit nga gjendja e apartamentit.\n"
    "Neni 7. Çdo mosmarrëveshje zgjidhet nga arbitri i caktuar nga qiradhënësi.\n")
CONTRATTO_IT = (
    "CONTRATTO DI LOCAZIONE AD USO ABITATIVO\nTra «Immobiliare Esempio» s.r.l. (locatore) e Mario Prova (conduttore), Milano, "
    "1.9.2026.\nArt. 1. Il locatore concede in locazione l'appartamento in via Esempio 5, Milano, ad uso abitativo.\n"
    "Art. 2. Il canone è di 900 euro mensili da pagare entro il giorno 5. Per ogni giorno di ritardo il conduttore paga una penale "
    "di 80 euro.\nArt. 3. La durata è di 4 anni. Il conduttore non può recedere prima della scadenza; se lascia l'immobile paga i "
    "canoni fino alla scadenza.\nArt. 4. Il locatore può risolvere il contratto in qualsiasi momento con preavviso di 7 giorni.\n"
    "Art. 5. Il deposito cauzionale è di 5.400 euro e non viene restituito in nessun caso.\n"
    "Art. 6. Il locatore non risponde di alcun danno derivante dallo stato dell'immobile.\n"
    "Art. 7. Ogni controversia è decisa da un arbitro nominato dal locatore.\n")

CASI = {
    "harta_apartament": ("AL", FAKTET_HARTA, [("kodi_civil", n) for n in ("756", "752", "753", "755", "718")]),
    "kontrate_qira": ("AL", KONTRATA, [("kodi_civil", n) for n in ("544", "801", "806", "807", "820", "686", "602", "655")]
                      + [("ligji_arbitrazhi", "9"), ("ligji_konsumatoret", "27")]),
    "contratto_locazione_it": ("IT", CONTRATTO_IT, [("codice_civile", n) for n in ("1384", "1341", "1229", "1571", "1575", "1579")]
                               + [("locazioni_abitative", "13"), ("locazioni_abitative", "2")]),
}

for nome, (giur, testo, attesi) in CASI.items():
    brain.set_request_jurisdiction(giur)
    B._jurisdiction_ctx.code = giur
    t0 = time.time()
    try:
        tri = B._triage(testo[:6000], [], None)
        pairs = list(B._retrieve(tri) or [])
    except Exception as e:  # noqa: BLE001
        print(f"===== {nome}: ERRORE {type(e).__name__}: {e}")
        continue
    chiavi = [(a.code, str(a.number)) for a, _ in pairs]
    mancano = [f"{c} {n}" for c, n in attesi if (c, n) not in chiavi]
    print(f"===== {nome} [{giur}] — {time.time() - t0:.0f} s, {len(pairs)} articoli")
    print("   query:", " | ".join((tri.search_queries or [])[:6])[:400])
    print("   blocco:", " · ".join(f"{c} {n}" for c, n in chiavi))
    print(f"   attesi {len(attesi) - len(mancano)}/{len(attesi)}  mancano: {mancano}")
