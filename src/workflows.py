"""V8.15 Workflow library.

A *workflow* is a small, declarative, reusable plan a lawyer can attach
to a case so the assistant knows what step is next. We avoid a full
BPMN engine on purpose — a workflow is a *list of steps with a current
index*. State lives in `case_workflows` rows; each step's output is
stashed in a JSON blob keyed by step id.

Step kinds
──────────
- ``ai_call``           — calls the brain backend with a prompt template.
- ``manual``            — waits for the lawyer to mark complete (e.g.
                          "raccolta firma del mandato").
- ``document_request``  — emits an ``auto_letters`` row asking the
                          client / opponent for a document.
- ``deadline_calc``     — computes a court deadline via
                          ``pro_features.processual_deadlines`` and
                          inserts the resulting events into the calendar.
- ``checklist``         — multi-item checklist; advances when all items
                          are ticked off.

The workflows here are deliberately broad — Romeo wanted a *library*
that demonstrates the DSL, not an exhaustive playbook. Studi can copy
+ tweak via the `custom_definition` JSON when they create one.

Design note: predefined definitions are pure data (DEFINITIONS dict).
The runtime (storage.start_workflow / advance_workflow) interprets
them. This means the library can be edited without touching SQL.
"""
from __future__ import annotations

from typing import Any


# ── DSL types (lightweight — plain dicts, validated at load) ───────────

# Step shape:
#   {
#       "id":          unique-within-workflow string slug,
#       "title":       short human label (Albanian),
#       "kind":        one of the kinds above,
#       "description": longer human explanation (optional),
#       "params":      kind-specific dict (see below),
#       "blocking":    bool — if true, can't advance past until complete,
#       "output_key":  optional, where to stash the step's result,
#   }
#
# Per-kind params
# ───────────────
#  ai_call:
#       prompt_system, prompt_user, max_tokens, tier ('opus'|'medium'|'fast')
#  manual:
#       hint
#  document_request:
#       recipient_kind ('client'|'opponent'|'court'), letter_kind,
#       subject_template, body_template (Jinja-like {{var}} placeholders)
#  deadline_calc:
#       trigger_field (which prior output supplies the trigger date),
#       deadline_kind (KPC/KPP key — e.g. 'apel_civil')
#  checklist:
#       items: list of strings


def _ai(id: str, title: str, prompt_user: str, *,
        prompt_system: str = "Ti je Super Avvocato — avokat shqiptar i kujdesshëm.",
        max_tokens: int = 1200, tier: str = "medium",
        description: str = "",
        output_key: str | None = None) -> dict:
    return {
        "id": id, "title": title, "kind": "ai_call",
        "description": description,
        "params": {
            "prompt_system": prompt_system,
            "prompt_user": prompt_user,
            "max_tokens": max_tokens,
            "tier": tier,
        },
        "blocking": True,
        "output_key": output_key or id,
    }


def _manual(id: str, title: str, hint: str = "") -> dict:
    return {
        "id": id, "title": title, "kind": "manual",
        "description": hint,
        "params": {"hint": hint},
        "blocking": True,
        "output_key": id,
    }


def _checklist(id: str, title: str, items: list[str], description: str = "") -> dict:
    return {
        "id": id, "title": title, "kind": "checklist",
        "description": description,
        "params": {"items": items},
        "blocking": True,
        "output_key": id,
    }


def _doc_request(id: str, title: str, recipient_kind: str,
                 letter_kind: str, subject: str, body: str) -> dict:
    return {
        "id": id, "title": title, "kind": "document_request",
        "description": "",
        "params": {
            "recipient_kind": recipient_kind,
            "letter_kind": letter_kind,
            "subject_template": subject,
            "body_template": body,
        },
        "blocking": False,
        "output_key": id,
    }


def _deadline(id: str, title: str, deadline_kind: str,
              trigger_field: str = "decision_date") -> dict:
    return {
        "id": id, "title": title, "kind": "deadline_calc",
        "description": "",
        "params": {
            "deadline_kind": deadline_kind,
            "trigger_field": trigger_field,
        },
        "blocking": False,
        "output_key": id,
    }


# ── Definitions ────────────────────────────────────────────────────────

DEFINITIONS: dict[str, dict[str, Any]] = {

    # 1. Apertura di una causa civile contenziosa (AL default)
    "open_contentious_case": {
        "key": "open_contentious_case",
        "title": "Hapje çështjeje civile gjyqësore",
        "summary": "Workflow standard për të hapur një çështje civile "
                   "kontestuese — nga intaku te depozitimi i kërkesë-"
                   "padisë.",
        "jurisdiction": ["AL"],
        "estimated_days": 14,
        "steps": [
            _checklist(
                "intake_docs", "Mbledhja e dokumenteve nga klienti",
                ["Karta identitetit", "Mandati i nënshkruar",
                 "Kontrata bazë / akti themelor", "Korrespondencë e mëparshme",
                 "Provat dokumentare të disponueshme"],
                "Asnjë shkresë nuk depozitohet pa pasur këto në dosje.",
            ),
            _ai(
                "fact_summary",
                "Përmbledhje faktike",
                "Mbi bazën e dokumenteve dhe bisedës, harto një përmbledhje "
                "faktike neutrale (≤ 400 fjalë) të rastit. Përfshi: palët, "
                "kronologjinë, pretendimet, provat e disponueshme. Mos shto "
                "vlerësim juridik këtu.",
                description="Përmbledhja shërben si bazë për të gjitha hapat e "
                            "tjerë — duhet të jetë e qartë, e datuar, jo "
                            "argumentuese.",
                tier="medium",
            ),
            _ai(
                "legal_theory",
                "Teoria juridike",
                "Mbi bazën e përmbledhjes faktike (output i hapit fact_summary), "
                "identifiko: (1) kauzën juridike kryesore, (2) nenet e KC/KPC "
                "më të aplikueshme, (3) precedentë të GJL që mbështesin tezën, "
                "(4) rreziqet kryesore. Kthe markdown me 4 seksione.",
                description="Strategjia bazë para se të nxjerrim kërkesë-padinë.",
                tier="opus",
                max_tokens=1800,
            ),
            _ai(
                "draft_kerkesa",
                "Hartim i kërkesë-padisë",
                "Mbi bazën e teorisë juridike, harto kërkesë-padinë e plotë "
                "në formë zyrtare KPC: rubrum, faktet, baza ligjore, "
                "kërkimet, lista e provave. Lër placeholder-a [...] për të "
                "dhënat që ende mungojnë.",
                tier="opus",
                max_tokens=3000,
            ),
            _manual(
                "review_signoff",
                "Rishikim i avokatit dhe nënshkrimi",
                "Avokati duhet të lexojë drafit të kërkesë-padisë, të "
                "korrigjojë çdo placeholder dhe të nënshkruajë.",
            ),
            _manual(
                "court_filing",
                "Depozitim në gjykatë",
                "Depozito kërkesë-padinë në gjykatën kompetente. Shëno "
                "numrin e protokollit në fushën e dosjes.",
            ),
            _deadline(
                "compute_response_window",
                "Llogarit afatin e prapësimit të palës tjetër",
                deadline_kind="prapesim_civil",
                trigger_field="court_filing",
            ),
        ],
    },

    # 2. Review di un contratto M&A
    "review_ma_contract": {
        "key": "review_ma_contract",
        "title": "Review i kontratës M&A",
        "summary": "Workflow strukturuar për due-diligence kontraktuale të "
                   "një operacioni M&A.",
        "jurisdiction": ["AL", "IT", "EU"],
        "estimated_days": 7,
        "steps": [
            _checklist(
                "scope_check",
                "Përcakto fushën e review-it",
                ["Lloji i operacionit (share deal / asset deal)",
                 "Juridiksioni mbizotërues", "Shumat dhe paritë",
                 "Datat kyçe (signing / closing / long-stop)",
                 "Disponueshmëria e VDR (data room)"],
            ),
            _ai(
                "clause_map",
                "Hartë e klauzolave",
                "Lexo kontratën dhe ndërto një tabelë me të gjitha klauzolat "
                "kryesore (R&W, indemnities, conditions precedent, MAC, "
                "earn-out, non-compete, termination, governing law, "
                "dispute resolution). Për secilën, shëno: numri/titull, "
                "rrezikshmëria 0-5, koment 1 fjali.",
                tier="opus",
                max_tokens=3500,
            ),
            _ai(
                "redflag_report",
                "Raport flamuj të kuq",
                "Mbi bazën e clause_map, identifiko 5-10 flamuj të kuq më "
                "kritikë. Për secilin: cilët dispozitë, pse rrezik, "
                "rekomandim (rishkrim / fshirje / kërkesë garancie).",
                tier="opus",
                max_tokens=2500,
            ),
            _ai(
                "negotiation_playbook",
                "Playbook negociator",
                "Përgatit pikat negociatore për takim me palën tjetër: "
                "must-have / should-have / nice-to-have. Sugjero formulime "
                "alternative për çdo flamur të kuq.",
                tier="medium",
                max_tokens=2000,
            ),
            _manual(
                "client_walkthrough",
                "Prezantim i raportit te klienti",
                "Takim 1h me klientin për të kaluar flamujt e kuq dhe "
                "marrë vendime negociator.",
            ),
        ],
    },

    # 3. Preparazione udienza
    "hearing_prep": {
        "key": "hearing_prep",
        "title": "Përgatitje për seancë gjyqësore",
        "summary": "Plan 5-ditor pa-seance: nga rishikimi i fashikullit "
                   "deri te prova e fjalimit.",
        "jurisdiction": ["AL"],
        "estimated_days": 5,
        "steps": [
            _checklist(
                "fascikull_review",
                "Rishiko fashikullin",
                ["Akti i fundit i palës tjetër", "Provat e dorëzuara",
                 "Dëshmitarët e konfirmuar", "Vendimet e mëparshme procedurale"],
            ),
            _ai(
                "issues_list",
                "Lista e çështjeve për seancë",
                "Mbi bazën e historikut të çështjes, harto listën e çështjeve "
                "konkrete që pritet të diskutohen në këtë seancë. Për "
                "secilën: pozicioni ynë, pozicioni i kundërt, pikat e forta, "
                "pikat e dobëta.",
                tier="opus",
                max_tokens=2000,
            ),
            _ai(
                "anticipate_questions",
                "Pyetje të mundshme nga gjyqtari",
                "Bazuar në çështjet, gjenero 8-12 pyetje që një gjyqtar i "
                "vëmendshëm mund të bëjë. Për secilën, përgjigjja jonë e "
                "shkurtër (≤ 60 fjalë).",
                tier="medium",
            ),
            _ai(
                "speech_outline",
                "Skema e fjalimit",
                "Harto skemë 7 minuta për fjalimin hapës: (1) kuadri, "
                "(2) faktet pranuara, (3) pikat e mosmarrëveshjes, "
                "(4) baza ligjore, (5) kërkimet konkrete. Bullet, jo "
                "tekst i plotë.",
                tier="medium",
            ),
            _manual(
                "rehearsal",
                "Provë e fjalimit",
                "Provoje fjalimin me kohë; duhet të rrijë nën 8 minuta.",
            ),
            _manual(
                "pack_materials",
                "Përgatit materialet fizike",
                "Tre kopje të akteve, lista e dëshmitarëve, prokura, "
                "kartë identitetit.",
            ),
        ],
    },

    # 4. Mass-tort intake
    "mass_tort_intake": {
        "key": "mass_tort_intake",
        "title": "Mass-tort: pranim i një grupi klientësh",
        "summary": "Onboarding i strukturuar për kauzë me shumë klientë "
                   "(p.sh. konsumatorë, punonjës, viktima).",
        "jurisdiction": ["AL", "EU"],
        "estimated_days": 21,
        "steps": [
            _ai(
                "eligibility_criteria",
                "Kriteret e pranueshmërisë",
                "Përcakto kriteret që një individ duhet të plotësojë për të "
                "qenë pjesë e grupit. Kthe JSON me fushat: required (listë), "
                "disqualifying (listë), evidence_required (listë).",
                tier="opus",
                max_tokens=1200,
            ),
            _doc_request(
                "intake_form",
                "Formulari i pranimit te klienti",
                recipient_kind="client",
                letter_kind="document_request",
                subject="Formulari i pranimit — kauzë kolektive",
                body="Mirëdita,\n\nNë vijim të bisedës, ju lutem plotësoni "
                     "formularin e bashkëngjitur dhe na dërgoni dokumentet:\n"
                     "{{evidence_list}}\n\nFalemnderit,\n{{lawyer_name}}",
            ),
            _checklist(
                "data_room",
                "Krijo data-room të grupit",
                ["Folder për secilin klient", "Tabelë master me ID, status, "
                 "pranueshmëri", "Sistem versionimi i mandateve",
                 "Konfidencialitet brenda-grupi i adresuar"],
            ),
            _ai(
                "common_facts",
                "Fakte të përbashkëta",
                "Mbi bazën e formularit dhe dokumenteve, identifiko faktet "
                "që përsëriten te të gjithë klientët dhe ato që ndryshojnë. "
                "Faktet e përbashkëta janë baza e padisë kolektive.",
                tier="opus",
                max_tokens=2000,
            ),
            _ai(
                "class_strategy",
                "Strategjia kolektive",
                "A duhet ngritur si padi e vetme me bashkë-paditës (KPC), "
                "si padi paralele individuale, ose si action-collective EU "
                "(Direktiva 2020/1828)? Krahaso 3 opsionet me kosto, kohë, "
                "rrezik.",
                tier="opus",
                max_tokens=2500,
            ),
            _manual(
                "client_meeting",
                "Mbledhje informuese me grupin",
                "Prezanto strategjinë te grupi, mblidh pyetje, konfirmo "
                "pjesëmarrjen.",
            ),
        ],
    },

    # 5. Due-diligence (corporate / pre-acquisition)
    "due_diligence": {
        "key": "due_diligence",
        "title": "Due-diligence ligjore",
        "summary": "Audit ligjor i një target-i korporativ — corporate, "
                   "kontrata, punësim, gjyqësore, IP, GDPR.",
        "jurisdiction": ["AL", "IT", "EU"],
        "estimated_days": 14,
        "steps": [
            _checklist(
                "scope_engagement",
                "Përcakto fushën e DD",
                ["Lloji (red-flag / full)", "Periudha kohore",
                 "Praktikat e mbuluara (corporate, kontrata, punësim, "
                 "fiskal, IP, GDPR, gjyqësore, real-estate)",
                 "Format i raportit final", "Afati"],
            ),
            _doc_request(
                "vdr_request_list",
                "Lista e dokumenteve për VDR",
                recipient_kind="client",
                letter_kind="document_request",
                subject="DD — kërkesë e parë e dokumenteve",
                body="Më poshtë lista e parë e dokumenteve të kërkuara për "
                     "data-room. Ju lutem ngarkoni në VDR brenda "
                     "{{deadline}}.\n\n{{document_list}}",
            ),
            _ai(
                "corporate_review",
                "Review corporate",
                "Analizo statutin, regjistrin tregtar, vendimet e ortakëve "
                "dhe të bordit. Identifiko: probleme në kapital, kufizime "
                "transfertash, change-of-control, konflikt interesi.",
                tier="opus",
                max_tokens=2500,
            ),
            _ai(
                "contracts_review",
                "Review kontratash material",
                "Analizo kontratat material (top 20 për vlerë). Për secilën: "
                "klauzola change-of-control, exclusivity, liability cap, "
                "termination, garancitë e dhëna. Tabela përmbledhëse.",
                tier="opus",
                max_tokens=3000,
            ),
            _ai(
                "litigation_employment",
                "Gjyqësore + punësim",
                "Përmblidh çështjet gjyqësore aktive (vlerë, fazë, rrezik) "
                "dhe gjendjen e punësimit (kontrata, kolektivë, përfitime "
                "të akumuluara).",
                tier="medium",
                max_tokens=2000,
            ),
            _ai(
                "ip_data_review",
                "IP + GDPR",
                "Inventarizoj patentat, markat, copyright-et dhe domain-et. "
                "Verifiko konformitetin GDPR (Art. 30 ROPA, kontratat me "
                "processor, transfertat ndërkombëtare).",
                tier="medium",
                max_tokens=2000,
            ),
            _ai(
                "final_report",
                "Raport përfundimtar DD",
                "Mblidh të gjitha review-et e mëparshme në një raport "
                "executive: 5 flamuj të kuq kryesorë (severity 1-5, "
                "remedy), checklist veprimesh para closing-ut, "
                "kalkulim i ndikimit te price-adjustment.",
                tier="opus",
                max_tokens=4000,
            ),
        ],
    },
}


# ── Public helpers ─────────────────────────────────────────────────────

def list_definitions() -> list[dict]:
    """Library catalogue — short summaries for `/api/workflows`."""
    return [
        {
            "key": d["key"],
            "title": d["title"],
            "summary": d["summary"],
            "jurisdiction": d["jurisdiction"],
            "estimated_days": d["estimated_days"],
            "step_count": len(d["steps"]),
        }
        for d in DEFINITIONS.values()
    ]


def get_definition(key: str) -> dict | None:
    return DEFINITIONS.get(key)


def validate_custom(definition: dict) -> tuple[bool, str]:
    """Validate a user-supplied JSON DSL workflow.

    Returns (ok, error_message). On ok=True, message is empty.
    """
    if not isinstance(definition, dict):
        return False, "definition_not_object"
    for field in ("key", "title", "steps"):
        if field not in definition:
            return False, f"missing_{field}"
    steps = definition["steps"]
    if not isinstance(steps, list) or not steps:
        return False, "steps_must_be_nonempty_list"
    seen_ids: set[str] = set()
    valid_kinds = {"ai_call", "manual", "document_request",
                   "deadline_calc", "checklist"}
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            return False, f"step_{i}_not_object"
        for field in ("id", "title", "kind"):
            if field not in st:
                return False, f"step_{i}_missing_{field}"
        if st["kind"] not in valid_kinds:
            return False, f"step_{i}_unknown_kind:{st['kind']}"
        if st["id"] in seen_ids:
            return False, f"step_{i}_duplicate_id:{st['id']}"
        seen_ids.add(st["id"])
    return True, ""


def step_summary(step: dict) -> dict:
    """Project a step to the shape returned by the API to the UI."""
    return {
        "id": step["id"],
        "title": step["title"],
        "kind": step["kind"],
        "description": step.get("description", ""),
        "blocking": step.get("blocking", True),
        "params": step.get("params", {}),
    }
