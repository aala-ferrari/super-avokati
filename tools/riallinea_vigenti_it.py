# -*- coding: utf-8 -*-
"""v9.405 — RIALLINEA il corpus italiano al TESTO VIGENTE OGGI (sull'HOST, come l'ingest; backup dei JSON).

`versioni_future_it.py report` trova gli articoli per cui Normattiva senza data dà una versione FUTURA (656 al 29 set 2026:
i vecchi atti fiscali «ABROGATI» dal 2027, più 13 articoli con modifiche future e 3 articoli che esistono solo dal futuro).
Qui, atto per atto (due pagine dell'atto: senza data e con la data di oggi):
  - per ogni articolo con una versione diversa, il testo di OGGI diventa il testo del JSON e la versione futura si conserva in
    `futuro` = {"dal", "heading", "body", "repealed"} con la data letta dalla sua pagina («Testo in vigore dal: …»);
    `vigente_fino` = l'ultimo giorno della versione di oggi;
  - un articolo che c'è SOLO nella versione futura prende `non_in_vigore_dal` = la sua data (resta nel corpus, ma il
    cervello non lo cita come vigente).
`build_it_index.py` usa il testo giusto alla data del build e scrive le date in `it_corrispondenze.json` (`_vigenze`).

    python3 tools/riallinea_vigenti_it.py apply [--only id1,id2] [--dry]
"""
import html as _html
import json
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normattiva_lib as nl  # noqa: E402

SRC = Path(os.environ.get("IT_ACTS_DIR", "/var/www/apps/super-avvocato/data/processed/it_acts"))
VF = Path(os.environ.get("IT_VF_OUT", "/var/www/apps/super-avvocato/data/processed/it_versioni_future.json"))
_VIG_RE = re.compile(r"Testo in vigore dal:\s*(\d{1,2})-(\d{1,2})-(\d{4})(?:\s*al:\s*(\d{1,2})-(\d{1,2})-(\d{4}))?")


def _vigenza(page: str):
    """(dal, al) ISO dalla pagina dell'articolo, o (None, None)."""
    t = _html.unescape(re.sub(r"<[^>]+>", " ", page or "")).replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    m = _VIG_RE.search(t)
    if not m:
        return None, None
    dal = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    al = f"{int(m.group(6)):04d}-{int(m.group(5)):02d}-{int(m.group(4)):02d}" if m.group(4) else None
    return dal, al


def _key(href):
    def g(rx):
        m = re.search(rx, href)
        return m.group(1) if m else ""
    return (g(r"flagTipoArticolo=(-?\d+)") or "0", g(r"art\.idArticolo=(\d+)"), g(r"art\.idSottoArticolo=(\d+)"),
            g(r"art\.idSottoArticolo1=(\d+)"))


def _versione(href):
    m = re.search(r"art\.versione=(\d+)", href)
    return int(m.group(1)) if m else 0


def _num_lab(lab: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"^\s*art(?:icolo)?\.?\s*", "", (lab or "").lower()).strip().rstrip("."))


def _numero_nel_json(num_lab: str, gruppo: str, sizes: dict, etichette: dict, main: str | None = None) -> str | None:
    """Il numero che l'ingest ha dato a quell'articolo (`normattiva_lib.assign_numbers`): il gruppo più grande della pagina
    tiene i numeri, il gruppo 0 diventa «N-legge», un altro gruppo numerato «N-allK», i gruppi non numerati (Tabelle,
    Prospetto) si scartano salvo gli «Allegato …». Prima si cercava solo per numero e, nell'imposta di registro, l'art. 5
    della TABELLA finiva sopra l'art. 5 del testo unico (29 set 2026)."""
    if not num_lab:
        return None
    if len(sizes) <= 1:
        return num_lab
    # `main` dal JSON («main_group»): il bollo ha il decreto nel gruppo 0 e la Tariffa, più lunga, nel gruppo 1 (v9.409)
    main = main if main is not None else max(sizes, key=lambda g: sizes[g])
    if gruppo == main:
        return num_lab
    if gruppo == "0":
        return num_lab + "-legge"
    labs = etichette.get(gruppo) or []
    numerati = sum(1 for x in labs if re.match(r"^\d", _num_lab(x)))
    if numerati >= max(3, int(len(labs) * 0.8)):
        return f"{num_lab}-all{gruppo}"
    return num_lab if num_lab.startswith("allegato") else None


def _trova(arts, numero, gruppo):
    """L'articolo del JSON con ESATTAMENTE quel numero (e, se il JSON lo dice, lo stesso gruppo)."""
    n = str(numero).lower()
    c = [a for a in arts if str(a.get("number")).lower() == n and
         (a.get("group") is None or str(a.get("group")) == str(gruppo))]
    return c[0] if len(c) == 1 else None


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    vf = json.loads(VF.read_text(encoding="utf-8"))
    oggi = date.today().isoformat()
    nm = nl.Normattiva(delay=0.6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tot = {"ok": 0, "ko": 0, "nf": 0}
    for cid in sorted((vf.get("atti") or {})):
        if only and cid not in only:
            continue
        f = SRC / f"{cid}.json"
        if not f.exists():
            continue
        j = json.loads(f.read_text(encoding="utf-8"))
        urn = j.get("urn") or ""
        arts = j.get("articles") or []
        try:
            fut = {_key(h): (h, l) for h, l, _g in nm.article_links_all(nm.open_act(urn))}
            cur = {_key(h): (h, l) for h, l, _g in nm.article_links_all(nm.open_act(urn + "!vig=" + oggi))}
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {cid}: {exc}", flush=True)
            continue
        ok = ko = nf = 0
        sizes, etichette = {}, {}
        for k, (_h, lab) in cur.items():
            sizes[k[0]] = sizes.get(k[0], 0) + 1
            etichette.setdefault(k[0], []).append(lab)
        for k, (h_oggi, lab) in cur.items():
            fh = fut.get(k)
            if not fh or _versione(fh[0]) == _versione(h_oggi):
                continue
            target = _numero_nel_json(_num_lab(lab), k[0], sizes, etichette, j.get("main_group"))
            if target is None:
                print(f"    - {cid} {lab} (gruppo {k[0]}): gruppo non numerato, fuori dal corpus", flush=True)
                continue
            if _trova(arts, target, k[0]) is None:
                print(f"    - {cid} {lab} (gruppo {k[0]} → «{target}»): non è nel corpus", flush=True)
                continue
            try:
                p_oggi = nm.fetch_article(h_oggi)
                a_oggi = nl.parse_article_page(p_oggi, fallback_number=lab)
                p_fut = nm.fetch_article(fh[0])
                a_fut = nl.parse_article_page(p_fut, fallback_number=lab)
                if not a_oggi or not a_fut:
                    ko += 1
                    continue
                # il numero dall'ETICHETTA del link e dal GRUPPO (la pagina può leggersi male: «art. 437 bis» → «437»); il
                # numero letto dalla pagina serve solo da controllo
                num_lab = _num_lab(lab)
                a = _trova(arts, target, k[0])
                if str(a_oggi.get("number") or "").lower() not in ("", num_lab):
                    ko += 1
                    print(f"    ? {cid} {lab}: numero della pagina {a_oggi.get('number')} ≠ etichetta {num_lab}: saltato", flush=True)
                    continue
                dal_fut, _ = _vigenza(p_fut)
                _d, al_oggi = _vigenza(p_oggi)
                if not a.get("futuro"):
                    a["futuro"] = {"dal": dal_fut, "heading": a_fut.get("heading") or "", "body": a_fut.get("body") or "",
                                   "repealed": nl.is_repealed(a_fut.get("heading"), a_fut.get("body"))}
                # v9.409 — un atto scaricato GIÀ al testo vigente (`vigente_al`, i vecchi atti fiscali del wave10) ha il testo di
                # oggi, e magari tariffe e tabelle rilette apposta (bollo, imposte ipotecarie): si aggiunge solo la versione futura
                if not j.get("vigente_al"):
                    a["heading"] = a_oggi.get("heading") or ""
                    a["body"] = a_oggi.get("body") or ""
                    a["repealed"] = nl.is_repealed(a["heading"], a["body"])
                    if a_oggi.get("notes"):
                        a["notes"] = a_oggi["notes"]
                a["vigente_fino"] = al_oggi
                a["riallineato"] = oggi
                ok += 1
            except Exception as exc:  # noqa: BLE001
                ko += 1
                print(f"    ! {cid} {lab}: {type(exc).__name__} {str(exc)[:80]}", flush=True)
        for k, (fh, lab) in fut.items():
            if k in cur:
                continue
            try:
                p_fut = nm.fetch_article(fh)
                # il numero dall'ETICHETTA del link, a confronto esatto: la pagina di «art. 437 bis» si legge «437» (rubrica fra
                # doppie parentesi) e si segnerebbe come non in vigore l'art. 437 c.p., che è vigente
                sizes_f, etich_f = {}, {}
                for kk, (_h, ll) in fut.items():
                    sizes_f[kk[0]] = sizes_f.get(kk[0], 0) + 1
                    etich_f.setdefault(kk[0], []).append(ll)
                target = _numero_nel_json(_num_lab(lab), k[0], sizes_f, etich_f, j.get("main_group"))
                a = _trova(arts, target, k[0]) if target else None
                if a is None:
                    print(f"    ? {cid} {lab}: articolo solo futuro non trovato nel JSON", flush=True)
                    continue
                dal_fut, _ = _vigenza(p_fut)
                a["non_in_vigore_dal"] = dal_fut or "futuro"
                nf += 1
                print(f"    · {cid} art. {a.get('number')}: non ancora in vigore (dal {dal_fut})", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! {cid} {lab}: {type(exc).__name__} {str(exc)[:80]}", flush=True)
        print(f"  {cid:30s} riallineati {ok:4d} · falliti {ko:3d} · non ancora in vigore {nf}", flush=True)
        tot["ok"] += ok; tot["ko"] += ko; tot["nf"] += nf
        if not dry and (ok or nf):
            shutil.copy2(f, f.with_name(f.name + f".bak-{stamp}-vigenti"))
            j["riallineato_vigenti"] = oggi
            f.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTOTALE riallineati {tot['ok']} · falliti {tot['ko']} · non ancora in vigore {tot['nf']}{' (a secco)' if dry else ''}")


if __name__ == "__main__":
    main()
