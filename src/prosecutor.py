"""Procuratore (Prokurori) — prosecution analysis (Phase 2).

Given the facts / case file, produces a GROUNDED prosecution playbook: legal
qualification of the offense(s), element-by-element evidence sufficiency with
GAP detection (what is still missing to charge), the investigative next steps,
the possible sentence — and, mandatorily, an OBJECTIVITY REVIEW (the defense
case + exculpatory evidence + weak elements). That review is the ethics shield:
research shows AI defaults to "charge", so we force it to see the other side.

ASSISTIVE ONLY: the prosecutor decides and signs. Never auto-charges, never
scores a defendant. Grounded — articles come from the corpus, never invented.
"""
from __future__ import annotations

from . import expertise as _expertise
from .logging_utils import get_logger

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



log = get_logger(__name__)

_LABEL = {
    "kodi_penal": "Kodi Penal", "kodi_proc_penale": "K. Pr. Penale",
    "kodi_civil": "Kodi Civil", "kodi_familjes": "Kodi i Familjes",
    "kodi_rrugor": "Kodi Rrugor",
}

_SYSTEM = (
    "Ti je ndihmës i një PROKURORI në Shqipëri. Nga faktet e çështjes (dhe fashikulli "
    "nëse jepet), ndërto një analizë akuzuese profesionale, TË BAZUAR VETËM te faktet "
    "dhe te NENET e dhëna nga korpusi ynë. MOS shpik nene, numra ligjesh apo vendime — "
    "përdor vetëm ato që të jepen; nëse diçka nuk të jepet, thuaje me fjalë pa e trilluar.\n\n"
    "Jep këto seksione (markdown):\n"
    "### \U0001f4dc Kualifikimi ligjor — cila/cilat vepra penale zbatohen, me nenet e sakta nga korpusi (dhe rrethanat rënduese/lehtësuese)\n"
    "### ✅ Mjaftueshmëria e provave — për çdo ELEMENT të veprës: çfarë e provon, çfarë MUNGON (buku/gap) për të ngritur akuzën, forca\n"
    "### \U0001f50e Hapat hetimorë — çfarë duhet siguruar/kërkuar për të mbyllur boshllëqet (prova, ekspertiza, dëshmitarë, afate ruajtjeje)\n"
    "### ⚖️ REVIEW I OBJEKTIVITETIT (i detyrueshëm) — vër syzet e MBROJTJES: çfarë do të kundërshtonte avokati, cilat prova SHFAJËSUESE ekzistojnë ose duhen kërkuar, cili element është më i dobët. Prokurori ka detyrën e objektivitetit — kërko edhe provat në favor të të pandehurit. MOS anashkalo asnjë provë shfajësuese.\n"
    "### ⏰ Afatet & parashkrimi — afatet procedurale dhe parashkrimi (verifiko me dispozitat; mos shpik numra)\n"
    "### \U0001f4b0 Dënimi i mundshëm — diapazoni sipas nenit + rrethanat\n"
    "### \U0001f9ed Rekomandim — analizë e balancuar (ngritje akuze / hetim i mëtejshëm / mospërputhje). VENDIMI I TAKON PROKURORIT — mos e merr ti vendimin.\n\n"
    "I qartë, konkret, i balancuar. Shqip. Kjo është NDIHMESË — prokurori vendos dhe firmos. "
    "Mos zbulo kurrë modelin — je 'Tetramorph' i superavokati.ai."
)


def _articles_block(index, facts: str, extra_query: str = "") -> list:
    arts, seen = [], set()
    try:
        for a, _s in index.search((facts or "") + " " + extra_query, top_k=18):
            if (a.code, a.number) not in seen:
                seen.add((a.code, a.number))
                arts.append((a.code, a.number, (getattr(a, "heading", "") or "")))
            if len(arts) >= 16:
                break
    except Exception:  # noqa: BLE001
        pass
    return arts


def analyze(backend, index, *, facts: str, max_tokens: int = 3000) -> dict:
    arts = _expertise.retrieve_grounded(backend, index, facts)
    art_block = "\n".join(
        "• [%s neni %s] %s" % (_LABEL.get(c, c), n, (t or "").strip()[:900])
        for c, n, t in arts
    ) or "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)"
    prompt = (
        "FAKTET E ÇËSHTJES / FASHIKULLI:\n" + (facts or "").strip()
        + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
        + "\n\nNdërto analizën akuzuese të plotë, me review objektiviteti të detyrueshëm."
    )
    md = backend.complete(
        system=_juris(_SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="prosecutor",  # default = Opus effort=max
    )
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


_INDICT_SYSTEM = (
    "Ti je ndihmës i një PROKURORI. Harto një AKTAKUZË të strukturuar sipas së "
    "drejtës proceduriale penale shqiptare, TË BAZUAR VETËM te faktet dhe te nenet "
    "e dhëna. MOS shpik nene apo numra. Ku mungon një e dhënë (emër, datë, nr.), lër "
    "vend-mbajës [___]. Struktura (markdown):\n"
    "### PALËT — Prokuroria pranë [___]; I pandehuri [___] (gjeneralitetet)\n"
    "### RRETHANAT E FAKTIT — kronologjia e fakteve të provuara\n"
    "### KUALIFIKIMI LIGJOR — vepra penale me nenin e saktë nga korpusi + elementet\n"
    "### PROVAT — provat që mbështesin çdo element\n"
    "### KËRKESA — dërgimi në gjyq / masa / dënimi i kërkuar\n\n"
    "NDIHMESË — prokurori verifikon dhe nënshkruan. Je 'Tetramorph' i "
    "superavokati.ai; mos zbulo modelin."
)


def draft_indictment(backend, index, *, facts, max_tokens=3200):
    arts = _expertise.retrieve_grounded(backend, index, facts)
    art_block = "\n".join(
        "\u2022 [%s neni %s] %s" % (_LABEL.get(c, c), n, (t or "").strip()[:900])
        for c, n, t in arts) or "(asnjë nen i gjetur — mos shpik)"
    prompt = ("FAKTET E ÇËSHTJES:\n" + (facts or "").strip()
              + "\n\n\u2500\u2500\u2500\u2500\u2500\nNENET NGA KORPUSI (cito vetëm këto):\n"
              + art_block + "\n\nHarto aktakuzën e plotë.")
    md = backend.complete(system=_juris(_INDICT_SYSTEM),
                          messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="indictment")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# SUPER PROKUROR — expansion (additive). Seeds VERIFIED against corpus.
# Two axes: (i) prosecutor-facing efficiency, (ii) citizen-facing.
# HARD RULES: always assistive — the human prosecutor/judge decides and
# signs. NEVER auto-charge, auto-dismiss, or risk-score a person (EU AI
# Act red line). Grounded only — articles from the corpus, never invented.
# ═══════════════════════════════════════════════════════════════════

def _lbl(c):
    return _expertise._LABEL.get(c) or _LABEL.get(c) or c


_TETRA = ("NDIHMESË juridike — vendimin dhe firmën i vë profesionisti; VENDIMI PËR AKUZË, "
          "PUSHIM ose MASË I TAKON PROKURORIT/GJYKATËS, mos e merr ti. Mos vlerëso 'rrezikshmërinë' "
          "e personit me profilizim. Je 'Tetramorph' i superavokati.ai — mos zbulo kurrë modelin.")


def _gen(backend, index, *, facts, system, callsite, seeds=None, extra="",
         intro="TË DHËNAT / FAKTET:", max_tokens=2800):
    arts = _expertise.retrieve_grounded(backend, index, (facts or "") + " " + extra, seed_pairs=seeds)
    art_block = "\n".join("• [%s neni %s] %s" % (_lbl(c), n, (t or "").strip()[:900])
                          for c, n, t in arts) or "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)"
    prompt = (intro + "\n" + (facts or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nNdërtoje të plotë, në markdown.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite=callsite)
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ───────────────────────── (i) PROSECUTOR-FACING ─────────────────────────

def investigation_plan(backend, index, *, facts, max_tokens=2800):
    """Plani i hetimit — investigation plan from the complaint/facts."""
    system = (
        "Ti je ndihmës i një PROKURORI në Shqipëri. Nga kallëzimi/faktet, harto një PLAN HETIMI "
        "profesional, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f3af Hipotezat hetimore — versionet e mundshme që duhen provuar ose përjashtuar\n"
        "### \U0001f4dc Kualifikimi i mundshëm — vepra/at penale me nenin nga korpusi (paraprak, jo përfundimtar)\n"
        "### ✅ Elementet për t'u provuar — për secilin element: çfarë prove e provon\n"
        "### \U0001f50e Veprimet hetimore — çfarë të kryhet (kontroll, sekuestrim, ekspertim, përgjim), radha dhe përse\n"
        "### \U0001f465 Kush të pyetet — dëshmitarë, të pandehur, ekspertë — dhe çka të pyeten\n"
        "### ⏰ Afatet — afati i hetimit paraprak dhe zgjatja (verifiko me dispozitat, mos shpik numra)\n"
        "### ⚖️ Objektiviteti — edhe provat SHFAJËSUESE që duhen kërkuar (detyra e objektivitetit)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_plan",
                seeds=[("kodi_proc_penale", "24"), ("kodi_proc_penale", "287"),
                       ("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "283")],
                extra="plan hetimi veprime hetimore afati", max_tokens=max_tokens)


_ACT_KINDS = {
    "kontroll": {"label": "Kërkesë për kontroll (person/vend)",
                 "seed": [("kodi_proc_penale", "202"), ("kodi_proc_penale", "204"), ("kodi_proc_penale", "205")],
                 "q": "kontroll personi vendi kushtet"},
    "sekuestrim": {"label": "Kërkesë për sekuestrim",
                   "seed": [("kodi_proc_penale", "208"), ("kodi_proc_penale", "203"), ("kodi_proc_penale", "301")],
                   "q": "sekuestrim objekti provë materiale"},
    "ekspertim": {"label": "Kërkesë për ekspertim",
                  "seed": [("kodi_proc_penale", "178"), ("kodi_proc_penale", "179"),
                           ("kodi_proc_penale", "183"), ("kodi_proc_penale", "185")],
                  "q": "ekspertim ekspert detyra pyetjet"},
    "pergjim": {"label": "Kërkesë për përgjim",
                "seed": [("kodi_proc_penale", "221"), ("kodi_proc_penale", "224"), ("kodi_proc_penale", "225")],
                "q": "përgjim kufijtë lejimi"},
}


def list_act_kinds():
    return [{"key": k, "label": v["label"]} for k, v in _ACT_KINDS.items()]


def investigative_act(backend, index, *, kind, facts, max_tokens=2600):
    """Veprime hetimore — draft a request for a search/seizure/expertise/interception."""
    cfg = _ACT_KINDS.get(kind) or _ACT_KINDS["kontroll"]
    system = (
        "Ti je ndihmës i një PROKURORI. Harto KËRKESËN/URDHRIN për veprimin hetimor '" + cfg["label"]
        + "' sipas Kodit të Procedurës Penale, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS "
        "shpik nene. Ku mungon një e dhënë, lër [___]. Jep (markdown):\n"
        "### \U0001f4cc Baza ligjore & kushtet — nenet nga korpusi dhe kushtet që duhen plotësuar\n"
        "### \U0001f9e9 Arsyetimi — pse ky veprim është i nevojshëm dhe proporcional me hetimin\n"
        "### \U0001f4dd Kërkesa/urdhri — teksti i plotë, gati për t'u paraqitur (objekti, vendi/personi, çka kërkohet)\n"
        "### ⚠️ Kujdes — çka duhet respektuar që veprimi të mos jetë i pavlefshëm (autorizim gjyqësor nëse kërkohet, afate, të drejtat)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_act",
                seeds=cfg["seed"], extra=cfg["q"], max_tokens=max_tokens)


def coercive_measure(backend, index, *, facts, max_tokens=2800):
    """Kërkesë për masë sigurimi — SENSITIVE (liberty). Strictly a draft; court decides."""
    system = (
        "Ti je ndihmës i një PROKURORI. Harto një KËRKESË PËR MASË SIGURIMI drejtuar gjykatës, sipas "
        "KPP, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. ⚠️ LIRIA E PERSONIT ËSHTË NË LOJË: "
        "kjo është VETËM PROJEKT-kërkesë; GJYKATA vendos. MOS rekomando arrestin si të sigurt — parashtro "
        "kushtet objektivisht dhe zgjidh masën më pak shtrënguese që mjafton. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f4dc Vepra & kualifikimi — nenet nga korpusi\n"
        "### \U0001f50d Dyshimi i arsyeshëm (fumus) — provat që e mbështesin, element për element\n"
        "### ⚠️ Rreziqet (periculum) — rreziku i ikjes/përsëritjes/prishjes së provave, KONKRET (jo hamendje)\n"
        "### ⚖️ Proporcionaliteti — pse masa e kërkuar; a mjafton një masë më e butë (detyrim paraqitjeje, arrest shtëpie)?\n"
        "### \U0001f4dd Kërkesa — masa e kërkuar dhe teksti drejtuar gjykatës\n"
        "### \U0001f6e1️ Ana e mbrojtjes — çfarë do të kundërshtonte mbrojtja (objektiviteti)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_measure",
                seeds=[("kodi_proc_penale", "228"), ("kodi_proc_penale", "229"),
                       ("kodi_proc_penale", "230"), ("kodi_proc_penale", "232"),
                       ("kodi_proc_penale", "237"), ("kodi_proc_penale", "238"),
                       ("kodi_proc_penale", "244")],
                extra="masë sigurimi personal arrest kushtet kriteret", max_tokens=max_tokens)


def dismissal_request(backend, index, *, facts, max_tokens=2600):
    """Kërkesë për pushim/mosfillim — SENSITIVE. Assistive draft; prosecutor decides."""
    system = (
        "Ti je ndihmës i një PROKURORI. Harto një KËRKESË/PROJEKT-VENDIM për PUSHIM ose MOSFILLIM të "
        "procedimit sipas KPP, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. VENDIMI I TAKON "
        "PROKURORIT — ky është vetëm projekt i arsyetuar. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f4dc Baza ligjore — mosfillim apo pushim, me nenin nga korpusi dhe shkakun\n"
        "### \U0001f9ed Arsyetimi — pse nuk ka vend për ndjekje (mungon fakti/prova/vepra, parashkrim etj.)\n"
        "### ⚖️ Kundërshtimi i mundshëm — a ka prova që do të kërkonin vazhdim? (objektiviteti)\n"
        "### \U0001f4e2 Njoftimi & ankimi — kush njoftohet dhe e drejta e të dëmtuarit për ankim\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_dismiss",
                seeds=[("kodi_proc_penale", "290"), ("kodi_proc_penale", "291"),
                       ("kodi_proc_penale", "328")],
                extra="pushim mosfillim procedimi", max_tokens=max_tokens)


def stress_test(backend, index, *, text, max_tokens=2600):
    """Test objektiviteti — stress-test a prosecutor work-product from the defense side."""
    system = (
        "Ti je AVOKATI MBROJTËS më i zoti, që lexon një AKT TË PROKURORISË (aktakuzë, kërkesë mase, "
        "analizë) dhe kërkon çdo dobësi PARA se ta paraqesë prokurori. Bazohu te teksti dhe te nenet e "
        "dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f6e1️ Dobësitë e provave — cili element mbetet i paprovuar ose i dobët\n"
        "### ⚖️ Kundër-argumentet — çfarë do të ngrejë mbrojtja për çdo pikë\n"
        "### \U0001f6a8 Pavlefshmëritë procedurale — veprime pa autorizim, afate të shkelura, të drejta të cenuara\n"
        "### \U0001f50e Provat shfajësuese — çka duhet kërkuar në favor të të pandehurit\n"
        "### ✅ Si të forcohet akti — çka duhet plotësuar para paraqitjes\n"
        + _TETRA)
    return _gen(backend, index, facts=text, system=system, callsite="pros_stress",
                seeds=None, intro="AKTI PËR STRES-TEST:", extra="dobësi pavlefshmëri provë",
                max_tokens=max_tokens)


# ───────────────────────── (ii) CITIZEN-FACING ─────────────────────────

def citizen_complaint(backend, index, *, facts, max_tokens=2800):
    """Kallëzim penal builder + office router (Prokuroria vs SPAK) + attachments."""
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të përgatisë një KALLËZIM PENAL të saktë (ndihmesë, jo "
        "këshillë ligjore zyrtare). Nga rrëfimi, harto kallëzimin TË PLOTË dhe të strukturuar, TË BAZUAR "
        "te faktet dhe te nenet e dhëna. MOS shpik nene. Ku mungon një e dhënë, lër [___]. Jep (markdown):\n"
        "### \U0001f4dd KALLËZIMI — teksti gati për dorëzim: kallëzuesi, të dhënat, RRETHANAT (kush/çfarë/kur/ku), "
        "dëmi, provat, personat e përfshirë (nëse dihen), dhe KËRKESA për fillim procedimi\n"
        "### \U0001f4cd Ku dorëzohet — Prokuroria pranë gjykatës kompetente sipas vendit; ose SPAK nëse është "
        "korrupsion/krim i organizuar/funksionarë të lartë (shpjego shkurt pse)\n"
        "### \U0001f4ce Dokumentet për t'u bashkangjitur — lista konkrete sipas llojit të veprës\n"
        "### ⚖️ Të drejtat e tua si i dëmtuar — shkurt (neni 58 KPP) dhe se mund të njoftohesh e të ankohesh\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_complaint",
                seeds=[("kodi_proc_penale", "283"), ("kodi_proc_penale", "58"),
                       ("kodi_proc_penale", "290")],
                intro="RRËFIMI I QYTETARIT:", extra="kallëzim i dëmtuar të drejtat",
                max_tokens=max_tokens)


def victim_rights(backend, index, *, facts, max_tokens=2400):
    """Të drejtat e viktimës + shpjegim i fazave — plain-language."""
    system = (
        "Ti je ndihmës që i shpjegon një QYTETARI TË DËMTUAR të drejtat dhe fazat e procesit penal, "
        "thjesht dhe qartë (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos "
        "shpik. Jep (markdown):\n"
        "### ⚖️ Të drejtat e tua — çfarë mund të kërkosh (informim, akses në akte, kërkim provash, "
        "njoftim për arrestin/lirimin, ankim, dëmshpërblim si paditës civil) — bazuar në nenin 58 KPP\n"
        "### \U0001f5fa️ Fazat & çfarë presin — hetimi paraprak, vendimi (akuzë/pushim), gjykimi — thjesht\n"
        "### ⏰ Afatet që të interesojnë — kur pritet çfarë dhe brenda sa kohe mund të veprosh (verifiko, mos shpik numra)\n"
        "### ✅ Hapat e tu të radhës — konkret\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_victim",
                seeds=[("kodi_proc_penale", "58"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "329"), ("kodi_proc_penale", "323")],
                intro="SITUATA E QYTETARIT:", extra="të drejtat i dëmtuar faza afati",
                max_tokens=max_tokens)


def dismissal_appeal(backend, index, *, facts, max_tokens=2600):
    """Ankim kundër pushimit/mosfillimit — decode + draft the victim's appeal. SENSITIVE deadline."""
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR TË DËMTUAR të kuptojë një VENDIM PUSHIMI/MOSFILLIMI dhe "
        "të përgatisë ANKIMIN në gjykatë (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e "
        "dhëna — mos shpik. ⚠️ AFATET E ANKIMIT janë vendimtare — thekso që të verifikohen me "
        "avokat/dispozitat. Jep (markdown):\n"
        "### \U0001f50e Çfarë thotë vendimi — shpjegim i thjeshtë i arsyeve të pushimit/mosfillimit\n"
        "### ⚖️ A ka bazë ankimi — pikat e dobëta të vendimit dhe të drejta e ankimit (neni 291/329 KPP)\n"
        "### \U0001f4dd ANKIMI — teksti i strukturuar drejtuar gjykatës kompetente\n"
        "### ⏰ Afati — brenda sa kohe duhet paraqitur (VERIFIKO me dispozitat/avokat — mos u vono)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_appeal",
                seeds=[("kodi_proc_penale", "291"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "328"), ("kodi_proc_penale", "329"),
                       ("kodi_proc_penale", "284")],
                intro="VENDIMI / SITUATA:", extra="ankim pushim mosfillim afati",
                max_tokens=max_tokens)


def delay_complaint(backend, index, *, facts, max_tokens=2400):
    """Ankesa për vonesa — escalation to the office + Avokati i Popullit + doc-copy request."""
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të ankohet për VONESA në hetim/procedim (ndihmesë, jo "
        "këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f4e8 Ankesa te Prokuroria — teksti drejtuar prokurorit/kryeprokurorit, që kërkon "
        "përshpejtim dhe informim mbi ecurinë (referto afatin e hetimit, neni 323/324 KPP)\n"
        "### \U0001f3db️ Ankesa te Avokati i Popullit — teksti i shkurtër i ankesës për vonesë/mosveprim\n"
        "### \U0001f4c4 Kërkesë për kopje aktesh — teksti për të marrë kopje të akteve të çështjes\n"
        "### ✅ Këshilla praktike — si t'i protokollosh dhe çka të ruash\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_delay",
                seeds=[("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "58")],
                intro="SITUATA E VONESËS:", extra="vonesa ankesa afati hetimit",
                max_tokens=max_tokens)
