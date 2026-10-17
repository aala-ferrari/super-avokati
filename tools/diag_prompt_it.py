# v9.648 — uso: bash tools/prova_pro.sh <nome> tools/diag_prompt_it.py [immagine] [cartella_src]  (prompt in /tmp/pp_<nome>/out)
# diagnosi: il prompt VERO che la lente kill_shot riceve in un fascicolo IT (dopo il collo di bottiglia del backend) — c'è albanese?
import sys, re, json
sys.path.insert(0, "/app")
from src import web, brain, genio, backends
web._ensure_loaded()
brain.set_request_jurisdiction("IT")
fatti = ("Il nostro cliente Mario Prova, autista assunto a tempo indeterminato nel 2019 da «Trasporti Esempio» s.r.l. (40 dipendenti), "
         "è stato licenziato oralmente il 2.10.2026 («non venire più domani»), senza lettera. La retribuzione di settembre non è stata "
         "pagata. La società sostiene che il lavoratore si è dimesso. Vogliamo la nullità del licenziamento orale, la reintegrazione e "
         "le retribuzioni. Come vinciamo?")
blocco_art, codici = web._nene_per_genio(fatti, "", None, "IT", web._INDEX_IT)
class C: title, stage = "Licenziamento orale — Mario Prova", "intake"
cb = genio.build_case_block(C(), jurisdiction="IT", recent_messages=[{"role": "user", "content": fatti}], articles_block=blocco_art)
p = next(x for x in genio.PERSPECTIVES if x.key == "kill_shot")
_sys, _ut = genio._testi_lente(p, cb)
system = genio._direttiva_gjuhe(cb) + genio._guard(cb) + _sys
user = genio._adatta_schema(_ut.format(case_block=cb, voice_samples_block=""), cb)
system_f = backends._apply_juris(system)
user_f = backends._direttiva_gjuhe(user)
ALB = re.compile(r"\b(të|dhe|është|për|nga|një|kjo|nuk|neni|nenit|Kodi|Kodit|ligji|ligjit|shqip\w*|gjykat\w*|vendim\w*)\b", re.I)
def mostra(nome, t):
    hits = ALB.findall(t)
    print(f"== {nome}: {len(t)} car., parole albanesi {len(hits)}")
    for m in list(re.finditer(ALB, t))[:25]:
        a = max(0, m.start() - 70); print("   …" + t[a:m.end() + 50].replace("\n", " ⏎ ") + "…")
mostra("SYSTEM finale", system_f)
mostra("USER finale", user_f)
open("/out/kill_shot_system.txt", "w").write(system_f)
open("/out/kill_shot_user.txt", "w").write(user_f)
