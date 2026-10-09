"""v9.570 — NOTE A PIÈ DI PAGINA DENTRO IL TESTO dei nene AL: il PDF QBZ stampa le note in fondo alla pagina e l'estrazione le lascia
in mezzo all'articolo, spesso a metà frase («…rrymat e trafikut nuk ⏎ 1 Shfuqizuar fjala “komunë” me ligjin nr.175/2014 ⏎
ndërpriten ndërmjet tyre», Kodi Rrugor 3). 25 nene (consumatori 13, Kodi Rrugor 6, …), alcune con informazioni vere — la Corte
costituzionale che annulla una lettera dell'art. 52 della legge urbanistica, una norma transitoria della legge 56/2024 — che NON si
buttano: la nota esce dal corpo e va nel campo `note` («[n] …»), il testo si ricongiunge. Una nota comincia con «N » + una parola
da nota (Shfuqizuar, Ndryshuar, Shtuar, Ligj, Me vendimin, Gjykata Kushtetuese, Kjo pikë, Fjalia…); se apre una citazione
(“ ‘’ ") continua finché la citazione si chiude. jsonl E pickle, backup, idempotente. Prova su copia: RUBPAR_JSONL / RUBPAR_PKL.
    python3 tools/repair_note_corpo_al.py [-v] [--apply]   → poi build_dense.py --rifai <pkl>.notecorpo.json"""
import json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "/app")
from src.parser import _paragrafet  # noqa: E402
from src.retrieval import ArticleIndex  # noqa: E402

JSONL = Path(os.environ.get("RUBPAR_JSONL", "/app/data/processed/all_articles.jsonl"))
PKL = Path(os.environ.get("RUBPAR_PKL", "/app/data/index/bm25.pkl"))
INIZIO = re.compile(r"^\s*(?P<n>\d{1,2})\s+(?P<t>(?:Ligj\b|Ligji\b|Vendim|VKM\b|Me ligjin|Me vendimin|Shfuqizuar|Ndryshuar|Shtuar|"
                    r"Hequr|Riformuluar|Shih\b|Gjykata Kushtetuese|Kjo pik[eë]|Kjo fjali|Fjalia|Ky paragraf|Ky nen|Titulli)\b.*)$")
# «10 Pikat 20 deri 32 shtuar me ligjin nr 71/2018.»: qualunque riga «N Maiuscola … shtuar/ndryshuar/… me ligjin/vendimin»
INIZIO_GEN = re.compile(r"^\s*(?P<n>\d{1,2})\s+(?P<t>[A-ZÇË][^\n]{0,160}?\b(?:[Ss]htuar|[Nn]dryshuar|[Ss]hfuqizuar|[Hh]equr|[Rr]iformuluar|[Pp]arashikuar)\b"
                        r"[^\n]{0,40}?\bme\s+(?:ligjin|vendimin|aktin)\b[^\n]{0,120})$")
# «2Ky ligj është përafruar pjesërisht me:» — il numero della nota attaccato
INIZIO_INCOLLATO = re.compile(r"^\s*(?P<n>\d{1,2})(?P<t>Ky ligj [eë]sht[eë] p[eë]rafruar\b.*)$")
# «Ligji nr. 16/2024, datë 8.2.2024 është botuar në Fletoren Zyrtare …» sotto un'altra pubblicazione: la stessa nota
PUBBLICAZIONE = re.compile(r"^\s*Ligji?\s+(?:nr\.\s*)?\d+[^\n]*\b(?:botuar|Fletoren Zyrtare)\b")
_FINE_FRASE = re.compile(r"[.;:”’\"]\s*$")


def _aperta(s: str) -> bool:
    """La citazione resta aperta: più virgolette d'apertura che di chiusura (le doppie ‘’ contano una volta)."""
    a = s.count("“") + s.count("‘‘") + s.count("‘’")
    c = s.count("”") + s.count("’’")
    return a > c


def separa(body: str):
    """(corpo senza le note, [note]). Una nota: una riga; se apre un ELENCO («vendosi:», «shprehet ;», «përafruar … me:») continua
    con punti numerati, trattini e righe spezzate; se apre una CITAZIONE continua finché si chiude — ma una riga minuscola dopo una
    frase chiusa è il testo dell'articolo che riprende (la citazione della Corte costituzionale nel Kodi Zgjedhor 162 non si chiude
    mai); le righe di pubblicazione in Gazzetta sotto la prima sono la stessa nota."""
    righe, tenute, note = (body or "").split("\n"), [], []
    i = 0
    while i < len(righe):
        m = INIZIO.match(righe[i]) or INIZIO_GEN.match(righe[i]) or INIZIO_INCOLLATO.match(righe[i])
        if not m:
            tenute.append(righe[i]); i += 1; continue
        testo, j, prev = m.group("t").strip(), i + 1, righe[i].strip()
        lista = bool(re.search(r"(?:vendosi|shprehet|me)\s*[:;]\s*$", testo))
        # l'elenco delle direttive UE («Ky ligj është përafruar … me:») ha voci che vanno a capo anche dopo un punto («e ndryshuar”.»
        # ⏎ «Numri CELEX …»): finisce solo alla lettera d'elenco dell'articolo che riprende («d) të sigurojë …»)
        direttive = m.re is INIZIO_INCOLLATO or "përafruar" in testo
        while j < len(righe) and j - i < 40:
            nx = righe[j].strip()
            if not nx:
                break
            if direttive:
                if re.match(r"^[a-zçë]{1,2}\)\s", nx):
                    break
            elif _aperta(testo):
                if re.search(r"[.”’]\s*$", prev) and nx[:1].islower():
                    break
            elif lista and (nx.startswith(("-", "“")) or re.match(r"^\d+\s?\.", nx) or not _FINE_FRASE.search(prev)):
                pass
            elif PUBBLICAZIONE.match(nx):
                pass
            else:
                break
            testo += " " + nx; prev = nx; j += 1
        note.append(f"[{m.group('n')}] " + " ".join(testo.split()))
        i = j
    return "\n".join(tenute).strip(), note


def main() -> int:
    apply, verbose = "--apply" in sys.argv, "-v" in sys.argv
    dati = [json.loads(r) for r in JSONL.read_text(encoding="utf-8").splitlines() if r.strip()]
    nuovi = {}
    for d in dati:
        if d.get("repealed"):
            continue
        corpo, note = separa(d.get("body") or "")
        if not note:
            continue
        k = (d["code"], str(d["number"]))
        nota = " ".join(x for x in ((d.get("note") or "").strip(), " ".join(note)) if x)
        nuovi[k] = (corpo, nota)
        print(f"{k[0]} {k[1]}: {len(note)} note → {' | '.join(n[:90] for n in note)}")
        if verbose:
            print("   PRIMA:", (d.get("body") or "")[:600].replace("\n", " ⏎ "))
            print("   DOPO :", corpo[:600].replace("\n", " ⏎ "))
        d["body"], d["note"], d["paragrafet"] = corpo, nota, _paragrafet(corpo if corpo else d.get("heading") or "")
    print("TOTALE", len(nuovi))
    if not apply or not nuovi:
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(JSONL, str(JSONL) + f".bak-{stamp}-notecorpo")
    JSONL.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dati) + "\n", encoding="utf-8")
    idx = ArticleIndex.load(PKL)
    shutil.copy2(PKL, str(PKL) + f".bak-{stamp}-notecorpo")
    for a in idx.articles:
        k = (a.code, str(a.number))
        if k in nuovi:
            a.body, a.note = nuovi[k]
            a.paragrafet = _paragrafet(a.body if a.body else a.heading or "")
    ArticleIndex.build(list(idx.articles), lang="sq", stem=bool(getattr(idx, "stem", False)),
                       fold=bool(getattr(idx, "fold", True))).save(PKL)
    Path(str(PKL) + ".notecorpo.json").write_text(json.dumps([list(k) for k in nuovi], ensure_ascii=False), encoding="utf-8")
    print("FATTO", len(nuovi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
