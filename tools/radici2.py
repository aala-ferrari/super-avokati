import sys; sys.path.insert(0, "/app")
from src import brain as B
SOSP = {"AL": ["ashk", "blej", "dal", "dehur", "ditë", "dore", "dorë", "drejt", "firm", "form", "hua", "kufi", "lënë", "mbaj", "mjet", "mur", "ndar", "pag", "pagu", "para", "pun", "shoh", "vit", "vite", "vjeç"],
        "IT": ["anni", "bando", "debit", "esclu", "isol", "orale", "prova", "tar", "vend"]}
for lang, anc in (("AL", B.ANCORE_AL), ("IT", B.ANCORE_IT)):
    for v in anc:
        for p in v[0]:
            els = p if isinstance(p, tuple) else (p,)
            hit = [x for x in els if x.strip() in SOSP[lang]]
            if hit:
                arts = ", ".join(f"{c} {n}" for c, n in v[2])[:60]
                print(f"{lang} {hit} in {els} → {arts} | solo domanda: {len(v) > 5 and bool(v[5])}")
