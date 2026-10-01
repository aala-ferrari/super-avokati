"""v9.427 — prova del FASCICOLO LUNGO: PDF misto (pagine digitali + scansionate) e PDF tutto scansionato oltre le vecchie 10
pagine; il tetto dell'OCR detto nel testo; lo scadenziario che legge il documento a pezzi. OCR e modello SIMULATI, tranne UNA
lettura vera di una pagina per misurarne il tempo (`--vero`). Nessun database toccato.

    docker run --rm … super-avvocato:vX python3 tools/prova_fascicolo_lungo.py [--vero]
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

from src import documents as docs, scadenziario as scad, brain  # noqa: E402

ESITI: list = []


def ok(nome: str, cond: bool, extra: str = "") -> None:
    ESITI.append(cond)
    print(("✓ " if cond else "✗ ") + nome + (f" — {extra}" if extra and not cond else ""))


def pagina_digitale(testo: str) -> bytes:
    """Un PDF di una pagina CON strato di testo, scritto a mano (niente librerie): Helvetica, ASCII."""
    righe = [testo[i:i + 80] for i in range(0, len(testo), 80)]
    flusso = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join("(" + r.replace("(", "").replace(")", "") + ") '" for r in righe) + " ET"
    oggetti = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(flusso)} >>\nstream\n{flusso}\nendstream"]
    out, pos = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for n, o in enumerate(oggetti, 1):
        pos.append(out.tell())
        out.write(f"{n} 0 obj\n{o}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(oggetti) + 1}\n0000000000 65535 f \n".encode())
    for p in pos:
        out.write(f"{p:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(oggetti) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def pagina_scansionata(testo: str) -> bytes:
    img = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(img).text((80, 120), testo, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    return buf.getvalue()


def componi(pagine: list[bytes], dove: Path) -> Path:
    w = PdfWriter()
    for b in pagine:
        for p in PdfReader(io.BytesIO(b)).pages:
            w.add_page(p)
    with open(dove, "wb") as f:
        w.write(f)
    return dove


class OcrFinto:
    def __init__(self):
        self.chiamate: list[int] = []

    def ocr_image(self, path, mimetype, prompt):
        n = int(re.search(r"page_(\d+)", str(path)).group(1))
        self.chiamate.append(n)
        return f"Pagina scansionata {n}. Udienza di discussione fissata al {n:02d}.11.2026 ore 10:00."


dove = Path(tempfile.mkdtemp(prefix="fasc_"))
brain.set_request_jurisdiction("IT")

# 1) PDF MISTO: 2 pagine digitali lunghe + 12 scansionate
digit = [pagina_digitale("Tribunale di Milano. Atto di citazione. Pagina digitale %d. " % i + "testo di prova " * 30) for i in (1, 2)]
scans = [pagina_scansionata(f"Pagina scansionata {i}") for i in range(3, 15)]
pdf_misto = componi(digit + scans, dove / "misto.pdf")
ocr = OcrFinto()
testo, usato = docs._extract_pdf(pdf_misto, ocr)
ok("PDF misto: le pagine scansionate si leggono (prima: mai, se le digitali avevano testo)", usato and len(ocr.chiamate) == 12,
   str(ocr.chiamate))
ok("PDF misto: ordine del documento e pagina 13 presente", testo.index("Pagina digitale 2") < testo.index("Pagina 3/14 (OCR)")
   and "fissata al 13.11.2026" in testo and "PAGINE NON LETTE" not in testo, testo[:300])

# 2) PDF TUTTO SCANSIONATO di 14 pagine: oltre le vecchie 10
pdf_scan = componi([pagina_scansionata(f"p{i}") for i in range(1, 15)], dove / "scan.pdf")
ocr2 = OcrFinto()
testo2, usato2 = docs._extract_pdf(pdf_scan, ocr2)
ok("PDF scansionato di 14 pagine: tutte lette (prima solo 10)", usato2 and len(ocr2.chiamate) == 14 and "Pagina 14/14" in testo2,
   str(ocr2.chiamate))

# 2a) v9.449: l'avanzamento pagina per pagina («Lettura pagina 23/60» nel portale)
passi_prog = []
docs._extract_pdf(pdf_misto, OcrFinto(), lambda f, t: passi_prog.append((f, t)))
ok("v9.449: l'avanzamento arriva pagina per pagina", passi_prog[:1] == [(1, 12)] and passi_prog[-1:] == [(12, 12)]
   and len(passi_prog) == 12, str(passi_prog[:3]))

# 2b) v9.448: una pagina ILLEGGIBILE si dice nel testo
class OcrConIlleggibile(OcrFinto):
    def ocr_image(self, path, mimetype, prompt):
        return "[IMMAGINE ILLEGGIBILE]" if "page_7." in str(path) else super().ocr_image(path, mimetype, prompt)


testo_i, _u = docs._extract_pdf(pdf_scan, OcrConIlleggibile())
ok("v9.448: la pagina illeggibile è detta nel testo col numero", "PAGINE ILLEGGIBILI: 7 su 14" in testo_i, testo_i[-250:])
ok("v9.448: … e nessun falso allarme se si leggono tutte", "ILLEGGIBILI" not in testo2)

# 3) il tetto si DICE: con 5 pagine massime, quali restano fuori
vecchio = docs.MAX_OCR_PAGES
docs.MAX_OCR_PAGES = 5
testo3, _u = docs._extract_pdf(pdf_scan, OcrFinto())
docs.MAX_OCR_PAGES = vecchio
ok("oltre il tetto: le pagine non lette sono dette nel testo, in italiano", "PAGINE NON LETTE: 6–14 su 14" in testo3, testo3[-300:])
brain.set_request_jurisdiction("AL")
testo3b, _u = (lambda: (setattr(docs, "MAX_OCR_PAGES", 5), docs._extract_pdf(pdf_scan, OcrFinto()))[1])()
docs.MAX_OCR_PAGES = vecchio
ok("… e in albanese in sessione albanese", "FAQE TË PALEXUARA: 6–14 nga 14" in testo3b and "Faqja 1/14" in testo3b)
brain.set_request_jurisdiction("IT")

# 4) lo scadenziario a PEZZI
lungo = "".join(f"\n── Pagina {i}/100 ──\n" + ("testo del fascicolo " * 40) + f"\nudienza del {i:02d}.10.2026\n" for i in range(1, 101))
pz, resto = scad.pezzi_del_testo(lungo)
ok("pezzi: tutto il fascicolo coperto, tagli ai cambi pagina", resto == 0 and len(pz) >= 2
   and all(lungo[lungo.find(p) + len(p):].startswith("\n── Pagina") for p in pz[:-1])   # ogni taglio a un cambio pagina
   and all(lungo.find(p) >= 0 for p in pz)
   and all(any(f"udienza del {i:02d}.10.2026" in p for p in pz) for i in range(1, 101)), f"{[len(p) for p in pz]} {resto}")
pz2, resto2 = scad.pezzi_del_testo("x" * 500_000)
ok("oltre i pezzi massimi: il resto non letto è contato", len(pz2) == scad.PEZZI_MAX and resto2 > 0, f"{len(pz2)} {resto2}")


class ModelloFinto:
    def __init__(self):
        self.n = 0

    def complete(self, system, messages, **kw):
        self.n += 1
        testo = messages[0]["content"]
        date = sorted(set(re.findall(r"udienza del (\d{2})\.10\.2026", testo)))
        return json.dumps({"date": [{"titolo": "Udienza", "data": f"2026-10-{d}", "citazione": f"udienza del {d}.10.2026"}
                                    for d in date[:120]], "termini": [], "inneschi": []})


m = ModelloFinto()
lungo2 = "".join(f"\n── Pagina {i}/60 ──\n" + ("testo del fascicolo " * 80) + f"\nudienza del {10 + i % 20:02d}.10.2026\n"
                 for i in range(1, 61))
est = scad.estrai_tutto(m, lungo2, "fascicolo.pdf", "it", "2026-09-30")
date_trovate = sorted({x["data"] for x in est["date"]})
ok("estrazione su tutto il documento, doppioni dei pezzi sovrapposti tolti",
   m.n >= 2 and len(date_trovate) == 20 and len(est["date"]) == len({(x["data"], x["citazione"]) for x in est["date"]}),
   f"chiamate {m.n}, date {len(date_trovate)}, righe {len(est['date'])}")

if "--vero" in sys.argv:                      # UNA lettura vera: quanto costa una pagina
    try:
        from src.backends import build_backend
        be = build_backend()
        img = dove / "page_1.png"
        Image.new("RGB", (1240, 1754), "white").save(img)
        d = ImageDraw.Draw(im := Image.open(img))
        d.text((80, 120), "TRIBUNALE DI MILANO - Udienza fissata al 12.11.2026 ore 10:00", fill="black")
        im.save(img)
        t0 = time.time()
        r = be.ocr_image(img, "image/png", docs.VISION_PROMPT_IT)
        print(f"   OCR vero di una pagina: {time.time() - t0:.1f} s → {r.strip()[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        print("   OCR vero non misurato:", exc)

print(f"\n{sum(ESITI)}/{len(ESITI)} ok")
sys.exit(0 if all(ESITI) else 1)
