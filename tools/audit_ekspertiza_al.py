# v9.644 — uso: bash tools/prova_pro.sh eksp tools/audit_ekspertiza_al.py [immagine] [cartella_src]  (risposte in /tmp/pp_eksp/out)
# Audit delle MODELE EKSPERTIZE col cervello vero (dati inventati): 4 tipologie in sessione AL e una in sessione IT.
# Ogni risposta in /out/<nome>.md; riga di sintesi con tempi, lunghezza, citazioni verificate/false, data di oggi, articoli dati.
import sys, time, collections, concurrent.futures as cf
sys.path.insert(0, "/app")
from pathlib import Path
from src import backends, brain, expertise
from src.retrieval import ArticleIndex
from src import citation_verifier as cv

b = backends.build_backend()
idx = ArticleIndex.load()
idx_it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))

CASI = {
    "plagosje_thike": ("AL", "plagosje", (
        "Klienti ynë Arben Prova (28 vjeç) akuzohet se më 20.9.2026 në Fier goditi me thikë në krah shtetasin Gent Shembulli "
        "gjatë një zënke para një lokali. Sipas aktit të ekspertimit mjeko-ligjor plaga sjell paaftësi të përkohshme në punë për "
        "12 ditë dhe nuk rrezikoi jetën. Klienti thotë se Gent Shembulli e sulmoi i pari me një shishe dhe se thika ishte e "
        "Gentit, që i ra gjatë përleshjes. Dy dëshmitarë e konfirmojnë që Genti e filloi zënkën; kamera e lokalit nuk punonte. "
        "Klienti nuk ka dënime të mëparshme. Thika u sekuestrua në vendngjarje.")),
    "aksident_kembesor": ("AL", "aksident_rrugor", (
        "Klientja jonë Blerina Shembulli (45 vjeç) u përplas më 3.8.2026 në Durrës nga një makinë ndërsa kalonte rrugën te "
        "vija e bardhë e këmbësorëve. Shoferi, Luan Shembulli, ishte duke folur në telefon (e thonë dy dëshmitarë). Policia "
        "rrugore mbajti procesverbal. Klientja ka thyerje të këmbës, 60 ditë paaftësi, fatura mjekësore 3.200 euro dhe nuk "
        "punoi dy muaj (paga 70.000 lekë në muaj). Makina ka sigurim TPL te një shoqëri sigurimesh shqiptare.")),
    "kontrate_sipermarrje": ("AL", "mosmarreveshje_civile", (
        "Klienti ynë Gent Shembulli lidhi më 10.3.2026 një kontratë me shkrim me shoqërinë «Ndërtimi Shembull» sh.p.k. për "
        "rikonstruksionin e apartamentit të tij në Tiranë, me çmim 18.000 euro dhe afat përfundimi 30.6.2026. Pagoi paradhënie "
        "10.000 euro me transfertë bankare. Punimet u ndërprenë në maj 2026 në rreth 40% dhe shoqëria nuk përgjigjet më; "
        "kontrata parashikon penalitet 50 euro për çdo ditë vonesë. Klienti ka foto të punimeve dhe mesazhet në WhatsApp.")),
    "abuzim_postoblloku": ("AL", "abuzim_policor", (
        "Klienti ynë Luan Shembulli u ndalua më 1.10.2026 në orën 23:00 në një posto-bllok në Elbasan. Dy agjentë pa uniformë "
        "të plotë dhe pa e treguar numrin e identifikimit i kërkuan ta hapte telefonin; kur refuzoi, e nxorën me forcë nga "
        "makina, e goditën dhe e mbajtën 9 orë në komisariat pa i lejuar të telefononte avokatin dhe pa i dhënë asnjë "
        "procesverbal. Të nesërmen bëri ekspertim mjeko-ligjor: hematoma në fytyrë dhe brinjë, 7 ditë paaftësi.")),
    "it_lesioni_coltello": ("IT", "plagosje", (
        "Il nostro cliente Mario Prova (28 anni) è accusato di aver colpito con un coltello al braccio Luca Esempio il 20 "
        "settembre 2026 a Bologna, durante una lite davanti a un bar. Secondo la consulenza medico-legale la ferita è guaribile "
        "in 25 giorni e non ha messo in pericolo la vita. Il cliente dice che Luca Esempio lo ha aggredito per primo con una "
        "bottiglia e che il coltello era di Luca, caduto durante la colluttazione. Due testimoni confermano che la lite l'ha "
        "iniziata Luca; la telecamera del bar non funzionava. Il cliente è incensurato. Il coltello è stato sequestrato.")),
}

SOT = ("16.10.2026", "16 tetor 2026", "16/10/2026", "16 ottobre 2026")


def corri(nome):
    lingua, tipo, fatti = CASI[nome]
    brain.set_request_jurisdiction(lingua)
    t0 = time.time()
    try:
        r = expertise.analyze(b, idx_it if lingua == "IT" else idx, case_type=tipo, facts=fatti)
        md = r.get("markdown") or ""
        arts = [f"{a['code']} {a['number']}" for a in (r.get("articles") or [])]
        err = None
    except Exception as e:  # noqa: BLE001
        md, arts, err = "", [], f"{type(e).__name__}: {e}"
    return nome, time.time() - t0, md, arts, err


ordine = list(CASI)
_solo = sys.argv[1] if len(sys.argv) > 1 else __import__("os").environ.get("SOLO", "")
if _solo:
    ordine = [n for n in ordine if any(s in n for s in _solo.split(","))]
with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, sec, md, arts, err in ex.map(corri, ordine):
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = collections.Counter()
        fake = []
        if md:
            # come la rotta dalla v9.644: la verifica coi codici degli articoli dati allo strumento
            res = cv.verify_text(md, idx_it if CASI[nome][0] == "IT" else idx,
                                 retrieved_codes=({a.split()[0] for a in arts} or None))
            for it in res.get("items", []):
                st[it.get("status")] += 1
                if it.get("status") in ("fake", "repealed"):
                    fake.append(it.get("raw"))
        oggi = any(s in md for s in SOT)
        alb = sum(md.count(w) for w in (" të ", " dhe ", " është ", "neni ")) if CASI[nome][0] == "IT" else 0
        print(f"===== {nome} [{CASI[nome][1]}] — {sec:.0f} s, {len(md)} chr {'ERRORE ' + err if err else ''}")
        print(f"   citazioni {dict(st)}  false/abrogate {fake[:6]}  data_di_oggi={oggi}  albanese={alb}")
        print(f"   articoli dati ({len(arts)}): {' · '.join(arts)}")
