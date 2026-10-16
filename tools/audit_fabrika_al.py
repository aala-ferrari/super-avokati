# v9.642 — uso: bash tools/prova_pro.sh fab tools/audit_fabrika_al.py [immagine] [cartella_src]
# Audit della «Fabrika e akteve» dell'avvocato (pro_features.draft_act) col cervello vero, dati inventati, sessione AL.
# Recupero come la rotta: triage + _retrieve del cervello + BM25 sul testo (≤16), poi i semi di procedura dell'atto.
import sys, time, re, json, collections, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import backends, brain, pro_features
from src.retrieval import ArticleIndex
from src import citation_verifier as cv

b = backends.build_backend()
idx = ArticleIndex.load()
br = brain.SuperAvvocato(index=idx, backend=b)

CASI = {
    "padi_pushim": ("padi", (
        "Paditësi Arben Prova, i biri i Ilirit, banues në Tiranë, rruga «Kavaja», ka punuar si shofer prej 6 vitesh (nga "
        "1.9.2020) me kontratë me afat të pacaktuar te shoqëria «Transport Shembull» sh.p.k., NIPT L00000000A, me seli në "
        "Tiranë. Më 15.9.2026 administratori i tha me gojë se është i pushuar nga puna, pa asnjë njoftim me shkrim, pa "
        "paralajmërim dhe pa asnjë arsye. Paga mujore bruto 80.000 lekë. Kërkojmë që zgjidhja e kontratës të shpallet e "
        "pajustifikuar dhe pagimin e pagës së periudhës së njoftimit, të shpërblimit për vjetërsi dhe të dëmshpërblimit deri "
        "në një vit pagë. Dëshmitar: kolegu Gent Shembulli, që ishte i pranishëm.")),
    "ankim_hua": ("ankim", (
        "Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm Durrës, me vendimin nr. 1234, datë 10.9.2026, rrëzoi "
        "padinë e klientit tonë Gent Shembulli kundër të paditurës Blerina Shembulli për kthimin e 12.000 eurove hua. Huaja "
        "u dha me një shkresë të thjeshtë të nënshkruar nga e paditura (jo me akt noterial) dhe me dy transferta bankare në "
        "llogarinë e saj. Gjykata arsyetoi se huaja mbi 10.000 euro duhej bërë me akt noterial dhe se transfertat nuk e "
        "provojnë huanë. Vendimi i arsyetuar na u njoftua më 2.10.2026. Duam të bëjmë apel.")),
    "kundershtim_kredi": ("kundershtim", (
        "Klienti Arben Prova mori më 12.10.2026 lajmërimin për ekzekutim vullnetar nga një përmbarues gjyqësor privat, në bazë "
        "të një urdhri ekzekutimi të lëshuar mbi kontratën e kredisë me bankën «Banka Shembull» sh.a. për 25.000 euro. Por "
        "kredia është shlyer plotësisht më 3.3.2025: kemi vërtetimin e bankës për mbylljen e kredisë dhe mandatet e pagesave. "
        "Duam ta kundërshtojmë ekzekutimin.")),
    "kerkese_mase": ("kerkese_penale", (
        "Klienti Gent Shembulli është në masën e sigurimit «arrest në burg» prej 5 muajsh për vjedhje me dhunë (neni 139 i "
        "Kodit Penal); çështja është dërguar tashmë në gjyq dhe provat janë marrë. Klienti nuk ka dënime të mëparshme, ka një "
        "fëmijë 2-vjeçar dhe nënën e sëmurë rëndë që e ka në ngarkim; ka banesë të vetën në Lezhë. Kërkojmë nga gjykata "
        "zëvendësimin e masës me «arrest në shtëpi».")),
}

SOT = ("16.10.2026", "16 tetor 2026", "16/10/2026")


def recupero(brief):
    br._jurisdiction_ctx.code = "AL"
    tri = br._triage(brief[:3000], [], None)
    pairs = list(br._retrieve(tri) or [])
    seen = {(a.code, str(a.number)) for a, _ in pairs}
    for a, sc in idx.search(brief[:3000], top_k=8):
        if len(pairs) >= 16:
            break
        if (a.code, str(a.number)) not in seen:
            pairs.append((a, sc)); seen.add((a.code, str(a.number)))
    return pairs[:16]


def corri(nome):
    tipo, brief = CASI[nome]
    brain.set_request_jurisdiction("AL")
    t0 = time.time()
    try:
        pairs = recupero(brief)
        d = pro_features.draft_act(b, idx, act_type=tipo, brief=brief, retrieved=pairs)
        err = None
    except Exception as e:  # noqa: BLE001
        d, err = {}, f"{type(e).__name__}: {e}"
        pairs = []
    return nome, time.time() - t0, d, err, [f"{a.code} {a.number}" for a, _ in pairs]


with cf.ThreadPoolExecutor(max_workers=2) as ex:
    for nome, sec, d, err, arts in ex.map(corri, list(CASI)):
        json.dump(d, open(f"/out/{nome}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        corpo = d.get("body_markdown") or ""
        st = collections.Counter(); fake = []
        for it in cv.verify_text(corpo, idx).get("items", []):
            st[it.get("status")] += 1
            if it.get("status") in ("fake", "repealed"):
                fake.append(it.get("raw"))
        print(f"===== {nome} — {sec:.0f} s, corpo {len(corpo)} chr {'ERRORE ' + err if err else ''}")
        print(f"   titolo {d.get('title')!r} · corte {d.get('court')!r}")
        print(f"   citazioni {dict(st)} false {fake[:6]} · data_di_oggi={any(s in corpo for s in SOT)} · vuoti={corpo.count('[___]')}")
        print(f"   articoli dati: {arts}")
        print(f"   avvisi: {d.get('warnings')}")
