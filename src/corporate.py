"""V9.3 — Corporate Intelligence.

Three tools for lawyers handling corporate cases:
  1. extract_corporate()  — Opus parses visura/statuto/procura/bilanci
                            into structured JSON (soci, CDA, procure, scadenze)
  2. check_signatory()    — authority check before a contract is signed
  3. kyc_checklist()      — rule-based AML/KYC gap analysis per Ligji 9917/2008
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from .backends import LLMBackend
from .genio import GENIO_JURISDICTION_GUARD

log = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────────────

_EXTRACT_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je ekspert i drejtësisë tregtare shqiptare (Ligji nr. 9901/2008 "
    "'Për tregtarët dhe shoqëritë tregtare', Ligji nr. 9917/2008 'Për "
    "parandalimin e pastrimit të parave', rregulloret QKB). Detyra jote: "
    "ekstrakto të dhëna strukturore nga dokumenti i shoqërisë dhe kthe "
    "VETËM JSON të vlefshëm pa asnjë tekst shtesë. Për fushat që nuk janë "
    "të pranishme në dokument, përdor null. Mos shpik të dhëna."
)

_GATE_SYSTEM = (
    GENIO_JURISDICTION_GUARD
    + "Je ekspert i autorizimeve të nënshkrimit sipas të drejtës tregtare "
    "shqiptare. Ligji 9901/2008 Neni 147 (administrator), Neni 167 (prokurist), "
    "Neni 120 (fuqia e nënshkrimit të organeve). Kthe VETËM JSON të vlefshëm."
)

# ── KYC requirements per Ligji 9917/2008 + udhëzimi BSH ─────────────

_KYC_REQS: list[dict] = [
    {
        "id": "ekstrakti_qkb",
        "label": "Ekstrakt QKB (jo më i vjetër se 3 muaj)",
        "basis": "Ligji 9917/2008 Neni 5",
        "doc_types": {"visura", "ekstrakti_qkb", "qkb", "regjistri_tregtar"},
    },
    {
        "id": "statuti",
        "label": "Statuti / Akti i themelimit",
        "basis": "Ligji 9917/2008 Neni 5",
        "doc_types": {"statuto", "statuti", "akt_themelimi"},
    },
    {
        "id": "nuis",
        "label": "Certifikatë NUIS/NIPT",
        "basis": "Ligji 9917/2008 Neni 5",
        "doc_types": {"nuis", "nipt", "certifikata_tatimore", "administrata_tatimore"},
    },
    {
        "id": "id_titullar",
        "label": "Dokument identiteti i titullarit efektiv (>25% kapital ose kontroll)",
        "basis": "Ligji 9917/2008 Neni 7 (titullari efektiv)",
        "doc_types": {"id", "pasaporte", "leternjoftim"},
    },
    {
        "id": "id_nenshkrues",
        "label": "Dokument identiteti i personit me të drejtë nënshkrimi",
        "basis": "Ligji 9917/2008 Neni 5",
        "doc_types": {"id", "pasaporte", "leternjoftim"},
    },
    {
        "id": "prokura",
        "label": "Prokurë / autorizim i nënshkruesit (nëse jo anëtar CDA)",
        "basis": "Ligji 9901/2008 Neni 167",
        "doc_types": {"procura", "prokura", "autorizim"},
    },
    {
        "id": "bilanci",
        "label": "Bilanci i audituar (3 vitet e fundit)",
        "basis": "Ligji 9917/2008 Neni 6",
        "doc_types": {"bilanci", "bilanco", "pasqyre_financiare"},
    },
    {
        "id": "deklarata_origjines",
        "label": "Deklaratë burimi fondesh",
        "basis": "Ligji 9917/2008 Neni 6 §3",
        "doc_types": {"deklarata_origjines", "deklarate_burimeve"},
    },
    {
        "id": "certif_tatimore",
        "label": "Certifikatë tatimore pa debi (≤1 muaj)",
        "basis": "Praktikë administrative QKB",
        "doc_types": {"certifikata_tatimore", "vertetim_tatimor"},
    },
]

# ── Extraction ────────────────────────────────────────────────────────

_EXTRACT_SCHEMA = {
    "emri_shoqerise": None,
    "nuis": None,
    "forma_juridike": None,
    "qkb_date": None,
    "kapitali_themeltar": None,
    "seli": None,
    "veprimtaria": None,
    "soci": [],
    "cda": [],
    "procure": [],
    "scadenze": [],
    "anomalie": [],
}

_EXTRACT_TEMPLATE = """\
Lloji dokumentit: {doc_type}

TEKSTI I DOKUMENTIT:
{doc_text}

Kthe VETËM JSON me strukturën e mëposhtme (fushat mungojnë → null/[]):

{{
  "emri_shoqerise": "...",
  "nuis": "...",
  "forma_juridike": "Sh.a. | Sh.p.k. | ... | null",
  "qkb_date": "YYYY-MM-DD | null",
  "kapitali_themeltar": "numër në ALL | null",
  "seli": "adresë | null",
  "veprimtaria": "...",
  "soci": [
    {{"emri": "...", "quota_pct": 0.0, "lloji": "fizik | juridik"}}
  ],
  "cda": [
    {{
      "emri": "...",
      "roli": "Administrator | Drejtor | Anëtar KD | ...",
      "nenshkrim_forme": "i pavarur | i perbashket | null",
      "limit_all": null,
      "mandati_skadon": "YYYY-MM-DD | null"
    }}
  ],
  "procure": [
    {{
      "emri": "...",
      "qellimi": "...",
      "limit_all": null,
      "skadon": "YYYY-MM-DD | null",
      "forme": "e posacme | e pergjithshme"
    }}
  ],
  "scadenze": [
    {{"dokumenti": "...", "skadon": "YYYY-MM-DD | null", "dite_mbetur": null}}
  ],
  "anomalie": ["vërejtje konkrete nëse ka"]
}}"""


def extract_corporate(
    doc_text: str,
    doc_type: str = "i panjohur",
    *,
    backend: LLMBackend,
) -> dict:
    """Parse a corporate document and return structured JSON."""
    prompt = _EXTRACT_TEMPLATE.format(
        doc_type=doc_type,
        doc_text=doc_text[:12000],
    )
    raw = backend.complete(
        system=_EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        callsite="corporate_extract",
    )
    return _parse_json(raw, _EXTRACT_SCHEMA)


# ── Gatekeeper ────────────────────────────────────────────────────────

_GATE_SCHEMA = {
    "ka_autoritet": False,
    "baza_ligjore": "",
    "fusha_e_autorizimit": "",
    "limit_financiar_all": None,
    "vlera_kontrates_all": None,
    "brenda_limitit": None,
    "skadon": None,
    "dite_mbetur": None,
    "paralajmerime": [],
    "risqe": [],
    "rekomandim": "",
}

_GATE_TEMPLATE = """\
KËRKESË VERIFIKIMI FIRMATARI

Firmatari: {signatory_name}
Vlera e kontratës: {value_all} ALL (0 nëse e panjohur)
Lloji i kontratës: {contract_type}

TË DHËNA KORPORATIVE (nga dokumentet e ngarkuara):
{corp_json}

Sot: {today}

Kthe VETËM JSON:
{{
  "ka_autoritet": true | false,
  "baza_ligjore": "neni/prokura konkrete",
  "fusha_e_autorizimit": "lloji kontratash/veprimesh",
  "limit_financiar_all": null,
  "vlera_kontrates_all": {value_all},
  "brenda_limitit": true | false | null,
  "skadon": "YYYY-MM-DD | null",
  "dite_mbetur": null,
  "paralajmerime": ["..."],
  "risqe": ["..."],
  "rekomandim": "VAZHDO / NDALO / KUJDES — arsyetim konkret"
}}"""


def check_signatory(
    signatory_name: str,
    value_all: float,
    contract_type: str,
    corp_extractions: list[dict],
    *,
    backend: LLMBackend,
) -> dict:
    """Check whether a signatory has authority to bind the company."""
    merged = _merge_extractions(corp_extractions)
    prompt = _GATE_TEMPLATE.format(
        signatory_name=signatory_name,
        value_all=int(value_all) if value_all else 0,
        contract_type=contract_type or "kontratë tregtare",
        corp_json=json.dumps(merged, ensure_ascii=False, indent=2)[:6000],
        today=date.today().isoformat(),
    )
    raw = backend.complete(
        system=_GATE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        callsite="corporate_gatekeeper",
    )
    result = _parse_json(raw, _GATE_SCHEMA)
    # auto-compute dite_mbetur
    if result.get("skadon"):
        try:
            exp = datetime.strptime(result["skadon"], "%Y-%m-%d").date()
            result["dite_mbetur"] = (exp - date.today()).days
        except ValueError:
            pass
    return result


# ── KYC Checklist (rule-based, no AI call) ───────────────────────────

def kyc_checklist(
    corp_extractions: list[dict],
    uploaded_doc_types: list[str],
) -> dict:
    """Return AML/KYC gap analysis per Ligji 9917/2008.

    uploaded_doc_types: list of doc_type strings from the case's corporate
    extractions (e.g. ["visura", "statuto", "procura"]).
    """
    present_types = {t.lower().strip() for t in uploaded_doc_types}
    merged = _merge_extractions(corp_extractions)
    today = date.today()

    checklist: list[dict] = []
    missing: list[str] = []
    expiring: list[str] = []

    for req in _KYC_REQS:
        found = bool(req["doc_types"] & present_types)
        # prokura: not needed if signatory is a CDA member
        if req["id"] == "prokura" and merged.get("cda"):
            found = True  # CDA members need no separate prokura
        checklist.append({
            "id": req["id"],
            "label": req["label"],
            "basis": req["basis"],
            "present": found,
        })
        if not found:
            missing.append(req["label"])

    # check scadenze from merged extractions
    for sc in merged.get("scadenze", []):
        if sc.get("skadon"):
            try:
                exp = datetime.strptime(sc["skadon"], "%Y-%m-%d").date()
                days = (exp - today).days
                if 0 <= days <= 60:
                    expiring.append(
                        f"{sc['dokumenti']} skadon {sc['skadon']} "
                        f"({days} ditë)"
                    )
            except ValueError:
                pass

    # check QKB extract freshness
    qkb_date = merged.get("qkb_date")
    if qkb_date:
        try:
            qd = datetime.strptime(qkb_date, "%Y-%m-%d").date()
            age_days = (today - qd).days
            if age_days > 90:
                expiring.append(
                    f"Ekstrakt QKB i datës {qkb_date} ({age_days} ditë i vjetër — kufiri 90 ditë)"
                )
        except ValueError:
            pass

    # risk level
    n_missing = len(missing)
    if n_missing >= 4 or merged.get("anomalie"):
        risk = "i lartë"
    elif n_missing >= 2 or expiring:
        risk = "i mesëm"
    else:
        risk = "i ulët"

    return {
        "checklist": checklist,
        "missing": missing,
        "expiring_soon": expiring,
        "risk_level": risk,
        "anomalie": merged.get("anomalie", []),
        "emri_shoqerise": merged.get("emri_shoqerise"),
        "nuis": merged.get("nuis"),
    }


# ── Helpers ───────────────────────────────────────────────────────────

def _merge_extractions(extractions: list[dict]) -> dict:
    """Merge multiple corporate extractions into a single view."""
    merged: dict = {
        "soci": [], "cda": [], "procure": [], "scadenze": [], "anomalie": [],
    }
    for ext in extractions:
        data = ext if "soci" in ext else ext.get("extracted_json", ext)
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
        for field in ("emri_shoqerise", "nuis", "forma_juridike",
                      "qkb_date", "kapitali_themeltar", "seli", "veprimtaria"):
            if data.get(field) and not merged.get(field):
                merged[field] = data[field]
        for list_field in ("soci", "cda", "procure", "scadenze", "anomalie"):
            merged[list_field].extend(data.get(list_field) or [])
    return merged


def _parse_json(raw: str, default: dict) -> dict:
    """Extract JSON from model output, strip code fences, fallback to default."""
    text = raw.strip()
    # strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    # find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    log.warning("corporate: JSON parse failed, returning default")
    return dict(default)
