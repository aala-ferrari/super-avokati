# -*- coding: utf-8 -*-
"""Testo da un .docx senza dipendenze (zip + word/document.xml): QBZ pubblica alcuni
consolidati SOLO in Word (VKM 651/2017 doganale 2026: PDF da 0 byte, docx da 179 MB di
immagini). Un paragrafo <w:p> = una riga; le tabelle diventano righe cella per cella
(«|» tra le celle). Le note a piè di pagina (footnotes.xml) si ignorano: nel PDF finivano
incollate ai numeri («Neni 1¹»).

    python3 tools/docx_text.py file.docx > testo.txt
"""
import re, sys, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")
    lines: list[str] = []

    def para_text(p) -> str:
        parts: list[str] = []
        for node in p.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W}tab":
                parts.append(" ")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        return "".join(parts)

    def walk(el):
        for child in el:
            if child.tag == f"{W}p":
                lines.append(para_text(child))
            elif child.tag == f"{W}tbl":
                for tr in child.iter(f"{W}tr"):
                    cells = []
                    for tc in tr.findall(f"{W}tc"):
                        cells.append(" ".join(para_text(p) for p in tc.iter(f"{W}p")).strip())
                    lines.append(" | ".join(c for c in cells if c))
            elif child.tag in (f"{W}sdt", f"{W}sdtContent"):
                walk(child)
    walk(body)
    text = "\n".join(ln.rstrip() for ln in lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


if __name__ == "__main__":
    sys.stdout.write(docx_to_text(Path(sys.argv[1])))
