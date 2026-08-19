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


def parse_article_page(page_html, fallback_number=""):
    """Parse one article page -> dict(number, heading, body, repealed, in_force_from).

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
    region = AGG_RE.sub("", region)          # drop amendment notes

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
    repealed = bool(re.search(r"\b(abrogat[oiae]|soppress[oiae])\b",
                              (heading + " " + body[:400]), re.I))
    if len(body) < 3:
        body = "[Articolo abrogato o senza testo]" if repealed else (heading or "[senza testo]")
    return {"number": number, "heading": heading, "body": body,
            "repealed": repealed, "in_force_from": in_force}


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


def ingest_act(urn, delay=0.45, progress=None, limit=None):
    """Full act -> list of parsed article dicts."""
    nm = Normattiva(delay=delay)
    act = nm.open_act(urn)
    links = nm.article_links(act)
    if limit:
        links = links[:limit]
    arts, fails = [], []
    for i, (href, label) in enumerate(links, 1):
        try:
            page = nm.fetch_article(href)
            a = parse_article_page(page, fallback_number=label)
            if a:
                arts.append(a)
        except Exception as e:  # noqa: BLE001
            fails.append((label, str(e)[:70]))
        if progress and (i % 25 == 0 or i == len(links)):
            progress(i, len(links), len(arts), len(fails))
    best = {}
    for a in arts:
        cur = best.get(a["number"])
        if cur is None or len(a["body"]) > len(cur["body"]):
            best[a["number"]] = a
    return [best[k] for k in sorted(best, key=sortkey)], fails
