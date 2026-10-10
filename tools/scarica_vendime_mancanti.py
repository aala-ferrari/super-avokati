#!/usr/bin/env python3
"""v9.583 — scarica in una cartella di PROVA le decisioni albanesi pubblicate e non ancora nel corpus: le sentenze finali della
Kushtetuese (pagina «vendime-perfundimtare-<anno>») e i vendime della Gjykata e Lartë nell'archivio pubblico (Strapi GraphQL,
file su S3) — la stessa logica del controllo quotidiano `ops/decisions-watch.py`, che li segnala per email. Nessun ingest:

    python3 tools/scarica_vendime_mancanti.py /tmp/raw_nuovi [anni…]          # sull'HOST (stdlib), anni = corrente e precedente
    docker run … -e RAW_DIR=/raw -v /tmp/raw_nuovi:/raw:ro … tools/reparse_vendime.py probe   # verifica uno per uno, non scrive
    … reparse_vendime.py run con OUT_JSONL/OUT_PKL su COPIE → build_case_graph.py (INDEX_PATH) → build_dense.py --only dec --force
    (INDEX_PATH, EMB_DIR) → misura (tools/eval_precedenti.py) → installazione con backup → riavvio guardato o rilascio

I file scaricati restano con lo stesso percorso relativo (kushtetuese/2026/vend_0082_2026.pdf, gjykata_elarte/2026/00-2026-541.docx):
`source_file` nel JSONL coincide con quello che avranno nella cartella vera."""
import json, os, re, sys, time, urllib.request, urllib.parse
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
RAW = "/var/www/apps/super-avvocato/data/raw/jurisprudence"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/raw_nuovi"
_oggi = time.localtime().tm_year
anni = [int(a) for a in sys.argv[2:]] or [_oggi - 1, _oggi]

def get(url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=dict({"User-Agent": UA}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")

def salva(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    print(f"  ✓ {path} ({len(blob)} B)", flush=True)

# 1) Kushtetuese
for y in anni:
    t = get(f"https://www.gjykatakushtetuese.gov.al/vendime-perfundimtare-{y}/")[0].decode("utf-8", "replace")
    d = os.path.join(RAW, "kushtetuese", str(y))
    noi = {int(x.group(1)) for f in (os.listdir(d) if os.path.isdir(d) else []) for x in [re.match(r"vend_0*(\d+)_", f)] if x}
    for m in re.finditer(r'(?is)<a[^>]+href="([^"]+uploads[^"]+)"[^>]*>(.*?)</a>', t):
        lab = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2)))
        mm = re.search(r"Nr\.?\s*:?\s*(\d{1,3})\b.*?Dat", lab, re.I)
        if not mm or int(mm.group(1)) in noi:
            continue
        n = int(mm.group(1)); url = m.group(1)
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or ".pdf"
        print(f"GJK {y} nr {n}: {lab[:90]} ← {url}", flush=True)
        blob, _ = get(url)
        salva(os.path.join(OUT, "kushtetuese", str(y), f"vend_{n:04d}_{y}{ext}"), blob)
        noi.add(n); time.sleep(1)

# 2) Gjykata e Lartë
q = json.dumps({"query": '{ files(limit: -1) { name ext url } }'}).encode()
files = json.loads(get("https://panel.gjykataelarte.gov.al/graphql", data=q, headers={"Content-Type": "application/json"}, timeout=180)[0])["data"]["files"]
num = re.compile(r"00\s*[-–_]\s*(20\d\d)\s*[-–_]\s*(\d{1,5})")
noi = set()
for root, _d, fs in os.walk(os.path.join(RAW, "gjykata_elarte")):
    for f in fs:
        for y, n in num.findall(f):
            noi.add(f"00-{y}-{int(n)}")
fatti = set()
for f in files:
    ext = (f.get("ext") or "").lower()
    if ext not in (".doc", ".docx", ".pdf"):
        continue
    for y, n in num.findall(f.get("name") or ""):
        k = f"00-{y}-{int(n)}"
        if int(y) not in anni or k in noi or k in fatti:
            continue
        url = f.get("url") or ""
        if url.startswith("/"):
            url = "https://panel.gjykataelarte.gov.al" + url
        print(f"GjL {k}: {f.get('name')} ← {url}", flush=True)
        try:
            blob, _ = get(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {k}: {exc}", flush=True); continue
        salva(os.path.join(OUT, "gjykata_elarte", y, f"{k}{ext}"), blob)
        fatti.add(k); time.sleep(1)
print("fatto:", len(fatti), "GjL")
