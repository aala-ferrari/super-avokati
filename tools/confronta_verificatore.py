# v9.646 — CONFRONTO del verificatore delle citazioni, vecchio contro nuovo, sulle risposte VERE salvate (sola lettura del DB).
# uso (container di prova con il codice nuovo montato su /app/src e il vecchio copiato in /tmp/cv_vecchio.py):
#   python3 tools/confronta_verificatore.py /tmp/cv_vecchio.py [giorni=120] [AL|IT|tutte]
# Per ogni citazione che cambia stato o codice stampa la riga del vecchio e del nuovo: si leggono tutte prima di rilasciare
# (un verificatore nuovo può togliere un «senza codice» o un «falso», mai crearne uno su una citazione giusta).
import sys, sqlite3, os, collections, importlib.util, datetime
sys.path.insert(0, "/app")
from pathlib import Path
import src
from src import citation_verifier as nuovo
from src.retrieval import ArticleIndex

vecchio_path = sys.argv[1]
giorni = int(sys.argv[2]) if len(sys.argv) > 2 else 120
quali = (sys.argv[3] if len(sys.argv) > 3 else "tutte").upper()
spec = importlib.util.spec_from_file_location("src.citation_verifier_vecchio", vecchio_path)
vecchio = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vecchio
spec.loader.exec_module(vecchio)

idx_al = ArticleIndex.load()
idx_it = ArticleIndex.load(Path("/app/data/index/bm25_it.pkl"))
for m in (nuovo, vecchio):
    try:
        m.registra_indici(al=idx_al, it=idx_it)
    except Exception:  # noqa: BLE001
        pass

db = os.environ.get("APP_DB_PATH", "/app/data/app.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
dal = (datetime.datetime.utcnow() - datetime.timedelta(days=giorni)).strftime("%Y-%m-%d")
rows = con.execute("SELECT m.id, m.content, COALESCE(c.jurisdiction,'AL') FROM messages m JOIN cases c ON c.id = m.case_id "
                   "WHERE m.role='assistant' AND m.created_at >= ? AND length(m.content) > 400 ORDER BY m.id", (dal,)).fetchall()
tot = {"vecchio": collections.Counter(), "nuovo": collections.Counter()}
cambi = []
n = 0
for mid, testo, giur in rows:
    giur = (giur or "AL").upper()
    if quali in ("AL", "IT") and giur != quali:
        continue
    idx = idx_it if giur == "IT" else idx_al
    n += 1
    out = {}
    for nome, mod in (("vecchio", vecchio), ("nuovo", nuovo)):
        try:
            r = mod.verify_text(testo, idx)
        except Exception as e:  # noqa: BLE001
            r = {"items": [], "stats": {}}
            print("ERRORE", nome, mid, type(e).__name__, e)
        for k, v in (r.get("stats") or {}).items():
            if isinstance(v, int):
                tot[nome][k] += v
        out[nome] = collections.Counter((it.get("raw"), it.get("status"), it.get("code")) for it in r.get("items", []))
    solo_v = out["vecchio"] - out["nuovo"]
    solo_n = out["nuovo"] - out["vecchio"]
    if solo_v or solo_n:
        cambi.append((mid, giur, sorted(solo_v.elements()), sorted(solo_n.elements())))

print(f"risposte {n} ({quali}, ultimi {giorni} giorni)")
for k in ("verified", "needs_code", "fake", "repealed", "stale", "foreign_verified", "foreign_unverified"):
    print(f"  {k:20s} vecchio {tot['vecchio'][k]:5d}   nuovo {tot['nuovo'][k]:5d}")
print(f"risposte cambiate: {len(cambi)}")
for mid, giur, sv, sn in cambi[:80]:
    print(f"--- messaggio {mid} [{giur}]")
    for x in sv:
        print("   - vecchio:", x)
    for x in sn:
        print("   + nuovo:  ", x)
