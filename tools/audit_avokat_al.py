# v9.644 — uso: bash tools/prova_pro.sh avok tools/audit_avokat_al.py [immagine] [cartella_src]  (risposte in /tmp/pp_avok/out)
# Audit di altri strumenti dell'AVVOCATO in sessione AL col cervello vero (dati inventati): il consulto dell'«Avvocato del
# diavolo», il secondo parere su una risposta con un errore messo apposta, il motore dei termini e la prescrizione.
# Ogni risposta in /out/<nome>.md; riga di sintesi con tempi, lunghezza, citazioni e titoli scritti «alla E» (GjilpEra, LEvizja).
import sys, time, re, collections, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import backends, brain, second_opinion, afati, deadlines
from src.retrieval import ArticleIndex
from src import citation_verifier as cv

b = backends.build_backend()
idx = ArticleIndex.load()
br = brain.SuperAvvocato(index=idx, backend=b)


def blocco_djalli(testo):
    """Come web._nenet_per_djallin senza fascicolo: il triage del cervello + lo stesso recupero ibrido della chat."""
    br._jurisdiction_ctx.code = "AL"
    tri = br._triage(testo[:6000], [], None)
    pairs = list(br._retrieve(tri) or [])
    return brain._format_articles_for_prompt(pairs)[:60000] if pairs else ""


SIT_DJALLI = (
    "Klienti ynë Gent Shembulli bleu në mars 2026 një apartament në Tiranë nga shoqëria «Ndërtimi Shembull» sh.p.k. me "
    "kontratë noteriale; pagoi 85.000 euro. Në shtator 2026 zbuloi se apartamenti ka lagështirë të rëndë në muret e jashtme "
    "(raport i një eksperti privat: defekt ndërtimi) dhe se sipërfaqja reale është 78 m² dhe jo 86 m² si në kontratë. Shoqëria "
    "nuk përgjigjet. Çfarë bëjmë dhe si e fitojmë?")
PYETJA_REVIEW = ("Klientja ime u njoftua më 2.10.2026 me vendimin e arsyetuar të Gjykatës së Shkallës së Parë Tiranë që rrëzoi "
                 "padinë e saj për pagimin e 6.000 eurove qira të prapambetura. Si e apelojmë?")
# risposta del «giovane» con un errore messo apposta: 30 giorni invece dei 15 del KPC 443, e nessuna parola sul KPC 444/148
PERGJIGJA_REVIEW = (
    "Mund të bëni apel në Gjykatën e Apelit brenda 30 ditëve nga njoftimi i vendimit (neni 443 KPC). Ankimi paraqitet "
    "drejtpërdrejt në Gjykatën e Apelit dhe duhet të përmbajë shkaqet e ankimit. Bashkëlidhni kontratën e qirasë dhe "
    "vendimin. Pas apelit, ekzekutimi i vendimit pezullohet automatikisht.")

CASI = {
    "djalli_apartament": ("consult", {"situation": SIT_DJALLI}),
    "review_apel_qira": ("review", {"question": PYETJA_REVIEW, "answer_text": PERGJIGJA_REVIEW}),
    "afat_pushim": ("afati", {"trigger": "pushim_nga_puna", "event_date": "2026-09-30", "facts": (
        "Punëmarrësja (4 vjet punë, kontratë me afat të pacaktuar) mori më 30.9.2026 shkresën e zgjidhjes së kontratës «për "
        "ristrukturim» me efekt nga 1.10.2026, pa takim paraprak dhe pa periudhë njoftimi.")}),
    "afat_vendim_penal": ("afati", {"trigger": "vendim_penal", "event_date": "2026-10-05", "facts": (
        "Gjykata e Shkallës së Parë Durrës shpalli më 5.10.2026 vendimin që dënon klientin tonë me 1 vit burgim për vjedhje; "
        "klienti ishte i pranishëm në shpallje; arsyetimi do të depozitohet më vonë.")}),
    "parashkrim_shpifje": ("prescription", {"facts": (
        "Shpifje (neni 120 i Kodit Penal) e kryer botërisht me një postim në Facebook më 10.11.2024; viktima dëshiron ta "
        "ndjekë penalisht autorin. A është ende në kohë?")}),
}

E_MADHE = re.compile(r"\b\w*[a-zç]E[a-zç]\w*\b|\b[A-Z]\w*[a-zç]E\b")      # «GjilpEra», «LEvizja», «nE», «tE»


def corri(nome):
    tipo, kw = CASI[nome]
    brain.set_request_jurisdiction("AL")
    t0 = time.time()
    try:
        if tipo == "consult":
            r = second_opinion.consult(b, situation=kw["situation"], context=blocco_djalli(kw["situation"]))
        elif tipo == "review":
            r = second_opinion.review(b, question=kw["question"], answer_text=kw["answer_text"],
                                      context=blocco_djalli(kw["question"]))
        elif tipo == "afati":
            r = afati.compute(b, idx, trigger=kw["trigger"], event_date=kw["event_date"], facts=kw["facts"], jurisdiction="AL")
        else:
            r = deadlines.prescription(b, idx, facts=kw["facts"], jurisdiction="AL")
        md, err = r.get("markdown") or "", None
        extra = r.get("afatet")
    except Exception as e:  # noqa: BLE001
        md, err, extra = "", f"{type(e).__name__}: {e}", None
    return nome, time.time() - t0, md, err, extra


with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, sec, md, err, extra in ex.map(corri, list(CASI)):
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = collections.Counter()
        fake = []
        if md:
            for it in cv.verify_text(md, idx).get("items", []):
                st[it.get("status")] += 1
                if it.get("status") in ("fake", "repealed"):
                    fake.append(it.get("raw"))
        titoli = [l for l in md.splitlines() if l.startswith("#")]
        alla_e = sorted({w for l in titoli for w in E_MADHE.findall(l)})
        print(f"===== {nome} [{CASI[nome][0]}] — {sec:.0f} s, {len(md)} chr {'ERRORE ' + err if err else ''}")
        print(f"   citazioni {dict(st)}  false/abrogate {fake[:6]}  titoli_alla_E={alla_e[:8]}")
        if extra:
            print(f"   afatet: {[(a.get('title'), a.get('date'), a.get('baza')) for a in extra][:8]}")
