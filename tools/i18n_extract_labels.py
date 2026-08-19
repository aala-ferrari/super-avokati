# -*- coding: utf-8 -*-
"""Estrae TUTTE le etichette UI strutturali SENZA indovinare la lingua.
Il filtro per parole albanesi aveva un buco: stringhe come "Lexo & mbush" o
"Ispektor i aktit" non hanno diacritici ne parole della lista, quindi
sfuggivano. Qui si prende tutto e si lascia decidere al traduttore."""
import re, io, json, html as H

h = io.open("/var/www/apps/super-avvocato/templates/index.html", encoding="utf-8").read()
js = io.open("/var/www/apps/super-avvocato/static/app.js", encoding="utf-8").read()

def unesc(raw):
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), raw)
    return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace") \
            .replace("\\'", "'").replace('\\"', '"')

T = set()
for m in re.finditer(r'"((?:[^"\\\n]|\\.)+)"\s*:\s*"', js):
    T.add(unesc(m.group(1)))
I18N_KEYS = set(re.findall(r'data-i18n(?:-ph)?="([\w_]+)"', h))

out = set()

def add(s):
    s = re.sub(r"[ \t]+", " ", H.unescape(s)).strip()
    if 2 < len(s) < 300 and s not in T and not re.fullmatch(r"[\W\d\s]+", s):
        out.add(s)

# menu PRO: titoli, descrizioni, divider (TUTTI)
for m in re.finditer(r'<div><strong>(.*?)</strong><em>(.*?)</em></div>', h, re.S):
    add(re.sub(r"<[^>]+>", "", m.group(1)))
    add(re.sub(r"<[^>]+>", "", m.group(2)))
for m in re.finditer(r'<div class="pro-menu-divider"[^>]*>(.*?)</div>', h, re.S):
    add(re.sub(r"<[^>]+>", "", m.group(1)))
# altre etichette strutturali del template: h3/h4/h5/summary/legend/button/label/th
for tag in ("h3", "h4", "h5", "h6", "summary", "legend", "th", "label", "button", "option"):
    for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", h, re.S | re.I):
        inner = m.group(1)
        if "data-i18n" in inner or "{{" in inner or "{%" in inner:
            continue
        add(re.sub(r"<[^>]+>", " ", inner))
# span/div con classi da UI (titoli sezione, chip, badge)
for m in re.finditer(r'<span class="(?:suggest-title|pro-menu-ico|chip|badge|kind|db-title)[^"]*"[^>]*>(.*?)</span>', h, re.S):
    add(re.sub(r"<[^>]+>", " ", m.group(1)))
# app.js: stessi contenitori dentro le stringhe generate
for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', js):
    raw = m.group(1) or m.group(2) or ""
    if len(raw) < 3 or "${" in raw:
        continue
    s = unesc(raw)
    for mm in re.finditer(r'<(?:span|div|h\d|button|summary|b|strong|em|li|td|th)[^>]*>([^<]{3,200})</', s):
        add(mm.group(1))

res = sorted(x for x in out if x not in I18N_KEYS)
print(f"ETICHETTE DA VALUTARE: {len(res)}")
io.open("/tmp/labels_todo.json", "w", encoding="utf-8", errors="replace").write(
    json.dumps(res, ensure_ascii=False, indent=1))
for s in res[:20]:
    print("  •", s[:100])
