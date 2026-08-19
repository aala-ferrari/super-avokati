"""Notaio (Noteri) — notary tools (Phase 3).

Civil-law notary vertical for Albania (Law 110/2018 "Për noterinë"). Three
tools, all GROUNDED in the corpus (articles retrieved, never invented) and
ASSISTIVE ONLY (the notary validates and signs — a defective deed is void):

  1. draft_deed   — draft a notarial deed from structured input, with the
                    mandatory clauses + formal requirements.
  2. check_deed   — formal-validity & consistency check of a pasted deed.
  3. succession   — grounded heirs + shares analysis.
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

DEED_TYPES = {
    "shitje_pasurie": {
        "label": "Kontratë shitjeje pasurie të paluajtshme", "emoji": "\U0001f3e0",
        "seed": [("kodi_civil", "750"), ("kodi_civil", "751")],
        "must": ["Identiteti i plotë i palëve (shitës/blerës)",
                 "Objekti: pasuria, nr. pasurie, zona kadastrale, sipërfaqja",
                 "Çmimi dhe mënyra e pagesës", "Deklarimi i mungesës së barrëve/hipotekave",
                 "Garancia për të metat", "Data, leximi, nënshkrimet, vula notariale"]},
    "hipoteke": {
        "label": "Kontratë hipotekore", "emoji": "\U0001f3e6",
        "seed": [("kodi_civil", "560"), ("kodi_civil", "562"), ("kodi_civil", "568")],
        "must": ["Palët (kreditor hipotekor/debitor)", "Kredia e siguruar dhe shuma",
                 "Pasuria e hipotekuar (nr. pasurie, kadastër)", "Rangu i hipotekës",
                 "Data, nënshkrimet, vula; regjistrimi në ZVRPP/kadastër"]},
    "prokure": {
        "label": "Prokurë (e përgjithshme ose e posaçme)", "emoji": "\U0001f4dd",
        "seed": [("kodi_civil", "70"), ("kodi_civil", "71"), ("kodi_civil", "72")],
        "must": ["Përfaqësuesi dhe i përfaqësuari (identiteti)",
                 "Kufijtë e tagrave (të përgjithshme/të posaçme)", "Afati/kohëzgjatja",
                 "E drejta e nën-delegimit (po/jo)", "Data, nënshkrimi, vula"]},
    "testament": {
        "label": "Testament", "emoji": "\U0001f4dc",
        "seed": [("kodi_civil", "372"), ("kodi_civil", "392"), ("kodi_civil", "393")],
        "must": ["Trashëgimlënësi (identiteti + zotësia për të vepruar)",
                 "Vullneti i qartë mbi pasurinë", "Respektimi i pjesës së rezervuar (nëse ka)",
                 "Forma (ollograf ose noterial)", "Data, nënshkrimi, dëshmitarët nëse kërkohen"]},
    "dhurim": {
        "label": "Kontratë dhurimi", "emoji": "\U0001f381",
        "seed": [("kodi_civil", "761"), ("kodi_civil", "764")],
        "must": ["Dhuruesi dhe i dhuruari", "Objekti i dhurimit",
                 "Forma noteriale (e detyrueshme për pasuri të paluajtshme)",
                 "Pranimi i të dhuruarit", "Data, nënshkrimet, vula"]},
    "trashegimi": {
        "label": "Dëshmi trashëgimie (akt noterial)", "emoji": "⚖️",
        "seed": [("kodi_civil", "316"), ("kodi_civil", "317")],
        "must": ["Trashëgimlënësi + data e vdekjes", "Trashëgimtarët + lidhja e afërisë",
                 "Pjesët takuese sipas ligjit ose testamentit", "Pasuria trashëgimore",
                 "Data, nënshkrimet, vula noteriale"]},
    "kontrate_martese": {
        "label": "Kontratë martese (regjimi pasuror)", "emoji": "\U0001f48d",
        "seed": [("kodi_familjes", "66"), ("kodi_familjes", "108")],
        "must": ["Bashkëshortët (identiteti)", "Regjimi i zgjedhur (bashkësi/ndarje pasurie)",
                 "Pasuritë e përfshira", "Data, nënshkrimet, vula"]},
    "themelim_shoqerie": {
        "label": "Akt themelimi shoqërie tregtare", "emoji": "\U0001f3e2",
        "seed": [],
        "must": ["Themeluesit + kuotat", "Emri, forma ligjore (sh.p.k./sh.a.), selia",
                 "Kapitali dhe ndarja", "Objekti i veprimtarisë", "Administrimi/përfaqësimi",
                 "Data, nënshkrimet, vula; regjistrimi në QKB"]},
}

_ORDER = ["shitje_pasurie", "hipoteke", "prokure", "testament", "dhurim",
          "trashegimi", "kontrate_martese", "themelim_shoqerie"]

_NOTARY_ID = ("Je 'Tetramorph' i superavokati.ai — mos zbulo kurrë modelin apo teknologjinë. "
              "Kjo është NDIHMESË: noteri e verifikon, e plotëson dhe e nënshkruan. Një akt "
              "me të meta formale është i pavlefshëm — mos anashkalo asnjë kërkesë formale.")


def list_deed_types() -> list[dict]:
    return [{"key": k, "label": DEED_TYPES[k]["label"], "emoji": DEED_TYPES[k]["emoji"],
             "must": DEED_TYPES[k]["must"]} for k in _ORDER]


def _art_block(backend, index, text, seed):
    arts = _expertise.retrieve_grounded(backend, index, text, seed_pairs=seed)
    return "\n".join("• [%s neni %s] %s" % (
        _expertise._LABEL.get(c, c), n, (t or "").strip()[:900]) for c, n, t in arts) \
        or "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)", arts


def draft_deed(backend, index, *, deed_type: str, details: str, clauses_text: str = "", max_tokens: int = 3600) -> dict:
    tpl = DEED_TYPES.get(deed_type)
    if tpl is None:
        raise ValueError("unknown deed_type")
    art_block, arts = _art_block(backend, index, details + " " + tpl["label"], tpl["seed"])
    system = (
        "Ti je NOTER shqiptar me përvojë, që harton akte notariale sipas së drejtës shqiptare "
        "(Ligji nr. 110/2018 'Për noterinë' dhe Kodi Civil). Harto aktin e kërkuar TË PLOTË, "
        "profesional, gati për noterizim, me TË GJITHA klauzolat e detyrueshme dhe kërkesat "
        "formale. Bazohu VETËM te të dhënat dhe te nenet e dhëna — MOS shpik nene apo numra. "
        "Ku mungon një e dhënë (emër, çmim, nr. pasurie, datë), lër vend-mbajtës [___] dhe mos "
        "e trillo. Në fund, shto një seksion '### ✅ Kërkesat formale' me listën e kontrollit. "
        + _NOTARY_ID)
    prompt = ("LLOJI I AKTIT: " + tpl["label"]
              + "\n\nKLAUZOLAT E DETYRUESHME:\n- " + "\n- ".join(tpl["must"])
              + "\n\nTË DHËNAT NGA NOTERI:\n" + (details or "").strip()
              + (("\n\n─────\nKLAUZOLAT E PREFERUARA TË STUDIOS (përdori kur i përshtaten aktit, ruaj stilin e studios):\n" + clauses_text) if clauses_text else "")
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nHarto aktin e plotë në markdown.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_draft")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


def check_deed(backend, index, *, text: str, max_tokens: int = 2400) -> dict:
    art_block, arts = _art_block(backend, index, text, None)
    system = (
        "Ti je NOTER-redaktor i rreptë. Kontrollo AKTIN NOTARIAL të dhënë për VLEFSHMËRI "
        "FORMALE dhe KOHERENCË, sipas së drejtës shqiptare. Bazohu te teksti dhe te nenet e "
        "dhëna — mos shpik nene. Jep (markdown):\n"
        "### \U0001f6a8 Mangësi formale — klauzola/formalitete të detyrueshme që MUNGOJNË (identitet, objekt, çmim, datë, nënshkrime, vula, forma e kërkuar)\n"
        "### ⚠️ Mospërputhje/kontradikta — data të gabuara, emra/shuma/nr. pasurie që s'përputhen brenda aktit\n"
        "### \U0001f4dc Nenet e cituara — a janë reale/në fuqi (nëse ka)\n"
        "### ✅ Përfundim — a është akti gati për noterizim apo çfarë duhet rregulluar para tij (rrezik pavlefshmërie).\n"
        + _NOTARY_ID)
    prompt = ("AKTI PËR KONTROLL:\n" + (text or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI:\n" + art_block + "\n\nKontrollo aktin.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_check")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


def succession(backend, index, *, situation: str, max_tokens: int = 2400) -> dict:
    art_block, arts = _art_block(backend, index, situation + " trashëgimi trashëgimtar pjesë takuese",
                                 [("kodi_civil", "316"), ("kodi_civil", "317"),
                                  ("kodi_civil", "361"), ("kodi_civil", "363")])
    system = (
        "Ti je NOTER ekspert i së drejtës së trashëgimisë shqiptare. Nga gjendja familjare e "
        "dhënë, përcakto TRASHËGIMTARËT dhe PJESËT takuese, sipas trashëgimisë me ligj (ose me "
        "testament nëse jepet). Bazohu VETËM te faktet dhe te nenet e dhëna — MOS shpik nene apo "
        "përqindje pa mbështetje. Jep (markdown):\n"
        "### \U0001f465 Trashëgimtarët — kush trashëgon dhe pse (radha e trashëgimit)\n"
        "### \U0001f4ca Pjesët takuese — pjesa e secilit (dhe pjesa e rezervuar nëse ka)\n"
        "### ⚠️ Kujdes — çfarë duhet verifikuar (testament, heqje dorë, përfaqësim)\n"
        "### \U0001f4dc Baza ligjore — nenet e zbatuara\n"
        + _NOTARY_ID)
    prompt = ("GJENDJA FAMILJARE:\n" + (situation or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI:\n" + art_block + "\n\nPërcakto trashëgimtarët dhe pjesët.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_succession")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# SUPER NOTERI — expansion (additive). Seeds VERIFIED against corpus.
# ═══════════════════════════════════════════════════════════════════

# ---- new contract & company deed types (appear in the existing dropdown) ----
DEED_TYPES.update({
    "qira": {
        "label": "Kontratë qiraje", "emoji": "\U0001f3e1",
        "seed": [("kodi_civil", "801"), ("kodi_civil", "802"), ("kodi_civil", "805"),
                 ("kodi_civil", "812"), ("kodi_civil", "814")],
        "must": ["Palët (qiradhënësi/qiramarrësi)", "Sendi/pasuria e dhënë me qira",
                 "Qiraja (masa) dhe afati (jo më shumë se 30 vjet)", "Mënyra e pagesës",
                 "Detyrimet e mirëmbajtjes dhe kthimi i sendit", "Data, nënshkrimet, vula"]},
    "huaje": {
        "label": "Kontratë huaje", "emoji": "\U0001f4b5",
        "seed": [("kodi_civil", "659")],
        "must": ["Huadhënësi dhe huamarrësi", "Shuma e huasë dhe monedha",
                 "Interesi (nëse ka) dhe afati i kthimit", "Këstet/mënyra e shlyerjes",
                 "Garancitë (nëse ka)", "Data, nënshkrimet, vula"]},
    "sipermarrje": {
        "label": "Kontratë sipërmarrjeje/shërbimi", "emoji": "\U0001f6e0️",
        "seed": [("kodi_civil", "853"), ("kodi_civil", "856"), ("kodi_civil", "864")],
        "must": ["Palët (porositësi/sipërmarrësi)", "Objekti i punës/shërbimit",
                 "Çmimi dhe mënyra e pagesës", "Afatet e dorëzimit", "Garancia për të metat",
                 "Penalitetet për vonesë", "Data, nënshkrimet, vula"]},
    "peng": {
        "label": "Kontratë pengu (send i luajtshëm)", "emoji": "\U0001f4ce",
        "seed": [("kodi_civil", "532"), ("kodi_civil", "547"), ("kodi_civil", "553")],
        "must": ["Palët (pengmarrësi/pengdhënësi)", "Detyrimi i siguruar dhe shuma",
                 "Sendi i luajtshëm i lënë peng", "Forma me shkresë/noteriale",
                 "Kushtet e shitjes në mospagim", "Data, nënshkrimet, vula"]},
    "shkembim": {
        "label": "Kontratë shkëmbimi", "emoji": "\U0001f501",
        "seed": [("kodi_civil", "757"), ("kodi_civil", "759"), ("kodi_civil", "760")],
        "must": ["Palët shkëmbyese", "Të dy sendet/pasuritë e shkëmbyera",
                 "Diferenca në vlerë (konguaji) nëse ka", "Garancia për të metat",
                 "Regjistrimi (për pasuri të paluajtshme)", "Data, nënshkrimet, vula"]},
    "shitje_automjeti": {
        "label": "Kontratë shitjeje automjeti", "emoji": "\U0001f697",
        "seed": [("kodi_civil", "705"), ("kodi_civil", "708")],
        "must": ["Shitësi dhe blerësi (identiteti)", "Automjeti (marka, targa, shasia, viti)",
                 "Çmimi dhe mënyra e pagesës", "Deklarimi i mungesës së barrëve/sekuestros",
                 "Çregjistrimi/regjistrimi në DPSHTRR", "Data, nënshkrimet, vula"]},
    "shitje_kuotash": {
        "label": "Kontratë kalimi/shitjeje kuotash (SHPK)", "emoji": "\U0001f4c8",
        "seed": [("ligji_shoqerite_tregtare", "34"), ("kodi_civil", "705")],
        "must": ["Shitësi (ortaku) dhe blerësi", "Shoqëria (SHPK) dhe NIPT-i",
                 "Kuotat e kaluara dhe përqindja", "Çmimi", "Miratimi/parablerja e ortakëve nëse kërkohet",
                 "Regjistrimi i ndryshimit në QKB", "Data, nënshkrimet, vula"]},
    "premtim_shitje": {
        "label": "Kontratë premtimi për shitje (me kapar)", "emoji": "\U0001f91d",
        "seed": [("kodi_civil", "659"), ("kodi_civil", "705")],
        "must": ["Palët premtuese", "Pasuria/objekti i premtimit dhe çmimi i rënë dakord",
                 "Kapari/paradhënia dhe pasojat në tërheqje", "Afati për lidhjen e kontratës përfundimtare",
                 "Data, nënshkrimet, vula"]},
    "aktmarreveshje": {
        "label": "Aktmarrëveshje (zgjidhje mosmarrëveshjeje)", "emoji": "\U0001f54a️",
        "seed": [("kodi_civil", "659")],
        "must": ["Palët", "Mosmarrëveshja që zgjidhet", "Lëshimet e ndërsjella (çfarë pranon secili)",
                 "Detyrimet e reja dhe afatet", "Klauzola e mbylljes së mosmarrëveshjes",
                 "Data, nënshkrimet, vula"]},
    "statut_shpk": {
        "label": "Statut i SHPK-së", "emoji": "\U0001f4d8",
        "seed": [("ligji_shoqerite_tregtare", "6"), ("ligji_shoqerite_tregtare", "8"),
                 ("ligji_shoqerite_tregtare", "12")],
        "must": ["Emri, forma (SHPK) dhe selia", "Objekti i veprimtarisë",
                 "Kapitali themeltar dhe kuotat e ortakëve", "Organet (asambleja, administratori) dhe kompetencat",
                 "Përfaqësimi ligjor", "Kohëzgjatja dhe rregullat e prishjes", "Data, nënshkrimet, vula; QKB"]},
    "vendim_asambleje": {
        "label": "Vendim i asamblesë së ortakëve", "emoji": "\U0001f5f3️",
        "seed": [("ligji_shoqerite_tregtare", "12")],
        "must": ["Shoqëria dhe NIPT-i", "Data dhe kuorumi i asamblesë", "Rendi i ditës",
                 "Vendimi (ndryshim administratori/objekti/kapitali/miratim bilanci)",
                 "Votat", "Nënshkrimet; regjistrimi në QKB"]},
    "likuidim_shpk": {
        "label": "Likuidim/mbyllje e shoqërisë (SHPK)", "emoji": "\U0001f6d1",
        "seed": [("ligji_shoqerite_tregtare", "3"), ("ligji_shoqerite_tregtare", "10")],
        "must": ["Shoqëria dhe NIPT-i", "Vendimi për prishje/likuidim", "Emërimi i likuiduesit",
                 "Shlyerja e kreditorëve dhe bilanci përfundimtar", "Ndarja e aktivit të mbetur",
                 "Çregjistrimi në QKB", "Data, nënshkrimet, vula"]},
})
_ORDER += ["qira", "huaje", "sipermarrje", "peng", "shkembim", "shitje_automjeti",
           "shitje_kuotash", "premtim_shitje", "aktmarreveshje",
           "statut_shpk", "vendim_asambleje", "likuidim_shpk"]

# ---- PROKURA builder: forms + scope library (tagrat) ----
_PROKURA_BASE = [("kodi_civil", "64"), ("kodi_civil", "66"), ("kodi_civil", "69"),
                 ("kodi_civil", "70"), ("kodi_civil", "71"), ("kodi_civil", "72"),
                 ("kodi_civil", "74"), ("kodi_civil", "75"), ("kodi_civil", "76")]

PROKURA_FORMS = {
    "e_pergjithshme": "Prokurë e përgjithshme (të gjitha veprimet e administrimit të zakonshëm)",
    "e_posacme": "Prokurë e posaçme (vetëm veprimet e listuara — e detyrueshme për disponime)",
}

PROKURA_SCOPES = {
    "shitje_pasurie": {"label": "Shitje/blerje pasurie të paluajtshme",
        "powers": ["të shesë ose blejë pasuri të paluajtshme", "të caktojë çmimin dhe kushtet",
                   "të arkëtojë ose paguajë shumën", "të nënshkruajë kontratën noteriale",
                   "të regjistrojë kalimin e pronësisë në ASHK"],
        "seed": [("kodi_civil", "750"), ("kodi_civil", "751"), ("kodi_civil", "705")]},
    "shitje_automjeti": {"label": "Shitje/blerje automjeti",
        "powers": ["të shesë ose blejë automjetin", "të nënshkruajë aktin e shitjes",
                   "të çregjistrojë/regjistrojë automjetin në DPSHTRR", "të dorëzojë dokumentet dhe çelësat"],
        "seed": [("kodi_civil", "705")]},
    "perfaqesim_tatimor": {"label": "Përfaqësim tatimor / para kontabilistit",
        "powers": ["të përfaqësojë para Drejtorisë së Tatimeve dhe organeve tatimore",
                   "të plotësojë e nënshkruajë deklarata tatimore", "të komunikojë me kontabilistin/ekspertin kontabël",
                   "të paguajë detyrimet ose të kërkojë rimbursim tatimor"],
        "seed": [("kodi_civil", "64"), ("kodi_civil", "66")]},
    "administrim_shoqerie": {"label": "Administrim/përfaqësim i shoqërisë (SHPK/SHA)",
        "powers": ["të administrojë e përfaqësojë shoqërinë", "të nënshkruajë kontrata në emër të saj",
                   "të operojë llogaritë bankare të shoqërisë", "të përfaqësojë para QKB dhe institucioneve"],
        "seed": [("ligji_shoqerite_tregtare", "12")]},
    "likuidim_shpk": {"label": "Likuidim/mbyllje e shoqërisë SHPK",
        "powers": ["të emërohet ose veprojë si likuidues i shoqërisë", "të kryejë procedurën e likuidimit",
                   "të shlyejë kreditorët dhe të mbyllë llogaritë bankare",
                   "të nënshkruajë e depozitojë aktet në QKB", "të çregjistrojë përfundimisht shoqërinë"],
        "seed": [("ligji_shoqerite_tregtare", "3"), ("ligji_shoqerite_tregtare", "10"),
                 ("kodi_civil", "70")]},
    "regjistrim_qkb": {"label": "Regjistrim/ndryshime në QKB",
        "powers": ["të regjistrojë shoqërinë ose ndryshimet në QKB",
                   "të ndryshojë objektin, administratorin ose kuotat", "të tërheqë ekstrakte dhe vërtetime"],
        "seed": [("ligji_shoqerite_tregtare", "1"), ("ligji_shoqerite_tregtare", "6")]},
    "perfaqesim_gjykate": {"label": "Përfaqësim në gjykatë",
        "powers": ["të përfaqësojë në procese civile/administrative", "të nënshkruajë akte procedurale",
                   "të bëjë pajtim ose të heqë dorë nga padia", "të ushtrojë ankim"],
        "seed": [("kodi_civil", "64")]},
    "bankar": {"label": "Veprime bankare",
        "powers": ["të hapë ose mbyllë llogari bankare", "të depozitojë ose tërheqë para",
                   "të nënshkruajë për kredi", "të operojë depozitat dhe kasafortën"],
        "seed": [("kodi_civil", "73")]},
    "terheqje_dokumentesh": {"label": "Tërheqje/depozitim dokumentesh (ASHK/QKB/gjendje civile)",
        "powers": ["të tërheqë ose depozitojë dokumente në ASHK, QKB, gjendje civile dhe e-Albania",
                   "të marrë certifikata, ekstrakte dhe vërtetime"],
        "seed": [("kodi_civil", "73")]},
    "pranim_trashegimie": {"label": "Pranim trashëgimie",
        "powers": ["të pranojë trashëgiminë në emër të të përfaqësuarit", "të marrë dëshminë e trashëgimisë",
                   "të regjistrojë pasurinë e trashëguar në ASHK"],
        "seed": [("kodi_civil", "316"), ("kodi_civil", "317")]},
    "heqje_dore_trashegimie": {"label": "Heqje dorë nga trashëgimia",
        "powers": ["të heqë dorë nga trashëgimia në emër të të përfaqësuarit", "të nënshkruajë deklaratën përkatëse"],
        "seed": [("kodi_civil", "316")]},
    "hipotekim_kredi": {"label": "Hipotekim i pasurisë / marrje kredie",
        "powers": ["të hipotekojë pasurinë e paluajtshme", "të marrë kredi pranë bankës",
                   "të nënshkruajë kontratën e kredisë dhe hipotekës", "të regjistrojë hipotekën në ASHK"],
        "seed": [("kodi_civil", "560"), ("kodi_civil", "562")]},
    "qira": {"label": "Lidhje/nënshkrim i kontratës së qirasë",
        "powers": ["të japë ose marrë me qira sendin/pasurinë", "të caktojë qiranë dhe afatin",
                   "të nënshkruajë kontratën e qirasë"],
        "seed": [("kodi_civil", "801")]},
    "administrata_publike": {"label": "Përfaqësim para administratës publike",
        "powers": ["të përfaqësojë para bashkisë, prefekturës, ministrive dhe institucioneve",
                   "të paraqesë kërkesa dhe të tërheqë dokumente", "të veprojë në e-Albania"],
        "seed": [("kodi_civil", "64")]},
    "kuota_shitje": {"label": "Shitje/blerje kuotash ose aksionesh",
        "powers": ["të shesë ose blejë kuota/aksione të shoqërisë", "të nënshkruajë aktin e kalimit",
                   "të regjistrojë ndryshimin në QKB"],
        "seed": [("ligji_shoqerite_tregtare", "34")]},
    "terheqje_page": {"label": "Tërheqje page/pensioni/përfitimesh",
        "powers": ["të tërheqë pagën, pensionin ose përfitimet", "të nënshkruajë për marrjen e tyre"],
        "seed": [("kodi_civil", "73")]},
}
_PROKURA_ORDER = ["shitje_pasurie", "shitje_automjeti", "perfaqesim_tatimor", "administrim_shoqerie",
                  "likuidim_shpk", "regjistrim_qkb", "perfaqesim_gjykate", "bankar",
                  "terheqje_dokumentesh", "pranim_trashegimie", "heqje_dore_trashegimie",
                  "hipotekim_kredi", "qira", "administrata_publike", "kuota_shitje", "terheqje_page"]


def list_prokura_scopes() -> dict:
    return {"forms": [{"key": k, "label": v} for k, v in PROKURA_FORMS.items()],
            "scopes": [{"key": k, "label": PROKURA_SCOPES[k]["label"],
                        "powers": PROKURA_SCOPES[k]["powers"]} for k in _PROKURA_ORDER]}


def draft_prokura(backend, index, *, form: str, scope_keys=None, details: str = "",
                  duration: str = "", subdelegation: bool = False, clauses_text: str = "",
                  max_tokens: int = 3200) -> dict:
    form = form if form in PROKURA_FORMS else "e_posacme"
    scope_keys = [k for k in (scope_keys or []) if k in PROKURA_SCOPES]
    seed = list(_PROKURA_BASE)
    scope_lines = []
    for k in scope_keys:
        sc = PROKURA_SCOPES[k]
        seed += sc["seed"]
        scope_lines.append("• " + sc["label"] + ": " + "; ".join(sc["powers"]))
    # dedup seed
    seen, dedup = set(), []
    for c, n in seed:
        if (c, n) not in seen:
            seen.add((c, n)); dedup.append((c, n))
    art_block, arts = _art_block(backend, index, (details or "") + " prokurë përfaqësim tagra", dedup)
    scope_txt = "\n".join(scope_lines) or "(të gjitha veprimet e administrimit të zakonshëm — prokurë e përgjithshme)"
    system = (
        "Ti je NOTER shqiptar që harton PROKURA sipas Kodit Civil (përfaqësimi, nenet 64–78) dhe "
        "Ligjit nr. 110/2018 'Për noterinë'. Harto prokurën TË PLOTË, gati për noterizim, me: "
        "identitetin e plotë të TË PËRFAQËSUARIT dhe PËRFAQËSUESIT, TAGRAT e sakta (vetëm ato të "
        "kërkuara — mos zgjeruar), afatin, të drejtën e nën-delegimit, dhe formalitetet (data, "
        "leximi, nënshkrimi, vula noteriale). KUJDES: disponimet (shitje/hipotekë/dhurim) kërkojnë "
        "prokurë të POSAÇME me tagra shprehimisht të përcaktuara — mos i nënkupto. Ku mungon një e "
        "dhënë, lër [___]. Bazohu VETËM te nenet e dhëna — mos shpik nene. Shto në fund '### ✅ "
        "Kërkesat formale'. " + _NOTARY_ID)
    prompt = ("LLOJI: " + PROKURA_FORMS[form]
              + "\n\nTAGRAT E KËRKUARA (qëllimet):\n" + scope_txt
              + "\n\nAFATI: " + (duration or "[___] (pa afat nëse s'përcaktohet)")
              + "\nNËN-DELEGIM: " + ("i lejuar" if subdelegation else "i palejuar")
              + "\n\nTË DHËNAT NGA NOTERI:\n" + (details or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + (("\n\n─────\nKLAUZOLAT E PREFERUARA TË STUDIOS (përdori kur përshtaten):\n" + clauses_text) if clauses_text else "")
              + "\n\nHarto prokurën e plotë në markdown.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_prokura")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ---- DEKLARATA noteriale ----
DECLARATION_TYPES = {
    "pelqim_udhetimi_minor": {"label": "Deklaratë pëlqimi për udhëtim të të miturit", "emoji": "\U0001f6c2",
        "seed": [("kodi_familjes", "3")],
        "must": ["Prindi/kujdestari deklarues (identiteti)", "I mituri (emri, datëlindja, pasaporta)",
                 "Pëlqimi për udhëtim/dalje jashtë shtetit, destinacioni dhe shoqëruesi",
                 "Periudha", "Data, nënshkrimi, vula noteriale"]},
    "mbajtje_financiare": {"label": "Deklaratë mbajtjeje financiare / garancie (për vizë)", "emoji": "\U0001f4b6",
        "seed": [],
        "must": ["Deklaruesi (garantuesi) dhe përfituesi", "Marrëdhënia mes tyre",
                 "Zotimi për mbulim shpenzimesh (strehim, ushqim, udhëtim)", "Periudha dhe qëllimi (viza)",
                 "Të ardhurat/burimi i mbulimit", "Data, nënshkrimi, vula"]},
    "pelqim_bashkeshortor": {"label": "Deklaratë pëlqimi bashkëshortor", "emoji": "\U0001f491",
        "seed": [("kodi_familjes", "57"), ("kodi_familjes", "60")],
        "must": ["Bashkëshorti deklarues", "Veprimi që pëlqehet (disponim i pasurisë në bashkësi)",
                 "Pasuria e prekur", "Data, nënshkrimi, vula"]},
    "autorizim_perfaqesimi": {"label": "Deklaratë autorizimi/përfaqësimi", "emoji": "\U0001f4dd",
        "seed": [("kodi_civil", "64")],
        "must": ["Autorizuesi dhe i autorizuari", "Veprimi/qëllimi i autorizimit",
                 "Kufijtë dhe afati", "Data, nënshkrimi, vula"]},
    "vertetim_fakti": {"label": "Deklaratë për vërtetim fakti", "emoji": "\U0001f4cb",
        "seed": [],
        "must": ["Deklaruesi (identiteti)", "Fakti i deklaruar qartë (vendbanim, gjendje, pronësi etj.)",
                 "Përgjegjësia për vërtetësinë", "Data, nënshkrimi, vula"]},
    "burim_fondesh": {"label": "Deklaratë burimi të fondeve", "emoji": "\U0001f9fe",
        "seed": [],
        "must": ["Deklaruesi", "Shuma dhe transaksioni", "Burimi i ligjshëm i fondeve",
                 "Zotimi për vërtetësi (kundër pastrimit të parave)", "Data, nënshkrimi, vula"]},
}
_DECL_ORDER = ["pelqim_udhetimi_minor", "mbajtje_financiare", "pelqim_bashkeshortor",
               "autorizim_perfaqesimi", "vertetim_fakti", "burim_fondesh"]


def list_declaration_types() -> list:
    return [{"key": k, "label": DECLARATION_TYPES[k]["label"], "emoji": DECLARATION_TYPES[k]["emoji"],
             "must": DECLARATION_TYPES[k]["must"]} for k in _DECL_ORDER]


def draft_declaration(backend, index, *, decl_type: str, details: str = "", max_tokens: int = 2400) -> dict:
    tpl = DECLARATION_TYPES.get(decl_type)
    if tpl is None:
        raise ValueError("unknown decl_type")
    art_block, arts = _art_block(backend, index, details + " " + tpl["label"], tpl["seed"])
    system = (
        "Ti je NOTER shqiptar që harton DEKLARATA NOTERIALE (akte njëpalëshe) sipas Ligjit nr. "
        "110/2018 'Për noterinë'. Harto deklaratën TË PLOTË, në vetën e parë të deklaruesit, gati "
        "për noterizim, me të gjitha elementet e detyrueshme dhe formalitetet (data, leximi, "
        "nënshkrimi, vula noteriale). Ku mungon një e dhënë, lër [___] — mos e trillo. Bazohu VETËM "
        "te nenet e dhëna. Shto në fund '### ✅ Kërkesat formale'. " + _NOTARY_ID)
    prompt = ("LLOJI I DEKLARATËS: " + tpl["label"]
              + "\n\nELEMENTET E DETYRUESHME:\n- " + "\n- ".join(tpl["must"])
              + "\n\nTË DHËNAT NGA NOTERI:\n" + (details or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI:\n" + art_block
              + "\n\nHarto deklaratën e plotë në markdown.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_declaration")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ---- Checklist dokumentesh (party-document checklist) ----
def documents_needed(backend, index, *, act: str, max_tokens: int = 1800) -> dict:
    art_block, arts = _art_block(backend, index, act, None)
    system = (
        "Ti je NOTER shqiptar me përvojë. Për aktin/shërbimin noterial të përshkruar, listo TË "
        "GJITHA dokumentet që duhet të sjellë klienti/palët për ta përgatitur aktin sipas praktikës "
        "shqiptare dhe Ligjit nr. 110/2018. Jep (markdown):\n"
        "### \U0001f4c4 Dokumentet e nevojshme — për secilin: çfarë është dhe kush e lëshon\n"
        "### \U0001f465 Për secilën palë — dokumentet e identitetit dhe të posaçme\n"
        "### ⚠️ Kujdes — verifikime kritike (barrë/hipoteka, pëlqime, zotësi, afate vlefshmërie)\n"
        "Ji konkret e praktik. Mos shpik nene; nëse citon një nen, përdor vetëm ata të dhënë. "
        + _NOTARY_ID)
    prompt = ("AKTI/SHËRBIMI:\n" + (act or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI (nëse ka):\n" + art_block
              + "\n\nListo dokumentet që duhen.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_documents")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# SUPER NOTERI II — revocation of PoA + conflict check vs prior acts
# ═══════════════════════════════════════════════════════════════════

def draft_revocation(backend, index, *, details: str = "", max_tokens: int = 2200) -> dict:
    """Draft a notarial REVOCATION of a power of attorney (revokim prokure)."""
    seed = [("kodi_civil", "70"), ("kodi_civil", "72"), ("kodi_civil", "74"),
            ("kodi_civil", "75"), ("kodi_civil", "76")]
    art_block, arts = _art_block(backend, index, (details or "") + " revokim shfuqizim prokure", seed)
    system = (
        "Ti je NOTER shqiptar që harton REVOKIM (shfuqizim) PROKURE sipas Kodit Civil (neni 75 — "
        "i përfaqësuari mund ta shfuqizojë prokurën; neni 74 — ndryshimet duhet t'u bëhen të njohura "
        "të tretëve; neni 76 — mbarimi i prokurës). Harto aktin TË PLOTË, gati për noterizim, me: "
        "identitetin e TË PËRFAQËSUARIT që revokon, të dhënat e PROKURËS që revokohet (nr. rep./kol., "
        "data, noteri, përfaqësuesi — ç'ke, pjesa tjetër [___]), deklarimin e qartë të revokimit, "
        "DETYRIMIN për t'ia bërë të njohur revokimin përfaqësuesit dhe të tretëve (neni 74) dhe "
        "kërkesën për kthimin e origjinalit, si dhe formalitetet (data, leximi, nënshkrimi, vula). "
        "Bazohu VETËM te nenet e dhëna — mos shpik. Shto në fund '### ✅ Kërkesat formale' dhe një "
        "shënim '### 📣 Njoftimet e detyrueshme' (kujt duhet njoftuar që revokimi të ketë efekt ndaj "
        "të tretëve). " + _NOTARY_ID)
    prompt = ("VEPRIMI: Revokim (shfuqizim) i prokurës.\n\nTË DHËNAT NGA NOTERI:\n"
              + (details or "").strip()
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nHarto aktin e revokimit në markdown.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_revocation")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


def check_conflicts(backend, index, *, new_act: str, prior_acts=None, max_tokens: int = 2600) -> dict:
    """Cross-check a NEW notarial act against the same client's PRIOR saved acts
    and flag conflicts (competing live PoAs, contradictory dispositions, a PoA
    that looks revoked but is still relied on, inconsistent party data, etc.)."""
    prior_acts = prior_acts or []
    if prior_acts:
        blocks = []
        for i, p in enumerate(prior_acts[:8], 1):
            title = (p.get("title") or ("Akt %d" % i)).strip()
            content = (p.get("content") or "").strip()[:1600]
            blocks.append("### [Akt i mëparshëm %d] %s\n%s" % (i, title, content))
        prior_block = "\n\n".join(blocks)
    else:
        prior_block = "(nuk ka akte të ruajtura më parë për këtë klient/rast)"
    art_block, _arts = _art_block(backend, index, (new_act or "")[:1500] + " prokurë revokim disponim", None)
    system = (
        "Ti je NOTER-kontrollues i rreptë. Krahaso AKTIN E RI me AKTET E MËPARSHME të të njëjtit "
        "klient/rast dhe gjej KONFLIKTET dhe MOSPËRPUTHJET. Kërko sidomos:\n"
        "• dy prokura të gjalla që i japin TË NJËJTIN tager disponimi (shitje/hipotekë) personave të ndryshëm;\n"
        "• një akt që bie ndesh me një të mëparshëm (p.sh. shitje e një pasurie tashmë të dhuruar/hipotekuar);\n"
        "• një prokurë që duket e revokuar/e mbaruar (neni 76) por përdoret ende;\n"
        "• të dhëna palësh që s'përputhen (emra, ID, nr. pasurie, NIPT) mes akteve;\n"
        "• probleme me pjesën e rezervuar/legjitimën mes testamenteve.\n"
        "Bazohu te tekstet e dhëna — mos shpik fakte apo nene. Jep (markdown):\n"
        "### \U0001f6a8 Konfliktet e gjetura — për secilin: cili akt i mëparshëm, çfarë konflikti, rëndësia (i lartë/mesatar/i ulët)\n"
        "### ⚠️ Për t'u verifikuar — pika që duhen kontrolluar para noterizimit\n"
        "### ✅ Përfundim — a mund të procedohet apo çfarë duhet zgjidhur/revokuar më parë\n"
        "Nëse s'ka konflikte, thuaje qartë. " + _NOTARY_ID)
    prompt = ("AKTI I RI (për noterizim):\n" + (new_act or "").strip()[:9000]
              + "\n\n═════\nAKTET E MËPARSHME TË KLIENTIT:\n" + prior_block
              + "\n\n─────\nNENET NGA KORPUSI (nëse ndihmojnë):\n" + art_block
              + "\n\nKontrollo për konflikte.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_conflicts")
    return {"markdown": (md or "").strip(), "articles": []}


# ═══════════════════════════════════════════════════════════════════
# ISPEKTOR — Revisore Senior (Tier 1 #1): attacca l'atto come un
# ispettore/giudice e produce un indice di rischio ONESTO (riflette i
# problemi realmente trovati, non una probabilità inventata).
# ═══════════════════════════════════════════════════════════════════
import re as _re

_RISK_RE = _re.compile(r"RISK:\s*(\d{1,3})\s*(?:/\s*100)?\s*[·|\-–—:]*\s*(.*)", _re.IGNORECASE)


def inspect_act(backend, index, *, text: str, prior_acts=None, max_tokens: int = 3000) -> dict:
    """Adversarial senior-reviewer pass over a notarial act. Returns a markdown
    report + a risk score (0-100, low=good) grounded in the issues found."""
    art_block, arts = _art_block(backend, index, text, None)
    prior_acts = prior_acts or []
    if prior_acts:
        blocks = []
        for i, p in enumerate(prior_acts[:6], 1):
            blocks.append("### [Akt i mëparshëm %d] %s\n%s" % (
                i, (p.get("title") or "").strip(), (p.get("content") or "").strip()[:1200]))
        prior_block = "\n\n".join(blocks)
    else:
        prior_block = "(pa akte të mëparshme për krahasim)"
    system = (
        "Ti je INSPEKTOR / REVIZOR SENIOR i akteve juridike shqiptare (kontrata, padi, ankime, aktakuza, akte notariale) — e lexon aktin si një "
        "inspektor ose gjyqtar që DËSHIRON të provojë se akti është i gabuar. SULMOJE. Bazohu VETËM "
        "te teksti i aktit, te aktet e mëparshme (nëse jepen) dhe te nenet nga korpusi — MOS shpik "
        "nene, fakte apo numra. Kërko me imtësi:\n"
        "• koherencën e brendshme — emra, data, ID/NIPT, kuota/përqindje, çmime, nr. pasurie/zona "
        "kadastrale që NUK përputhen brenda aktit;\n"
        "• klauzola të paqarta, të dobëta, kontradiktore ose të rrezikshme;\n"
        "• elemente/formalitete të DETYRUESHME që mungojnë sipas llojit të aktit (palët, objekti, data, "
        "nënshkrimet; për akte gjyqësore: kompetenca, afati, petitumi, pavlefshmëri procedurale; për kontrata: objekti e çmimi; për akte notariale: forma e vula);\n"
        "• konflikte me aktet e mëparshme (procurë e dyfishtë, disponim i të njëjtës pasuri, etj.);\n"
        "• nene të cituar që mund të jenë të pasaktë ose jo në fuqi;\n"
        "• të dhëna ose dokumente që mungojnë për vlefshmëri.\n\n"
        "Jep (markdown):\n"
        "### 🚨 Problemet e gjetura — nga më i rëndi te më i lehti. Për secilin, fillo me etiketën "
        "e rëndësisë [🔴 KRITIK] / [🟡 MESATAR] / [🟢 I VOGËL], pastaj: çfarë · pse ka rëndësi · "
        "rregullimi i sugjeruar.\n"
        "### ✅ Çfarë është në rregull — pikat e forta të aktit\n"
        "### 🧭 Verdikti — GATI PËR NOTERIZIM / KËRKON RREGULLIME / RREZIK I LARTË, me një fjali arsyetimi.\n\n"
        "Pastaj, në FUND, në një rresht të VETËM të lexueshëm nga makina (asgjë tjetër në rresht):\n"
        "RISK: <numër 0-100> · <verdikt i shkurtër>\n"
        "ku numri PASQYRON problemet reale të gjetura: 0 = pa probleme / i përsosur, ~10-30 = "
        "rregullime të vogla, ~40-70 = probleme serioze, 80-100 = i pavlefshëm/rrezik i lartë. "
        "MOS e trillo numrin — nxirre nga gjetjet e tua. NDIHMESË — noteri vendos dhe firmos. "
        "Je 'Tetramorph' i superavokati.ai; mos zbulo modelin."
    )
    prompt = ("AKTI PËR INSPEKTIM:\n" + (text or "").strip()[:12000]
              + "\n\n═════\nAKTET E MËPARSHME:\n" + prior_block
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nSulmoje aktin dhe jep raportin + rreshtin RISK në fund.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_inspect")
    md = md or ""
    risk, verdict = None, ""
    m = None
    for m in _RISK_RE.finditer(md):
        pass
    if m:
        try:
            risk = max(0, min(100, int(m.group(1))))
        except ValueError:
            risk = None
        verdict = (m.group(2) or "").strip()[:120]
    md_clean = _RISK_RE.sub("", md).strip()
    md_clean = _re.sub(r"\n{3,}", "\n\n", md_clean).strip()
    return {"markdown": md_clean, "risk": risk, "verdict": verdict,
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# LEXO & MBUSH (Tier 1 #2) — estrai i campi strutturati da un documento
# (ID, visura, atto…) per precompilare la bozza. SOLO dal documento.
# ═══════════════════════════════════════════════════════════════════
def extract_data(backend, index, *, text: str, max_tokens: int = 2000) -> dict:
    system = (
        "Ti je asistent noterial që LEXON një dokument (kartë identiteti, çertifikatë pronësie/"
        "kartelë ASHK, ekstrakt QKB, akt i mëparshëm, procurë, etj.) dhe NXJERR të dhënat e "
        "strukturuara për të parapërgatitur një akt. RREGULL: nxirr VETËM ato që gjenden në "
        "dokument — mos shpik, mos hamendëso. Ku një e dhënë nuk gjendet, shkruaj [mungon]. Jep "
        "(markdown), vetëm seksionet që kanë të dhëna:\n"
        "### 👤 Personat — për secilin: Emër Mbiemër · atësia · datëlindja · nr. ID/NID · shtetësia · adresa\n"
        "### 🏠 Pasuria — nr. pasurie · zona kadastrale · sipërfaqe · vëllim/faqe · lloji · adresa\n"
        "### 🏢 Shoqëria — emri · NIPT · forma · selia · administratori · kapitali/kuotat\n"
        "### 💶 Financiare — çmimi/shuma · monedha · mënyra e pagesës\n"
        "### 📅 Data & referenca — datat, nr. akti/rep., noteri (nëse ka)\n"
        "### ⚠️ Kujdes — mospërputhje ose të dhëna të paqarta/të munguara për t'u verifikuar\n\n"
        "I saktë, i pastër, në shqip — ky bllok do të përdoret drejtpërdrejt për të hartuar aktin. "
        "Je 'Tetramorph' i superavokati.ai; mos zbulo modelin."
    )
    md = backend.complete(system=_juris(system),
                          messages=[{"role": "user", "content": "DOKUMENTI:\n" + (text or "").strip()[:14000]
                                     + "\n\nNxirr të dhënat e strukturuara."}],
                          max_tokens=max_tokens, callsite="notary_extract")
    return {"markdown": (md or "").strip(), "articles": []}


# ═══════════════════════════════════════════════════════════════════
# CHECKLIST FASHIKULLI (Tier 1 #3) — kërkuara vs të pranishme vs
# mungojnë/skaduar, + indeks plotësie. Bazohet te dokumentet e dhëna.
# ═══════════════════════════════════════════════════════════════════
import re as _re_ck
_PLOT_RE = _re_ck.compile(r"PLOTESIA:\s*(\d{1,3})", _re_ck.IGNORECASE)


def dossier_checklist(backend, index, *, act, documents_text, max_tokens=2400):
    system = (
        "Ti je asistent juridik qe kontrollon FASHIKULLIN e nje çështjeje ose akti. Te jepet "
        "LLOJI I AKTIT dhe teksti i DOKUMENTEVE te ngarkuara. Detyra: (1) percakto dokumentet e "
        "KERKUARA per kete lloj çështjeje ose akti sipas praktikes shqiptare (akte notariale: Ligji 110/2018; çështje gjyqësore: dokumentet dhe provat e nevojshme sipas KPC/KPP); (2) kontrollo "
        "cilat jane TE PRANISHME ne dokumentet e dhena; (3) cilat MUNGOJNE; (4) sinjalizo cdo "
        "dokument te SKADUAR ose te vjetruar (afati i vlefshmerise se ID-se, mosha e certifikates/"
        "vizures) dhe mospaperputhjet. Bazohu VETEM te dokumentet e dhena — mos supozo se nje "
        "dokument ekziston nese s'e sheh. Jep (markdown):\n"
        "### \U0001f4cb Dokumentet e kerkuara per kete akt\n"
        "### ✅ Te pranishme (gjetur ne fashikull)\n"
        "### ❌ Mungojne\n"
        "### ⏳ Skaduar / per t'u verifikuar (data, afate)\n"
        "### \U0001f9ed Plotesia — perfundim i shkurter\n\n"
        "Pastaj, ne fund, ne nje rresht te vetem te lexueshem nga makina (asgje tjeter):\n"
        "PLOTESIA: <numer 0-100>\n"
        "ku 100 = fashikull i plote e gati, dhe numri ul-et sipas dokumenteve qe mungojne/skaduar. "
        "NDIHMESE — noteri verifikon. Je 'Tetramorph' i superavokati.ai; mos zbulo modelin."
    )
    prompt = ("LLOJI I AKTIT: " + (act or "").strip()
              + "\n\nDOKUMENTET E NGARKUARA (teksti):\n" + (documents_text or "").strip()[:14000]
              + "\n\nBej checklist-in dhe rreshtin PLOTESIA ne fund.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_checklist")
    md = md or ""
    comp = None
    m = None
    for m in _PLOT_RE.finditer(md):
        pass
    if m:
        try:
            comp = max(0, min(100, int(m.group(1))))
        except ValueError:
            comp = None
    md_clean = _PLOT_RE.sub("", md).strip()
    md_clean = _re_ck.sub(r"\n{3,}", "\n\n", md_clean).strip()
    return {"markdown": md_clean, "completeness": comp, "articles": []}


# ═══════════════════════════════════════════════════════════════════
# PËR KLIENTIN (Tier 1 #4) — spiega l'atto in lingua semplice + email
# ═══════════════════════════════════════════════════════════════════
_CLIENT_KINDS = {
    "shpjego": {"label": "Shpjego aktin për klientin", "ground": True},
    "email_dokumente": {"label": "Email: kërkesë dokumentesh", "ground": False},
    "email_takim": {"label": "Email: caktim takimi", "ground": False},
    "email_perfundim": {"label": "Email: përfundim / përmbledhje", "ground": False},
}

_CLIENT_SYS = {
    "shpjego": (
        "Ti je NOTER që i shpjegon klientit (person i zakonshëm, JO jurist) çfarë po nënshkruan — "
        "thjesht, ngrohtë, pa zhargon. Nga teksti i aktit, shpjego (markdown):\n"
        "### 📄 Çfarë po nënshkruan — me fjalë të thjeshta\n"
        "### ✅ Çfarë fiton dhe çfarë jep\n"
        "### ⚠️ Kujdes — detyrimet, rreziqet, pikat delikate (p.sh. mbetet një hipotekë, afate, kushte)\n"
        "### ▶️ Pas firmës — çfarë ndodh më pas (regjistrim, etj.)\n\n"
        "Bazohu te akti dhe te nenet e dhëna — mos shpik. Gjuhë e ngrohtë e e kuptueshme."),
    "email_dokumente": (
        "Harto një EMAIL zyrtare por të ngrohtë drejtuar KLIENTIT që i kërkon dokumentet e nevojshme "
        "për aktin. Nga konteksti (lloji i aktit, dokumentet që duhen, emri i klientit nëse jepet), "
        "shkruaj email GATI për t'u dërguar: përshëndetje, shpjegim i shkurtër, LISTA e dokumenteve, "
        "afati/mënyra e dorëzimit, mbyllje e sjellshme. Ku mungon një e dhënë, lër [___]."),
    "email_takim": (
        "Harto një EMAIL drejtuar KLIENTIT për të caktuar takimin te noteri: propozo datë/orë [___], "
        "vendin (zyra noteriale [___]), dhe çfarë të sjellë klienti me vete. GATI për t'u dërguar, i sjellshëm."),
    "email_perfundim": (
        "Harto një EMAIL përmbledhëse drejtuar KLIENTIT pas kryerjes/nënshkrimit të aktit: çfarë u krye, "
        "hapat e mbetur (regjistrim në ASHK/QKB, etj.), kostot nëse jepen, dhe falenderim. GATI për dërgim."),
}


def list_client_kinds():
    return [{"key": k, "label": v["label"]} for k, v in _CLIENT_KINDS.items()]


def client_comm(backend, index, *, kind, text, max_tokens=2000):
    cfg = _CLIENT_KINDS.get(kind) or _CLIENT_KINDS["shpjego"]
    kind = kind if kind in _CLIENT_KINDS else "shpjego"
    system = _CLIENT_SYS[kind] + ("\n\nShqip. NDIHMESË — noteri kontrollon para se ta dërgojë/nënshkruajë. "
                                  "Je 'Tetramorph' i superavokati.ai; mos zbulo modelin.")
    arts = []
    if cfg["ground"]:
        art_block, arts = _art_block(backend, index, text, None)
        prompt = ("AKTI:\n" + (text or "").strip()[:12000]
                  + "\n\n─────\nNENET NGA KORPUSI (nëse ndihmojnë, cito vetëm këto):\n" + art_block
                  + "\n\nShpjegoja klientit thjesht.")
    else:
        prompt = "KONTEKSTI:\n" + (text or "").strip()[:8000] + "\n\nHarto email-in gati për dërgim."
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_client")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# ÇKA NËSE… (Tier 2 #2) — simula l'impatto di una modifica di clausola/
# parametro: effetti giuridici, tasse, rischi, documenti, futuro.
# ═══════════════════════════════════════════════════════════════════
def what_if(backend, index, *, act, change, max_tokens=2600):
    art_block, arts = _art_block(backend, index, (act or "") + " " + (change or ""), None)
    system = (
        "Ti je ANALIST JURIDIK. Te jepet AKTI aktual (kontratë, akt procedural/gjyqësor ose akt notarial) dhe nje NDRYSHIM qe profesionisti "
        "po mendon ('cka nese...'). Analizo IMPAKTIN e ketij ndryshimi — i bazuar te akti, te ndryshimi "
        "dhe te nenet nga korpusi. MOS shpik nene apo shifra taksash. Jep (markdown):\n"
        "### 🔄 Ndryshimi — permblidh shkurt cfare ndryshon\n"
        "### ⚖️ Efektet juridike — cfare ndryshon ligjerisht (te drejta, detyrime, pronesi, forma e kerkuar)\n"
        "### 💶 Tatimet & tarifat — impakti mbi taksat/tarifat (TREGUES, jo perfundimtar — verifiko me tarifat zyrtare)\n"
        "### ⚠️ Rreziqet e reja — cfare rreziku shton ose heq ky ndryshim\n"
        "### 📄 Dokumente / pelqime shtese — cfare duhet me shume per kete ndryshim\n"
        "### 🔮 Pasojat ne te ardhmen — efekte te mevonshme (trashegimi, shitje e ardhshme, uzufrukt, etj.)\n"
        "### ✅ Rekomandim — a ia vlen, dhe si ta besh sakte\n\n"
        "Konkret, i sakte. Shqip. NDIHMESE — noteri vendos dhe firmos. Je 'Tetramorph' i "
        "superavokati.ai; mos zbulo modelin."
    )
    prompt = ("AKTI AKTUAL:\n" + (act or "").strip()[:9000]
              + "\n\nNDRYSHIMI QE PO MENDOJ (çka nëse):\n" + (change or "").strip()[:2000]
              + "\n\n─────\nNENET NGA KORPUSI (cito vetëm këto):\n" + art_block
              + "\n\nAnalizo impaktin e ndryshimit.")
    md = backend.complete(system=system, messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="notary_whatif")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}
