#!/usr/bin/env python3
"""v9.380 — la prova DALL'INIZIO ALLA FINE della ricerca delle leggi: domande scritte come le scrive un avvocato →
triage VERO del cervello (riscrive nei termini del codice) → `_retrieve` + ancore + nene chiesti → l'articolo decisivo
è nel blocco che il senior legge? Costa un triage (modello veloce) per domanda. Nessuna risposta viene scritta.

    docker exec super-avvocato python3 tools/eval_triage_ricerca.py
"""
import sys, time, threading
sys.path.insert(0, "/app")
from src import brain as B

CASI = [  # (giurisdizione, domanda dell'avvocato, articoli di cui almeno uno DEVE essere nel blocco)
    ("AL", "Vëllai i klientit kërkohej nga policia për vjedhje dhe klienti e mbajti dy ditë në shtëpi. A rrezikon përgjegjësi penale?", [("kodi_penal", "302")]),
    ("AL", "Klienti u mbajt 8 muaj në paraburgim dhe u pafajësua me vendim të formës së prerë. Çfarë kompensimi i takon dhe brenda çfarë afati?", [("kodi_proc_penale", "268"), ("kodi_proc_penale", "269")]),
    ("AL", "Punëdhënësi e pushoi klientin pas 8 vitesh pa asnjë paralajmërim. Çfarë i takon?", [("kodi_punes", "155"), ("kodi_punes", "146")]),
    ("AL", "Qiramarrësi nuk paguan qiranë prej 5 muajsh. Si ta nxjerr nga banesa?", [("kodi_civil", "801"), ("kodi_civil", "698"), ("kodi_civil", "703")]),
    # v9.394 — il caso del banco di prova che NESSUNA variante risolve (26 set: legge sugli stranieri 72-73 e premio di anzianità
    # mancati 6 giri su 6): licenziamento di un lavoratore straniero con permesso unico
    ("AL", "Shtetas i huaj, leje qëndrimi për punë, 3 vjet punë, zgjidhje e menjëhershme e kontratës pa shkak, pa afat njoftimi.", [("ligji_te_huajt", "72"), ("kodi_punes", "152")]),
    # v9.391 — stupefacenti (ligji 7975/1995 e 61/2023 nel corpus)
    ("AL", "Klienti u kap nga policia me 3 gram kokainë në xhep. Çfarë rrezikon dhe a mund të mbrohemi me përdorimin vetjak?", [("kodi_penal", "283")]),
    ("AL", "A lejohet në Shqipëri kultivimi i kanabisit për qëllime mjekësore dhe çfarë licence duhet?", [("ligji_kanabisi_mjekesor", "14"), ("ligji_kanabisi_mjekesor", "15"), ("ligji_kanabisi_mjekesor", "4"), ("ligji_kanabisi_mjekesor", "5"), ("ligji_kanabisi_mjekesor", "1")]),
    ("AL", "Ketamina konsiderohet lëndë narkotike sipas ligjit shqiptar apo është lëndë e kontrolluar?", [("ligji_lendet_narkotike", "2"), ("ligji_lendet_narkotike", "shtojca"), ("ligji_lendet_narkotike", "3")]),
    ("AL", "Farmacia e klientit shiste tramadol pa recetë mjekësore. Çfarë sanksionesh rrezikon?", [("ligji_lendet_narkotike", "101"), ("ligji_lendet_narkotike", "72"), ("ligji_lendet_narkotike", "65"), ("ligji_lendet_narkotike", "64")]),
    ("AL", "Klienti u kap në mars 2026 me disa gram HHC të blera në internet. A është vepër penale?", [("ligji_lendet_narkotike", "shtojca"), ("kodi_penal", "283")]),
    ("AL", "Një fermer kishte mbjellë 200 bimë kanabisi në tokën e tij. Çfarë dënimi rrezikon?", [("kodi_penal", "284")]),
    ("AL", "Klienti ka një borxh nga viti 2012 dhe kreditori tani e padit. A ka rënë në parashkrim?", [("kodi_civil", "114"), ("kodi_civil", "115")]),
    ("AL", "Dogana i sekuestroi klientit makinën për kontrabandë. Si ta kundërshtojmë?", [("kodi_doganor", "272"), ("kodi_doganor", "274"), ("ligji_gjykatat_administrative", "18")]),
    ("AL", "Bashkia i refuzoi klientit lejen e ndërtimit. Brenda sa ditësh e padisim në gjykatën administrative?", [("ligji_gjykatat_administrative", "18")]),
    ("AL", "Klientja kërkon divorc, bashkëshorti nuk pranon. Si shkojmë dhe kush merr fëmijët?", [("kodi_familjes", "129"), ("kodi_familjes", "132"), ("kodi_familjes", "155")]),
    ("AL", "Babai i klientit vdiq pa testament, ka lënë gruan dhe tre fëmijë. Si ndahet trashëgimia?", [("kodi_civil", "361")]),
    ("AL", "Klienti u godit nga një makinë në vendkalim për këmbësorë dhe ka dëme shëndetësore. Kë padisim dhe për çfarë?", [("kodi_civil", "608"), ("kodi_civil", "640"), ("ligji_sigurimi_mjeteve", "9")]),
    ("AL", "Një vendim i Gjykatës së Lartë e shkel të drejtën e klientit për proces të rregullt. Si i drejtohemi Gjykatës Kushtetuese dhe brenda sa kohe?", [("ligji_gjykata_kushtetuese", "71/a"), ("kushtetuta", "131")]),
    ("IT", "Il cliente, amministratore di una sh.p.k. albanese, residente in Italia, guida l'auto aziendale targata albanese. Rischia la confisca?", [("reg_ue_2015_2446", "215"), ("codice_strada", "93-bis")]),
    ("IT", "Il credito del cliente risale al 2013 e il debitore non ha mai pagato: è prescritto?", [("codice_civile", "2946")]),
    ("IT", "Il cliente è stato licenziato per giustificato motivo oggettivo, assunto nel 2018 in azienda con 30 dipendenti. Che tutele ha?", [("tutele_crescenti", "3")]),
]


def main() -> int:
    sa = B.SuperAvvocato()
    if getattr(sa, "index_it", None) is None:          # l'indice italiano lo carica l'app web all'avvio, non il cervello
        from pathlib import Path
        from src.retrieval import ArticleIndex
        sa.index_it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
    solo = [x for x in sys.argv[1:] if not x.startswith("-")]
    ok = 0; t0 = time.time()
    for jur, q, exp in [c for c in CASI if not solo or any(w.lower() in c[1].lower() for w in solo)]:
        B.set_request_jurisdiction(jur)
        try:
            sa._jurisdiction_ctx.code = jur
        except Exception:  # noqa: BLE001
            pass
        tr = sa._triage(q, [], None)
        ret = sa._retrieve(tr)
        ret = sa._ankoro_citimet(q, ret, areas=getattr(tr, "areas", None))
        if "--kerkuesi" in sys.argv:                   # il percorso vero: anche il ricercatore junior (una chiamata veloce)
            ret = sa._studio_kerkuesi(q, tr, ret)
        got = [(a.code, str(a.number)) for a, _ in ret]
        hit = [e for e in exp if e in got]
        ok += bool(hit)
        pos = min((got.index(e) + 1 for e in hit), default=None)
        print(f"{'✓' if hit else '✗'} [{jur}] {q[:70]:70s} | trovato {hit[:2]} pos {pos} | aree {tr.areas} | query {[x[:40] for x in tr.search_queries[:3]]}", flush=True)
        if not hit or "-v" in sys.argv:
            print("      blocco:", [f"{c}:{n}" for c, n in got[:14]], flush=True)
    n = len([c for c in CASI if not solo or any(w.lower() in c[1].lower() for w in solo)])
    print(f"\nnel blocco del senior: {ok}/{n} · {int((time.time()-t0)/max(n,1))} s/domanda (triage vero)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
