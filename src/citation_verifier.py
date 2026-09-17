"""V7.13 — Provenance lock: verify every legal citation in the model output.

For a lawyer, an unverified citation is a landmine. After the brain produces
its Albanian answer, we extract every ``Neni N <kodi>`` pattern and check it
against the BM25 index. Each citation gets one of three statuses:

    verified        — exact (code, number) match in the corpus
    fake            — code given but article number not in that code
    needs_code      — number given without code; we list candidate codes

The result is attached to the API response as ``citations`` so the UI can
show a trust badge ("✓ 4 të verifikuara · ⚠ 1 e paverifikuar") and turn each
citation into a clickable provenance link to the source article.

The verifier is a pure function of (text, index) — no side effects, no LLM.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .retrieval import ArticleIndex

# ── Code aliases ────────────────────────────────────────────────────────────
# Maps the spoken/written form Albanian lawyers use → the internal corpus key.
# Order matters for the regex (longer phrases first), but the lookup is a
# straight dict so we just normalise via lower() + strip first.
#
# Genitive/dative endings (-it, -ës, -in, -ut) are normalised here so that
# "Kodit Penal", "Kodi Penal", "Kodin Penal" all resolve the same.

CODE_ALIASES: dict[str, str] = {
    # Short abbreviations (uppercase or lowercase in source — we lowercase)
    "kp": "kodi_penal",
    "kpp": "kodi_proc_penale",
    "kpr.p": "kodi_proc_penale",
    "kpr p": "kodi_proc_penale",
    "kprp": "kodi_proc_penale",       # 16 set 2026: «KPrP» / «K.Pr.P.» (senza il punto finale: \b)
    "k.pr.p": "kodi_proc_penale",
    "kc": "kodi_civil",
    "kpc": "kodi_proc_civile",
    "kpr.c": "kodi_proc_civile",
    "kpr c": "kodi_proc_civile",
    "kprc": "kodi_proc_civile",       # «KPrC» — la sigla più usata dai giuristi, mancava (golden [79])
    "k.pr.c": "kodi_proc_civile",
    "kpa": "kodi_proc_admin",
    "kpra": "kodi_proc_admin",
    "k.pr.a": "kodi_proc_admin",
    "kf": "kodi_familjes",
    "kpu": "kodi_punes",
    "kpun": "kodi_punes",
    "kr": "kodi_rrugor",
    "kd": "kodi_doganor",
    "kdog": "kodi_doganor",
    "kdt": "kodi_detar",
    "kdet": "kodi_detar",
    "kz": "kodi_zgjedhor",
    "kzgj": "kodi_zgjedhor",

    # Spelled-out — keep all common case-form variants
    "kodi penal": "kodi_penal",
    "kodit penal": "kodi_penal",
    "kodin penal": "kodi_penal",

    "kodi civil": "kodi_civil",
    "kodit civil": "kodi_civil",
    "kodin civil": "kodi_civil",

    "kodi i procedurës penale": "kodi_proc_penale",
    "kodit të procedurës penale": "kodi_proc_penale",
    "kodi i procedures penale": "kodi_proc_penale",
    "kodit te procedures penale": "kodi_proc_penale",

    "kodi i procedurës civile": "kodi_proc_civile",
    "kodit të procedurës civile": "kodi_proc_civile",
    "kodi i procedures civile": "kodi_proc_civile",
    "kodit te procedures civile": "kodi_proc_civile",

    "kodi i procedurave administrative": "kodi_proc_admin",
    "kodit të procedurave administrative": "kodi_proc_admin",
    "kodi procedures administrative": "kodi_proc_admin",
    "kodi i procedurës administrative": "kodi_proc_admin",
    "kodit të procedurës administrative": "kodi_proc_admin",
    "kodi i procedures administrative": "kodi_proc_admin",
    "kodit te procedures administrative": "kodi_proc_admin",

    "kodi i familjes": "kodi_familjes",
    "kodit të familjes": "kodi_familjes",
    "kodin e familjes": "kodi_familjes",

    "kodi i punës": "kodi_punes",
    "kodit të punës": "kodi_punes",
    "kodi i punes": "kodi_punes",
    "kodit te punes": "kodi_punes",
    "kodin e punës": "kodi_punes",
    "kodin e punes": "kodi_punes",

    "kodi rrugor": "kodi_rrugor",
    "kodit rrugor": "kodi_rrugor",
    "kodi doganor": "kodi_doganor",
    "kodit doganor": "kodi_doganor",
    "kodi detar": "kodi_detar",
    "kodit detar": "kodi_detar",
    "kodi zgjedhor": "kodi_zgjedhor",
    "kodit zgjedhor": "kodi_zgjedhor",
    "kodi ajror": "kodi_ajror",
    "kodit ajror": "kodi_ajror",

    "kushtetuta": "kushtetuta",
    "kushtetutës": "kushtetuta",
    "kushtetutes": "kushtetuta",
    "kushtetutën": "kushtetuta",
    "kushtetuten": "kushtetuta",

    # The 4 special ligji — citation form usually quotes the law number,
    # but lawyers also use these short names colloquially.
    "ligji i falimentimit": "ligji_falimentimi",
    "ligji i shoqërive tregtare": "ligji_shoqerite_tregtare",
    "ligji shoqërive tregtare": "ligji_shoqerite_tregtare",
    "ligji i konsumatorëve": "ligji_konsumatoret",
    "ligji per mbrojtjen e konsumatoreve": "ligji_konsumatoret",
    # 16 set 2026: la 9887/2008 e' SHFUQIZUAR dalla 124/2024 (ne fuqi 1.2.2025) — il nome
    # generico va alla legge vigente; la vecchia si raggiunge solo col numero 9887
    "ligji i të dhënave personale": "ligji_te_dhenat_2024",
    "ligji i te dhenave personale": "ligji_te_dhenat_2024",
    "ligji i qkb": "ligji_qkb",
    "ligji per qkb": "ligji_qkb",
    "ligji i policisë së shtetit": "ligji_policia_2024",
    "ligji per policine e shtetit": "ligji_policia_2024",
    "ligji i policise se shtetit": "ligji_policia_2024",
    "ligji i policisë": "ligji_policia_2024",
    "ligji i policise": "ligji_policia_2024",
    "ligji per policine": "ligji_policia_2024",
    "policinë e shtetit": "ligji_policia_2024",
    "policisë së shtetit": "ligji_policia_2024",
    "policia e shtetit": "ligji_policia_2024",
    "rregullorja e policisë së shtetit": "rregullore_policia",
    "rregullore e policisë së shtetit": "rregullore_policia",
    "rregullorja e policisë": "rregullore_policia",
    "rregullore e policisë": "rregullore_policia",
    "rregullores së policisë": "rregullore_policia",
    "rregullorja e policise": "rregullore_policia",
    "ligji për policinë e shtetit": "ligji_policia_2024",
    "ligjit për policinë e shtetit": "ligji_policia_2024",
    "ligjit i policisë": "ligji_policia_2024",
    "ligji i policise": "ligji_policia_2024",
}


# ── 16 set 2026: 29 leggi albanesi da QBZ (tools/al_sources.json) ──
# Ogni voce: codice, frasi-base (dopo «ligji për …» o nome intero). Le forme declinate
# («ligjit për», «ligjin për») e quelle senza dieresi (ë→e, ç→c) si generano qui sotto:
# scriverle a mano tutte era la strada degli errori.
_AL_NEW_ALIASES: list[tuple[str, list[str]]] = [
    ("ligji_dnp", ["ligji për të drejtën ndërkombëtare private", "ligji i të drejtës ndërkombëtare private",
                   "e drejta ndërkombëtare private"]),
    ("ligji_te_huajt", ["ligji për të huajt", "ligji i të huajve"]),
    ("ligji_shtetesia", ["ligji për shtetësinë", "ligji i shtetësisë"]),
    ("kodi_te_miturve", ["kodi i drejtësisë penale për të mitur", "kodit të drejtësisë penale për të mitur",
                         "kodi i drejtesise penale per te mitur", "kodi për të mitur"]),
    ("ligji_procedurat_tatimore", ["ligji për procedurat tatimore", "ligji i procedurave tatimore"]),
    ("ligji_tatimi_te_ardhurat", ["ligji për tatimin mbi të ardhurat", "ligji i tatimit mbi të ardhurat"]),
    ("ligji_tvsh", ["ligji për tatimin mbi vlerën e shtuar", "ligji i tvsh-së", "ligji i tvsh", "ligji për tvsh-në",
                    "ligji për tvsh"]),
    ("ligji_sigurimi_mjeteve", ["ligji për sigurimin e detyrueshëm në sektorin e transportit",
                                "ligji për sigurimin e detyrueshëm"]),
    ("vkm_dispozita_doganore", ["dispozitat zbatuese të kodit doganor", "dispozitave zbatuese të kodit doganor",
                                "vkm 651/2017", "vkm nr. 651"]),
    ("ligji_ndihma_juridike", ["ligji për ndihmën juridike të garantuar nga shteti", "ligji për ndihmën juridike",
                               "ligji i ndihmës juridike"]),
    ("ligji_kundervajtjet", ["ligji për kundërvajtjet administrative", "ligji i kundërvajtjeve administrative"]),
    ("ligji_permbarimi_privat", ["ligji për shërbimin përmbarimor gjyqësor privat", "ligji për shërbimin përmbarimor",
                                 "ligji i përmbarimit"]),
    # 9669/2006 si cita col suo nome proprio; i nomi generici vanno alla legge VIGENTE 11/2026
    ("ligji_dhuna_familje", ["ligji për masa ndaj dhunës në marrëdhëniet familjare"]),
    ("ligji_dhuna_familje_2026", ["ligji për parandalimin dhe mbrojtjen nga dhuna ndaj grave dhe dhuna në familje",
                                  "ligji për dhunën ndaj grave", "ligji për dhunën në familje", "ligji i dhunës në familje",
                                  "ligji kundër dhunës në familje", "ligji i ri për dhunën në familje"]),
    ("ligji_gjendja_civile", ["ligji për gjendjen civile", "ligji i gjendjes civile"]),
    ("ligji_antimafia", ["ligji antimafia", "ligji për parandalimin dhe goditjen e krimit të organizuar"]),
    ("ligji_te_dhenat_2024", ["ligji për mbrojtjen e të dhënave personale", "ligji i mbrojtjes së të dhënave personale"]),
    ("ligji_sigurimet_shoqerore", ["ligji për sigurimet shoqërore", "ligji i sigurimeve shoqërore"]),
    ("ligji_avokatia", ["ligji për profesionin e avokatit", "ligji për avokatinë", "ligji i avokatisë"]),
    ("ligji_ndermjetesimi", ["ligji për ndërmjetësimin", "ligji i ndërmjetësimit"]),
    ("ligji_arbitrazhi", ["ligji për arbitrazhin", "ligji i arbitrazhit"]),
    ("ligji_planifikimi_territorit", ["ligji për planifikimin dhe zhvillimin e territorit", "ligji për planifikimin e territorit",
                                      "ligji i planifikimit të territorit"]),
    ("ligji_te_denuarit", ["ligji për të drejtat dhe trajtimin e të dënuarve", "ligji për trajtimin e të dënuarve"]),
    ("ligji_prokuroria", ["ligji për organizimin dhe funksionimin e prokurorisë", "ligji për prokurorinë",
                          "ligji i prokurorisë"]),
    ("ligji_diskriminimi", ["ligji për mbrojtjen nga diskriminimi", "ligji kundër diskriminimit"]),
    ("ligji_armet", ["ligji për armët", "ligji i armëve"]),
    ("ligji_transportet_rrugore", ["ligji për transportet rrugore", "ligji i transporteve rrugore"]),
    ("ligji_prokurimi_publik", ["ligji për prokurimin publik", "ligji i prokurimit publik"]),
    ("ligji_trajtimi_prones", ["ligji për trajtimin e pronës", "ligji i trajtimit të pronës"]),
    ("ligji_proceset_kalimtare", ["ligji për përfundimin e proceseve kalimtare të pronësisë",
                                  "ligji për proceset kalimtare të pronësisë"]),
    # audit 16 set: leggi già in corpus che non si riconoscevano per nome
    ("ligji_pastrimi_parave", ["ligji për parandalimin e pastrimit të parave", "ligji kundër pastrimit të parave",
                               "ligji i pastrimit të parave", "ligji antipastrim", "parandalimin e pastrimit të parave"]),
    ("ligji_qkb", ["ligji për qendrën kombëtare të biznesit", "qendrën kombëtare të biznesit", "qendra kombëtare e biznesit"]),
    ("ligji_shoqerite_tregtare", ["ligji për tregtarët dhe shoqëritë tregtare", "tregtarët dhe shoqëritë tregtare"]),
    ("ligji_falimentimi", ["ligji për falimentimin"]),
    ("ligji_konsumatoret", ["ligji për mbrojtjen e konsumatorëve"]),
    ("ligji_kadastra", ["ligji për kadastrën", "ligji i kadastrës"]),
    ("ligji_noteri", ["ligji për noterinë", "ligji i noterisë"]),
    ("rregullore_policia", ["vkm 112/2025", "vkm nr. 112/2025", "vkm nr. 112", "rregullorja e re e policisë",
                            "rregullore e policisë së shtetit (vkm 112/2025)"]),
    ("kodi_ajror", ["ligji nr. 96/2020", "kodi ajror", "kodit ajror"]),
]
_AL_TRANSLIT = str.maketrans({"ë": "e", "ç": "c", "Ë": "e", "Ç": "c"})
for _code, _phrases in _AL_NEW_ALIASES:
    for _p in _phrases:
        _forms = {_p}
        if _p.startswith("ligji "):
            _forms.update({"ligjit " + _p[6:], "ligjin " + _p[6:]})
        for _f in list(_forms):
            _forms.add(_f.translate(_AL_TRANSLIT))
        for _f in _forms:
            CODE_ALIASES.setdefault(_f.lower(), _code)

# The 5 special laws are most often cited by statute number ("ligji nr. 9901"),
# not by name. Map the canonical numbers to the corpus keys.
_LAW_NUMBER_ALIASES: dict[str, str] = {
    "9901": "ligji_shoqerite_tregtare",   # shoqëritë tregtare
    "8901": "ligji_falimentimi",          # falimentimi (klasik)
    "9887": "ligji_te_dhenat",            # mbrojtja e të dhënave personale
    "9902": "ligji_konsumatoret",         # mbrojtja e konsumatorëve
    "9723": "ligji_qkb",                  # QKB
    "108": "ligji_policia",              # Policia e Shtetit (108/2014)
    "750": "rregullore_policia",         # Rregullore Policia (VKM 750/2015)
    "82": "ligji_policia_2024",          # Policia e Shtetit (aktual, 82/2024)
    # ── 16 set 2026: chiavi «NUMERO/ANNO» (i numeri piccoli si ripetono ogni anno:
    # 111/2018 kadastra ≠ 111/2017 ndihma juridike) + numeri lunghi univoci ──
    "111/2018": "ligji_kadastra", "110/2018": "ligji_noteri", "110/2016": "ligji_falimentimi",
    "108/2014": "ligji_policia", "82/2024": "ligji_policia_2024", "750/2015": "rregullore_policia",
    "10428": "ligji_dnp", "10428/2011": "ligji_dnp",
    "79/2021": "ligji_te_huajt", "113/2020": "ligji_shtetesia", "37/2017": "kodi_te_miturve",
    "9920": "ligji_procedurat_tatimore", "9920/2008": "ligji_procedurat_tatimore",
    "29/2023": "ligji_tatimi_te_ardhurat", "92/2014": "ligji_tvsh",
    "32/2021": "ligji_sigurimi_mjeteve", "10076": "ligji_sigurimi_mjeteve",   # 10076/2009 shfuqizuar → 32/2021
    "651/2017": "vkm_dispozita_doganore", "651": "vkm_dispozita_doganore",
    "111/2017": "ligji_ndihma_juridike", "10279": "ligji_kundervajtjet", "10279/2010": "ligji_kundervajtjet",
    "26/2019": "ligji_permbarimi_privat", "9669": "ligji_dhuna_familje", "9669/2006": "ligji_dhuna_familje",
    "10129": "ligji_gjendja_civile", "10129/2009": "ligji_gjendja_civile",
    "10192": "ligji_antimafia", "10192/2009": "ligji_antimafia",
    "124/2024": "ligji_te_dhenat_2024", "7703": "ligji_sigurimet_shoqerore", "7703/1993": "ligji_sigurimet_shoqerore",
    "55/2018": "ligji_avokatia", "10385": "ligji_ndermjetesimi", "10385/2011": "ligji_ndermjetesimi",
    "52/2023": "ligji_arbitrazhi", "107/2014": "ligji_planifikimi_territorit", "81/2020": "ligji_te_denuarit",
    "97/2016": "ligji_prokuroria", "10221": "ligji_diskriminimi", "10221/2010": "ligji_diskriminimi",
    "74/2014": "ligji_armet", "8308": "ligji_transportet_rrugore", "8308/1998": "ligji_transportet_rrugore",
    "162/2020": "ligji_prokurimi_publik", "133/2015": "ligji_trajtimi_prones", "20/2020": "ligji_proceset_kalimtare",
    # audit 16 set: il corpus non riconosceva il proprio numero
    "9917": "ligji_pastrimi_parave", "9917/2008": "ligji_pastrimi_parave", "131/2015": "ligji_qkb",
    "9902/2008": "ligji_konsumatoret", "9901/2008": "ligji_shoqerite_tregtare", "110/2016": "ligji_falimentimi",
    "112/2025": "rregullore_policia",   # nuova Rregullore (VKM 112/2025; la 750/2015 è shfuqizuar)
    "96/2020": "kodi_ajror",
    "11/2026": "ligji_dhuna_familje_2026",   # trovata da freshness_check: 9669/2006 shfuqizuar
}
# cattura anche l'anno («ligji nr. 79/2021», «ligjit nr. 111, datë 14.12.2017» → 111 + 2017)
_LAW_NUM_RE = re.compile(r"ligj\w*\s+(?:nr\.?\s*)?(\d{2,5})(?:\s*/\s*(\d{4})|\s*,?\s*dat[ëe]\s*\d{1,2}\.\d{1,2}\.(\d{4}))?", re.IGNORECASE)

# Human-readable label per code → shown in the UI badge.
CODE_LABELS: dict[str, str] = {
    "kodi_penal": "Kodi Penal",
    "kodi_proc_penale": "K. Proc. Penale",
    "kodi_civil": "Kodi Civil",
    "kodi_proc_civile": "K. Proc. Civile",
    "kodi_proc_admin": "K. Proc. Adm.",
    "kodi_familjes": "Kodi i Familjes",
    "kodi_punes": "Kodi i Punës",
    "kodi_rrugor": "Kodi Rrugor",
    "kodi_doganor": "Kodi Doganor",
    "kodi_detar": "Kodi Detar",
    "kodi_zgjedhor": "Kodi Zgjedhor",
    "kodi_ajror": "Kodi Ajror",
    "kushtetuta": "Kushtetuta",
    "ligji_falimentimi": "Ligji Falimentimi",
    "ligji_shoqerite_tregtare": "Ligji Shoq. Tregtare",
    "ligji_konsumatoret": "Ligji Konsumatorët",
    "ligji_te_dhenat": "Ligji Mbr. Dhënash",
    "ligji_qkb": "Ligji QKB",
    "ligji_policia": "Ligji Policia 108/2014",
    "ligji_policia_2024": "Ligji Policia 82/2024",
    "rregullore_policia": "Rregullore Policia",
    "ligji_pastrimi_parave": "Ligji Kundër Pastrimit 9917/2008",
    "ligji_kadastra": "Ligji Kadastra 111/2018",
    "ligji_noteri": "Ligji Noteria 110/2018",
    # ── 16 set 2026: 29 leggi da QBZ ──
    "ligji_dnp": "Ligji DNP 10428/2011", "ligji_te_huajt": "Ligji Të Huajt 79/2021",
    "ligji_shtetesia": "Ligji Shtetësia 113/2020", "kodi_te_miturve": "K. Drejt. Penale Të Mitur 37/2017",
    "ligji_procedurat_tatimore": "Ligji Proc. Tatimore 9920/2008", "ligji_tatimi_te_ardhurat": "Ligji Tatimi Ardhurat 29/2023",
    "ligji_tvsh": "Ligji TVSH 92/2014", "ligji_sigurimi_mjeteve": "Ligji Sigurimi Transport 32/2021",
    "vkm_dispozita_doganore": "VKM 651/2017 Disp. Doganore", "ligji_ndihma_juridike": "Ligji Ndihma Juridike 111/2017",
    "ligji_kundervajtjet": "Ligji Kundërvajtjet 10279/2010", "ligji_permbarimi_privat": "Ligji Përmbarimi 26/2019",
    "ligji_dhuna_familje": "Ligji Dhuna në Familje 9669/2006 (shfuqizuar nga 11/2026)",
    "ligji_dhuna_familje_2026": "Ligji Dhuna ndaj Grave dhe në Familje 11/2026", "ligji_gjendja_civile": "Ligji Gjendja Civile 10129/2009",
    "ligji_antimafia": "Ligji Antimafia 10192/2009", "ligji_te_dhenat_2024": "Ligji Të Dhënat 124/2024",
    "ligji_sigurimet_shoqerore": "Ligji Sig. Shoqërore 7703/1993", "ligji_avokatia": "Ligji Avokatia 55/2018",
    "ligji_ndermjetesimi": "Ligji Ndërmjetësimi 10385/2011", "ligji_arbitrazhi": "Ligji Arbitrazhi 52/2023",
    "ligji_planifikimi_territorit": "Ligji Planifikimi 107/2014", "ligji_te_denuarit": "Ligji Të Dënuarit 81/2020",
    "ligji_prokuroria": "Ligji Prokuroria 97/2016", "ligji_diskriminimi": "Ligji Diskriminimi 10221/2010",
    "ligji_armet": "Ligji Armët 74/2014", "ligji_transportet_rrugore": "Ligji Transportet 8308/1998",
    "ligji_prokurimi_publik": "Ligji Prokurimi 162/2020", "ligji_trajtimi_prones": "Ligji Trajtimi Pronës 133/2015",
    "ligji_proceset_kalimtare": "Ligji Proceset Kalimtare 20/2020",
    # ── corpus italiano ──
    "antiriciclaggio": "D.Lgs 231/2007 (antiricicl.)",
    # ── wave5 + EUR-Lex (16 set 2026) ──
    "codice_doganale_nazionale": "D.Lgs 141/2024 (DNC dogane)",
    "accise": "TU Accise (D.Lgs 504/1995)",
    "iva": "DPR 633/1972 (IVA — abrogato dal TU D.Lgs 10/2026)",
    "imposta_registro": "DPR 131/1986 (registro — abrogato dal TU D.Lgs 123/2025)",
    "imposta_successioni": "D.Lgs 346/1990 (successioni — abrogato dal TU D.Lgs 123/2025)",
    "sanzioni_tributarie": "D.Lgs 472/1997 (abrogato dal TU D.Lgs 173/2024)",
    "giustizia_tributaria": "TU Giustizia trib. (D.Lgs 175/2024)",
    "statuto_contribuente": "L. 212/2000 (Statuto contrib.)",
    "accertamento_imposte": "DPR 600/1973 (in gran parte abrogato dal TU D.Lgs 141/2026)",
    "riscossione": "DPR 602/1973 (abrogato dal TU D.Lgs 33/2025)",
    "reati_tributari": "D.Lgs 74/2000 (abrogato dal TU D.Lgs 173/2024)",
    # ── wave6 (16 set 2026): i testi unici della riforma fiscale — la legge VIGENTE ──
    "tu_sanzioni_tributarie": "TU Sanzioni tributarie amm. e penali (D.Lgs 173/2024)",
    "tu_riscossione": "TU Versamenti e riscossione (D.Lgs 33/2025)",
    "tu_registro": "TU Registro e tributi indiretti (D.Lgs 123/2025)",
    "tu_iva": "TU IVA (D.Lgs 10/2026)",
    "tu_accertamento": "TU Adempimenti e accertamento (D.Lgs 141/2026)",
    # ── wave7 «blocco A» (16 set 2026) ──
    "diritto_internazionale_privato": "L. 218/1995 (dir. internaz. privato)",
    "cittadinanza": "L. 91/1992 (cittadinanza)",
    "regolamento_cittadinanza": "DPR 572/1993 (reg. cittadinanza)",
    "cittadini_ue": "D.Lgs 30/2007 (cittadini UE e familiari)",
    "protezione_internazionale": "D.Lgs 25/2008 (protezione internaz.)",
    "contratti_lavoro": "D.Lgs 81/2015 (contratti di lavoro)",
    "orario_lavoro": "D.Lgs 66/2003 (orario di lavoro)",
    "maternita_paternita": "D.Lgs 151/2001 (maternità/paternità)",
    "legge_biagi": "D.Lgs 276/2003 (Biagi)",
    "pubblico_impiego": "D.Lgs 165/2001 (pubblico impiego)",
    "negoziazione_assistita": "DL 132/2014 (negoziazione assistita)",
    "giudice_pace_penale": "D.Lgs 274/2000 (giudice di pace penale)",
    "mandato_arresto_europeo": "L. 69/2005 (mandato d'arresto europeo)",
    "casellario": "DPR 313/2002 (casellario giudiziale)",
    "unioni_civili": "L. 76/2016 (unioni civili/convivenze)",
    "consenso_informato_dat": "L. 219/2017 (consenso informato/DAT)",
    "regolamento_notarile": "R.D. 1326/1914 (reg. notarile)",
    "prestazione_energetica": "D.Lgs 192/2005 (APE)",
    "legge_urbanistica": "L. 1150/1942 (urbanistica)",
    "armi": "L. 110/1975 (armi)",
    "regolamento_penitenziario": "DPR 230/2000 (reg. penitenziario)",
    "tfue": "TFUE (Trattato sul funzionamento dell'UE)",
    "tue": "TUE (Trattato sull'Unione europea)",
    "carta_diritti_ue": "Carta dei diritti fondamentali UE",
    "codice_frontiere_schengen": "Reg. (UE) 2016/399 (codice frontiere Schengen)",
    "reg_ue_2018_1806": "Reg. (UE) 2018/1806 (visti: paesi esenti)",
    "codice_visti": "Reg. (CE) 810/2009 (codice dei visti)",
    "roma_iii": "Reg. (UE) 1259/2010 (Roma III)",
    "alimenti_ue": "Reg. (CE) 4/2009 (obbligazioni alimentari)",
    "regimi_patrimoniali_ue": "Reg. (UE) 2016/1103 (regimi patrimoniali)",
    "ingiunzione_europea": "Reg. (CE) 1896/2006 (ingiunzione europea)",
    "small_claims_ue": "Reg. (CE) 861/2007 (modesta entità)",
    "notifiche_ue": "Reg. (UE) 2020/1784 (notifiche UE)",
    # ── wave8 «blocco B»: trattati (allegato della legge di ratifica) ──
    "convenzione_it_al_fisco": "Convenzione Italia–Albania doppie imposizioni (L. 175/1998)",
    "protocollo_it_al_migranti": "Protocollo Italia–Albania migranti (L. 14/2024)",
    "cedu": "CEDU (Convenzione europea dei diritti dell'uomo)",
    "preleggi": "Preleggi (disp. sulla legge in generale, R.D. 262/1942)",
    "cedu_protocollo_1": "Prot. n. 1 CEDU (proprietà, istruzione, elezioni)",
    "cedu_protocollo_4": "Prot. n. 4 CEDU (circolazione, espulsioni)",
    "cedu_protocollo_6": "Prot. n. 6 CEDU (pena di morte)",
    "cedu_protocollo_7": "Prot. n. 7 CEDU (espulsione stranieri, ne bis in idem)",
    "cedu_protocollo_12": "Prot. n. 12 CEDU (discriminazione)",
    "cedu_protocollo_13": "Prot. n. 13 CEDU (pena di morte)",
    "cedu_protocollo_16": "Prot. n. 16 CEDU (pareri consultivi)",
    "legge_notarile": "L. 89/1913 (notariato)",
    "legge_52_1985": "L. 52/1985",
    "condono_edilizio": "L. 47/1985",
    "immobili_da_costruire": "D.Lgs 122/2005",
    "locazioni_abitative": "L. 431/1998",
    "locazioni_immobili_urbani": "L. 392/1978",
    "mediazione_civile": "D.Lgs 28/2010",
    "riti_civili_semplificati": "D.Lgs 150/2011",
    "ordinamento_forense": "L. 247/2012 (forense)",
    "licenziamenti_individuali": "L. 604/1966",
    "tutele_crescenti": "D.Lgs 23/2015",
    "responsabilita_sanitaria": "L. 24/2017 (Gelli)",
    "regolamento_immigrazione": "DPR 394/1999",
    "tuel": "TUEL (D.Lgs 267/2000)",
    "processo_penale_minorile": "DPR 448/1988",
    "codice_nautica_diporto": "Cod. nautica (D.Lgs 171/2005)",
    "codice_doganale_ue": "CDU (Reg. UE 952/2013)",
    "reg_ue_2015_2446": "Reg. del. (UE) 2015/2446",
    "reg_ue_2015_2447": "Reg. es. (UE) 2015/2447",
    "gdpr": "GDPR (Reg. UE 2016/679)",
    "bruxelles_i_bis": "Reg. UE 1215/2012",
    "roma_i": "Reg. CE 593/2008 (Roma I)",
    "roma_ii": "Reg. CE 864/2007 (Roma II)",
    "bruxelles_ii_ter": "Reg. UE 2019/1111",
    "successioni_ue": "Reg. UE 650/2012",
    "codice_civile": "c.c.",
    "codice_penale": "c.p.",
    "codice_procedura_civile": "c.p.c.",
    "codice_procedura_penale": "c.p.p.",
    "costituzione": "Cost.",
    "disp_att_cc": "disp. att. c.c.",
    "disp_att_cpp": "disp. att. c.p.p.",
    "codice_strada": "C.d.S.",
    "regolamento_strada": "Reg. C.d.S.",
    "codice_consumo": "Cod. Consumo",
    "codice_crisi_impresa": "CCII",
    "ordinamento_polizia": "L. 121/1981",
    "tulps": "TULPS",
    "statuto_lavoratori": "Stat. Lav.",
    "sicurezza_lavoro": "TU Sicurezza",
    "tu_bancario": "TUB",
    "tu_finanza": "TUF",
    "codice_proprieta_industriale": "C.P.I.",
    "codice_terzo_settore": "CTS",
    "codice_assicurazioni": "Cod. Ass.",
    "responsabilita_enti": "D.Lgs 231/2001",
    "procedimento_amministrativo": "L. 241/1990",
    "codice_processo_amministrativo": "c.p.a.",
    "codice_amministrazione_digitale": "CAD",
    "tu_documentazione_amministrativa": "DPR 445/2000",
    "codice_contratti_pubblici": "Cod. Contratti",
    "sanzioni_amministrative": "L. 689/1981",
    "tu_spese_giustizia": "TU Spese Giust.",
    "codice_privacy": "Cod. Privacy",
    "codice_ambiente": "TUA",
    "tu_edilizia": "TU Edilizia",
    "tu_immigrazione": "TU Immigrazione",
    "codice_antimafia": "Cod. Antimafia",
    "tuir": "TUIR",
    "codice_beni_culturali": "Cod. Beni Cult.",
    "codice_navigazione": "Cod. Nav.",
    "stupefacenti": "DPR 309/1990",
    "ordinamento_penitenziario": "Ord. Pen.",
    "codice_pari_opportunita": "Cod. Pari Opp.",
    "codice_protezione_civile": "Cod. Prot. Civ.",
    "divorzio": "L. 898/1970",
    "adozione": "L. 184/1983",
    "equa_riparazione": "Legge Pinto",
}


# ── Citation regex ─────────────────────────────────────────────────────────
# Matches "neni|nenin|nenit|nenet  N(/sub)?  [optional code-tail]".
# The article number admits common Albanian forms:
#   simple:    132
#   slash:     132/a, 132/1, 132-a
#   sub-list:  132 paragrafi 2 (we just capture 132 here; the model usually
#              writes the paragraph spelled out which we ignore for matching)
#
# We deliberately keep the tail-capture small (≤ 60 chars) so we don't drag
# the next sentence in as if it were the code. The tail is then probed for
# a known code alias.

# One article-number token: "132", "132/a", "132/1", "132-a", "4/1/2".
_NUM_TOKEN = r"\d+(?:[/\-\u2013][a-zA-Z\u00e7\u00eb\u00c7\u00cb0-9]{1,4})*"
# Enumerated-list separators: "nenet 134, 135 dhe 136 të Kodit Penal".
_LIST_SEP = r"(?:\s*(?:,|;|\bdhe\b|\be\b)\s*)"

# 17 set 2026 — SOTTO-RIFERIMENTI INTERPOSTI fra il numero e il codice. La coda non attraversa mai
# le virgole (giusto: altrimenti una citazione ruba il codice della frase dopo), ma così la forma
# PIÙ USATA dai giuristi e dal cervello — «neni 155, pika 1, i Kodit të Punës», «Neni 34, pika 1,
# shkronja "d", e Ligjit nr. 79/2021» — usciva «pa kod» con il codice scritto lì accanto (prova
# viva v9.345: 21 «pa kod» su 30; 140 occorrenze nelle ultime 121 risposte salvate). Regola: si può
# attraversare UNA virgola solo dopo «pika/shkronja/paragrafi …» e solo se subito dopo viene la
# formula di attribuzione «i/e/të/së Kodit|Ligjit|Kushtetutës…» (o l'anafora «i po këtij ligji»);
# «neni 155, pika 1, ndërsa Kodi Civil…» NON attraversa (la coda resta vuota → «pa kod», come prima).
# valori: cifre dopo «pika/paragrafi/fjalia», lettere SOLO dopo «shkronja/germa» («"d"», «dh)», «c»);
# una lettera nuda mai seguita da un punto («, L.», «, c.c.» sono codici, non lettere) né una particella
_SUB_NUM = r"\d{1,3}(?![\w/])\)?"
_SUB_LET = (r"(?:[\"“«'][a-zçë]{1,2}[\"”»']|[a-zçë]{1,2}\)|"
            r"(?!(?:e|i|t[ëe]|s[ëe]|me|n[ëe]|se|ose|dhe|po|si|sa)(?![\wçë]))[a-zçë]{1,2}(?![\wçë/.]))")
_SUB_AL = (r"(?:\s*,?\s*(?:(?:pik[aë]t?|paragraf\w{0,3}|fjali[aë]?|n[ëe]npik[aë]t?)\s+" + _SUB_NUM +
           r"|(?:shkronj[aë]t?|g[ëe]rm[aë]t?)\s+" + _SUB_LET + r")"
           r"(?:\s*(?:,|\bdhe\b|\be\b)\s*(?:" + _SUB_NUM + r"|" + _SUB_LET + r"))*)")
_CONN_AL = (r"(?:i|e|t[ëe]|s[ëe]|sipas)\s+(?:po\s+)?(?:k[ëe]tij\s+(?:ligji|kodi)\b|"
            r"kodit\b|ligjit\b|kushtetut[ëe]s\b|vkm\b|rregullores\b|dekretit\b|k\.\s?p|kp\b|kc\b|kpc\b|kpp\b|krr\b|kf\b)")

CITATION_RE = re.compile(
    r"\bnen(?:i|in|it|et|eve|ve)?\b\s+"
    r"(?P<nums>" + _NUM_TOKEN + r"(?:" + _LIST_SEP + _NUM_TOKEN + r")*)"
    r"(?P<sub>" + _SUB_AL + r"*)"
    r"(?:\s*,(?=\s+" + _CONN_AL + r"))?"      # la virgola sì, lo spazio resta alla coda
    # Tail = up to 8 words, but never crossing "dhe" or another "nen..." —
    # otherwise one citation swallows the next and steals its code.
    r"(?P<tail>(?:\s+(?!nen(?:i|in|it|et|eve|ve)?\b)(?!dhe\b)[^\s,;:\n()]+){0,8})",
    re.IGNORECASE,
)
# Anafora: «neni 37, pika 1, i po këtij ligji» / «art. 4 del medesimo decreto» → il codice/legge
# nominato per ULTIMO nel testo prima della citazione (finestra corta), mai un'ipotesi.
_ANAFORA_AL = re.compile(r"^\s*(?:i|e|t[ëe]|s[ëe])\s+(?:po\s+)?k[ëe]tij\s+(?:ligji|kodi)\b", re.I)
_ANAFORA_IT = re.compile(r"^\s*(?:del|della|dello|dell[’'])\s*(?:medesim[oa]|stess[oa]|citat[oa]|predett[oa]|suddett[oa])\s+"
                         r"(?:decreto|legge|codice|regolamento|d\.?\s?lgs\.?|testo\s+unico|d\.?p\.?r\.?)", re.I)
_ANAFORA_WINDOW = 1500
# Pull each individual number out of a (possibly enumerated) nums block.
_NUM_RE = re.compile(_NUM_TOKEN)

# Detect a code alias inside the tail. We use word boundaries so "kpc" inside
# "skpcial" wouldn't match (no risk in practice but cheap insurance).
# The alias keys are sorted longest-first so multi-word forms win over short
# abbreviations when both appear in the same tail.
_ALIAS_PATTERNS = sorted(CODE_ALIASES.keys(), key=len, reverse=True)
_ALIAS_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ALIAS_PATTERNS) + r")\b",
    re.IGNORECASE,
)

# 16 set 2026 — «KP» è AMBIGUA: Kodi Penal per l'alias, ma i giuristi (e il cervello) la usano
# anche per il Kodi i PUNËS. Prova viva: «neni 155/1 KP» (zgjidhja e pajustifikuar, Kodi i Punës)
# usciva VERIFICATO sul Kodi Penal 155 «Shkatërrimi i rrugëve» — verde e sbagliato, la classe
# peggiore. La sigla nuda si scioglie dal DOCUMENTO: quale dei due codici è nominato per esteso
# nel testo; poi il contesto del retrieval; poi in quale dei due esiste il numero; se resta
# ambigua → «kod i pa-specifikuar» con i due candidati (onesto), mai un verde a caso.
_KP_BARE_RE = re.compile(r"(?<![\wë])k\.?\s?p\.?(?![\wë])", re.I)
_KP_PUNES_RE = re.compile(r"kod\w*\s+(?:i\s+|e\s+|t[ëe]\s+)?pun[ëe]s", re.I)
_KP_PENAL_RE = re.compile(r"kod\w*\s+(?:i\s+|e\s+|t[ëe]\s+)?penal", re.I)


def _kp_bare(tail: str, code: str | None) -> bool:
    """La citazione porta SOLO la sigla nuda «KP»/«K.P.» (nessun nome per esteso)."""
    return (code in (None, "kodi_penal") and bool(_KP_BARE_RE.search(tail or ""))
            and not re.search(r"penal|pun[ëe]s", tail or "", re.I))


def _kp_resolve(number: str, text: str, retrieved_codes: set, lookup: dict) -> str | None:
    n_punes, n_penal = len(_KP_PUNES_RE.findall(text)), len(_KP_PENAL_RE.findall(text))
    if n_punes and not n_penal:
        return "kodi_punes"
    if n_penal and not n_punes:
        return "kodi_penal"
    ctx = [c for c in ("kodi_punes", "kodi_penal") if c in retrieved_codes]
    if len(ctx) == 1:
        return ctx[0]
    has = [c for c in ("kodi_punes", "kodi_penal") if _verify_number(lookup, c, number) is not None]
    if len(has) == 1:
        return has[0]
    return None


# ── Italian citations (art. N c.c./c.p./c.p.c./c.p.p./Cost.) ─────────────────
# 16 set 2026 (benchmark lab): dopo la riforma Cartabia il c.p.c. arriva a «281-terdecies» — i suffissi
# oltre «decies» spezzavano il numero («281» + coda «-terdecies») e la citazione restava senza codice
_NUM_TOKEN_IT = (r"\d+(?:[\-\s](?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies|undecies|duodecies|"
                 r"terdecies|quaterdecies|quinquiesdecies|sexiesdecies|septiesdecies|octiesdecies|noviesdecies|vicies)"
                 r"(?![a-z]))?")
# 17 set 2026 — «art. 18, comma 4, L. 300/1970» è LA forma canonica italiana e usciva «senza codice»
# (117 occorrenze nelle ultime 121 risposte): stessa regola dell'albanese — dopo «comma/commi/lett./
# n./punto …» si attraversa UNA virgola solo se segue una legge/codice («L.», «D.Lgs.», «c.c.», «del
# codice», «della legge», «Cost.»…) o l'anafora «del medesimo decreto». «art. 18, comma 4, di
# conseguenza il codice civile…» NON attraversa. ⚠️ «c.» come abbreviazione di comma NON è ammessa fra
# i sotto-riferimenti: «art. 2, c.c.» diventerebbe «comma c».
_SUB_NUM_IT = r"\d{1,3}(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?(?![\w/])\)?"
_SUB_LET_IT = (r"(?:[\"“«'][a-z]{1,2}[\"”»']|[a-z]{1,2}\)|"
               r"(?!(?:e|ed|o|al|il|la|lo|le|di|in|su|se|no|un|ai|da|ne|si)(?![a-z]))[a-z]{1,2}(?![a-z/.]))")
_SUB_IT = (r"(?:\s*,?\s*(?:(?:comm[ai]|co\.|n\.|nn\.|punt[oi]|par(?:agraf[oi])?\.?|§)\s*" + _SUB_NUM_IT +
           r"|lett(?:era|ere)?\.?\s*" + _SUB_LET_IT + r")"
           r"(?:\s*(?:,|\be\b|\bed\b)\s*(?:" + _SUB_NUM_IT + r"|" + _SUB_LET_IT + r"))*)")
_CONN_IT = (r"(?:(?:del|della|dello|dell[’']|dal|dalla)\s*(?:codice|cod\.|legge|l\.|d\.?\s?lgs|d\.?\s?l\b|d\.?\s?l\.|d\.?p\.?r|r\.?d\.?|"
            r"t\.?u\.?|reg\b|reg\.|regolamento|direttiva|dir\.|statuto|costituzione|cost\.|convenzione|protocollo|trattato|carta|"
            r"cedu|tfue|tue|gdpr|cdu|dnc|tuel|tuir|tub|tuf|cad|cpa|cpi|ccii|c\.[a-z]|medesim|stess|citat|predett|suddett)|"
            r"l\.\s?\d|legge\b|d\.?\s?lgs|d\.?\s?l\.\s?\d|d\.?p\.?r\.?\s?\d|r\.?d\.?\s?\d|d\.?m\.?\s?\d|t\.?u\.?\b|reg\.?\s?(?:\(|\d|ue|ce)|"
            r"regolamento|direttiva|dir\.|cod\.|codice|c\.[a-z]|cost\.?\b|statuto|carta|cedu|tfue|tue|gdpr|cdu|dnc|tuel|tuir|tub|tuf|cad|"
            r"cpa|cpi|ccii|c\.d\.s\.|cds\b|l\.\s?fall|preleggi|disp\.|convenzione|protocollo|trattato)")

CITATION_RE_IT = re.compile(
    r"\bart(?:t|icol[oi])?\.?\s+"
    r"(?P<nums>" + _NUM_TOKEN_IT + r"(?:\s*(?:,|;|\be\b|\bed\b)\s*" + _NUM_TOKEN_IT + r")*)"
    r"(?P<sub>" + _SUB_IT + r"*)"
    r"(?:\s*,(?=\s+" + _CONN_IT + r"))?"      # la virgola sì, lo spazio resta alla coda
    # 16 set 2026 (benchmark lab): «art. 215 Reg. (UE) 2015/2446» — il token «(UE)» spezzava la
    # coda e la citazione restava «senza codice»; i soli parentetici ammessi sono le sigle UE/CE/CEE
    # v9.348: «art. 13-ter (allegato) Codice del processo amministrativo» — l'etichetta di gruppo
    # che il prompt mostra per gli articoli degli allegati non deve spezzare la coda
    r"(?P<tail>(?:\s+(?!art\b)(?:\((?:UE|CE|CEE|Euratom|allegato|atto di approvazione)\)|[^\s,;:\n()]+)){0,6})",
    re.IGNORECASE,
)
_NUM_RE_IT = re.compile(_NUM_TOKEN_IT)
# Ordered longest/most-specific first so cpc/cpp beat cp, codice* beats abbrevs.
_IT_CODE_CHECKS = [
    # ── full names first (most specific wins) ──
    # D.Lgs 231/2007 antiriciclaggio — «2312007» distingue dal 231/2001 (enti)
    ("2312007", "antiriciclaggio"),
    ("decretoantiriciclaggio", "antiriciclaggio"),
    ("antiriciclaggio", "antiriciclaggio"),
    # ── wave7 «blocco A» (16 set 2026): nomi per esteso (prima di «romaii»: «romaiii» lo contiene) ──
    ("romaiii", "roma_iii"),
    ("trattatosulfunzionamento", "tfue"), ("tfue", "tfue"),
    ("trattatosullunioneeuropea", "tue"),
    ("cartadeidirittifondamentali", "carta_diritti_ue"), ("cdfue", "carta_diritti_ue"),
    ("codicefrontiereschengen", "codice_frontiere_schengen"),
    ("codicedeivisti", "codice_visti"),
    ("dirittointernazionaleprivato", "diritto_internazionale_privato"),
    ("leggesullacittadinanza", "cittadinanza"), ("leggecittadinanza", "cittadinanza"),
    ("negoziazioneassistita", "negoziazione_assistita"),
    ("mandatodarrestoeuropeo", "mandato_arresto_europeo"),
    ("casellariogiudiziale", "casellario"),
    ("unionicivili", "unioni_civili"),
    ("regolamentonotarile", "regolamento_notarile"),
    ("leggeurbanistica", "legge_urbanistica"),
    ("testounicopubblicoimpiego", "pubblico_impiego"),
    ("testounicomaternita", "maternita_paternita"),
    # audit 16 set: abbreviazioni e «disposizioni di attuazione» PRIMA delle sigle corte
    ("codciv", "codice_civile"), ("codpen", "codice_penale"), ("codprocciv", "codice_procedura_civile"),
    ("codprocpen", "codice_procedura_penale"),
    ("disposizionidiattuazionedelcodicecivile", "disp_att_cc"), ("disposizionidiattuazionedelcodiceciv", "disp_att_cc"),
    ("dispattcc", "disp_att_cc"), ("disposizionidiattuazionecc", "disp_att_cc"), ("dispattcodciv", "disp_att_cc"),
    ("normediattuazionedelcodicediprocedurapenale", "disp_att_cpp"), ("disposizionidiattuazionedelcodicediprocedurapenale", "disp_att_cpp"),
    ("dispattcpp", "disp_att_cpp"), ("normeattcpp", "disp_att_cpp"), ("normediattuazionecpp", "disp_att_cpp"),
    ("regolamentodiesecuzionedelcodicedellastrada", "regolamento_strada"), ("regolamentodiesecuzionecds", "regolamento_strada"),
    ("regesecuzionecds", "regolamento_strada"), ("regolamentocds", "regolamento_strada"), ("regolamentodelcodicedellastrada", "regolamento_strada"),
    # audit 16 set (per titolo): codici citati col nome, senza numero/anno
    ("codiceinmateriadiprotezionedeidatipersonali", "codice_privacy"), ("protezionedeidatipersonali", "codice_privacy"),
    ("codicedellaprivacy", "codice_privacy"), ("codiceprivacy", "codice_privacy"),
    ("codicedellepariopportunit", "codice_pari_opportunita"), ("pariopportunit", "codice_pari_opportunita"),
    ("testounicodelledilizia", "tu_edilizia"), ("testounicoedilizia", "tu_edilizia"), ("tuedilizia", "tu_edilizia"),
    ("testounicoinmateriaedilizia", "tu_edilizia"),
    ("leggesuldivorzio", "divorzio"), ("leggedivorzio", "divorzio"), ("leggesulladozione", "adozione"), ("leggeadozione", "adozione"),
    ("dirittodelminoreaunafamiglia", "adozione"),
    ("testounicosicurezzasullavoro", "sicurezza_lavoro"), ("testounicosicurezzalavoro", "sicurezza_lavoro"),
    ("testounicostupefacenti", "stupefacenti"), ("codicedellamministrazionedigitale", "codice_amministrazione_digitale"),
    ("codicedellambiente", "codice_ambiente"), ("codiceambiente", "codice_ambiente"),
    # preleggi (disposizioni sulla legge in generale): «art. 12 preleggi», «disp. prel. c.c.»
    ("preleggi", "preleggi"), ("disposizionisullaleggeingenerale", "preleggi"),
    ("disposizionipreliminari", "preleggi"), ("dispprel", "preleggi"),
    # wave8: trattati — MAI la sigla nuda «cedu» (sta dentro «procedura»)
    ("convenzioneitaliaalbania", "convenzione_it_al_fisco"), ("convenzionetraitaliaealbania", "convenzione_it_al_fisco"),
    ("protocolloitaliaalbania", "protocollo_it_al_migranti"),
    ("convenzioneeuropeadeidirittidelluomo", "cedu"), ("convenzioneeuropeaperlasalvaguardia", "cedu"),
    # ── wave5 + EUR-Lex (16 set 2026): nomi per esteso / sigle ──
    ("disposizioninazionalicomplementari", "codice_doganale_nazionale"),
    ("codicedoganalenazionale", "codice_doganale_nazionale"),
    ("codicedoganaledellunione", "codice_doganale_ue"),
    ("statutodeidirittidelcontribuente", "statuto_contribuente"),
    ("statutodelcontribuente", "statuto_contribuente"),
    ("testounicodellegiustiziatributaria", "giustizia_tributaria"),
    ("testounicoentilocali", "tuel"),
    ("testounicoaccise", "accise"),
    ("testounicodelleaccise", "accise"),
    ("leggenotarile", "legge_notarile"),
    ("ordinamentodelnotariato", "legge_notarile"),
    ("ordinamentoforense", "ordinamento_forense"),
    ("bruxellesiiter", "bruxelles_ii_ter"),
    ("bruxellesibis", "bruxelles_i_bis"),
    ("romaii", "roma_ii"),
    ("romai", "roma_i"),
    ("gdpr", "gdpr"),
    ("tuel", "tuel"),
    ("cdu", "codice_doganale_ue"),
    ("dnc", "codice_doganale_nazionale"),
    ("ordinamentodellamministrazionedellapubblicasicurezza", "ordinamento_polizia"),
    ("testounicodocumentazioneamministrativa", "tu_documentazione_amministrativa"),
    ("testounicodelleleggidipubblicasicurezza", "tulps"),
    ("testounicodelleimpostesuiredditi", "tuir"),
    ("codicedellamministrazionedigitale", "codice_amministrazione_digitale"),
    ("codicedelprocessoamministrativo", "codice_processo_amministrativo"),
    ("codicedellaproprietaindustriale", "codice_proprieta_industriale"),
    ("codicedelleassicurazioniprivate", "codice_assicurazioni"),
    ("testounicospesedigiustizia", "tu_spese_giustizia"),
    ("codicedellaprotezionecivile", "codice_protezione_civile"),
    ("codicedellepariopportunita", "codice_pari_opportunita"),
    ("codicedeicontrattipubblici", "codice_contratti_pubblici"),
    ("codicedelleassicurazioni", "codice_assicurazioni"),
    ("codicedellacrisidimpresa", "codice_crisi_impresa"),
    ("codicedidiprocedurapenale", "codice_procedura_penale"),
    ("codicediprocedurapenale", "codice_procedura_penale"),
    ("codicediproceduracivile", "codice_procedura_civile"),
    ("ordinamentopenitenziario", "ordinamento_penitenziario"),
    ("codicedeibeniculturali", "codice_beni_culturali"),
    ("testounicosullimmigrazione", "tu_immigrazione"),
    ("regolamentodiesecuzione", "regolamento_strada"),
    ("codicedellanavigazione", "codice_navigazione"),
    ("testounicodellafinanza", "tu_finanza"),
    ("testounicostupefacenti", "stupefacenti"),
    ("testounicoimmigrazione", "tu_immigrazione"),
    ("codicedelterzosettore", "codice_terzo_settore"),
    ("statutodeilavoratori", "statuto_lavoratori"),
    ("testounicosicurezza", "sicurezza_lavoro"),
    ("testounicobancario", "tu_bancario"),
    ("testounicoedilizia", "tu_edilizia"),
    ("codicedellambiente", "codice_ambiente"),
    ("codicedellastrada", "codice_strada"),
    ("codiceantimafia", "codice_antimafia"),
    ("codicedelconsumo", "codice_consumo"),
    ("codiceambiente", "codice_ambiente"),
    ("codiceprivacy", "codice_privacy"),
    ("codicecivile", "codice_civile"),
    ("codicepenale", "codice_penale"),
    ("costituzione", "costituzione"),
    ("leggepinto", "equa_riparazione"),
    # ── abbreviations, longest first ──
    ("tulps", "tulps"),
    ("ccii", "codice_crisi_impresa"),
    ("tuir", "tuir"),
    ("cds", "codice_strada"),
    ("cpp", "codice_procedura_penale"),
    ("cpc", "codice_procedura_civile"),
    ("cpa", "codice_processo_amministrativo"),
    ("cpi", "codice_proprieta_industriale"),
    ("tub", "tu_bancario"),
    ("tuf", "tu_finanza"),
    ("cts", "codice_terzo_settore"),
    ("cp", "codice_penale"),
    ("cc", "codice_civile"),
    ("cost", "costituzione"),
]


# Riferimenti PER NUMERO («D.Lgs. 141/2024», «Reg. (UE) 2015/2446», «DPR 633/1972»):
# il passaggio alfabetico sopra scarta le cifre, quindi «dlgs» da solo non dice nulla.
# Qui si confronta il numero+anno compattato (v9.326). Ordine: il piu' lungo prima.
_IT_CODE_NUM_CHECKS = [
    ("20152446", "reg_ue_2015_2446"), ("20152447", "reg_ue_2015_2447"), ("20191111", "bruxelles_ii_ter"),
    # wave6: testi unici della riforma fiscale (prima dei vecchi atti che hanno abrogato)
    ("1732024", "tu_sanzioni_tributarie"), ("1232025", "tu_registro"), ("1412026", "tu_accertamento"),
    ("332025", "tu_riscossione"), ("102026", "tu_iva"),
    # wave7 «blocco A»: prima le chiavi lunghe (sottostringhe: «2742000» contiene «742000»)
    ("13261914", "regolamento_notarile"), ("11501942", "legge_urbanistica"), ("20161103", "regimi_patrimoniali_ue"),
    ("20181806", "reg_ue_2018_1806"), ("20201784", "notifiche_ue"), ("18962006", "ingiunzione_europea"),
    ("12592010", "roma_iii"), ("2016399", "codice_frontiere_schengen"), ("8102009", "codice_visti"),
    ("8612007", "small_claims_ue"), ("2181995", "diritto_internazionale_privato"), ("5721993", "regolamento_cittadinanza"),
    ("1512001", "maternita_paternita"), ("2762003", "legge_biagi"), ("1652001", "pubblico_impiego"),
    ("1322014", "negoziazione_assistita"), ("2742000", "giudice_pace_penale"), ("3132002", "casellario"),
    ("2192017", "consenso_informato_dat"), ("1922005", "prestazione_energetica"), ("1101975", "armi"),
    ("2302000", "regolamento_penitenziario"), ("911992", "cittadinanza"), ("302007", "cittadini_ue"),
    ("252008", "protezione_internazionale"), ("812015", "contratti_lavoro"), ("662003", "orario_lavoro"),
    ("692005", "mandato_arresto_europeo"), ("762016", "unioni_civili"),
    # wave8: trattati ratificati con legge
    ("1751998", "convenzione_it_al_fisco"), ("8481955", "cedu"), ("142024", "protocollo_it_al_migranti"),
    # audit 16 set: atti di base che non si risolvevano per numero/anno
    ("8981970", "divorzio"), ("1841983", "adozione"), ("1982006", "codice_pari_opportunita"),
    ("3541975", "ordinamento_penitenziario"), ("1211981", "ordinamento_polizia"), ("3091990", "stupefacenti"),
    ("1152002", "tu_spese_giustizia"), ("4452000", "tu_documentazione_amministrativa"), ("422004", "codice_beni_culturali"),
    ("362023", "codice_contratti_pubblici"), ("3271942", "codice_navigazione"), ("822005", "codice_amministrazione_digitale"),
    ("12152012", "bruxelles_i_bis"), ("2016679", "gdpr"), ("9522013", "codice_doganale_ue"),
    ("5932008", "roma_i"), ("8642007", "roma_ii"), ("6502012", "successioni_ue"),
    ("1412024", "codice_doganale_nazionale"), ("5041995", "accise"), ("6331972", "iva"),
    ("1311986", "imposta_registro"), ("3461990", "imposta_successioni"), ("4721997", "sanzioni_tributarie"),
    ("1752024", "giustizia_tributaria"), ("2122000", "statuto_contribuente"), ("6001973", "accertamento_imposte"),
    ("6021973", "riscossione"), ("742000", "reati_tributari"), ("891913", "legge_notarile"),
    ("521985", "legge_52_1985"), ("471985", "condono_edilizio"), ("1222005", "immobili_da_costruire"),
    ("4311998", "locazioni_abitative"), ("3921978", "locazioni_immobili_urbani"), ("282010", "mediazione_civile"),
    ("1502011", "riti_civili_semplificati"), ("2472012", "ordinamento_forense"), ("6041966", "licenziamenti_individuali"),
    ("232015", "tutele_crescenti"), ("242017", "responsabilita_sanitaria"), ("3941999", "regolamento_immigrazione"),
    ("2672000", "tuel"), ("4481988", "processo_penale_minorile"), ("1712005", "codice_nautica_diporto"),
    ("2312007", "antiriciclaggio"), ("2312001", "responsabilita_enti"), ("2852001", "codice_strada"),
    ("3802001", "tu_edilizia"), ("2861998", "tu_immigrazione"), ("1962003", "codice_privacy"),
    ("1522006", "codice_ambiente"), ("2062005", "codice_consumo"), ("2092005", "codice_assicurazioni"),
    ("812008", "sicurezza_lavoro"), ("3001970", "statuto_lavoratori"), ("2411990", "procedimento_amministrativo"),
    ("6891981", "sanzioni_amministrative"), ("1592011", "codice_antimafia"), ("142019", "codice_crisi_impresa"),
    # ultimo perche' corto: «Reg. (CE) n. 4/2009» — dopo tutte le chiavi lunghe
    ("42009", "alimenti_ue"),
]


_CEDU_PROT = ("1", "4", "6", "7", "12", "13", "16")
# chiavi corte che devono restare sottostringhe («Roma I» → «romai» non è mai una parola)
_SHORT_AS_SUBSTRING = frozenset({"romai"})


def _resolve_code_it(tail: str):
    compact = re.sub(r"[^a-z]", "", (tail or "").lower())
    # CEDU: MAI come sottostringa compattata («procedura» contiene «cedu») — parola intera
    # nel testo grezzo; «Prot. 1 / Protocollo n. 7 / P7 CEDU» → il protocollo, altrimenti
    # la Convenzione (art. 1-59).
    _low = (tail or "").lower()
    if re.search(r"(?<![a-z])c\.?e\.?d\.?u\.?(?![a-z])", _low) or (
            "convenzione europea" in _low and "diritti dell" in _low):
        m = re.search(r"(?:prot(?:ocollo)?\.?\s*(?:addizionale\s*)?(?:n\.?\s*)?|(?<![a-z])p\s*)(\d{1,2})(?![\d/])", _low)
        if m and m.group(1) in _CEDU_PROT:
            return f"cedu_protocollo_{m.group(1)}"
        if "addizionale" in _low:
            return "cedu_protocollo_1"
        return "cedu"
    # Sigle corte («cc», «cp», «cpc», «tub», «cost»…) SOLO come parola intera: nel testo
    # compattato «accise», «successioni», «accertamento» contengono «cc» e finivano nel
    # codice civile (audit_corpus, 16 set 2026). Le abbreviazioni puntate si ricompongono
    # prima («c.p.c.» → «cpc», «Cost.» → «cost»); le chiavi lunghe restano sottostringhe.
    _norm = re.sub(r"\b([a-z])\.\s*(?=[a-z]\.)", r"\1", _low)
    _norm = re.sub(r"\b([a-z]{1,5})\.", r"\1", _norm)
    _tokens = set(re.findall(r"[a-z]+", _norm))
    for pat, code in _IT_CODE_CHECKS:
        if len(pat) <= 5 and pat not in _SHORT_AS_SUBSTRING:
            if pat in _tokens:
                return code
        elif pat in compact:
            return code
    # secondo passaggio: numero/anno (le sigle «D.Lgs.», «DPR», «Reg.» da sole non bastano);
    # «legge n. 91 del 1992» vale come «91/1992» (17 set 2026)
    with_digits = re.sub(r"[^a-z0-9]", "", re.sub(r"(\d+)\s+del\s+(\d{4})", r"\1/\2", (tail or "").lower()))
    if any(ch.isdigit() for ch in with_digits):
        for pat, code in _IT_CODE_NUM_CHECKS:
            if pat in with_digits:
                return code
    return None


@dataclass
class Citation:
    raw: str                 # the matched substring, e.g. "neni 132 KP"
    number: str              # "132" or "132/a"
    code: str | None         # canonical key, e.g. "kodi_penal", or None
    code_label: str | None   # human label for the badge, or None
    status: str              # "verified" | "fake" | "needs_code"
    candidates: list[dict]   # for needs_code: which codes contain this number
    article_heading: str | None = None  # populated when verified
    volatility: str | None = None            # STABLE/MEDIUM — freshness hint
    last_amendment_date: str | None = None   # last known amendment date
    resolved_by: str | None = None           # None (codice scritto) | retrieval | documento | anafora


def _normalise_number(n: str) -> str:
    """Normalise '132/A' / '132-a' / '132 / a' → '132/a' (lowercase)."""
    s = n.strip().lower().replace(" ", "")
    s = s.replace("-", "/").replace("\u2013", "/")
    return s


def _build_lookup(index: ArticleIndex) -> dict[tuple[str, str], object]:
    """(code, normalised_number) → Article. Cached on the index instance."""
    cached = getattr(index, "_citation_lookup", None)
    if cached is not None:
        return cached
    table: dict[tuple[str, str], object] = {}
    for art in index.articles:
        if art.repealed:
            continue
        table[(art.code, _normalise_number(art.number))] = art
    index._citation_lookup = table
    return table


def _build_lookup_all(index: ArticleIndex) -> dict[tuple[str, str], object]:
    """(code, number) -> Article, INCLUDING repealed ones. Lets us tell a real
    but repealed article apart from a genuinely nonexistent (hallucinated) one."""
    cached = getattr(index, "_citation_lookup_all", None)
    if cached is not None:
        return cached
    table: dict[tuple[str, str], object] = {}
    for art in index.articles:
        table[(art.code, _normalise_number(art.number))] = art
    index._citation_lookup_all = table
    return table


def _build_number_to_codes(index: ArticleIndex) -> dict[str, list[str]]:
    """normalised_number → [codes that have an article with that number]."""
    cached = getattr(index, "_citation_num_index", None)
    if cached is not None:
        return cached
    table: dict[str, list[str]] = defaultdict(list)
    for art in index.articles:
        if art.repealed:
            continue
        table[_normalise_number(art.number)].append(art.code)
    # de-dup while preserving order
    table = {k: list(dict.fromkeys(v)) for k, v in table.items()}
    index._citation_num_index = table
    return table


def _resolve_code(tail: str) -> str | None:
    """Extract a canonical code key from the text right after the article num."""
    if not tail:
        return None
    # Fold whitespace (newlines, double spaces) so multi-word code aliases
    # like "kodit të procedurës penale" still match when the source wraps
    # mid-phrase ("të Kodit të\nProcedurës Penale").
    flat = re.sub(r"\s+", " ", tail.lower())
    m = _ALIAS_RE.search(flat)
    if m:
        return CODE_ALIASES.get(m.group(1).lower())
    # No named code — try a special law cited by number ("ligji nr. 9901").
    lm = _LAW_NUM_RE.search(flat)
    if lm:
        num, year = lm.group(1), (lm.group(2) or lm.group(3))
        if year and f"{num}/{year}" in _LAW_NUMBER_ALIASES:
            return _LAW_NUMBER_ALIASES[f"{num}/{year}"]
        return _LAW_NUMBER_ALIASES.get(num)
    return None


# 17 set 2026 (v9.348) — NUMERI DI GRUPPO del corpus IT (v9.327): «13-ter-all3» = art. 13-ter di un
# ALLEGATO (nel lookup, normalizzato: «13/ter/all3»), «1-legge» = art. 1 dell'atto di approvazione.
# Un giurista cita «art. 13-ter c.p.a.» (le norme di attuazione sono l'allegato 2): il lookup esatto
# manca e la citazione usciva «inesistente». Se il numero NON esiste nel testo principale ma esiste
# in UN solo allegato di quel codice, è quello — il testo principale vince sempre quando c'è.
_GRUPPO_KEY_RE = re.compile(r"^(.*?)/(all\d+|legge)$")
_GRUPPO_CACHE: dict = {}


def _annex_maps(lookup: dict) -> tuple[dict, dict]:
    """((code, base) → [Article], base → {code}) per i soli numeri con suffisso «/allK»; cache per lookup."""
    key = (id(lookup), len(lookup))
    m = _GRUPPO_CACHE.get(key)
    if m is None:
        per_code, per_base = {}, {}
        for (code, num), art in lookup.items():
            g = _GRUPPO_KEY_RE.match(num)
            if g and g.group(2).startswith("all"):
                per_code.setdefault((code, g.group(1)), []).append(art)
                per_base.setdefault(g.group(1), set()).add(code)
        m = (per_code, per_base)
        if len(_GRUPPO_CACHE) > 8:
            _GRUPPO_CACHE.clear()
        _GRUPPO_CACHE[key] = m
    return m


def _verify_number(lookup: dict, code: str, number: str):
    """Resolve an article, tolerant of paragraph/range notation.

    Albanian citations write paragraphs as "134/1" (paragraph 1 of art. 134)
    and ranges as "379-390". Neither is a distinct article number, so an exact
    lookup misses and a valid citation would be flagged "fake". We fall back to
    the base article and, for ranges, the range endpoints — a conservative
    move that kills false-fakes without inventing anything.
    """
    art = lookup.get((code, number))
    if art is not None:
        return art
    hits = _annex_maps(lookup)[0].get((code, number))
    if hits and len(hits) == 1:
        return hits[0]           # esiste solo in un allegato di questo codice (v9.348)
    if "/" in number:
        parts = number.split("/")
        base, first = parts[0], parts[1]
        # Only a NUMERIC first suffix is a paragraph/range of the base article
        # ("134/1" -> 134, "379/390" -> 379, "4/1/2" -> 4). A LETTER suffix
        # ("134/a") is a DISTINCT inserted article — never collapse it to the
        # base. And never resolve the suffix itself as a standalone article:
        # that green-lit hallucinations like "480/5" -> real art. 5.
        if first.isdigit():
            art = lookup.get((code, base))
            if art is not None:
                return art
        else:
            # Suffisso-LETTERA. Due casi che si scrivono uguale:
            #
            #   «149/a» → articolo inserito a se' (Shkelja e te drejtave te
            #             pronesise industriale). Sta nel lookup, e l'abbiamo
            #             gia' trovato sopra.
            #   «432/c» → la lettera c) e' un COMMA dentro l'articolo 432
            #             («per shkelje procedurale...»). Non e' un articolo,
            #             ma la citazione e' correttissima.
            #
            # Il secondo caso finiva "fake", e all'avvocato compariva un
            # «nen fantazme» su una citazione giusta e decisiva. Per
            # distinguerli non si indovina: si guarda se quel comma c'e'
            # davvero scritto nel testo dell'articolo base.
            padre = lookup.get((code, base))
            if padre is not None and _lettera_e_un_koma(padre, first):
                return padre
            # «149/a/2» = comma 2 dell'articolo 149/a. Prima di arrendersi si
            # prova la coppia base+lettera, che puo' essere un articolo vero.
            if len(parts) > 2:
                art = lookup.get((code, base + "/" + first))
                if art is not None:
                    return art
    return None


def _lettera_e_un_koma(article, lettera: str) -> bool:
    """La lettera e' davvero un comma scritto dentro questo articolo?

    Si cerca il marcatore come lo stampa il codice — «c)» a inizio comma —
    nel corpo e nella rubrica. Se non c'e', la citazione resta falsa: cosi'
    un «neni 432/z» inventato continua a cadere, perche' nel 432 non esiste
    nessuna lettera z.
    """
    if article is None:
        return False
    lettera = (lettera or "").strip().lower()
    if not lettera or len(lettera) > 2 or not lettera.isalpha():
        return False
    testo = ((getattr(article, "body", "") or "") + " " +
             (getattr(article, "heading", "") or "")).lower()
    if not testo.strip():
        return False
    return re.search(r"(?:^|[\s;,.])%s\s*[)\]]" % re.escape(lettera),
                     testo) is not None


def _codes_for_number(num_to_codes: dict, number: str,
                      lookup_koma: dict | None = None) -> list:
    """Candidate codes for a bare number, tolerant of paragraph/range form.

    `lookup_koma` — (code, number) → Article — serve per il caso «432/c»
    scritto senza nominare il codice: un codice diventa candidato solo se in
    quel codice l'articolo base contiene davvero la lettera come comma.
    Senza questo controllo si aprirebbe la maglia a qualunque lettera; con
    questo, «432/z» resta senza candidati e quindi falso.
    """
    codes = list(num_to_codes.get(number, []))
    if not codes and lookup_koma is not None:
        # v9.348: numero che esiste SOLO negli allegati («13-ter» del c.p.a. = norme di attuazione)
        codes = sorted(_annex_maps(lookup_koma)[1].get(number, ()))
    if not codes and "/" in number:
        parts = number.split("/")
        base = parts[0]
        if len(parts) > 1 and parts[1].isdigit():
            codes = list(num_to_codes.get(base, []))
        elif len(parts) > 1 and lookup_koma is not None:
            lettera = parts[1]
            # prima: «149/a» come articolo inserito a se'
            codes = list(num_to_codes.get(base + "/" + lettera, []))
            if not codes:
                # poi: la lettera come comma dentro l'articolo base
                codes = [c for c in num_to_codes.get(base, [])
                         if _lettera_e_un_koma(lookup_koma.get((c, base)), lettera)]
    return codes


def _codice_precedente(text: str, pos: int, resolve) -> str | None:
    """Anafora («neni 37, pika 1, i po këtij ligji», «art. 4 del medesimo decreto»): la legge o il
    codice nominato per ULTIMO nella finestra di testo PRIMA della citazione (17 set 2026). Si
    scandisce a ritroso a blocchi di 6 parole con lo stesso risolutore delle code; nessun nome
    nella finestra → None (la citazione resta «senza codice», mai un'ipotesi)."""
    win = text[max(0, pos - _ANAFORA_WINDOW):pos]
    words = win.split()
    for i in range(len(words) - 1, -1, -1):
        code = resolve(" ".join(words[i:i + 6]))
        if code:
            return code
    return None


def verify_text(
    text: str,
    index: ArticleIndex,
    *,
    retrieved_codes: Iterable[str] | None = None,
    context_text: str | None = None,
) -> dict:
    """Scan ``text`` for ``Neni N <code>`` patterns and verify each one.

    ``retrieved_codes`` is the set of codes that the BM25 retrieval surfaced
    for the user's query — if a "needs_code" citation has exactly one
    candidate code that's also in retrieved_codes, we promote it to "verified"
    via context (the model very likely meant that one).

    ``context_text`` (17 set 2026): un testo in più da cui leggere i LEGAMI numero→codice (il
    claim binding verifica le sole citazioni estratte, ma il codice sta nella risposta intera).

    Returns:
        {
            "items": [Citation as dict, ...],
            "stats": {"verified": int, "fake": int, "needs_code": int, "total": int},
        }
    """
    lookup = _build_lookup(index)
    lookup_all = _build_lookup_all(index)
    num_to_codes = _build_number_to_codes(index)
    retrieved_codes = set(retrieved_codes or [])

    # V-IT: Italian corpus -> Italian citation extraction (art. N c.c. ...).
    _lang = getattr(index, "lang", "sq")
    _cite_re = CITATION_RE_IT if _lang == "it" else CITATION_RE
    _num_re = _NUM_RE_IT if _lang == "it" else _NUM_RE
    _resolve = _resolve_code_it if _lang == "it" else _resolve_code
    _cite_prefix = "art. " if _lang == "it" else "neni "
    _anafora_re = _ANAFORA_IT if _lang == "it" else _ANAFORA_AL

    # 17 set 2026 — LEGAME A LIVELLO DI DOCUMENTO: «Neni 144 i Kodit të Punës … Pika 5 e nenit 144»,
    # «nenit 155/4» dopo «neni 155, pika 1, i Kodit të Punës». Il numero nudo prende il codice che LO
    # STESSO documento gli dà altrove — solo se è UNO solo e se quell'articolo esiste davvero in quel
    # codice (può solo togliere un «pa kod», mai creare un «fantazmë»). Prima veniva prima del
    # contesto del recupero: quello era ambiguo (anche il Kodi Civil ha un 144), il documento no.
    legami: dict[str, set] = {}
    for _src in (text or "", context_text or ""):
        for _m in _cite_re.finditer(_src):
            _tail = _m.group("tail") or ""
            _code = _resolve(_tail)
            _kp = _lang != "it" and _kp_bare(_tail, _code)   # «neni 155 KP» si scioglie dal documento, non dall'alias
            for _nr in _num_re.findall(_m.group("nums")):
                _n = _normalise_number(_nr)
                _c = _kp_resolve(_n, _src, retrieved_codes, lookup) if _kp else _code
                if _c:
                    legami.setdefault(_n.split("/")[0], set()).add(_c)

    def _esiste(code: str, number: str) -> bool:
        return (_verify_number(lookup, code, number) is not None
                or _verify_number(lookup_all, code, number) is not None)

    def _dal_documento(number: str) -> str | None:
        b = legami.get(number.split("/")[0])
        if b and len(b) == 1:
            c = next(iter(b))
            return c if _esiste(c, number) else None
        return None

    seen: set[tuple[str, str]] = set()  # dedupe (number, code-or-empty)
    citations: list[Citation] = []

    def _emit(number: str, code: str | None, raw: str, resolved_by: str | None = None) -> None:
        """Classify one (number, code) pair and append its Citation."""
        if code:
            art = _verify_number(lookup, code, number)
            if art is not None:
                citations.append(Citation(
                    raw=raw, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="verified", candidates=[],
                    article_heading=getattr(art, "heading", None),
                    resolved_by=resolved_by,
                ))
                return
            rart = _verify_number(lookup_all, code, number)
            if rart is not None:
                # exists in this code but REPEALED — real, not hallucinated
                citations.append(Citation(
                    raw=raw, number=number, code=code,
                    code_label=CODE_LABELS.get(code, code),
                    status="repealed", candidates=[],
                    article_heading=getattr(rart, "heading", None),
                    resolved_by=resolved_by,
                ))
                return
            citations.append(Citation(
                raw=raw, number=number, code=code,
                code_label=CODE_LABELS.get(code, code),
                status="fake", candidates=[],
            ))
            return
        candidate_codes = _codes_for_number(num_to_codes, number, lookup_all)
        # Promotion via retrieval context: if exactly one candidate appears in
        # the retrieved set, we treat it as verified.
        in_ctx = [c for c in candidate_codes if c in retrieved_codes]
        if len(in_ctx) == 1:
            code_resolved = in_ctx[0]
            art = _verify_number(lookup, code_resolved, number)
            citations.append(Citation(
                raw=raw, number=number, code=code_resolved,
                code_label=CODE_LABELS.get(code_resolved, code_resolved),
                status="verified", candidates=[],
                article_heading=getattr(art, "heading", None),
                resolved_by="retrieval",
            ))
        elif candidate_codes:
            citations.append(Citation(
                raw=raw, number=number, code=None, code_label=None,
                status="needs_code",
                candidates=[{"code": c, "label": CODE_LABELS.get(c, c)}
                            for c in candidate_codes[:6]],
            ))
        else:
            # Number not present in any code in our corpus → fake.
            citations.append(Citation(
                raw=raw, number=number, code=None,
                code_label=None, status="fake", candidates=[],
            ))

    for m in _cite_re.finditer(text):
        nums_block = m.group("nums")
        tail = m.group("tail") or ""
        code = _resolve(tail)              # one shared code for the list
        numbers = _num_re.findall(nums_block)
        full_raw = text[m.start():m.end()].strip()
        if len(full_raw) > 60:
            full_raw = full_raw[:60].rstrip() + "…"
        multi = len(numbers) > 1
        kp_bare = _lang != "it" and _kp_bare(tail, code)
        # anafora: «i po këtij ligji» / «del medesimo decreto» → l'ultima legge nominata prima
        anafora = None
        if code is None and not kp_bare and _anafora_re.match(tail):
            anafora = _codice_precedente(text, m.start(), _resolve)
        for number_raw in numbers:
            number = _normalise_number(number_raw)
            code_n = _kp_resolve(number, text, retrieved_codes, lookup) if kp_bare else code
            via = None
            if code_n is None and not kp_bare:
                if anafora and _esiste(anafora, number):
                    code_n, via = anafora, "anafora"
                else:
                    _d = _dal_documento(number)
                    if _d:
                        code_n, via = _d, "documento"
            key = (number, code_n or ("kp?" if kp_bare else ""))
            if key in seen:
                continue
            seen.add(key)
            # In a list each article gets its own clean label; a lone citation
            # keeps the full matched span for context.
            raw = (_cite_prefix + number_raw) if multi else full_raw
            if kp_bare and code_n is None:
                # sigla «KP» irrisolvibile: i due candidati che hanno quel numero, mai un verde a caso
                cands = [c for c in ("kodi_punes", "kodi_penal") if _verify_number(lookup, c, number) is not None]
                citations.append(Citation(
                    raw=raw, number=number, code=None, code_label=None,
                    status="needs_code" if cands else "fake",
                    candidates=[{"code": c, "label": CODE_LABELS.get(c, c)} for c in cands]))
                continue
            _emit(number, code_n, raw, via)

    for _c in citations:
        if _c.status in ("verified", "repealed") and _c.code:
            _a = (_verify_number(lookup, _c.code, _c.number)
                  or _verify_number(lookup_all, _c.code, _c.number))
            if _a is not None:
                _c.volatility = getattr(_a, "volatility", None)
                _c.last_amendment_date = getattr(_a, "last_amendment_date", None)
    stats = {
        "verified": sum(1 for c in citations if c.status == "verified"),
        "fake": sum(1 for c in citations if c.status == "fake"),
        "repealed": sum(1 for c in citations if c.status == "repealed"),
        "needs_code": sum(1 for c in citations if c.status == "needs_code"),
        "stale": sum(1 for c in citations if c.status == "verified"
                     and (c.volatility or "").upper() == "MEDIUM"),
        "total": len(citations),
    }
    return {
        "items": [asdict(c) for c in citations],
        "stats": stats,
    }
