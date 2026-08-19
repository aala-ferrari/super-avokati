# -*- coding: utf-8 -*-
"""VERIFICA FINALE: pagina servita in sessione IT — nodi di testo E attributi
visibili — simulando il traduttore col dizionario reale."""
import json, re, io, html as H, urllib.request, http.cookiejar

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open(urllib.request.Request("http://127.0.0.1:5050/api/login",
        data=json.dumps({"username": "admin.it", "password": "AdminIT2026!",
                         "lang": "it"}).encode(),
        headers={"Content-Type": "application/json"}), timeout=30)
page = op.open("http://127.0.0.1:5050/", timeout=30).read().decode("utf-8", "replace")

js = io.open("/var/www/apps/super-avvocato/static/app.js", encoding="utf-8").read()
T = set()
for m in re.finditer(r'"((?:[^"\\\n]|\\.)+)"\s*:\s*"', js):
    k = re.sub(r"\\u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), m.group(1))
    T.add(k.replace("\\'", "'").replace('\\"', '"'))
# chiavi statiche I18N_IT (applyStaticI18n)
static_keys = set(re.findall(r'data-i18n(?:-ph)?="([\w_]+)"', page))

AL = re.compile(r"[ëçËÇ]|\b(rast|raste|nene|neni|kliko|shkruaj|kujtes|afat|afatet|"
                r"gjyqtar|korpus|mjete|bised|ngjarje|majtas|vendime|perdor|zgjidh|"
                r"ruaj|fashikull|klient|avokat|prokuror|noter|kerko|shto|fshi|mbyll|"
                r"hapur|nuk|eshte|jane|shqip|provat|ceshtje|pyet|harto|pamja|krijuar)\b", re.I)

body = page[page.find("<body"):]
clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)

# 1) nodi di testo
txt = []
for chunk in re.split(r"<[^>]*>", clean):
    s = re.sub(r"[ \t]+", " ", H.unescape(chunk).replace("\xa0", " ")).strip()
    if len(s) >= 3 and AL.search(s) and s not in T:
        txt.append(s)

# 2) attributi visibili (esclusi quelli con data-i18n sullo stesso tag)
attrs = []
for m in re.finditer(r"<[^>]+>", clean):
    tag = m.group(0)
    if "data-i18n" in tag:
        continue
    for am in re.finditer(r'\b(title|aria-label|placeholder|alt)="([^"]{3,300})"', tag):
        v = H.unescape(am.group(2)).strip()
        if AL.search(v) and v not in T:
            attrs.append(f"[{am.group(1)}] {v}")

def uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

txt, attrs = uniq(txt), uniq(attrs)
print("=" * 64)
print(f"RESIDUI — testo: {len(txt)} | attributi: {len(attrs)}")
print("=" * 64)
for s in txt:
    print("  TESTO •", s[:110])
for s in attrs:
    print("  ATTR  •", s[:110])
