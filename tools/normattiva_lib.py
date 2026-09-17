# -*- coding: utf-8 -*-
"""Normattiva ingester library — official consolidated Italian statutes.
Italian statutes carry no copyright (Art. 5 L. 633/1941).

Flow: visit the act page (URN) to open a session, harvest the per-article
links from the act tree, then fetch each article's current version and parse
the Akoma Ntoso markup (article-num-akn / article-heading-akn / commi).
"""
import gzip, html as _html, http.cookiejar, re, time, urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HOST = "https://www.normattiva.it"
URN_BASE = HOST + "/uri-res/N2Ls?urn:nir:stato:"

LINK_RE = re.compile(r"showArticle\('([^']+)',\s*this\);\"[^>]*class=\"numero_articolo\">([^<]*)</a>")
NUM_RE = re.compile(r'<h2[^>]*class="article-num-akn"[^>]*>(.*?)</h2>', re.S | re.I)
HEAD_RE = re.compile(r'<div[^>]*class="article-heading-akn"[^>]*>(.*?)</div>', re.S | re.I)
COMMA_RE = re.compile(r'<div[^>]*class="art-comma-div-akn"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="art-comma-div-akn"|</div>|$)', re.S | re.I)
PRE_RE = re.compile(r'<div[^>]*class="article-pre-comma-text-akn"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="art-commi-div-akn")', re.S | re.I)
VIGENZA_RE = re.compile(r"Testo in vigore dal:\s*([0-9\-]+)", re.I)
ORD = ["bis", "ter", "quater", "quinquies", "sexies", "septies", "octies", "novies",
       "decies", "undecies", "duodecies", "terdecies", "quaterdecies", "quinquiesdecies",
       "sexiesdecies", "septiesdecies", "duodevicies", "undevicies", "vicies"]


class Normattiva:
    """One session per act (Normattiva keys the article endpoint to the session)."""

    def __init__(self, delay=0.45):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.delay = delay
        self.referer = HOST + "/"
        self._act_urn = None

    def _get(self, url, retries=5):
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "it-IT,it;q=0.9",
                    "Referer": self.referer,
                })
                with self.op.open(req, timeout=90) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return raw.decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                last = e
                # Normattiva throttles bursts: back off, and from the third
                # attempt re-open the act so a dropped session is rebuilt.
                time.sleep(2 * (2 ** attempt))
                if attempt >= 2 and self._act_urn:
                    try:
                        self.cj.clear()
                        self.open_act(self._act_urn)
                    except Exception:  # noqa: BLE001
                        pass
        raise RuntimeError(f"GET failed after {retries} tries {url[:80]}… :: "
                           f"{type(last).__name__}: {last}")

    def open_act(self, urn):
        """Open the act page; returns its HTML (also arms the session cookies)."""
        url = URN_BASE + urn
        self._act_urn = urn
        html = self._get(url)
        self.referer = url
        return html

    @staticmethod
    def article_links(act_html):
        """Current-version article links only (skip historical 'agg.N' versions)."""
        out, seen = [], set()
        for u, label in LINK_RE.findall(act_html):
            if "imUpdate=true" in u or label.strip().lower().startswith("agg"):
                continue
            m = re.search(r"art\.idArticolo=(\d+)", u)
            key = (m.group(1) if m else label.strip(), re.search(r"art\.idSottoArticolo=(\d+)", u).group(1)
                   if re.search(r"art\.idSottoArticolo=(\d+)", u) else "")
            if key in seen:
                continue
            seen.add(key)
            out.append((_html.unescape(u), label.strip()))
        return out

    @staticmethod
    def article_links_all(act_html):
        """Tutti i link-articolo correnti, con il GRUPPO `art.flagTipoArticolo`:
        0 = articoli dell'atto stesso (decreto/legge di approvazione o ratifica),
        1 = allegato, 2+ = altri allegati (c.c.: 1 = preleggi, 2 = il codice; convenzione
        IT-AL: 2 = testo inglese; TU IVA: 2 = tabelle). La dedup di article_links
        (chiave idArticolo+idSottoArticolo) buttava via gli allegati con gli stessi
        numeri: c.c. artt. 1-31, DNC 1-10, l'art. 1 di ogni testo unico (16 set 2026)."""
        out, seen = [], set()
        for u, label in LINK_RE.findall(act_html):
            if "imUpdate=true" in u or label.strip().lower().startswith("agg"):
                continue
            m = re.search(r"art\.idArticolo=(\d+)", u)
            ms = re.search(r"art\.idSottoArticolo=(\d+)", u)
            mf = re.search(r"flagTipoArticolo=(\d+)", u)
            key = (m.group(1) if m else label.strip(), ms.group(1) if ms else "", mf.group(1) if mf else "0")
            if key in seen:
                continue
            seen.add(key)
            out.append((_html.unescape(u), label.strip(), key[2]))
        return out

    def fetch_article(self, href):
        time.sleep(self.delay)
        return self._get(HOST + href if href.startswith("/") else href)


def _plain(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = re.sub(r"</(p|div|li|tr)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


BODY_RE = re.compile(r'<div[^>]*class="bodyTesto"[^>]*>(.*?)</div>\s*(?:<div[^>]*class="d-flex|</div>\s*</div>|$)', re.S | re.I)
AGG_RE = re.compile(r'<div[^>]*class="art_aggiornamento-akn"[^>]*>.*?(?=<div[^>]*class="art_aggiornamento-akn"|$)', re.S | re.I)
JUST_RE = re.compile(r'<span[^>]*class="art-just-text-akn"[^>]*>(.*?)</span>', re.S | re.I)
ATTACH_RE = re.compile(r'<span[^>]*class="attachment-just-text"[^>]*>(.*?)</span>', re.S | re.I)
COMMA_ONE = re.compile(r'<div[^>]*class="art-comma-div-akn"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="art-comma-div-akn"|</div>|$)', re.S | re.I)
LEGACY_HEAD = re.compile(r"^\s*Art(?:icolo)?\.?\s*([0-9]+(?:[\-\s]?[a-z]+)*)\.?\s*(?:\(([^)]{0,200})\)\.?)?", re.I)
CHROME_RE = re.compile(r"(?m)^\s*(Articoli|Approfondimenti e Funzioni|articolo precedente|"
                       r"articolo successivo|aggiornamenti all'articolo|Testo in vigore dal:.*|"
                       r"flagTipoArticolo:.*|descrizione.*|progressivo:.*|version:.*|"
                       r"tipoArticolo:.*|\(.*-art\.\s*[0-9]+.*\)|-->)\s*$")


# «Abrogato» solo quando l'articolo NON C'E' PIU': Normattiva scrive in testa
# «((ARTICOLO ABROGATO DAL …))» / «((PROVVEDIMENTO ABROGATO …))». La vecchia regola (la parola
# «abrogato» nei primi 400 caratteri) marcava abrogati — e la ricerca saltava — gli articoli
# che PARLANO di abrogazioni: art. 15 preleggi «Abrogazione delle leggi», gli articoli
# «Abrogazioni» dei testi unici, TUEL 274 «Norme abrogate» (16 set 2026).
# La nota editoriale di Normattiva sta tra doppie parentesi e dice ARTICOLO/PROVVEDIMENTO
# (mai «COMMA ABROGATO» o «NUMERO ABROGATO», che sono abrogazioni parziali di un articolo vivo);
# a volte è preceduta dalla rubrica o dal titolo dell'allegato → si cerca nei primi 400 caratteri.
# MAIUSCOLO e senza re.I: la nota è «((ARTICOLO ABROGATO DAL …))», ma capita anche
# «( ARTICOLO ABROGATO DALLA L. …» o nella rubrica senza parentesi (c.c. 2429-bis); la prosa
# normale scrive «l'articolo abrogato» in minuscolo e non deve scattare.
_ABRO_MARK = re.compile(r"(?:ARTICOLO|ART\.|PROVVEDIMENTO)\s+(?:ABROGAT[OAI]|SOPPRESS[OAI])")
_ABRO_WORD = re.compile(r"\b(abrogat[oiae]|soppress[oiae])\b", re.I)


def is_repealed(heading, body):
    h, b = (heading or "").strip(), (body or "").strip()
    if _ABRO_MARK.search((h + "\n" + b)[:400]):
        return True
    if "[Articolo abrogato o senza testo]" in b:
        return True
    return len(b) < 200 and bool(_ABRO_WORD.search(h + " " + b))   # moncone: solo la nota di abrogazione


# 16 set 2026 (roadmap v3 P3b-IT) — le NOTE DI AGGIORNAMENTO per articolo («AGGIORNAMENTO (9) Il
# D.L. 4 ottobre 2018, n. 113 … ha disposto (con l'art. 14, comma 2) che la presente modifica si
# applica ai procedimenti in corso…») sono la storia dell'articolo E la disciplina transitoria:
# prima venivano scartate; ora si conservano nel JSON (`notes`) — l'atto modificante con la sua URN
# e la data, e il testo della nota. Il testo normativo resta pulito come prima.
_NOTE_TITLE = re.compile(r"AGGIORNAMENTO\s*\((\d+)\)", re.I)
_NOTE_ACT = re.compile(r'<a[^>]*href="/uri-res/N2Ls\?urn:nir:stato:([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


def parse_notes(region):
    """Le note di aggiornamento della pagina-articolo -> [{n, date, acts:[{label, urn}], text}]."""
    out = []
    for m in AGG_RE.finditer(region or ""):
        block = m.group(0)
        tm = _NOTE_TITLE.search(block)
        acts = [{"label": " ".join(_plain(lab).split()), "urn": _html.unescape(urn)} for urn, lab in _NOTE_ACT.findall(block)]
        text = " ".join(_plain(block).split())
        text = re.sub(r"^-{3,}\s*", "", text)
        text = _NOTE_TITLE.sub("", text, count=1).strip(" -")
        dm = re.search(r":(\d{4}-\d{2}-\d{2});", acts[0]["urn"]) if acts else None
        out.append({"n": int(tm.group(1)) if tm else 0, "date": dm.group(1) if dm else "",
                    "acts": acts[:4], "text": text[:900]})
    return out


def parse_article_page(page_html, fallback_number=""):
    """Parse one article page -> dict(number, heading, body, repealed, in_force_from, notes).

    Returns None when the page carries no usable article text."""
    vm = VIGENZA_RE.search(page_html)
    in_force = vm.group(1).strip() if vm else ""

    # Delimit the text container by index: a non-greedy regex stops at the
    # first nested </div> and truncates long articles.
    i = page_html.find('class="bodyTesto"')
    if i >= 0:
        j = page_html.find('<div class="d-flex justify-content-between', i)
        region = page_html[i:j if j > i else len(page_html)]
    else:
        region = page_html
    notes = parse_notes(region)              # keep the amendment notes (history + transitional rules)
    region = AGG_RE.sub("", region)          # drop them from the normative text

    number, heading, parts = "", "", []

    num_m = NUM_RE.search(region)
    if num_m:                                 # ── formats A / B ──
        raw_num = _plain(num_m.group(1))
        nm = re.search(r"Art(?:icolo)?\.?\s*([0-9]+(?:[\-\s]?[a-z]+)*)", raw_num, re.I)
        number = (nm.group(1) if nm else "").strip()
        tail = region[num_m.end():]
        hm = HEAD_RE.search(tail)
        if hm:
            heading = _plain(hm.group(1)).strip().strip("().").strip()[:300]
            tail = tail[:hm.start()] + tail[hm.end():]
        # The body is simply everything left after num/heading: converting the
        # whole remaining region keeps pre-comma text, every comma and nested
        # markup in document order (iterating comma divs dropped commi 2..N).
        parts.append(_plain(tail))
    else:                                     # ── format C: legacy attachment ──
        blocks = ATTACH_RE.findall(region)
        text = _plain("\n".join(blocks) if blocks else region)
        m = LEGACY_HEAD.match(text)
        if m:
            number = (m.group(1) or "").strip()
            heading = (m.group(2) or "").strip().strip(".").strip()[:300]
            text = text[m.end():].strip()
        parts.append(text)

    if not number:
        number = fallback_number or ""
    number = re.sub(r"^art(?:icolo)?\.?\s*", "", number.strip(), flags=re.I)
    number = re.sub(r"[\s\-]+", "-", number).lower().rstrip("-.")
    if not number:
        return None

    body = "\n".join(p for p in parts if p).strip()
    body = CHROME_RE.sub("", body).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    repealed = is_repealed(heading, body)
    if len(body) < 3:
        body = "[Articolo abrogato o senza testo]" if repealed else (heading or "[senza testo]")
    return {"number": number, "heading": heading, "body": body,
            "repealed": repealed, "in_force_from": in_force, "notes": notes}


def sortkey(num):
    m = re.match(r"^(\d+)(?:-(.*))?$", num or "")
    if not m:
        return (10 ** 9, 0)
    suf, rank = m.group(2) or "", 0
    for i, o in enumerate(ORD, start=1):
        if suf.startswith(o):
            rank = i
            break
    return (int(m.group(1)), rank)


def _dedup_longest(arts):
    """Stesso numero nello stesso gruppo (indice che ripete i titoli): resta il corpo più lungo."""
    best = {}
    for a in arts:
        cur = best.get(a["number"])
        if cur is None or len(a["body"]) > len(cur["body"]):
            best[a["number"]] = a
    return [best[k] for k in sorted(best, key=sortkey)]


def assign_numbers(arts, sizes=None):
    """Numerazione per GRUPPO (16 set 2026) per gli atti «approvati con allegato».

    Il gruppo con più articoli è il testo principale e tiene i numeri; il gruppo 0 (l'atto
    di approvazione/ratifica: «1. È approvato l'unito testo unico…», 1-10 articoli) diventa
    «N-legge»; un altro gruppo numerato («art. N», es. le preleggi del c.c.) diventa
    «N-allK» (il chiamante può poi farne un corpus a sé); i gruppi non numerati (Tabelle,
    testo inglese della convenzione) si scartano. Prima vinceva il corpo più lungo e i TU
    perdevano l'art. 1 dell'allegato, il c.c. gli artt. 1-31.
    `sizes` = dimensione completa di ogni gruppo (per la riparazione parziale)."""
    groups = {}
    for a in arts:
        groups.setdefault(str(a.get("group", "0")), []).append(a)
    sizes = sizes or {g: len(v) for g, v in groups.items()}
    if len(sizes) <= 1:
        return _dedup_longest(arts)
    main = max(sizes, key=lambda g: sizes[g])
    out = []
    for g, items in groups.items():
        numbered = sum(1 for a in items if re.match(r"^\d", a.get("number") or ""))
        if g == main:
            out.extend(items)
        elif g == "0":
            out.extend(dict(a, number=f"{a['number']}-legge") for a in items)
        elif numbered >= max(3, int(len(items) * 0.8)):
            out.extend(dict(a, number=f"{a['number']}-all{g}") for a in items)
        else:
            # 17 set 2026 — gli ALLEGATI con suffisso («Allegato I-bis» del codice ambiente, «II-octies»
            # del codice del consumo = avviso sulla garanzia legale, «III-bis» stupefacenti) stanno in
            # un gruppo non numerato e finivano scartati con le Tabelle: il refresh perdeva 12 allegati
            # che il corpus aveva dal 19 ago. Si tengono col loro nome (unico, mai in collisione);
            # il resto del gruppo (Tabelle, Convention…) resta scartato.
            out.extend(a for a in items if str(a.get("number") or "").lower().startswith("allegato"))
    return _dedup_longest(out)


def ingest_act(urn, delay=0.45, progress=None, limit=None):
    """Full act -> list of parsed article dicts (numerati per gruppo, vedi assign_numbers)."""
    nm = Normattiva(delay=delay)
    act = nm.open_act(urn)
    links = nm.article_links_all(act)
    if limit:
        links = links[:limit]
    arts, fails = [], []
    for i, (href, label, flag) in enumerate(links, 1):
        try:
            page = nm.fetch_article(href)
            a = parse_article_page(page, fallback_number=label)
            if a:
                a["group"] = flag
                arts.append(a)
        except Exception as e:  # noqa: BLE001
            fails.append((label, str(e)[:70]))
        if progress and (i % 25 == 0 or i == len(links)):
            progress(i, len(links), len(arts), len(fails))
    return assign_numbers(arts), fails
