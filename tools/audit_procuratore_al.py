# v9.642 — uso: bash tools/prova_pro.sh pros tools/audit_procuratore_al.py [immagine] [cartella_src]  (risposte in /tmp/pp_pros/out)
# Audit del PROCURATORE ALBANESE col cervello vero (dati inventati): 14 casi sugli 11 strumenti.
# Ogni risposta in /out/<nome>.md; riga di sintesi con tempi, citazioni verificate/false, data di oggi, [___].
import sys, time, re, json, collections, concurrent.futures as cf
sys.path.insert(0, "/app")
from src import backends, brain, prosecutor
from src.retrieval import ArticleIndex
from src import citation_verifier as cv

b = backends.build_backend()
idx = ArticleIndex.load()

CASI = {
    "analiza_grabitje": ("analyze", {"facts": (
        "Më 3.9.2026, rreth orës 22:30, në rrugën «Myslym Shyri», Tiranë, shtetasi Gent Shembulli (25 vjeç) u sulmua nga dy "
        "persona që e goditën me grushte dhe i morën me forcë telefonin celular (vlera rreth 900 euro) dhe portofolin me 15.000 "
        "lekë. Sipas aktit të ekspertimit mjeko-ligjor lëndimet sjellin paaftësi të përkohshme në punë për 9 ditë. Kamerat e një "
        "dyqani e regjistruan ngjarjen, por fytyrat nuk duken qartë. Më 5.9.2026 policia gjeti telefonin e viktimës te shtetasi "
        "Arben Prova (23 vjeç), i cili deklaroi se e kishte blerë nga një person i panjohur për 100 euro. Arben Prova ka një "
        "dënim të mëparshëm për vjedhje (2022). Viktima e njohu Arben Provën në procedurën e njohjes si njërin nga sulmuesit, "
        "por deklaroi se «nuk është 100% i sigurt». Personi i dytë nuk është identifikuar.")}),
    "aktakuze_vjedhje_banese": ("draft_indictment", {"facts": (
        "Procedimi penal nr. 1234/2026 i Prokurorisë pranë Gjykatës së Shkallës së Parë të Juridiksionit të Përgjithshëm Durrës. "
        "I pandehuri: Arben Prova, i biri i Ilirit, lindur më 12.4.1998 në Durrës, banues në Durrës, lagjja nr. 5. Më 14.6.2026, "
        "rreth orës 03:00, i pandehuri hyri duke thyer dritaren në banesën e shtetases Blerina Shembulli në Durrës dhe mori një "
        "laptop, bizhuteri ari dhe 2.000 euro. Provat: gjurmët e gishtave të të pandehurit në dritare (akt ekspertimi "
        "daktiloskopik nr. 55/2026), bizhuteritë e gjetura te i pandehuri gjatë kontrollit të banesës së tij të autorizuar me "
        "vendim të gjykatës, deklarata e dëshmitarit Gent Shembulli që e pa duke dalë nga oborri. Hetimet përfunduan; i "
        "pandehuri dhe mbrojtësi i tij, av. Luan Shembulli, u njoftuan për përfundimin e hetimeve më 1.10.2026 dhe nuk paraqitën "
        "kërkesa brenda afatit. Viktima u njoftua po atë ditë.")}),
    "plan_mashtrim_online": ("investigation_plan", {"facts": (
        "Kallëzim nga shtetasja Blerina Shembulli (12.9.2026): në gusht 2026 pa në Facebook një njoftim për shitje makine "
        "(Volkswagen Golf, 2018) me çmim 6.500 euro. Shitësi, që u prezantua si «Ardi», i kërkoi një paradhënie prej 1.500 euro "
        "me transfertë bankare në një llogari në emër të shtetasit Gent Shembulli dhe pastaj nuk u përgjigj më. Profili në "
        "Facebook u fshi. Ka mesazhet në Messenger, mandatin e transfertës dhe numrin e telefonit të shitësit.")}),
    "akt_ekspertim_plage": ("investigative_act", {"kind": "ekspertim", "facts": (
        "Procedim për plagosje me thikë: më 20.9.2026 në Fier shtetasi Gent Shembulli u godit me thikë në bark gjatë një "
        "zënke me shtetasin Arben Prova; u shtrua në spital dhe u operua. Duhet përcaktuar natyra dhe rëndësia e plagës, mjeti "
        "me të cilin u shkaktua, nëse plaga rrezikonte jetën dhe kohëzgjatja e paaftësisë. Thika u sekuestrua në vendngjarje.")}),
    "akt_kontroll_droge": ("investigative_act", {"kind": "kontroll", "facts": (
        "Informacion i policisë së Elbasanit: në banesën e shtetasit Arben Prova, rruga «Rinia», pallati 3, ruhen lëndë "
        "narkotike (kanabis) për shitje. Një person i pyetur si person që ka dijeni deklaroi se ka blerë dy herë prej tij javën "
        "e kaluar; vëzhgimi i policisë ka parë hyrje-dalje të shpeshta të të rinjve në banesë për 5 ditë rresht.")}),
    "mase_dhune_familje": ("coercive_measure", {"facts": (
        "I pandehuri Arben Prova, 35 vjeç, dyshohet se më 10.10.2026 goditi me grushte dhe kërcënoi me thikë bashkëshorten "
        "Blerina Shembulli në banesën e tyre në Shkodër, në prani të fëmijës 8-vjeçar. Ndaj tij ishte në fuqi një urdhër "
        "mbrojtjeje i gjykatës (qershor 2026) që i ndalonte afrimin te banesa. Viktima ka akt mjeko-ligjor për lëndime me 6 ditë "
        "paaftësi. Ai u arrestua në flagrancë po atë natë. Nuk ka dënime të mëparshme. Punon si shofer kamioni dhe ka shtëpi "
        "të vetën në Shkodër.")}),
    "pushim_autor_panjohur": ("dismissal_request", {"facts": (
        "Procedimi penal nr. 777/2026 për veprën «Vjedhja» (neni 134 i Kodit Penal): më 2.3.2026 nga një makinë e parkuar në "
        "Fier u vodh një çantë me dokumente dhe 300 euro. Autori nuk u identifikua: nuk ka kamera, nuk ka dëshmitarë, gjurmët "
        "e marra në makinë nuk përputhen me asnjë person në regjistrat e policisë. Afati i hetimeve paraprake mbaron më "
        "2.11.2026. Prokurori po mendon të përfundojë procedimin.")}),
    "pushim_fakti_tjeter": ("dismissal_request", {"facts": (
        "Procedimi penal nr. 812/2026 për veprën «Shkatërrimi i pronës» (neni 150 i Kodit Penal): më 15.5.2026 shtetasi Arben "
        "Prova dyshohej se theu xhamin e vitrinës së një dyqani në Korçë. Gjatë hetimit, kamera e bashkisë tregoi qartë se "
        "xhamin e theu një kamion që bëri manovër; Arben Prova vetëm kalonte aty. Hetimet kanë përfunduar.")}),
    "stres_kerkese_mase": ("stress_test", {"text": (
        "KËRKESË PËR CAKTIMIN E MASËS SË SIGURIMIT «ARREST NË BURG»\n"
        "Prokuroria pranë Gjykatës së Shkallës së Parë të Juridiksionit të Përgjithshëm Tiranë kërkon caktimin e masës «arrest "
        "në burg» ndaj të pandehurit Gent Shembulli për veprën «Vjedhja» (neni 134 KP). I pandehuri është person i rrezikshëm "
        "për shoqërinë. Më 1.9.2026 policia kontrolloi banesën e tij (pa vendim të gjykatës, sepse ishte urgjente; nuk ishte "
        "rast flagrance) dhe gjeti dy telefona të vjedhur. Deklarata e dëshmitarit u mor më 20.12.2026, pas mbarimit të afatit "
        "të hetimeve (15.12.2026). Kërkojmë arrest në burg sepse çdo masë tjetër është e pamjaftueshme.")}),
    "kallezim_shpifje_fb": ("citizen_complaint", {"facts": (
        "Ish-partneri im, Arben Prova, ka publikuar në Facebook më 5.10.2026 një postim ku shkruan se unë jam «hajdute» dhe se "
        "«kam vjedhur paratë e firmës ku punoja», gjë që nuk është e vërtetë. Postimi ka 300 shpërndarje. Kam screenshot-et "
        "dhe dy kolegë që e kanë lexuar. Jetoj në Tiranë. Dua ta kallëzoj.")}),
    "kallezim_korrupsion_bashki": ("citizen_complaint", {"facts": (
        "Një punonjës i zyrës së urbanistikës në Bashkinë Vlorë më kërkoi 2.000 euro për të më dhënë lejen e ndërtimit më "
        "shpejt; tha se pa paratë dosja ime «do të humbasë». Kam regjistrim audio të bisedës (12.10.2026) dhe mesazhet në "
        "WhatsApp. Nuk i kam dhënë paratë.")}),
    "viktima_dhune_familje": ("victim_rights", {"facts": (
        "Jam viktimë e dhunës në familje nga bashkëshorti. E kallëzova në polici para një jave; ai u arrestua, por gjykata e "
        "liroi me «detyrim paraqitjeje». Kam frikë se do të kthehet në shtëpi. Kemi dy fëmijë të mitur. Çfarë të drejtash kam "
        "dhe çfarë ndodh tani?")}),
    "ankim_mosfillim_kercenim": ("dismissal_appeal", {"facts": (
        "Më 10.10.2026 mora njoftimin e vendimit të prokurorit për mosfillimin e procedimit për kallëzimin tim kundër fqinjit, "
        "që më shkatërroi gardhin dhe më kërcënoi. Prokurori thotë se «fakti nuk përbën vepër penale» sepse është «konflikt "
        "civil për kufirin e pronës». Por fqinji më tha «do të të vras» para dy dëshmitarëve dhe ka një thikë gjuetie.")}),
    "vonese_mashtrim_15muaj": ("delay_complaint", {"facts": (
        "Në korrik 2025 bëra kallëzim në Prokurorinë e Tiranës për mashtrim (më morën 8.000 euro për një shtëpi me qira që nuk "
        "ekzistonte). Kanë kaluar 15 muaj dhe nuk kam marrë asnjë njoftim; në telefon më thonë «është në hetim». Nuk e di as "
        "nëse procedimi është regjistruar.")}),
}

SOT = ("16.10.2026", "16 tetor 2026", "16/10/2026")


def corri(nome):
    fn, kw = CASI[nome]
    brain.set_request_jurisdiction("AL")
    t0 = time.time()
    try:
        r = getattr(prosecutor, fn)(b, idx, **kw)
        md = r.get("markdown") or ""
        err = None
    except Exception as e:  # noqa: BLE001
        md, err = "", f"{type(e).__name__}: {e}"
    return nome, time.time() - t0, md, err


ordine = list(CASI)
if len(sys.argv) > 1:
    ordine = [n for n in ordine if any(s in n for s in sys.argv[1].split(","))]
with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for nome, sec, md, err in ex.map(corri, ordine):
        open(f"/out/{nome}.md", "w", encoding="utf-8").write(md)
        st = collections.Counter()
        fake = []
        if md:
            res = cv.verify_text(md, idx)
            for it in res.get("items", []):
                st[it.get("status")] += 1
                if it.get("status") in ("fake", "repealed"):
                    fake.append(it.get("raw"))
        oggi = any(s in md for s in SOT)
        print(f"===== {nome} [{CASI[nome][0]}] — {sec:.0f} s, {len(md)} chr {'ERRORE ' + err if err else ''}")
        print(f"   citazioni {dict(st)}  false/abrogate {fake[:6]}  data_di_oggi={oggi}  vuoti={md.count('[___]')}")
