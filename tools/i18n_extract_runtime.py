# -*- coding: utf-8 -*-
"""ESTRAZIONE DEFINITIVA delle stringhe che finiscono A SCHERMO dal JS,
SENZA filtro di lingua (i filtri per parole albanesi hanno gia lasciato
passare "Lexo & mbush", "AI po mendon…", "Po nis intake-n…").

Prende ogni stringa assegnata a textContent/innerHTML/placeholder/title, i
toast, confirm/alert, e i frammenti di testo dentro markup generato — poi
toglie quelle gia nel dizionario. Decide il traduttore cosa e albanese."""
import re, io, json, html as H

A = "/var/www/apps/super-avvocato/static/app.js"
js = io.open(A, encoding="utf-8").read()

def unesc(raw):
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), raw)
    s = s.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return (s.replace("\\n", "\n").replace("\\t", " ")
             .replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\"))

T = set()
for m in re.finditer(r'"((?:[^"\\\n]|\\.)+)"\s*:\s*"', js):
    T.add(unesc(m.group(1)))

out = set()

def add(s):
    s = re.sub(r"[ \t]+", " ", s).strip()
    if not (2 < len(s) < 300) or s in T:
        return
    if "${" in s or "{{" in s:
        return
    if re.fullmatch(r"[\W\d\s]+", s):
        return
    if re.fullmatch(r"[a-z0-9_\-]+", s):            # identificatori
        return
    if s.startswith(("/", "#", ".", "http")) or "://" in s:
        return
    if not re.search(r"[a-zA-ZëçËÇ]{2}", s):
        return
    # scarta il codice puro
    if re.search(r"[<>]{1}[a-z]+ |function\s*\(|=>|querySelector|document\.", s):
        return
    out.add(s)

# 1) assegnazioni dirette a proprieta visibili
for prop in ("textContent", "innerHTML", "innerText", "placeholder", "title",
             "ariaLabel", "value"):
    for m in re.finditer(rf'\.{prop}\s*=\s*"((?:[^"\\\n]|\\.)*)"', js):
        add(unesc(m.group(1)))
    for m in re.finditer(rf"\.{prop}\s*=\s*'((?:[^'\\\n]|\\.)*)'", js):
        add(unesc(m.group(1)))

# 2) toast / alert / confirm / prompt
for fn in ("toast", "alert", "confirm", "prompt"):
    for m in re.finditer(rf'\b{fn}\(\s*"((?:[^"\\\n]|\\.)*)"', js):
        add(unesc(m.group(1)))
    for m in re.finditer(rf"\b{fn}\(\s*'((?:[^'\\\n]|\\.)*)'", js):
        add(unesc(m.group(1)))

# 3) frammenti di testo dentro markup generato (stringhe con tag)
for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', js):
    raw = m.group(1) or m.group(2) or ""
    if "<" not in raw or len(raw) < 8:
        continue
    s = unesc(raw)
    for frag in re.split(r"<[^>]*>", s):
        frag = H.unescape(frag)
        if frag.strip():
            add(frag)

# 4) proprieta di configurazione dei tool (sub/placeholder/btn/loading/label/title)
for key in ("sub", "placeholder", "btn", "loading", "label", "title", "saveTitle",
            "hint", "desc", "empty"):
    for m in re.finditer(rf'\b{key}\s*:\s*"((?:[^"\\\n]|\\.)*)"', js):
        add(unesc(m.group(1)))

res = sorted(out)
print(f"STRINGHE A SCHERMO NON NEL DIZIONARIO: {len(res)}")
io.open("/tmp/runtime_todo.json", "w", encoding="utf-8", errors="replace").write(
    json.dumps(res, ensure_ascii=False, indent=1))
for s in res[:25]:
    print("  •", s[:100])
