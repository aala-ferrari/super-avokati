# -*- coding: utf-8 -*-
"""v9.409 — IMPOSTA DI BOLLO (d.P.R. 642/1972): la numerazione per gruppi dell'ingest («il gruppo più grande è il testo») qui
sbagliava. Il gruppo 0 sono i 43 articoli del DECRETO (quelli che si citano: «art. 13 d.P.R. 642/1972»), il gruppo 1 la Tariffa
(Allegato A, 54 voci), il 2 la Tabella (Allegato B, 36): la Tariffa, più lunga, prendeva i numeri e il decreto diventava «N-legge».
Qui: il decreto torna ai suoi numeri, la Tariffa diventa «N-all1» e la Tabella resta «N-all2», con la parte nella rubrica; le voci
della Tariffa (una tabella disegnata a caratteri, che il parser scartava: restava «Articolo della tariffa 1 (29) (49)») si
rileggono con `normattiva_lib.tabelle_in_testo`. Backup.

    python3 tools/fix_bollo_it.py [--dry] [--rifai]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402
from riallinea_vigenti_it import _key, _num_lab  # noqa: E402

F = Path("/var/www/apps/super-avvocato/data/processed/it_acts/imposta_bollo.json")
PARTI = {"1": "Tariffa (Allegato A)", "2": "Tabella (Allegato B) — atti esenti in modo assoluto"}
# Le cifre della Tariffa sono quelle ORIGINARIE in lire: Normattiva non aggiorna le celle, i cambi stanno nelle note di
# aggiornamento (che il parser toglie dal testo) e la loro catena si ferma al 2004-2005 (euro 11, euro 1,81). Il passo che
# decide oggi — verificato sul testo vigente dell'art. 7-bis, c. 3, D.L. 43/2013 — si dichiara come nota NOSTRA.
NOTA_LIRE = ("Nota di collegamento (redazionale, non del testo ufficiale): le cifre in lire della tabella sono le misure "
             "originarie. Per l'art. 7-bis, comma 3, D.L. 26 aprile 2013, n. 43 (conv. L. 24 giugno 2013, n. 71) le misure "
             "dell'imposta fissa di bollo di euro 1,81 e di euro 14,62 «ovunque ricorrano» sono oggi di euro 2,00 e di euro "
             "16,00 (le vecchie «lire 2.500» e «lire 20.000», già convertite in euro 1,81 e euro 11, poi euro 14,62). Per le "
             "altre misure in lire verificare l'importo vigente nelle note di aggiornamento.")


_NON_PIU = re.compile(r"ARTICOLO\s+NON\s+PI[UÙ]\s+PREVISTO", re.I)


def _testa_via(b):
    """Via le intestazioni della pagina («ALLEGATO A», «Articolo della tariffa / 33», «Allegato A-art. 10 bis»)."""
    b = re.sub(r"^\s*(?:ALLEGATO\s+[AB]\s*\n+\s*)?(?:Articolo della tariffa\s*\n+\s*[\w-]+\s*\n+)?", "", b or "")
    b = re.sub(r"^\s*Allegato\s+[AB]\s*-\s*art\.\s*[\w -]+?\s*\n+", "", b)
    return b.strip()


def main():
    dry = "--dry" in sys.argv
    j = json.loads(F.read_text(encoding="utf-8"))
    arts = j["articles"]
    if any(str(a.get("number")).endswith("-all1") for a in arts):
        bak = sorted(F.parent.glob(F.name + ".bak-*-bollo"))
        if "--rifai" not in sys.argv or not bak:
            print("già corretto (--rifai per rileggere dal primo backup)"); return
        j = json.loads(bak[0].read_text(encoding="utf-8"))          # il JSON com'era PRIMA del primo giro
        arts = j["articles"]
    nm = nl.Normattiva(delay=0.6)
    links = nm.article_links_all(nm.open_act(j["urn"] + "!vig=" + time.strftime("%Y-%m-%d")))
    by_g = {}
    for h, l, g in links:
        by_g.setdefault(g, []).append((h, l))
    out = []
    for a in arts:
        g, n = str(a.get("group")), str(a.get("number"))
        if g == "0":
            out.append(dict(a, number=n.replace("-legge", "")))
        elif g == "1":
            out.append(dict(a, number=re.sub(r"-all\d+$", "", n) + "-all1"))
        else:
            out.append(a)
    # le pagine della Tariffa e della Tabella rilette con le tabelle
    idx = {(str(a.get("group")), str(a["number"])): a for a in out}
    rilette = 0
    vuote = set()
    for g in ("1", "2"):
        for h, lab in by_g.get(g, []):
            num = _num_lab(lab) + f"-all{g}"
            a = idx.get((g, num))
            if a is None:
                print(f"  ? gruppo {g} {lab}: non nel JSON ({num})"); continue
            p = nm.fetch_article(h)
            nuovo = nl.parse_article_page(nl.tabelle_in_testo(p), fallback_number=lab) or {}
            b = _testa_via(nuovo.get("body") or "")
            if len(re.sub(r"[()\s.=_-]", "", b)) < 20 and len(nuovo.get("heading") or "") > 40:
                # «((Atti e documenti posti in essere …))»: il testo MODIFICATO in doppie parentesi letto come rubrica
                b = re.sub(r"\s+", " ", nuovo["heading"]).strip("() .") + "."
                nuovo["heading"] = ""
            vecchio = _testa_via(a.get("body") or "")
            if len(b) > len(vecchio) * 0.8:
                a["body"] = b
                a["repealed"] = nl.is_repealed(nuovo.get("heading"), b)
                rilette += 1
            else:
                a["body"] = vecchio
            if _NON_PIU.search(a["body"]):
                a["repealed"] = True                            # «ARTICOLO NON PIÙ PREVISTO DAL D.M. 20 AGOSTO 1992»
            if len(re.sub(r"[()\s.=_-]", "", a["body"])) < 20:
                vuote.add((g, num)); continue                   # pagina senza testo: fuori
            if g == "1" and re.search(r"\blire\b", a.get("body") or "", re.I):
                a["note"] = NOTA_LIRE
            a["body"] = re.sub(r"N\s?o\s?t\s?e\b", "Note", a.get("body") or "")
            rub = (nuovo.get("heading") or "").strip()
            if not rub and g == "1":                           # l'OGGETTO della voce: senza, fatture e atti notarili si confondono
                for mv in re.finditer(r"(?m)^\s*\d+(?:-\w+)?\.\s*(.+?)(?=[:;]| — |\s\d+(?:-\w+)?\.\s|$)", a["body"]):
                    ogg = re.sub(r"\s+", " ", mv.group(1)).strip(" .")
                    lettere = [c for c in ogg if c.isalpha()]
                    if not lettere or sum(c.isupper() for c in lettere) > 0.6 * len(lettere):
                        continue                                # «NOTA SOPPRESSA DAL D.L. …» non è l'oggetto
                    rub = ogg if len(ogg) <= 110 else ogg[:110].rsplit(" ", 1)[0] + " …"
                    break
            a["heading"] = PARTI[g] + f", art. {_num_lab(lab)}" + (f" — {rub}" if rub else "")
    out = [a for a in out if (str(a.get("group")), str(a["number"])) not in vuote]
    print(f"pagine senza testo tolte: {sorted(n for _, n in vuote)}")
    print(f"decreto {sum(1 for a in out if str(a.get('group')) == '0')} articoli · tariffa/tabella rilette {rilette}")
    for a in out[:3] + [x for x in out if str(x.get("group")) == "1"][:3]:
        print("  ", a["number"], "|", a.get("heading", "")[:60], "|", (a.get("body") or "")[:120].replace("\n", " "))
    if not dry:
        shutil.copy2(F, F.with_name(F.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S") + "-bollo"))
        j["articles"] = out
        j["main_group"] = "0"
        F.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
