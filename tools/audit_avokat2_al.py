# v9.645 — uso: bash tools/prova_pro.sh <nome> tools/audit_avokat2_al.py [immagine] [cartella_src]  (risposte in /tmp/pp_<nome>/out)
# Audit degli strumenti dell'AVVOCATO senza recupero degli articoli (sessione AL, dati inventati): la mappa delle pretese
# («Harta e Pretendimeve»), il Red Team sul contratto («Kundërshtari»), la revisione del contratto. Conta le citazioni
# verificate / false / senza codice: senza il blocco del corpus il modello cita a memoria.
import sys, time, collections, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import backends, brain, adversary, web
from src.retrieval import ArticleIndex
from src import citation_verifier as cv

b = backends.build_backend()
idx = ArticleIndex.load()
cv.registra_indici(al=idx)

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


def harta():
    return b.complete(system=web._HARTA_SYSTEM, messages=[{"role": "user", "content": FAKTET_HARTA}], max_tokens=3000,
                      fast=False, callsite="audit_claim_chart")


def red_team():
    return adversary.attack(b, text=KONTRATA).get("markdown") or ""


def rishikim():
    return b.complete(system=web.CONTRACT_REVIEW_SYSTEM, messages=[{"role": "user", "content": KONTRATA}], max_tokens=3000,
                      fast=False, callsite="audit_contract_review")


CASI = {"harta_apartament": harta, "red_team_qira": red_team, "rishikim_qira": rishikim}


def corri(nome):
    brain.set_request_jurisdiction("AL")
    t0 = time.time()
    try:
        md, err = CASI[nome]() or "", None
    except Exception as e:  # noqa: BLE001
        md, err = "", f"{type(e).__name__}: {e}"
    return nome, time.time() - t0, md, err


with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, sec, md, err in ex.map(corri, list(CASI)):
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = collections.Counter()
        cattive = []
        for it in (cv.verify_text(md, idx).get("items", []) if md else []):
            st[it.get("status")] += 1
            if it.get("status") in ("fake", "repealed"):
                cattive.append(it.get("raw"))
        print(f"===== {nome} — {sec:.0f} s, {len(md)} chr {'ERRORE ' + err if err else ''}")
        print(f"   citazioni {dict(st)}  false/abrogate {cattive[:8]}")
