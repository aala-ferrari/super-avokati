# -*- coding: utf-8 -*-
"""Le etichette renderizzate come "icona + testo" o prese da MAPPE hardcoded
sfuggono al dizionario (il nodo di testo contiene anche l'icona). Le trova
tutte, cosi si traducono ALLA FONTE."""
import re, io

A = "/var/www/apps/super-avvocato/static/app.js"
js = io.open(A, encoding="utf-8").read()

AL = re.compile(r"[ëçËÇ]|\b(?:i lart|mesatar|i ul|nese|nëse|po\b|jo\b|kod|nene|"
                r"rast|afat|prov|gjykat|vendim|akte|klient|avokat|prokuror|noter|"
                r"seanc|takim|dorezim|tjeter|hapur|mbyllur|ruajtur|derguar|pritje|"
                r"aktiv|pezull|skaduar|urgjen|larte|ulet)\b", re.I)

print("=" * 66)
print("MAPPE DI ETICHETTE CON VALORI ALBANESI")
print("=" * 66)
found = 0
# const X = { key: "valore", ... }  su una o piu righe
for m in re.finditer(r"(const|let|var)\s+(\w*[Ll]abel\w*|\w*LABEL\w*|\w*Txt\w*|"
                     r"\w*Name\w*|\w*Map\w*)\s*=\s*\{([^}]{10,600})\}", js, re.S):
    body = m.group(3)
    vals = re.findall(r'["\']([^"\']{2,60})["\']', body)
    hits = [v for v in vals if AL.search(v)]
    if not hits:
        continue
    line = js.count("\n", 0, m.start()) + 1
    # gia condizionato su _CAL_IT?
    ctx = js[max(0, m.start() - 200):m.start() + 300]
    if "_CAL_IT" in ctx:
        continue
    found += 1
    print(f"\nL{line}: {m.group(2)}")
    for v in hits[:8]:
        print(f"    • {v!r}")

print(f"\n\ntotale mappe da tradurre: {found}")

print("\n" + "=" * 66)
print("TEMPLATE 'icona + etichetta' (il nodo include l'icona)")
print("=" * 66)
n2 = 0
for m in re.finditer(r"\$\{(\w+(?:\[[^\]]+\])?)\s*\|\|\s*[\"']([^\"']{2,40})[\"']\}", js):
    if AL.search(m.group(2)):
        line = js.count("\n", 0, m.start()) + 1
        ctx = js[max(0, m.start() - 160):m.start()]
        if "_CAL_IT" in ctx:
            continue
        n2 += 1
        print(f"  L{line}: ${{{m.group(1)} || {m.group(2)!r}}}")
print(f"\ntotale: {n2}")
