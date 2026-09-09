# -*- coding: utf-8 -*-
"""GUARDIA GIURISDIZIONE — impedisce il ritorno del bug "risponde in albanese".

Storia: 41 chiamate al cervello sparse in 15 moduli non applicavano la
giurisdizione della sessione, quindi in sessione IT notaio, perizie, intake,
scadenze e segretaria rispondevano in albanese con diritto albanese. Il fix
non e' stato rattoppare i 41 punti, ma applicare il vincolo dentro
backends.complete() — il collo di bottiglia da cui passa OGNI chiamata.

Questa guardia verifica le tre proprieta' da cui dipende il fix:
  1. ogni metodo complete()/complete_stream() concreto applica _apply_juris
  2. apply_jurisdiction e' IDEMPOTENTE (chi la applica gia' a mano non
     ottiene il vincolo due volte)
  3. la giurisdizione della richiesta arriva davvero ai moduli

Da rilanciare dopo ogni modifica a backends.py / brain.py / auth.py."""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

fails: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {GREEN + '✓' + RESET if ok else RED + '✗' + RESET} {label}")
    if not ok:
        fails.append(label)


# ── 1. ogni complete() concreto applica la giurisdizione ─────────────────
print("\n== 1. il collo di bottiglia copre tutte le chiamate ==")
src = io.open(os.path.join(SRC, "backends.py"), encoding="utf-8").read()
lines = src.split("\n")
SIG = re.compile(r"^    def (complete|complete_stream)\s*\(")
concrete = 0
for i, ln in enumerate(lines):
    if not SIG.match(ln):
        continue
    body = "\n".join(lines[i:i + 60])
    if "@abstractmethod" in "\n".join(lines[max(0, i - 3):i]):
        continue                      # la firma astratta non ha corpo
    if "raise NotImplementedError" in body[:400]:
        continue
    concrete += 1
    name = ln.strip()[4:].split("(")[0]
    check("_apply_juris(system)" in body,
          f"riga {i+1}: {name}() applica la giurisdizione")
check(concrete >= 4, f"metodi concreti trovati: {concrete} (attesi >= 4)")

# ── 2. apply_jurisdiction idempotente ────────────────────────────────────
print("\n== 2. applicare due volte non raddoppia il vincolo ==")
sys.path.insert(0, ROOT)
from src import brain  # noqa: E402

BASE = "Ti je avokat. Pergjigju sipas Kodit Civil."
for code in ("IT", "EU"):
    once = brain.apply_jurisdiction(BASE, code)
    twice = brain.apply_jurisdiction(once, code)
    check(once == twice, f"{code}: apply_jurisdiction e' idempotente")
    mark = (brain.JURISDICTION_OVERRIDE_IT if code == "IT"
            else brain.JURISDICTION_OVERRIDE_EU)
    check(once.count(mark) == 1, f"{code}: l'istruzione finale compare una volta sola")
    check(len(once) > len(BASE), f"{code}: il vincolo viene effettivamente aggiunto")
al = brain.apply_jurisdiction(BASE, "AL")
check(al == BASE, "AL: prompt invariato (i prompt sono gia' albanesi)")

# ── 3. la giurisdizione della richiesta raggiunge i moduli ───────────────
print("\n== 3. la sessione IT arriva fino al prompt ==")
brain.set_request_jurisdiction("IT")
check(brain.request_jurisdiction() == "IT", "request_jurisdiction() legge IT")
out = brain.apply_current(BASE)
check("ITALIAN" in out.upper(), "apply_current() adatta il prompt alla sessione")

from src import backends as _bk  # noqa: E402
check(_bk._apply_juris(BASE) == out,
      "backends._apply_juris() applica lo stesso vincolo di apply_current()")
brain.set_request_jurisdiction("AL")
check(_bk._apply_juris(BASE) == BASE, "tornando ad AL il prompt resta intatto")

# ── 4. la LINGUA della sessione arriva nel messaggio utente ──────────────
# (9 set 2026) «sessione albanese → solo albanese, italiana → solo italiano»:
# il vincolo nel system prompt non bastava (premortem albanese in un
# fascicolo IT quando la domanda era in albanese). La riga va in coda al
# messaggio utente, dal collo di bottiglia, per tutte le chiamate.
print("\n== 4. la lingua della sessione viaggia nel messaggio utente ==")
_al = brain.direttiva_gjuhe_prompt("Pyetja ime", "AL")
_it = brain.direttiva_gjuhe_prompt("La mia domanda", "IT")
check(_al.endswith(brain.DIRETTIVA_GJUHE["AL"]) and "VETËM SHQIP" in _al,
      "AL: la riga «VETËM SHQIP» e' in coda al messaggio")
check(_it.endswith(brain.DIRETTIVA_GJUHE["IT"]) and "SOLO ITALIANO" in _it,
      "IT: la riga «SOLO ITALIANO» e' in coda al messaggio")
check(brain.direttiva_gjuhe_prompt(_it, "IT") == _it, "IT: idempotente (applicare due volte = una)")
check(brain.direttiva_gjuhe_prompt("", "IT") == "", "un prompt vuoto resta vuoto")
check("anche se la domanda" in brain.JURISDICTION_OVERRIDE_IT.lower()
      or "ANCHE SE la domanda" in brain.JURISDICTION_OVERRIDE_IT,
      "IT: l'istruzione finale copre la domanda scritta in albanese")
_bsrc = io.open(os.path.join(SRC, "backends.py"), encoding="utf-8").read()
check(_bsrc.count("prompt = _direttiva_gjuhe(prompt)") == 2,
      "backends: complete() e complete_stream() accodano la riga di lingua")
check("if not raw_system:\n            prompt = _direttiva_gjuhe(prompt)" in _bsrc,
      "backends: raw_system (Përkthim) salta la riga — tradurre e' cambiare lingua")
brain.set_request_jurisdiction("IT")
check(_bk._direttiva_gjuhe("x").endswith(brain.DIRETTIVA_GJUHE["IT"]),
      "backends._direttiva_gjuhe() legge la giurisdizione della richiesta")
brain.set_request_jurisdiction("AL")
check(_bk._direttiva_gjuhe("x").endswith(brain.DIRETTIVA_GJUHE["AL"]),
      "tornando ad AL la riga torna albanese")

# ── esito ────────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
if fails:
    print(f"{RED}== {len(fails)} CONTROLLI FALLITI =={RESET}")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print(f"{GREEN}== TUTTO VERDE — la giurisdizione non puo' sfuggire =={RESET}")
