#!/usr/bin/env python3
"""12 ott 2026 — controllo della landing (landing/index.html) PRIMA di pubblicarla: vive fuori dal container (nginx la serve
da /var/www/superavokati-landing) e il golden non la vede.

Controlla: il JSON-LD si legge; gli script si compilano (node --check); le tre lingue hanno le stesse chiavi e ogni chiave
del markup c'è in tutte; la SOCIETÀ della lingua (albanese → Albania Auto Legal Alliance sh.p.k., NIPT M61628011J,
+355 69 955 5777; italiano e inglese → Deltalux Srl, P.IVA 12021700963, +39 380 635 8654) e mai quella dell'altro mercato
nella stessa riga; la lingua iniziale (scelta del visitatore > vecchia scelta it/en > paese dall'IP di nginx > browser >
albanese) su 10 casi con un browser finto. Esce 1 se qualcosa non torna.

Uso:  python3 tools/verifica_landing.py [landing/index.html]
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

CASI = [  # (localStorage, data-paese, lingua del browser, attesa)
    ({}, "IT", "sq-AL", "it"), ({}, "AL", "it-IT", "sq"), ({}, "", "it-IT", "it"), ({}, "", "en-GB", "en"),
    ({}, "", "de-DE", "sq"), ({"sa_lang": "sq"}, "IT", "it", "it"), ({"sa_lang": "it"}, "AL", "sq", "it"),
    ({"sa_lang_scelta": "sq"}, "IT", "it", "sq"), ({"sa_lang_scelta": "en"}, "AL", "sq", "en"), ({}, None, "", "sq"),
]
SOCIETA = {
    "sq": (["Albania Auto Legal Alliance sh.p.k.", "M61628011J", "+355 69 955 5777"], ["Deltalux", "12021700963"]),
    "it": (["Deltalux Srl", "12021700963", "+39 380 635 8654"], ["M61628011J"]),
    "en": (["Deltalux Srl", "12021700963", "+39 380 635 8654"], ["M61628011J"]),
}


def main(argv):
    f = pathlib.Path(argv[0] if argv else "landing/index.html")
    s = f.read_text(encoding="utf-8")
    errori = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', s, re.S):
        try:
            json.loads(m.group(1))
        except ValueError as e:
            errori.append(f"JSON-LD: {e}")
    tmp = pathlib.Path(tempfile.mkdtemp())
    for i, m in enumerate(re.finditer(r'<script(?![^>]*ld\+json)[^>]*>(.*?)</script>', s, re.S)):
        p = tmp / f"s{i}.js"
        p.write_text(m.group(1), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
        if r.returncode:
            errori.append(f"script {i}: {r.stderr[:200]}")
    i = s.index("const I18N = {")
    j = s.index("\nfunction setLang", i)
    obj = s[i:j]
    k = s.index("function linguaIniziale(){")
    e = s.index("setLang(linguaIniziale(),false);", k)
    fn = s[k:e].replace("navigator.languages", "NAV.languages").replace("navigator.language", "NAV.language")
    markup = sorted(set(re.findall(r'data-i18n(?:-html|-ph)?="([^"]+)"', s)))
    js = obj + "\n" + fn + "\n" + """
const out={chiavi:{},markup:{},soc:{},casi:[]};
const L=['sq','it','en'], base=Object.keys(I18N.sq).sort().join('|');
for(const l of L){out.chiavi[l]=Object.keys(I18N[l]).sort().join('|')===base;
  out.markup[l]=MARKUP.filter(x=>!(x in I18N[l]));
  out.soc[l]=[I18N[l].foot_soc||'', I18N[l].foot_tel||'', I18N[l].foot_prop||''];}
for(const [st,p,n,att] of CASI){
  global.localStorage={getItem:k=>(k in st?st[k]:null)};
  global.document={documentElement:{getAttribute:()=>p}};
  global.NAV={languages:[n],language:n};
  out.casi.push([JSON.stringify(st),p,n,linguaIniziale(),att]);}
console.log(JSON.stringify(out));
""".replace("MARKUP", json.dumps(markup)).replace("CASI", json.dumps(CASI))
    p = tmp / "prova.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True)
    if r.returncode:
        errori.append("prova: " + r.stderr[:300])
        out = {"chiavi": {}, "markup": {}, "soc": {}, "casi": []}
    else:
        out = json.loads(r.stdout)
    for l, ok in out["chiavi"].items():
        if not ok:
            errori.append(f"chiavi diverse in «{l}»")
    for l, mancano in out["markup"].items():
        if mancano:
            errori.append(f"«{l}» senza: {', '.join(mancano)}")
    for l, (devono, vietate) in SOCIETA.items():
        soc, tel, prop = out["soc"].get(l, ["", "", ""])
        for x in devono:
            if x not in soc + tel:
                errori.append(f"«{l}»: manca {x}")
        for x in vietate:
            if x in soc + tel + prop:
                errori.append(f"«{l}»: c'è {x} (l'altro mercato)")
    giusti = 0
    for st, p_, n, ris, att in out["casi"]:
        if ris == att:
            giusti += 1
        else:
            errori.append(f"lingua {st} {p_} {n}: {ris}, attesa {att}")
    print(f"casi della lingua {giusti}/{len(CASI)} · chiave del markup {len(markup)} · lingue allineate "
          f"{sum(1 for v in out['chiavi'].values() if v)}/3")
    for x in errori:
        print("✗", x)
    print("LANDING OK" if not errori else f"LANDING: {len(errori)} problemi")
    return 1 if errori else 0



if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
