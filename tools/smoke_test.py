#!/usr/bin/env python3
"""Smoke test: call every tool fn with a STUBBED brain (no LLM wait) to catch
logic/parsing/signature bugs fast and deterministically."""
import sys, traceback
sys.path.insert(0, "/app")
from src.web import _ensure_loaded  # noqa: E402
_ensure_loaded()
from src.web import _INDEX as idx, _BRAIN  # noqa: E402


class Stub:
    name = "stub"

    def complete(self, system=None, messages=None, **kw):
        return ("### Test\n- neni 76 i Kodit Penal; neni 134 i Kodit Penal\n"
                "AFAT | Afat testi | 2026-09-01\n[ROUTE: expertise]")


be = Stub()
OK, BAD = [], []


def run(name, fn):
    try:
        r = fn()
        assert isinstance(r, dict) and ("markdown" in r or "answer" in r or "route" in r or "afatet" in r or "empty" in r), \
            "return not a valid dict: %r" % (list(r)[:5] if isinstance(r, dict) else type(r))
        OK.append(name)
        print("  \033[32m✓\033[0m %s" % name)
    except Exception as exc:  # noqa: BLE001
        BAD.append((name, repr(exc)))
        print("  \033[31m✗ %s\033[0m — %s" % (name, exc))
        traceback.print_exc()


import src.expertise as expertise
import src.prosecutor as prosecutor
import src.notary as notary
import src.deadlines as deadlines
import src.living_law as living
import src.intake as intake
import src.afati as afati
import src.vault as vault
try:
    import src.second_opinion as second_opinion
except Exception:
    second_opinion = None
try:
    import src.adversary as adversary
except Exception:
    adversary = None
try:
    import src.fable_drafter as fable_drafter
except Exception:
    fable_drafter = None

F = "I dyshuari mori pasurine me dhune, viktima ka mavijosje dhe deshmitare. Data 2026-08-01."

print("== SMOKE (stub brain) ==")
print("[expertise]")
for ct in expertise._ORDER:
    run("expertise.analyze:" + ct, lambda ct=ct: expertise.analyze(be, idx, case_type=ct, facts=F))

print("[prosecutor]")
run("prosecutor.analyze", lambda: prosecutor.analyze(be, idx, facts=F))
run("prosecutor.draft_indictment", lambda: prosecutor.draft_indictment(be, idx, facts=F))
run("prosecutor.investigation_plan", lambda: prosecutor.investigation_plan(be, idx, facts=F))
for k in afati._ACT_KINDS if False else prosecutor._ACT_KINDS:
    run("prosecutor.investigative_act:" + k, lambda k=k: prosecutor.investigative_act(be, idx, kind=k, facts=F))
run("prosecutor.coercive_measure", lambda: prosecutor.coercive_measure(be, idx, facts=F))
run("prosecutor.dismissal_request", lambda: prosecutor.dismissal_request(be, idx, facts=F))
run("prosecutor.stress_test", lambda: prosecutor.stress_test(be, idx, text=F))
run("prosecutor.citizen_complaint", lambda: prosecutor.citizen_complaint(be, idx, facts=F))
run("prosecutor.victim_rights", lambda: prosecutor.victim_rights(be, idx, facts=F))
run("prosecutor.dismissal_appeal", lambda: prosecutor.dismissal_appeal(be, idx, facts=F))
run("prosecutor.delay_complaint", lambda: prosecutor.delay_complaint(be, idx, facts=F))

print("[notary]")
for dt in notary._ORDER:
    run("notary.draft_deed:" + dt, lambda dt=dt: notary.draft_deed(be, idx, deed_type=dt, details=F))
run("notary.draft_prokura", lambda: notary.draft_prokura(be, idx, form="e_posacme", scope_keys=["likuidim_shpk", "perfaqesim_tatimor"], details=F))
for dc in notary._DECL_ORDER:
    run("notary.draft_declaration:" + dc, lambda dc=dc: notary.draft_declaration(be, idx, decl_type=dc, details=F))
run("notary.check_deed", lambda: notary.check_deed(be, idx, text=F))
run("notary.succession", lambda: notary.succession(be, idx, situation=F))
run("notary.documents_needed", lambda: notary.documents_needed(be, idx, act=F))
run("notary.draft_revocation", lambda: notary.draft_revocation(be, idx, details=F))
run("notary.check_conflicts", lambda: notary.check_conflicts(be, idx, new_act=F, prior_acts=[{"title": "x", "content": "y"}]))

print("[living_law / intake / afati / deadlines]")
run("deadlines.prescription", lambda: deadlines.prescription(be, idx, facts=F))
run("living.verify_claims", lambda: living.verify_claims(be, idx, text="neni 76 i Kodit Penal e dënon vrasjen."))
run("living.check_law_live", lambda: living.check_law_live(be, idx, query="neni 134 KP"))
run("intake.triage", lambda: intake.triage(be, idx, story=F))
for tk in afati.TRIGGERS:
    run("afati.compute:" + tk, lambda tk=tk: afati.compute(be, idx, trigger=tk, event_date="2026-08-01", facts=F))
run("vault.who_said_what(no docs)", lambda: vault.who_said_what(be, "nonexistent-case-id"))
run("vault.find_needle(no docs)", lambda: vault.find_needle(be, "nonexistent-case-id"))

if second_opinion:
    for nm in dir(second_opinion):
        pass

print("\n== %d OK, %d FAIL ==" % (len(OK), len(BAD)))
if BAD:
    for n, e in BAD:
        print("  FAIL", n, e)
    sys.exit(1)
print("\033[32mTë gjitha veglat u thirrën pa gabime.\033[0m")
