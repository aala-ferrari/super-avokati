# v9.648 — uso: bash tools/prova_pro.sh <nome> tools/diag_prompt_chat_it.py [immagine] [cartella_src]  (log in /tmp/pp_<nome>/out)
# diagnosi LINGUA = SESSIONE al livello dei PROMPT: ogni testo che il cervello riceve in una domanda italiana (percorso semplice,
# cervello vero), registrato dopo il collo di bottiglia del backend; poi le parole albanesi per chiamata, col contesto.
import sys, re, json, threading, collections
sys.path.insert(0, "/app")
from src import web, brain, backends
web._ensure_loaded()
_TL = threading.local()
LOG = []
_orig_aj, _orig_dg = backends._apply_juris, backends._direttiva_gjuhe
def _aj(system):
    out = _orig_aj(system)
    LOG.append((getattr(_TL, "cs", None) or "?", "system", out or ""))
    return out
def _dg(prompt):
    out = _orig_dg(prompt)
    LOG.append((getattr(_TL, "cs", None) or "?", "user", out or ""))
    return out
backends._apply_juris, backends._direttiva_gjuhe = _aj, _dg
for nome in ("complete", "complete_stream"):
    orig = getattr(backends.ClaudeCodeBackend, nome)
    def _wrap(self, *a, __orig=orig, **kw):
        _TL.cs = kw.get("callsite") or __orig.__name__
        return __orig(self, *a, **kw)
    setattr(backends.ClaudeCodeBackend, nome, _wrap)
brain.set_request_jurisdiction("IT")
domanda = ("Il nostro cliente, assunto a tempo indeterminato nel 2019, non si presenta al lavoro dal 3 ottobre; la società dice che si è "
           "dimesso per fatti concludenti dopo 15 giorni di assenza. Le dimissioni sono valide senza il modulo telematico?")
fine = None
for kind, payload in web._BRAIN.answer_stream(domanda, history=[], jurisdiction="IT"):
    if kind == "final":
        fine = payload
    elif kind == "error":
        print("ERRORE", payload)
testo = getattr(fine, "text", "") or ""
ALB = re.compile(r"\b(të|dhe|është|për|nga|një|kjo|nuk|neni|nenit|nenet|Kodi|Kodit|ligji|ligjit|gjykat\w*|vendim\w*|përgjigj\w*|fjal\w*|rregull\w*|lexoje|kërk\w*|shqip\w*)\b", re.I)
per = collections.defaultdict(list)
for cs, k, t in LOG:
    per[(cs, k)].append(t)
print(f"chiamate registrate: {len(LOG)} · risposta {len(testo)} car., parole albanesi nella risposta {len(ALB.findall(testo))}")
for (cs, k), testi in per.items():
    hits = [m for t in testi for m in re.finditer(ALB, t)]
    print(f"== {cs} [{k}] ×{len(testi)}: parole albanesi {len(hits)}")
    visti = set()
    for t in testi:
        for m in re.finditer(ALB, t):
            a = max(0, m.start() - 60)
            frase = t[a:m.end() + 60].replace("\n", " ⏎ ")
            chiave = frase[:40]
            if chiave in visti:
                continue
            visti.add(chiave)
            print("   …" + frase + "…")
            if len(visti) >= 8:
                break
json.dump([[cs, k, t] for cs, k, t in LOG], open("/out/prompt_log.json", "w"), ensure_ascii=False)
open("/out/risposta.txt", "w").write(testo)
