"""Procuratore (Prokurori) — prosecution analysis (Phase 2).

Given the facts / case file, produces a GROUNDED prosecution playbook: legal
qualification of the offense(s), element-by-element evidence sufficiency with
GAP detection (what is still missing to charge), the investigative next steps,
the possible sentence — and, mandatorily, an OBJECTIVITY REVIEW (the defense
case + exculpatory evidence + weak elements). That review is the ethics shield:
research shows AI defaults to "charge", so we force it to see the other side.

ASSISTIVE ONLY: the prosecutor decides and signs. Never auto-charges, never
scores a defendant. Grounded — articles come from the corpus, never invented.

v9.397 — DUE GIURISDIZIONI. Prima era scritto solo per l'Albania (prompt, istituzioni — SPAK,
Avokati i Popullit — e norme di partenza del KPP) e in sessione italiana reggeva solo perché il
vincolo di giurisdizione lo correggeva a valle: alcuni prompt nominavano per numero articoli
albanesi («neni 291/329 KPP») dentro un parere italiano. Ora in sessione IT ogni strumento ha il
suo prompt italiano (pubblico ministero, GIP, archiviazione, avocazione, persona offesa) e le norme
di partenza del c.p.p./c.p. — tutte verificate sul corpus il 27 set 2026. La sessione AL è invariata.
E il testo degli articoli arriva al modello INTERO fino a 3.500 caratteri (prima 900: l'art. 275
c.p.p. ne ha 7.516, il KPP 58 2.483 — si perdevano proprio i commi decisivi), con l'avviso del taglio.
"""
from __future__ import annotations

import re as _re

from . import expertise as _expertise
from .logging_utils import get_logger
from .gjykatat import EMRAT_GJYKATAVE_AL

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt


def _lingua() -> str:
    """«it» in sessione italiana, altrimenti «sq» (la giurisdizione la decide la sessione)."""
    try:
        from .brain import request_jurisdiction
        return "it" if (request_jurisdiction() or "AL").upper() == "IT" else "sq"
    except Exception:  # noqa: BLE001
        return "sq"



log = get_logger(__name__)

_LABEL = {
    "kodi_penal": "Kodi Penal", "kodi_proc_penale": "K. Pr. Penale",
    "kodi_civil": "Kodi Civil", "kodi_familjes": "Kodi i Familjes",
    "kodi_rrugor": "Kodi Rrugor",
}

# Testo dell'articolo nel prompt: intero fino a questo punto (per articolo) e in tutto.
_MAX_ART = 3500
# v9.404: 60.000 (era 42.000) — coi semi dei reati tributari italiani (testo unico delle sanzioni, prescrizione, sequestro) il
# blocco arriva a 30-39 articoli e gli ultimi, quelli trovati dalla ricerca sul reato, restavano a 400 caratteri
_MAX_TOT = 60000


def _lbl(c):
    return _expertise._LABEL.get(c) or _LABEL.get(c) or _expertise.etichetta_al(c)   # v9.399: mai l'id interno


def _lbl_it(c):
    try:
        from .citation_verifier import CODE_LABELS
        if CODE_LABELS.get(c):
            return CODE_LABELS[c]
    except Exception:  # noqa: BLE001
        pass
    return c.replace("_", " ")


def _blocco(arts, lang: str) -> str:
    """Il blocco degli articoli per il prompt, con le etichette della sessione («art.» / «neni»)."""
    out, tot = [], 0
    _chiavi = {(c, str(n)) for c, n, _t in arts}
    for c, n, t in arts:
        t = (t or "").strip()
        cap = _MAX_ART if tot < _MAX_TOT else 400
        # v9.405: il testo unico non ancora applicabile con la sua norma previgente subito sotto → un estratto
        _abbr = lang == "it" and _expertise.tu_da_abbreviare(c, n, _chiavi)
        if _abbr:
            cap = min(cap, _expertise._CAP_TU_ABBREVIATO)
        testo = t[:cap]
        if len(t) > cap:
            testo += ((" […testo unico abbreviato: fino al 31/12/2026 si applica l'articolo previgente riportato subito sotto]"
                       if _abbr else " […testo tagliato qui: altri %d caratteri — non completarlo a memoria]" % (len(t) - cap))
                      if lang == "it" else
                      " […teksti u shkurtua këtu: edhe %d karaktere — mos e plotëso nga kujtesa]" % (len(t) - cap))
        if lang == "it":
            out.append("• [%s art. %s] %s" % (_lbl_it(c), n, _expertise._nota_tu(c, t, str(n)) + testo))   # v9.404-405: la decorrenza
        else:
            out.append("• [%s neni %s] %s" % (_lbl(c), n, testo))
        tot += len(testo)
    if out:
        return "\n".join(out)
    return ("(nessun articolo trovato — descrivi a parole, non inventare)" if lang == "it"
            else "(asnjë nen i gjetur — përshkruaj me fjalë, mos shpik)")


def _cpp(*nums):
    return [("codice_procedura_penale", n) for n in nums]


# v9.403 — SEMI DI SITUAZIONE (sessione AL). Misurato sui casi dell'audit del 29 set, dove il modello aveva scritto «il corpus
# non contiene…» (tools/misura_semi_pro: la norma decisiva fra gli articoli dati, 2 campioni dei termini per caso): oggi 21/40,
# con questi semi 32/40. Le fatture false portavano il falso documentale (KP 186) ma non l'occultamento dei redditi (KP 180,
# con le soglie di 5 e 10 milioni di lekë) — l'estrazione dei termini scriveva «evazion fiskal», che nessun titolo contiene;
# il sequestro fatto dalla polizia non portava la CONVALIDA del pubblico ministero entro 48 ore (KPP 301, e 300 per il
# sequestro d'urgenza); il riciclaggio portava gli articoli della legge ANTIRICICLAGGIO (preventiva) al posto del KP 287.
# Solo articoli verificati sul corpus; sono materiale, la qualificazione resta al procuratore.
_RX_FISCALE = _re.compile(
    r"fatur\w*\s+(fiktiv|false|t[e]\s+rreme)|evazion|fsheh\w*\s+(\w+\s+){0,3}ardhur|"
    r"(mos|pa|nuk)\s*(ka\s+)?deklar\w*\s+(\w+\s+){0,2}(tvsh|tatim|ardhur|qarkullim)|\btvsh|detyrim\w*\s+tatimor|"
    r"shmang\w*\s+(nga\s+)?(pagim|tatim|detyrim)")
_RX_ARKA = _re.compile(r"\barka\b|arkat?\s+fiskal|aparat\w*\s+mat|kupon")
_RX_MOSPAGIM = _re.compile(r"(mos\s*|nuk\s+(ka\s+|i\s+)?)pag\w*\s+(\w+\s+){0,2}(tatim|taks|detyrim)|papagu")
_RX_PASTRIM = _re.compile(
    r"pastrim|pastr\w+\s+(\w+\s+){0,2}(parave|produkt)|shpelarj|shperlarj|legaliz\w*\s+(\w+\s+){0,2}(parave|ardhura)|"
    r"origjin\w*\s+(\w+\s+){0,2}paligjshme|(fsheh|mbul)\w*\s+(\w+\s+){0,3}origjin")


# v9.618 — dall'audit dei 27 strumenti in sessione AL (11 ott, staging): il modello scriveva onestamente «non è nel corpus» per il
# CONCORSO di persone (KP 25-27: le fatture fiktive hanno sempre chi le usa), per la RECIDIVA (KP 50/ç: il reato commesso dopo una
# condanna per un crimine; e 50/h), per l'ARRESTO IN FLAGRANZA e la sua CONVALIDA (KPP 251-252, 258 entro 48 ore, 259), per il NE
# BIS IN IDEM coi fatti fiscali già sanzionati dall'amministrazione (KPP 7), per il CALCOLO DEI TERMINI (KPP 144: ore, giorni, il
# giorno festivo), per l'IDENTIFICAZIONE con le impronte (KPP 295) e i campioni biologici (KPP 201/a), per la conservazione dei DATI
# INFORMATICI (KPP 299/a, 191/a, 208/a) e per gli ORDINI DI PROTEZIONE della legge 11/2026 nella violenza in famiglia o dal
# partner. Tutti verificati sul corpus; come gli altri semi, si AGGIUNGONO ai 16 del recupero.
_RX_BASHKEPUNIM = _re.compile(
    r"bashkepun|se\s+bashku|bashke\s+me\s+(nje|dy|tre|disa|te)|me\s+ndihmen\s+e|\bne\s+grup|grup\w*\s+(i\s+|te\s+)?(organizuar|strukturuar|kriminal)|"
    r"\bband[aeë]\b|organizator|"
    r"\b(dy|tre|kater|disa)\s+(persona|te\s+pandehur|autor)|ndihmes\w*\s+(i|e|te)\s+(veprës|vepres|autorit)|shtyt\w*\s+(i|e)\s+|"
    r"fatur\w*\s+(fiktiv|false|t[e]\s+rreme)")
_RX_ORGANIZUAR = _re.compile(r"grup\w*\s+(i\s+|te\s+)?(organizuar|strukturuar)|organizat\w*\s+kriminal|krim\w*\s+(e\s+|te\s+)?organizuar|"
                            r"band\w*\s+(e\s+)?armatosur")
_RX_DENIM_MEPARSHEM = _re.compile(
    r"denim\w*\s+(te\s+|e\s+)?meparsh|(i|e)\s+denuar\s+(me\s+pare|perpara|disa\s+here)|(eshte|ishte|kishte\s+qene)\s+denuar|"
    r"precedent\w*\s+penal|recidiv|(here|heren)\s+(e\s+)?(dyte|trete)|per\s+te\s+njejten\s+veper")
_RX_FLAGRANCE = _re.compile(r"flagranc|\bu\s+kap\b|\bkapur\s+(ne|duke)|arrestu|u\s+ndalua|ndaluar\s+nga\s+policia")
_RX_GISHTA = _re.compile(r"gjurm\w*\s+(e\s+|te\s+)?gisht|daktilo")
_RX_BIOLOGJIK = _re.compile(r"\badn\b|\bdna\b|kampion\w*\s+biologjik|gjak\w*\s+(i|e)\s+(gjetur|mbetur)")
_RX_ELEKTRONIK = _re.compile(
    r"online|internet|platform|aplikacion|\be-?mail|mesazh|whatsapp|facebook|instagram|tiktok|telegram|kompjuter|"
    r"elektronik|kripto|bitcoin|(nga|me|ne|permes)\s+(celular|telefon)|telefonat")
# v9.628 — una MISURA CAUTELARE già in atto nei fatti. Non «masat e sigurimit teknik» (la sicurezza sul lavoro), non «u arrestua
# në shtëpi» (l'arresto A casa), non «detyrimi për të paraqitur deklaratën» (l'obbligo di presentare un atto)
_RX_MASE = _re.compile(r"\bmas\w*\s+(e\s+|te\s+)?sigurimi\w*\b(?!\s+(teknik|ne\s+pune|shoqeror|shendetesor))|\bmas\w*\s+shtrengues|"
                       r"paraburgim|\barrest(i|it|in)?\s+(ne\s+)?(burg|shtepi)|detyrim\w*\s+(per\s+t\W?u\s+)?paraqit|"
                       r"ndalim\w*\s+(i\s+|e\s+)?dalje\w*\s+jashte")
_RX_DHUNE = _re.compile(r"sulm|dhun|rrah|godit|kercen|ngacm|perndjek|plagos|terroriz")
_RX_FAMILJE = _re.compile(r"partner|bashkeshort|\bburri|\bgruaja|e\s+dashur|i\s+dashur|bashkejetu|familj|\bbabai|\bnena\b|vellai|motra|"
                          r"djali|vajza|ish-|ish\s")
# v9.642 — dall'audit del procuratore AL del 16 ott (14 casi col cervello vero + la diagnosi del recupero: 22/30 norme attese nel
# blocco): l'analisi della RAPINA scriveva «il corpus non contiene l'articolo sulla vjedhja me dhunë» (KP 139 c'è: i termini
# estratti dicevano «grabitje», che nessuna rubrica contiene) né quello sull'acquisto di cose rubate (KP 287/b, con la difesa
# «l'ho comprato da uno sconosciuto»); 9 giorni di inabilità senza il KP 90 (fino a 9 giorni: è lui, non l'89); il furto in casa
# senza la violazione di domicilio (KP 112) e il danneggiamento (150); la minaccia «do të të vras» senza la Kanosja (KP 84); la
# violazione dell'ordine di protezione senza il KP 321; l'AUTORE IGNOTO senza la SOSPENSIONE delle indagini (KPP 326: il modello
# proponeva l'archiviazione, che per l'autore ignoto non c'è); insulto e diffamazione senza i KP 119-120 e la vittima-accusatrice
# (KPP 59: si va in tribunale, non in procura); la corruzione senza i KP 259/244 e la competenza (KPP 75/a).
_RX_GRABITJE = _re.compile(r"grabit|(me\s+forc|me\s+dhun|godit|rrah|sulm)\w*.{0,90}?\b(mor|vodh|rremb)\w*|"
                           r"\b(mor|vodh|rremb)\w*.{0,60}?(me\s+forc|me\s+dhun)")
_RX_ARME = _re.compile(r"\barm[eë]\w*|\bthik|pistolet|kallash|revole|\bgjuet")
_RX_LENDIM = _re.compile(r"paaftesi|plag[eo]s|lendim|lendua|demtim\w*\s+(trupor|i\s+shendet)")
_RX_BLERE_VJEDHUR = _re.compile(r"(\bble(u|re|ri|n)\b|blerj)\w*.{0,120}?(vjedh|panjohur)|(vjedh|panjohur).{0,120}?(\bble(u|re|ri|n)\b|blerj)")
_RX_BANESE_HYRJE = _re.compile(r"(banes|shtepi|apartament)\w*.{0,80}?(\bhyri|\bhyre\b|\bhyrj|u\s+fut|\bfuti|\bthye)|"
                               r"(\bhyri|\bhyrj|u\s+fut|\bfuti|\bthye)\w*.{0,80}?(banes|shtepi|apartament)")
_RX_KANOSJE = _re.compile(r"kercen|kanos|do\s+te\s+(te\s+)?(vras|mbys|plagos)|kam\s+per\s+te\s+(te\s+)?vrare")
_RX_URDHER_MBROJTJE = _re.compile(r"urdh\w*\s+(i\s+|e\s+|te\s+)?mbrojtj")
_RX_AUTOR_PANJOHUR = _re.compile(r"autor\w*\s+(i\s+|e\s+|te\s+)?(panjohur|paidentifik)|i\s+paidentifikuar|"
                                 r"autor\w*\s+(\w+\s+){0,3}(nuk|s)\s+(u\s+)?(identifikua|zbulua|gjet)|"
                                 r"(nuk|s)\s+(u\s+)?(identifikua|zbulua)\w*\s+(\w+\s+){0,2}autor")
_RX_NDER = _re.compile(r"shpif|\bfye|\bfyer|ofend|\bnderi?\b|dinjitet|poshter|cnder|nuk\s+(eshte|jane)\s+e\s+vertet")
_RX_KORRUPSION = _re.compile(r"ryshfet|korrupsion|kerkoi\s+.{0,40}?(euro|leke|para|dhurat)|"
                             r"per\s+te\s+(me\s+)?dhene\s+.{0,40}?(leje|vendim|dokument|licenc)")


def _semi_situazione_al(facts: str) -> list:
    f = _expertise._fold(facts or "")
    out = []
    if _RX_FISCALE.search(f):
        out.append(("kodi_penal", "180"))
        out.append(("kodi_proc_penale", "7"))    # v9.618: ne bis in idem — l'amministrazione fiscale sanziona già lo stesso fatto
        # v9.619 (ri-audit dell'11 ott, l'analisi delle fatture fiktive): «il riciclaggio, la confisca del prodotto e il sequestro dei
        # conti non sono nel corpus» → KP 287 (riciclaggio del prodotto), KP 36 (confisca), KPP 210 (sequestro presso le banche)
        out += [("kodi_penal", "287"), ("kodi_penal", "36"), ("kodi_proc_penale", "210")]
        if _RX_ARKA.search(f):
            out.append(("kodi_penal", "182"))
        if _RX_MOSPAGIM.search(f):
            out.append(("kodi_penal", "181"))
    if _RX_PASTRIM.search(f):
        out.append(("kodi_penal", "287"))
    if "sekuestr" in f:
        out.append(("kodi_proc_penale", "208"))
        if _re.search(r"\bpolic", f):
            out += [("kodi_proc_penale", "300"), ("kodi_proc_penale", "301"), ("kodi_proc_penale", "144")]   # v9.618: le 48 ore
    if "shperdor" in f:
        out += [("kodi_penal", "248"), ("kodi_penal", "135")]
    # v9.630 — un TENDER o un'asta pubblica nei fatti: la violazione dell'uguaglianza dei partecipanti (KP 258, il funzionario e chi
    # concorre) e l'abuso d'ufficio (248). Prova in Chrome del 12 ott: «shkelja e barazisë së pjesëmarrësve në tendera publike /
    # shpërdorimi i detyrës nga zyrtari … nuk janë në korpusin e dhënë»
    if _re.search(r"\btender|\bankand|prokurim\w*\s+publik", f):
        out += [("kodi_penal", "258"), ("kodi_penal", "248")]
    # v9.405 — il fatto TENTATO (KP 22 «Kuptimi i tentativës», 23 «Përgjegjësia për tentativën»): nell'audit AL del 29 set
    # l'analisi di un tentativo lo qualificava senza gli articoli sulla tentativa
    # v9.618: «u përpoq të ikte» (tentò la FUGA) non è il tentativo del reato
    _f_tent = _re.sub(r"(u perpoq|perpiqej|perpjek\w*)\s+(per\s+)?te\s+(ik|larg|arratis|fsheh|shmang)\w*", " ", f)
    if _re.search(r"tentativ|tentoi|tenton|u perpoq|perpiqej|perpjek|nuk arriti|pa arritur|u pengua|u ndalua para", _f_tent):
        out += [("kodi_penal", "22"), ("kodi_penal", "23")]
    # v9.618 (vedi sopra `_RX_BASHKEPUNIM`)
    if _RX_BASHKEPUNIM.search(f):
        out += [("kodi_penal", "25"), ("kodi_penal", "26"), ("kodi_penal", "27")]
    if _RX_ORGANIZUAR.search(f):
        out += [("kodi_penal", "28"), ("kodi_proc_penale", "75/a")]
    if _RX_DENIM_MEPARSHEM.search(f):
        out.append(("kodi_penal", "50"))
    if _RX_FLAGRANCE.search(f):
        out += [("kodi_proc_penale", n) for n in ("251", "252", "258", "259", "144")]
    # v9.628 — la misura in atto: condizioni e criteri (KPP 228, 229), revoca e sostituzione (260); con la custodia anche i criteri
    # speciali dell'arresto in carcere (230) e la durata per fase (263). Audit AL del 12 ott, l'atto d'accusa: «dispozitat mbi masat
    # e sigurimit personal dhe kriteret e tyre nuk përfshihen në korpusin e dispozitave të dhëna»
    if _RX_MASE.search(f):
        out += [("kodi_proc_penale", n) for n in ("228", "229", "260")]
        if _re.search(r"paraburgim|\barrest(i|it|in)?\s+(ne\s+)?burg", f):
            out += [("kodi_proc_penale", "230"), ("kodi_proc_penale", "263")]
    if _RX_GISHTA.search(f):
        out.append(("kodi_proc_penale", "295"))
    # v9.619: la cosa trovata nell'auto o in casa = una perquisizione e un sequestro (KPP 202 condizioni, 298 in flagranza, 208)
    if _re.search(r"\bu\s+gjet\w*\s+(\w+\s+){0,3}(ne|te|tek)\s+(makin|banes|shtepi|zyr|automjet|xhep|cant)|kontroll\w*\s+(i\s+|e\s+|te\s+)?"
                  r"(makin|banes|shtepi|personit|automjet|zyr)|kontrolluan|\bkontrolli\s+fizik", f):
        out += [("kodi_proc_penale", "202"), ("kodi_proc_penale", "298"), ("kodi_proc_penale", "208")]
    if _RX_BIOLOGJIK.search(f):
        out += [("kodi_proc_penale", "295"), ("kodi_proc_penale", "201/a")]
    if _RX_ELEKTRONIK.search(f):
        out += [("kodi_proc_penale", "299/a"), ("kodi_proc_penale", "191/a"), ("kodi_proc_penale", "208/a")]
    # v9.619: una società o un'impresa nei fatti → la responsabilità penale della persona giuridica (KP 45) e le pene accessorie (KP 30)
    if _re.search(r"\bshoqeri|\bsh\.?p\.?k\b|\bsh\.?a\.?\b|kompani|person\w*\s+juridik|\bbiznes", f):
        out += [("kodi_penal", "45"), ("kodi_penal", "30")]
        # v9.628 — e la LEGGE a cui il KP 45/4 rinvia (ligji 9754/2007): le basi della responsabilità della società (3), le pene
        # principali e accessorie con la confisca (9, 10), le fasce della multa per pena del reato (11), le attenuanti — i modelli di
        # organizzazione, il danno risarcito (20) — e il rappresentante della società nel procedimento (26, entro 10 giorni). Audit AL
        # del 12 ott (fatture false): «neni 45 ¶4 i delegon … një ligji të veçantë, i cili nuk është në korpusin e dhënë»
        out += [("ligji_personat_juridike", n) for n in ("3", "9", "10", "11", "20", "26")]
        # v9.630 — prova in Chrome del 12 ott (l'amministratore paga il funzionario per vincere l'appalto): l'analisi dava «non nel
        # corpus» le durate delle pene accessorie, le misure cautelari verso la società e la sua prescrizione — ci sono: il ponte
        # verso KP e KPP (2: la legge vale «për aq sa nuk është parashikuar ndryshe» nei codici; 25: le norme del procedimento
        # sull'indagato e l'imputato «për aq sa është e mundur»), chi è organo della società (4), lo scioglimento (12), il divieto
        # di attività (18); con un appalto o fondi pubblici nei fatti l'esclusione dagli appalti (15: da 1 a 5 anni)
        out += [("ligji_personat_juridike", n) for n in ("2", "4", "12", "18", "25")]
        if _re.search(r"\btender|\bankand|prokurim|fond\w*\s+(e\s+|te\s+)?publik", f):
            out.append(("ligji_personat_juridike", "15"))
    if _RX_DHUNE.search(f) and _RX_FAMILJE.search(f):
        out += [("ligji_dhuna_familje_2026", n) for n in ("18", "26", "30", "36", "42")]
        out.append(("kodi_penal", "130/a"))                      # v9.642: la figura della violenza in famiglia
    # v9.642 (vedi `_RX_GRABITJE`)
    if _RX_GRABITJE.search(f):
        out.append(("kodi_penal", "139"))
        if _RX_ARME.search(f):
            out.append(("kodi_penal", "140"))
    if _RX_LENDIM.search(f):
        out += [("kodi_penal", "89"), ("kodi_penal", "90")]
        if _re.search(r"rrezik\w*\s+(per\s+)?jet|\brende\b|gjymt|shemtim|\bthik|\barm", f):
            out.append(("kodi_penal", "88"))
    if _RX_BLERE_VJEDHUR.search(f):
        out.append(("kodi_penal", "287/b"))
    if _RX_BANESE_HYRJE.search(f):
        out.append(("kodi_penal", "112"))
        if _re.search(r"\bthye|demtoi|shkaterr", f):
            out.append(("kodi_penal", "150"))
    if _RX_KANOSJE.search(f):
        out.append(("kodi_penal", "84"))
    if _RX_URDHER_MBROJTJE.search(f):
        out.append(("kodi_penal", "321"))
    if _RX_AUTOR_PANJOHUR.search(f):
        out.append(("kodi_proc_penale", "326"))
    if _RX_NDER.search(f):
        out += [("kodi_penal", "119"), ("kodi_penal", "120"), ("kodi_proc_penale", "59")]
    if _RX_KORRUPSION.search(f):
        out += [("kodi_penal", "259"), ("kodi_penal", "244"), ("kodi_proc_penale", "75/a")]
    return out


def _semi_al(seeds, facts: str, extra=()) -> tuple[list, int]:
    """(semi dello strumento + semi mancanti misurati + semi di situazione, quanti in più): i posti in più si AGGIUNGONO ai
    16 del recupero, non li tolgono alla ricerca del reato."""
    base = list(seeds or [])
    add = [x for x in list(extra) + _semi_situazione_al(facts) if x not in base]
    add = list(dict.fromkeys(add))
    return base + add, len(add)


# v9.642 — QUALI CODICI può portare il recupero del procuratore AL (i semi passano sempre). Nell'audit del 16 ott il blocco del
# furto aveva la legge sull'assicurazione auto, la VKM doganale («merci di valore trascurabile»), il codice dei minori e la legge
# sui rapporti con le autorità straniere; quello dell'archiviazione la sospensione del procedimento disciplinare dell'ufficiale
# giudiziario: il modello spiegava uno per uno perché non si applicano. Dentro sempre il codice penale e quello di procedura; gli
# altri codici penali o di settore solo col loro motivo nei fatti; della Costituzione solo le garanzie del processo penale.
_KUSHT_PENALE = frozenset({"27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "42", "43"})
_CODICI_COL_MOTIVO_AL = (
    (r"narkotik|droge|\bdrog|kokain|heroin|kanabis|marihuan|hashash|psikotrop|metamfetamin|ekstazi|lend\w*\s+narkotik", ("ligji_lendet_narkotike", "ligji_kanabisi_mjekesor", "ligji_barnat")),
    (r"\bshoqeri|\bsh\.?p\.?k\b|\bsh\.?a\.?\b|kompani|person\w*\s+juridik|\bbiznes|administrator", ("ligji_personat_juridike", "ligji_shoqerite_tregtare")),
    (r"\bi\s+mitur|\be\s+mitur|\bte\s+mitur|\bnen\s+(14|16|18)\s+vjec|\b(1[0-7]|[1-9])\s*(-\s*)?vjec", ("kodi_te_miturve",)),
    (r"jashte\s+shtetit|ekstradim|leterporosi|\bi\s+huaj|\be\s+huaj|shtetas\w*\s+(i\s+|e\s+)?huaj|interpol|europol", ("ligji_marredheniet_juridiksionale", "ligji_te_huajt")),
    (r"aksident|rrugor|automjet|\bmakin|patent|drejtim\w*\s+(e\s+|te\s+)?mjet|alkool|\bshpejtesi", ("kodi_rrugor", "ligji_sigurimi_mjeteve", "ligji_transportet_rrugore")),
    (r"dogan|kontraband|import|eksport", ("kodi_doganor", "vkm_dispozita_doganore")),
    (r"tatim|\btvsh|fiskal|\bfatur|evazion", ("ligji_procedurat_tatimore", "ligji_tvsh", "ligji_tatimi_te_ardhurat")),
    (r"\barm[eë]\w*|pistolet|kallash|revole|municion|\bgjuet", ("ligji_armet",)),
    (r"pastrim|shpelarj|origjin\w*\s+(\w+\s+){0,2}paligjshme", ("ligji_pastrimi_parave",)),
    (r"organizat\w*\s+kriminal|grup\w*\s+(i\s+|te\s+)?(strukturuar|organizuar)|mafi|pasuri\w*\s+(e\s+|te\s+)?paligjshme", ("ligji_antimafia",)),
    (r"ndertim|leje\s+(e\s+)?ndertim|kat\s+shtese|\bpallat", ("ligji_planifikimi_territorit", "ligji_inspektimi_territorit")),
    (r"\bpolic\w*.{0,60}?(dhun|keqtrajt|abuz|tortur|rrah)", ("ligji_policia_2024", "rregullore_policia")),
    (r"te\s+dhena\w*\s+personale|privatesi|kamer\w*\s+(e\s+)?fsheht", ("ligji_te_dhenat_2024",)),
    (r"\bburg\b|\bburgu\b|i\s+burgosur|i\s+denuar\s+me\s+burg|paraburgim", ("ligji_te_denuarit",)),
    (r"zgjedh|\bvot", ("kodi_zgjedhor",)),
    (r"tender|ankand|prokurim\w*\s+publik", ("ligji_prokurimi_publik",)),
    (r"falimentim", ("ligji_falimentimi",)),
)


def _codici_ammessi_al(facts: str):
    f = _expertise._fold(facts or "")
    ok = {"kodi_penal", "kodi_proc_penale"}
    if _RX_DHUNE.search(f) and _RX_FAMILJE.search(f) or _RX_URDHER_MBROJTJE.search(f):
        ok.add("ligji_dhuna_familje_2026")
    for rx, codici in _CODICI_COL_MOTIVO_AL:
        if _re.search(rx, f):
            ok.update(codici)

    def ammessi(code, number):
        if code == "kushtetuta":
            return str(number) in _KUSHT_PENALE
        return code in ok
    return ammessi


# v9.404 — SEMI DI SITUAZIONE in sessione IT (stessa misura, 9 casi × 3 campioni dei termini, indice IT con le rubriche v9.403):
# 15/27 → 27/27. Nell'audit IT del 29 set il pubblico ministero, sulle fatture per operazioni inesistenti, trovava l'art. 79 del
# testo unico delle sanzioni tributarie ma scriveva «non figurano tra gli articoli forniti» per confisca, non punibilità per
# pagamento, prescrizione e rapporti col processo tributario (artt. 86-97 del testo unico) e per la prescrizione del codice penale
# (157-161); il sequestro fatto dalla polizia giudiziaria senza la convalida (c.p.p. 354-355); il riciclaggio (648-bis ss.).
_CP_GENERALE_IT = [("codice_penale", n) for n in ("81", "157", "158", "160", "161")]
_TU_FISCALE_IT = [("tu_sanzioni_tributarie", n) for n in ("73", "86", "87", "88", "89", "90", "93", "96", "97")]
_RX_FISC_IT = _re.compile(
    r"fattur\w*\s+(?:per\s+)?operazion\w*\s+inesistent|operazioni\s+inesistenti|evasion\w*\s+(?:fiscal|dell|d'imposta|di\s+imposta)|"
    r"dichiarazion\w*\s+(?:fraudolent|infedel|omess|dei\s+redditi)|omess\w*\s+(?:dichiarazion|versament)|"
    r"non\s+ha\s+versat\w*\s+(?:l'|lo\s+|la\s+|le\s+|i\s+|gli\s+)?(?:iva|imposta|ritenut)|indebit\w*\s+compensazion|"
    r"sottrazion\w*\s+fraudolent|\bsocietà\s+cartier|fatture\s+false|costi\s+fittizi", _re.I)
_RX_INESISTENTI_IT = _re.compile(r"inesistent|fatture\s+false|cartier|fittizi", _re.I)
_RX_RICICL_IT = _re.compile(r"ricicl|reimpieg|autoricicl|provenienza\s+(?:illecita|delittuosa)|ostacol\w*\s+(?:l['’])?identificazion",
                            _re.I)
_RX_PG_IT = _re.compile(r"guardia\s+di\s+finanza|polizia|carabinier|finanzier|\bp\.?\s?g\.?\b|agenti|militari", _re.I)


def _semi_situazione_it(facts: str) -> list:
    f = facts or ""
    out = []
    if _RX_FISC_IT.search(f):
        out += _TU_FISCALE_IT + [("codice_procedura_penale", "321")]     # + il sequestro preventivo (per equivalente)
        if _RX_INESISTENTI_IT.search(f):
            out += [("tu_sanzioni_tributarie", n) for n in ("74", "79", "80")]
        # v9.405 — prova viva sulle fatture false: il pubblico ministero scriveva «non figura fra gli articoli forniti» per il
        # passaggio dalla verifica fiscale all'indagine penale (art. 220 disp. att. c.p.p.: emersi indizi di reato, le garanzie
        # del codice), per la consulenza tecnica contabile (art. 359 c.p.p.) e, con una società, per la responsabilità dell'ente
        # (d.lgs. 231/2001 artt. 5, 10 e 25-quinquiesdecies «Reati tributari»)
        out += [("disp_att_cpp", "220"), ("codice_procedura_penale", "359")]
        if _re.search(r"\bs\.?r\.?l\b|\bs\.?p\.?a\b|societ|\bente\b|impresa", f, _re.I):
            out += [("responsabilita_enti", "5"), ("responsabilita_enti", "10"), ("responsabilita_enti", "25-quinquiesdecies")]
    if _RX_RICICL_IT.search(f):
        out += [("codice_penale", n) for n in ("648-bis", "648-ter", "648-ter.1")]
    if _re.search(r"sequestr", f, _re.I):
        out.append(("codice_procedura_penale", "253"))
        if _RX_PG_IT.search(f):
            out += [("codice_procedura_penale", "354"), ("codice_procedura_penale", "355")]
    # v9.405 — il delitto TENTATO (c.p. 56)
    if _re.search(r"tentat|\btentò|cercato di|cercava di|non (?:è )?riuscit|senza riuscir|fu fermat|è stato fermat", f, _re.I):
        out.append(("codice_penale", "56"))
    return out


def _semi_it(seeds, facts: str, extra=()) -> tuple[list, int]:
    base = list(seeds or [])
    add = [x for x in list(dict.fromkeys(list(extra) + _semi_situazione_it(facts))) if x not in base]
    return base + add, len(add)


# per il procuratore, a parità di parole nel titolo vince il codice penale (misurato: «ndërtim pa leje» → titoli della legge
# urbanistica al posto del KP 199/a; «pastrim parash» → legge antiriciclaggio al posto del KP 287)
_PREF_AL = ("kodi_penal",)


def _cp(*nums):
    return [("codice_penale", n) for n in nums]


# ───────────────────────── prompt albanesi (invariati) ─────────────────────────

_SYSTEM = (
    "Ti je ndihmës i një PROKURORI në Shqipëri. Nga faktet e çështjes (dhe fashikulli "
    "nëse jepet), ndërto një analizë akuzuese profesionale, TË BAZUAR VETËM te faktet "
    "dhe te NENET e dhëna nga korpusi ynë. MOS shpik nene, numra ligjesh apo vendime — "
    "përdor vetëm ato që të jepen; nëse diçka nuk të jepet, thuaje me fjalë pa e trilluar.\n\n"
    "Jep këto seksione (markdown):\n"
    "### \U0001f4dc Kualifikimi ligjor — cila/cilat vepra penale zbatohen, me nenet e sakta nga korpusi (dhe rrethanat rënduese/lehtësuese)\n"
    "### ✅ Mjaftueshmëria e provave — për çdo ELEMENT të veprës: çfarë e provon, çfarë MUNGON (buku/gap) për të ngritur akuzën, forca\n"
    "### \U0001f50e Hapat hetimorë — çfarë duhet siguruar/kërkuar për të mbyllur boshllëqet (prova, ekspertiza, dëshmitarë, afate ruajtjeje)\n"
    "### ⚖️ REVIEW I OBJEKTIVITETIT (i detyrueshëm) — vër syzet e MBROJTJES: çfarë do të kundërshtonte avokati, cilat prova SHFAJËSUESE ekzistojnë ose duhen kërkuar, cili element është më i dobët. Prokurori ka detyrën e objektivitetit — kërko edhe provat në favor të të pandehurit. MOS anashkalo asnjë provë shfajësuese.\n"
    "### ⏰ Afatet & parashkrimi — afatet procedurale dhe parashkrimi (verifiko me dispozitat; mos shpik numra)\n"
    "### \U0001f4b0 Dënimi i mundshëm — diapazoni sipas nenit + rrethanat\n"
    "### \U0001f9ed Rekomandim — analizë e balancuar (ngritje akuze / hetim i mëtejshëm / mospërputhje). VENDIMI I TAKON PROKURORIT — mos e merr ti vendimin.\n\n"
    "I qartë, konkret, i balancuar. Shqip. Kjo është NDIHMESË — prokurori vendos dhe firmos. "
    "Mos zbulo kurrë modelin — je 'Tetramorph' i superavokati.ai."
)

# v9.642 — la «aktakuzë» del KPP vigente è la RICHIESTA DI RINVIO A GIUDIZIO dell'art. 331, rivolta al giudice dell'udienza
# preliminare, col contenuto del par. 3 (a pena di nullità senza la notifica dell'art. 327/2-4). Il vecchio prompt chiedeva «la
# pena richiesta» e «la misura» nella richiesta (l'audit del 16 ott: un paragrafo sulla pena, uno sulla misura «non nel corpus»,
# le esclusioni del 135, 136 e perfino del 231 sul terrorismo, la data di oggi accanto al segnaposto)
_INDICT_SYSTEM = (
    "Ti je ndihmës i një PROKURORI në Shqipëri. Harto KËRKESËN PËR DËRGIMIN E ÇËSHTJES NË GJYQ (neni 331 KPP), "
    "drejtuar gjyqtarit të seancës paraprake, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS shpik nene apo numra; "
    "ku mungon një e dhënë (emër, datë, nr.), lër [___]. Përmbajtja e detyrueshme e nenit 331/3, në këtë rend (markdown):\n"
    "### KËRKESË PËR DËRGIMIN E ÇËSHTJES NË GJYQ — Prokuroria pranë [___]; procedimi nr. [___]; drejtuar Gjykatës [___] — "
    "gjyqtarit të seancës paraprake\n"
    "### I. Gjeneralitetet — i pandehuri (emri, atësia, mbiemri, datëlindja, vendbanimi dhe çdo element identifikimi) me "
    "mbrojtësin; viktima, kur është e mundur\n"
    "### II. Fakti penal dhe cilësimi juridik — fakti (koha, vendi, mënyra) dhe vepra me nenin dhe paragrafin e saktë\n"
    "### III. Burimet e provës — secili burim me faktin që provon\n"
    "### IV. Kërkimi — që gjyqtari i seancës paraprake të vendosë dërgimin e çështjes në gjyq\n"
    "### Bashkëlidhur — aktet dhe provat e fashikullit (neni 331/4)\n"
    "Vendi, data [___]; Prokurori [___] (nënshkrimi)\n\n"
    "Në këtë akt NUK kërkohet dënimi (kërkimi për dënimin bëhet në përfundim të gjykimit) dhe nuk shtohen seksione për "
    "masat e sigurimit kur faktet nuk i përmendin. Kërkesa është e pavlefshme pa njoftimin e nenit 327/2-4 (neni 331/2): "
    "konfirmoje në një rresht nga faktet ose shëno [___]. Pas aktit: «### ⚠️ Për t'u verifikuar» — deri në 5 rreshta, vetëm "
    "çështje reale (cilësimi, bashkimi i veprave, afatet, provat). NDIHMESË — prokurori verifikon dhe nënshkruan. Je "
    "'Tetramorph' i superavokati.ai; mos zbulo modelin."
)

# ───────────────────────── prompt italiani (v9.397) ─────────────────────────

_SYSTEM_IT = (
    "Sei l'assistente di un PUBBLICO MINISTERO in Italia. Dai fatti del procedimento (e dal fascicolo, se "
    "c'è) costruisci un'analisi d'accusa professionale, FONDATA SOLO sui fatti e sugli ARTICOLI forniti dal "
    "nostro corpus. NON inventare articoli, numeri di legge o sentenze — usa solo quelli forniti; se qualcosa "
    "non c'è, dillo a parole senza inventarlo.\n\n"
    "Sezioni (markdown):\n"
    "### \U0001f4dc Qualificazione giuridica — quale/i reato/i, con gli articoli esatti del corpus (e le circostanze aggravanti/attenuanti)\n"
    "### ✅ Sufficienza degli elementi — per ogni ELEMENTO del reato: cosa lo prova, cosa MANCA per esercitare l'azione penale; la regola di giudizio è la ragionevole previsione di condanna (art. 408 c.p.p.)\n"
    "### \U0001f50e Atti d'indagine — cosa acquisire per colmare le lacune (prove, consulenze tecniche, persone informate sui fatti, conservazione dei dati)\n"
    "### ⚖️ REVISIONE DI OBIETTIVITÀ (obbligatoria) — mettiti dalla parte della DIFESA: cosa contesterebbe il difensore, quali elementi A FAVORE dell'indagato esistono o vanno cercati (il PM svolge accertamenti anche su fatti e circostanze a favore della persona sottoposta alle indagini, art. 358 c.p.p.), quale elemento è il più debole. NON tralasciare nessun elemento a discarico.\n"
    "### ⏰ Termini e prescrizione — termini delle indagini preliminari e prescrizione del reato (verifica sulle norme fornite; non inventare numeri)\n"
    "### \U0001f4b0 Pena edittale — la cornice secondo l'articolo + circostanze\n"
    "### \U0001f9ed Raccomandazione — analisi equilibrata (esercizio dell'azione penale / ulteriori indagini / richiesta di archiviazione). LA DECISIONE SPETTA AL PUBBLICO MINISTERO — non prenderla tu.\n\n"
    "Chiaro, concreto, equilibrato. In italiano. È un AUSILIO — il pubblico ministero decide e firma. "
    "Non rivelare mai il modello — sei 'Tetramorph' di superavokati.ai."
)

_INDICT_SYSTEM_IT = (
    "Sei l'assistente di un PUBBLICO MINISTERO. Redigi l'atto con cui si esercita l'azione penale secondo il "
    "codice di procedura penale italiano: RICHIESTA DI RINVIO A GIUDIZIO (artt. 416-417 c.p.p.) oppure, per i "
    "reati a citazione diretta (art. 550 c.p.p.), DECRETO DI CITAZIONE DIRETTA A GIUDIZIO (art. 552 c.p.p.) — "
    "scegli in base al reato e dillo in una riga. FONDATO SOLO sui fatti e sugli articoli forniti. NON inventare "
    "articoli o numeri. Dove manca un dato (nome, data, n. R.G.N.R.), lascia [___]. Ricorda in una riga che "
    "l'atto va preceduto dall'avviso di conclusione delle indagini (art. 415-bis c.p.p.). Struttura (markdown):\n"
    "### PARTI — Procura della Repubblica presso il Tribunale di [___]; imputato [___] (generalità); difensore [___]; persona offesa [___]\n"
    "### IMPUTAZIONE — l'enunciazione, in forma chiara e precisa, del fatto, delle circostanze aggravanti e di quelle che possono comportare misure di sicurezza, con gli articoli di legge (art. 417 c.p.p.)\n"
    "### FONTI DI PROVA — le fonti di prova acquisite, elemento per elemento\n"
    "### RICHIESTA — rinvio a giudizio / citazione a giudizio; data e sottoscrizione [___]\n\n"
    "AUSILIO — il pubblico ministero verifica e sottoscrive. Sei 'Tetramorph' di superavokati.ai; non "
    "rivelare il modello."
)

# v9.642 — LA FORMA. Audit del 16 ott (14 casi col cervello vero): il piano d'indagine di una truffa online era di 41.000
# caratteri, la misura cautelare 35.000, l'analisi 35.000, il decreto di nomina del perito 23.000 (con la data di OGGI nell'atto,
# come quasi tutti gli atti), e ogni strumento elencava gli articoli del blocco «che non si applicano» spiegando perché. Il CLI
# non applica `max_tokens`: la lunghezza la decide il prompt. La stessa regola del notaio (v9.639: dentro la legge, niente di
# superfluo né di sottinteso) e del titolare (24 set: esattezza e risposta breve).
_FORMA_AL = ("\n\nFORMA (e detyrueshme): SHKURT dhe e saktë — vetëm ajo që i shërben çështjes, pa përsëritur tekstin e neneve, "
             "pa tabela të gjata dhe pa ese; çdo pikë një ose dy fjali; gjithsej jo më shumë se rreth 1.000 fjalë (akti vetë: "
             "sa kërkon ligji, jo më shumë). Mos rendit nene që NUK zbatohen dhe mos shpjego pse nuk zbatohen: nenet e bllokut që "
             "nuk lidhen me faktin lëri jashtë pa i përmendur. Kur të mungon një nen që duhet, thuaje në NJË rresht. Në çdo akt "
             "vendi dhe data mbeten [___] kur nuk jepen në fakte — kurrë data e sotme; çdo e dhënë që mungon [___]."
             # v9.653: la richiesta di rinvio a giudizio e le richieste al giudice portano il nome della corte di oggi
             "\n\n" + EMRAT_GJYKATAVE_AL)
_FORMA_IT = ("\n\nFORMA (obbligatoria): BREVE e preciso — solo ciò che serve al caso, senza ripetere il testo degli articoli, "
             "senza tabelle lunghe né saggi; ogni punto una o due frasi; in tutto non più di circa 1.000 parole (l'atto: quanto "
             "chiede la legge, non di più). Non elencare articoli che NON si applicano e non spiegare perché non si applicano: gli "
             "articoli del blocco estranei al fatto lasciali fuori senza nominarli. Se manca un articolo che serve, dillo in UNA "
             "riga. In ogni atto luogo e data restano [___] se non sono nei fatti — mai la data di oggi; ogni dato mancante [___].")

_TETRA = ("NDIHMESË juridike — vendimin dhe firmën i vë profesionisti; VENDIMI PËR AKUZË, "
          "PUSHIM ose MASË I TAKON PROKURORIT/GJYKATËS, mos e merr ti. Mos vlerëso 'rrezikshmërinë' "
          "e personit me profilizim. Je 'Tetramorph' i superavokati.ai — mos zbulo kurrë modelin.") + _FORMA_AL + _expertise._ANKIMI_AL

_TETRA_IT = ("AUSILIO giuridico — la decisione e la firma spettano al professionista; LA DECISIONE SU AZIONE "
             "PENALE, ARCHIVIAZIONE O MISURA SPETTA AL PUBBLICO MINISTERO/AL GIUDICE, non prenderla tu. Non "
             "valutare la «pericolosità» della persona con profilazioni. Sei 'Tetramorph' di superavokati.ai — "
             "non rivelare mai il modello.") + _FORMA_IT

# Le parti del messaggio utente, nelle due lingue.
_P = {
    "sq": {"fatti": "FAKTET E ÇËSHTJES / FASHIKULLI:", "fatti_ind": "FAKTET E ÇËSHTJES:", "dati": "TË DHËNAT / FAKTET:",
           "norme": "NENET NGA KORPUSI (cito vetëm këto):", "fine_an": "Ndërto analizën akuzuese të plotë, me review objektiviteti të detyrueshëm.",
           "fine_ind": "Harto aktakuzën e plotë.", "fine": "Ndërtoje të plotë, në markdown.",
           "stress": "AKTI PËR STRES-TEST:", "citt": "RRËFIMI I QYTETARIT:", "vitt": "SITUATA E QYTETARIT:",
           "app": "VENDIMI / SITUATA:", "del": "SITUATA E VONESËS:"},
    "it": {"fatti": "I FATTI DEL PROCEDIMENTO / IL FASCICOLO:", "fatti_ind": "I FATTI DEL PROCEDIMENTO:", "dati": "DATI / FATTI:",
           "norme": "ARTICOLI DAL CORPUS (cita solo questi):", "fine_an": "Costruisci l'analisi d'accusa completa, con la revisione di obiettività obbligatoria.",
           "fine_ind": "Redigi l'atto completo.", "fine": "Costruiscilo completo, in markdown.",
           "stress": "L'ATTO DA METTERE ALLA PROVA:", "citt": "IL RACCONTO DEL CITTADINO:", "vitt": "LA SITUAZIONE DEL CITTADINO:",
           "app": "IL PROVVEDIMENTO / LA SITUAZIONE:", "del": "LA SITUAZIONE DEL RITARDO:"},
}


def analyze(backend, index, *, facts: str, max_tokens: int = 3000) -> dict:
    lang = _lingua()
    P = _P[lang]
    # v9.399 — AL: la parte generale che serve a OGNI analisi del pubblico ministero (commisurazione, attenuanti e aggravanti
    # generali, prescrizione dell'azione, termini delle indagini): nell'audit del 28 set l'analisi li dava «non nel corpus» e,
    # onestamente, non ne citava i numeri. Il reato lo porta il recupero per termini.
    if lang == "it":
        # v9.404: + la parte generale che l'analisi chiede sempre (continuazione, prescrizione) e i semi di situazione
        seeds, n_add = _semi_it(_cpp("358", "405", "408"), facts, extra=_CP_GENERALE_IT)
        arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds, max_arts=16 + n_add)
    else:
        # v9.403: + KPP 284 (i reati perseguibili solo a querela della vittima: la procedibilità) e i semi di situazione;
        # v9.404: + KP 55 (più reati: l'audit IT e AL scriveva «il concorso di reati non è nel corpus»)
        seeds, n_add = _semi_al([("kodi_penal", "47"), ("kodi_penal", "48"), ("kodi_penal", "50"), ("kodi_penal", "66"),
                                 ("kodi_proc_penale", "323"), ("kodi_proc_penale", "324")], facts,
                                # v9.619: + KP 1 (crimine o contravvenzione: decide la prescrizione del KP 66) e KP 59 (la
                                # sospensione con la messa alla prova) — nel ri-audit «non sono nel corpus»
                                extra=[("kodi_proc_penale", "284"), ("kodi_penal", "55"), ("kodi_penal", "1"), ("kodi_penal", "59"),
                                       # v9.627: e gli OBBLIGHI della messa alla prova (KP 60) accanto alla sospensione (59): l'audit
                                       # del 12 ott «Detyrimet sipas nenit 60 (teksti i nenit 60 nuk është në korpus)»
                                       ("kodi_penal", "60")])
        arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds, max_arts=16 + n_add, preferiti=_PREF_AL,
                                            ammessi=_codici_ammessi_al(facts))
    prompt = (
        P["fatti"] + "\n" + (facts or "").strip()
        + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
        + "\n\n" + P["fine_an"]
    )
    md = backend.complete(
        system=_juris((_SYSTEM_IT + _FORMA_IT) if lang == "it" else (_SYSTEM + _FORMA_AL)),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, callsite="prosecutor",  # default = Opus effort=max
    )
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


def draft_indictment(backend, index, *, facts, max_tokens=3200):
    lang = _lingua()
    P = _P[lang]
    if lang == "it":
        # v9.404: + 33-bis/33-ter (tribunale collegiale o monocratico: lo decide l'atto) e 407 (durata massima delle indagini) —
        # nell'audit IT del 29 set l'atto d'accusa li dava «norma non fornita»
        seeds, n_add = _semi_it(_cpp("415-bis", "416", "417", "550", "552", "33-bis", "33-ter", "407"), facts)
        arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds, max_arts=16 + n_add)
    else:
        # v9.619: la richiesta di rinvio a giudizio (KPP 331: nulla se manca il contenuto) e l'udienza preliminare (332), la
        # commisurazione e le circostanze (KP 47, 48, 50), la parte civile (KPP 61) e l'età imputabile (KP 12) — nel ri-audit
        # dell'11 ott l'atto d'accusa le dava «non nel corpus» e lasciava [___]
        seeds, n_add = _semi_al([("kodi_proc_penale", "331"), ("kodi_proc_penale", "332"), ("kodi_penal", "47"),
                                 ("kodi_penal", "48"), ("kodi_penal", "50"), ("kodi_proc_penale", "61"), ("kodi_penal", "12")], facts,
                                extra=[("kodi_penal", "55")])      # v9.642: il concorso di reati
        arts = _expertise.retrieve_grounded(backend, index, facts, seed_pairs=seeds or None, max_arts=16 + n_add,
                                            preferiti=_PREF_AL, ammessi=_codici_ammessi_al(facts))
    prompt = (P["fatti_ind"] + "\n" + (facts or "").strip()
              + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
              + "\n\n" + P["fine_ind"])
    md = backend.complete(system=_juris((_INDICT_SYSTEM_IT + _FORMA_IT) if lang == "it" else (_INDICT_SYSTEM + _FORMA_AL)),
                          messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite="indictment")
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ═══════════════════════════════════════════════════════════════════
# SUPER PROKUROR — expansion (additive). Seeds VERIFIED against corpus.
# Two axes: (i) prosecutor-facing efficiency, (ii) citizen-facing.
# HARD RULES: always assistive — the human prosecutor/judge decides and
# signs. NEVER auto-charge, auto-dismiss, or risk-score a person (EU AI
# Act red line). Grounded only — articles from the corpus, never invented.
# ═══════════════════════════════════════════════════════════════════


def _gen(backend, index, *, facts, system, callsite, seeds=None, extra="",
         intro=None, max_tokens=2800, semi_in_piu_al=(), semi_in_piu_it=()):
    lang = _lingua()
    P = _P[lang]
    if lang == "it":
        sd, n_add = _semi_it(seeds, facts, extra=semi_in_piu_it)
        arts = _expertise.retrieve_grounded(backend, index, (facts or "") + " " + extra, seed_pairs=sd or None,
                                            max_arts=16 + n_add)
    else:
        sd, n_add = _semi_al(seeds, facts, extra=semi_in_piu_al)
        arts = _expertise.retrieve_grounded(backend, index, (facts or "") + " " + extra, seed_pairs=sd or None,
                                            max_arts=16 + n_add, preferiti=_PREF_AL, ammessi=_codici_ammessi_al(facts))
    prompt = ((intro or P["dati"]) + "\n" + (facts or "").strip()
              + "\n\n─────\n" + P["norme"] + "\n" + _blocco(arts, lang)
              + "\n\n" + P["fine"])
    md = backend.complete(system=_juris(system), messages=[{"role": "user", "content": prompt}],
                          max_tokens=max_tokens, callsite=callsite)
    return {"markdown": (md or "").strip(),
            "articles": [{"code": c, "number": n} for c, n, _t in arts]}


# ───────────────────────── (i) PROSECUTOR-FACING ─────────────────────────

def investigation_plan(backend, index, *, facts, max_tokens=2800):
    """Plani i hetimit — investigation plan from the complaint/facts."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO in Italia. Dalla notizia di reato/dai fatti, redigi un PIANO "
            "DELLE INDAGINI professionale, FONDATO SOLO sui fatti e sugli articoli forniti. NON inventare articoli. "
            "Sezioni (markdown):\n"
            "### \U0001f3af Ipotesi investigative — le versioni possibili da provare o escludere\n"
            "### \U0001f4dc Qualificazione provvisoria — il reato o i reati con l'articolo del corpus (provvisoria, non definitiva)\n"
            "### ✅ Elementi da provare — per ogni elemento: quale prova lo dimostra\n"
            "### \U0001f50e Atti d'indagine — cosa compiere (perquisizioni, sequestri, accertamenti tecnici, intercettazioni, acquisizione di dati e tabulati), in che ordine e perché\n"
            "### \U0001f465 Chi sentire — persone informate sui fatti, indagato (con le garanzie difensive), consulenti — e su cosa\n"
            "### ⏰ Termini — durata delle indagini preliminari e proroghe (verifica sulle norme, non inventare numeri)\n"
            "### ⚖️ Obiettività — anche gli elementi A FAVORE dell'indagato da cercare (art. 358 c.p.p.)\n"
            + _TETRA_IT)
        # v9.404: il piano chiede perquisizioni, sequestri, accertamenti tecnici, intercettazioni: le loro basi nel c.p.p.
        # (247, 253, 266, 359, 360, 321) — misurato: 0/3 → 3/3 col caso della truffa
        return _gen(backend, index, facts=facts, system=system, callsite="pros_plan",
                    seeds=_cpp("326", "327", "358", "335", "405", "406", "407"),
                    extra="piano delle indagini atti di indagine termini", max_tokens=max_tokens,
                    semi_in_piu_it=_cpp("247", "253", "266", "359", "360", "321"))
    system = (
        "Ti je ndihmës i një PROKURORI në Shqipëri. Nga kallëzimi/faktet, harto një PLAN HETIMI "
        "profesional, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f3af Hipotezat hetimore — versionet e mundshme që duhen provuar ose përjashtuar\n"
        "### \U0001f4dc Kualifikimi i mundshëm — vepra/at penale me nenin nga korpusi (paraprak, jo përfundimtar)\n"
        "### ✅ Elementet për t'u provuar — për secilin element: çfarë prove e provon\n"
        "### \U0001f50e Veprimet hetimore — çfarë të kryhet (kontroll, sekuestrim, ekspertim, përgjim), radha dhe përse\n"
        "### \U0001f465 Kush të pyetet — dëshmitarë, të pandehur, ekspertë — dhe çka të pyeten\n"
        "### ⏰ Afatet — afati i hetimit paraprak dhe zgjatja (verifiko me dispozitat, mos shpik numra)\n"
        "### ⚖️ Objektiviteti — edhe provat SHFAJËSUESE që duhen kërkuar (detyra e objektivitetit)\n"
        + _TETRA)
    # v9.403: il piano chiede «kontroll, sekuestrim, ekspertim, përgjim» e le misure patrimoniali — le loro basi nel KPP
    # (202 condizioni della perquisizione, 208 sequestro, 178 perizia, 221 limiti delle intercettazioni, 274 sequestro
    # preventivo) e la procedibilità (284): nell'audit del 29 set il piano le dava tutte «fuori dal corpus»
    return _gen(backend, index, facts=facts, system=system, callsite="pros_plan",
                seeds=[("kodi_proc_penale", "24"), ("kodi_proc_penale", "287"),
                       ("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "283")],
                extra="plan hetimi veprime hetimore afati", max_tokens=max_tokens,
                semi_in_piu_al=[("kodi_proc_penale", "284"), ("kodi_proc_penale", "202"), ("kodi_proc_penale", "208"),
                                ("kodi_proc_penale", "178"), ("kodi_proc_penale", "221"), ("kodi_proc_penale", "274"),
                                ("kodi_proc_penale", "144"),   # v9.618: il calcolo dei termini (KPP 144)
                                # v9.627 — la PRESCRIZIONE del reato (KP 66, con KP 1: crimine o contravvenzione) e la DURATA delle
                                # misure cautelari (KPP 263): l'audit AL del 12 ott (truffa da 5.000 €) le dava «nuk janë në korpusin
                                # e dhënë» e «jashtë korpusit»
                                ("kodi_penal", "66"), ("kodi_penal", "1"), ("kodi_proc_penale", "263")])


_ACT_KINDS = {
    # v9.642: le etichette dicono CHI decide — la perquisizione la decide il GIUDICE su richiesta (KPP 202/1, 202/a), il
    # sequestro probatorio e la nomina del perito li decide il PM stesso (208/1; 179: «organi procedues»), l'intercettazione la
    # autorizza il giudice (222/1). Prima tutte e quattro erano «Kërkesë për …» e il perito usciva come richiesta al giudice
    "kontroll": {"label": "Kërkesë për vendim kontrolli (drejtuar gjykatës)",
                 "seed": [("kodi_proc_penale", "202"), ("kodi_proc_penale", "202/a"), ("kodi_proc_penale", "204"),
                          ("kodi_proc_penale", "205")],
                 "q": "kontroll personi vendi kushtet"},
    "sekuestrim": {"label": "Vendim për sekuestrimin e provave materiale",
                   "seed": [("kodi_proc_penale", "208"), ("kodi_proc_penale", "203"), ("kodi_proc_penale", "301")],
                   "q": "sekuestrim objekti provë materiale"},
    "ekspertim": {"label": "Vendim për caktimin e ekspertit",
                  "seed": [("kodi_proc_penale", "178"), ("kodi_proc_penale", "179"),
                           ("kodi_proc_penale", "183"), ("kodi_proc_penale", "185")],
                  "q": "ekspertim ekspert detyra pyetjet"},
    "pergjim": {"label": "Kërkesë për autorizimin e përgjimit (drejtuar gjykatës)",
                # v9.399: + 222 (la decisione che autorizza: il cuore dell'atto), 223 (esecuzione), 226 (inutilizzabilità)
                "seed": [("kodi_proc_penale", "221"), ("kodi_proc_penale", "222"), ("kodi_proc_penale", "223"),
                         ("kodi_proc_penale", "226")],
                "q": "përgjim kufijtë lejimi"},
}

# Stesse chiavi (l'API e l'interfaccia non cambiano), atti e norme del c.p.p.
_ACT_KINDS_IT = {
    "kontroll": {"label": "Decreto di perquisizione (personale/locale)",
                 "seed": _cpp("247", "249", "250", "251", "191"),
                 "q": "perquisizione personale locale domicilio decreto motivato"},
    "sekuestrim": {"label": "Decreto di sequestro probatorio / richiesta di sequestro preventivo",
                   "seed": _cpp("253", "257", "262", "321", "191"),
                   "q": "sequestro probatorio preventivo corpo del reato cose pertinenti"},
    "ekspertim": {"label": "Accertamento tecnico / consulenza tecnica",
                  "seed": _cpp("359", "360", "191"),
                  "q": "consulente tecnico accertamento tecnico non ripetibile avviso difensore"},
    "pergjim": {"label": "Richiesta di autorizzazione alle intercettazioni",
                # v9.404: + art. 15 Cost. (riserva di legge e di giurisdizione), c.p.p. 103 (le comunicazioni del difensore) e
                # codice privacy 132 (i tabulati: atto distinto) — nell'audit IT «non compresi fra gli articoli recuperati»
                "seed": _cpp("266", "267", "268", "271", "103") + [("costituzione", "15"), ("codice_privacy", "132")],
                "q": "intercettazioni gravi indizi assolutamente indispensabili decreto autorizzazione"},
}


def list_act_kinds():
    kinds = _ACT_KINDS_IT if _lingua() == "it" else _ACT_KINDS
    return [{"key": k, "label": v["label"]} for k, v in kinds.items()]


def investigative_act(backend, index, *, kind, facts, max_tokens=2600):
    """Veprime hetimore — draft a request for a search/seizure/expertise/interception."""
    if _lingua() == "it":
        cfg = _ACT_KINDS_IT.get(kind) or _ACT_KINDS_IT["kontroll"]
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi il DECRETO o la RICHIESTA per l'atto d'indagine '"
            + cfg["label"] + "' secondo il codice di procedura penale, FONDATO SOLO sui fatti e sugli articoli forniti. "
            "NON inventare articoli. Dove manca un dato, lascia [___]. Sezioni (markdown):\n"
            "### \U0001f4cc Base giuridica e presupposti — gli articoli del corpus e le condizioni da soddisfare\n"
            "### \U0001f9e9 Motivazione — perché l'atto è necessario e proporzionato alle indagini\n"
            "### \U0001f4dd Testo del decreto/della richiesta — completo, pronto (oggetto, luogo/persona, cosa si dispone, avvisi e garanzie per il difensore quando dovuti)\n"
            "### ⚠️ Attenzione — cosa rispettare perché l'atto non sia nullo né la prova inutilizzabile (autorizzazione del giudice quando richiesta, termini, garanzie difensive)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_act",
                    seeds=cfg["seed"], extra=cfg["q"], max_tokens=max_tokens)
    cfg = _ACT_KINDS.get(kind) or _ACT_KINDS["kontroll"]
    system = (
        "Ti je ndihmës i një PROKURORI. Harto AKTIN për veprimin hetimor '" + cfg["label"]
        + "' sipas Kodit të Procedurës Penale — KËRKESË drejtuar gjykatës kur neni e kërkon vendimin e gjykatës, VENDIM "
        "i prokurorit kur neni ia jep atij — TË BAZUAR VETËM te faktet dhe te nenet e dhëna. MOS shpik nene. Ku mungon një "
        "e dhënë, lër [___]. Jep (markdown):\n"
        "### \U0001f4cc Baza ligjore & kushtet — nenet dhe kushtet që duhen plotësuar (deri në 6 pika)\n"
        "### \U0001f4dd Akti — teksti i plotë, gati për nënshkrim: objekti, vendi ose personi, çfarë kërkohet ose urdhërohet, "
        "arsyetimi i shkurtër (nevoja dhe proporcionaliteti), njoftimet dhe të drejtat që duhen bërë të ditura; data [___]\n"
        "### ⚠️ Kujdes — deri në 5 pika: çfarë duhet respektuar që akti të mos jetë i pavlefshëm dhe prova e papërdorshme\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_act",
                seeds=cfg["seed"], extra=cfg["q"], max_tokens=max_tokens)


def coercive_measure(backend, index, *, facts, max_tokens=2800):
    """Kërkesë për masë sigurimi — SENSITIVE (liberty). Strictly a draft; court decides."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi una RICHIESTA DI APPLICAZIONE DI MISURA CAUTELARE "
            "PERSONALE al giudice per le indagini preliminari, secondo il c.p.p., FONDATA SOLO sui fatti e sugli "
            "articoli forniti. ⚠️ È IN GIOCO LA LIBERTÀ PERSONALE: è solo una BOZZA; decide il GIUDICE. NON "
            "presentare il carcere come scontato: esponi le condizioni in modo obiettivo e scegli la misura MENO "
            "AFFLITTIVA che basta (adeguatezza e proporzionalità). NON inventare articoli. Sezioni (markdown):\n"
            "### \U0001f4dc Reato e qualificazione — gli articoli del corpus e i limiti di pena che consentono la misura\n"
            "### \U0001f50d Gravi indizi di colpevolezza — gli elementi che li sostengono, elemento per elemento\n"
            "### ⚠️ Esigenze cautelari — pericolo di inquinamento probatorio, di fuga, di reiterazione: CONCRETE e ATTUALI, non ipotetiche\n"
            "### ⚖️ Adeguatezza e proporzionalità — perché la misura richiesta e non una meno grave (obbligo di presentazione, divieto di espatrio, obbligo/divieto di dimora, arresti domiciliari)\n"
            "### \U0001f4dd Richiesta — la misura richiesta e il testo per il GIP, con l'elenco degli elementi a favore dell'indagato che il PM deve trasmettere insieme alla richiesta\n"
            "### \U0001f6e1️ La parte della difesa — cosa obietterebbe il difensore (obiettività)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_measure",
                    seeds=_cpp("272", "273", "274", "275", "280", "283", "284", "285", "291", "292"),
                    extra="misure cautelari esigenze cautelari gravi indizi criteri di scelta", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës i një PROKURORI. Harto një KËRKESË PËR MASË SIGURIMI drejtuar gjykatës, sipas "
        "KPP, TË BAZUAR VETËM te faktet dhe te nenet e dhëna. ⚠️ LIRIA E PERSONIT ËSHTË NË LOJË: "
        "kjo është VETËM PROJEKT-kërkesë; GJYKATA vendos. MOS rekomando arrestin si të sigurt — parashtro "
        "kushtet objektivisht dhe zgjidh masën më pak shtrënguese që mjafton. MOS shpik nene. Jep (markdown):\n"
        "### \U0001f4dc Vepra & kualifikimi — nenet nga korpusi\n"
        "### \U0001f50d Dyshimi i arsyeshëm (fumus) — provat që e mbështesin, element për element\n"
        "### ⚠️ Rreziqet (periculum) — rreziku i ikjes/përsëritjes/prishjes së provave, KONKRET (jo hamendje)\n"
        "### ⚖️ Proporcionaliteti — pse masa e kërkuar; a mjafton një masë më e butë (detyrim paraqitjeje, arrest shtëpie)?\n"
        "### \U0001f4dd Kërkesa — masa e kërkuar dhe teksti drejtuar gjykatës\n"
        "### \U0001f6e1️ Ana e mbrojtjes — çfarë do të kundërshtonte mbrojtja (objektiviteti)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_measure",
                seeds=[("kodi_proc_penale", "228"), ("kodi_proc_penale", "229"),
                       ("kodi_proc_penale", "230"), ("kodi_proc_penale", "232"),
                       ("kodi_proc_penale", "237"), ("kodi_proc_penale", "238"),
                       ("kodi_proc_penale", "244")],
                # v9.618: la gjykata kompetente (KPP 74), il ricorso contro la misura (249: 5 giorni) e la durata della custodia (263)
                # — nell'audit dell'11 ott «le disposizioni sulla competenza non sono nel corpus»
                semi_in_piu_al=[("kodi_proc_penale", "74"), ("kodi_proc_penale", "249"), ("kodi_proc_penale", "263")],
                extra="masë sigurimi personal arrest kushtet kriteret", max_tokens=max_tokens)


def dismissal_request(backend, index, *, facts, max_tokens=2600):
    """Kërkesë për pushim/mosfillim — SENSITIVE. Assistive draft; prosecutor decides."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente di un PUBBLICO MINISTERO. Redigi una RICHIESTA DI ARCHIVIAZIONE al giudice per le "
            "indagini preliminari, secondo il c.p.p., FONDATA SOLO sui fatti e sugli articoli forniti. LA DECISIONE "
            "SPETTA AL PUBBLICO MINISTERO E POI AL GIUDICE — è solo una bozza motivata. NON inventare articoli. "
            "Sezioni (markdown):\n"
            "### \U0001f4dc Base giuridica — infondatezza della notizia di reato per mancanza di una ragionevole previsione di condanna, oppure gli altri casi di archiviazione (condizione di procedibilità mancante, reato estinto, fatto non previsto dalla legge come reato, particolare tenuità del fatto) o autore ignoto — con gli articoli del corpus\n"
            "### \U0001f9ed Motivazione — perché non c'è luogo a procedere, elemento per elemento\n"
            "### ⚖️ Possibile opposizione — ci sono elementi che imporrebbero di proseguire le indagini? (obiettività)\n"
            "### \U0001f4e2 Avvisi — alla persona offesa che ha chiesto di essere informata e, per i delitti commessi con violenza alla persona, in ogni caso; il termine per l'opposizione (verifica sulle norme fornite)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_dismiss",
                    seeds=_cpp("408", "409", "410", "411", "415") + _cp("131-bis"),
                    # v9.404: il reato estinto per prescrizione, la querela mancante o tardiva (c.p. 120, 124) e il dovere di
                    # cercare anche gli elementi a favore (c.p.p. 358) — nell'audit IT del 29 set «non compresi fra gli articoli»
                    semi_in_piu_it=_cp("157", "158", "160", "161", "120", "124") + _cpp("358"),
                    extra="richiesta di archiviazione infondatezza notizia di reato", max_tokens=max_tokens)
    # v9.642 — l'audit del 16 ott: col reato d'AUTORE IGNOTO lo strumento proponeva il «pushim» del 328/1/ç (per l'autore ignoto
    # il KPP prevede la SOSPENSIONE delle indagini, art. 326) e, sul crimine, dava «il 329/a non è nel corpus» (la richiesta al
    # giudice dell'udienza preliminare): i semi non avevano né il 326 né il 329/a né il KP 1 (crimine o contravvenzione)
    system = (
        "Ti je ndihmës i një PROKURORI. Harto aktin për MBYLLJEN ose NDALIMIN e procedimit sipas KPP, TË BAZUAR VETËM te "
        "faktet dhe te nenet e dhëna. VENDIMI I TAKON PROKURORIT (dhe, për krimet, GJYQTARIT) — ky është projekt i arsyetuar. "
        "MOS shpik nene. Së PARI zgjidh rrugën që përcakton KPP:\n"
        "• AUTORI I PANJOHUR (nuk është identifikuar askush): nuk ka pushim — prokurori vendos PEZULLIMIN E HETIMEVE (neni "
        "326), pasi janë kryer të gjitha veprimet e mundshme; vendimi i arsyetuar i njoftohet viktimës ose kallëzuesit, që "
        "mund të ankohen brenda 10 ditëve te gjyqtari i seancës paraprake; hetimi rifillon me vendim të prokurorit.\n"
        "• Para fillimit të procedimit, kur ka një nga rrethanat e nenit 290: VENDIM PËR MOSFILLIM (neni 291).\n"
        "• Pas hetimeve, kur ka një shkak të nenit 328/1: për KUNDËRVAJTJE PENALE prokurori VENDOS vetë pushimin (neni 328, "
        "njoftimi brenda 5 ditëve, ankim neni 329); për KRIM prokurori i KËRKON gjyqtarit të seancës paraprake pushimin "
        "(neni 329/a). Vepra është kundërvajtje penale kur neni i Kodit Penal e thotë shprehimisht («përbën kundërvajtje "
        "penale»); përndryshe është krim (neni 1 KP).\n"
        "Jep (markdown):\n"
        "### \U0001f9ed Rruga — cili akt dhe pse, me nenin (deri në 3 rreshta)\n"
        "### \U0001f4dd Akti — vendimi ose kërkesa, i plotë, gati për nënshkrim (shkaku me nenin dhe arsyetimi i shkurtër)\n"
        "### \U0001f4e2 Njoftimi & ankimi — kush njoftohet, brenda sa ditësh, ku ankohet\n"
        "### ⚖️ Para se ta mbyllësh — a ka ende veprime ose prova që do të kërkonin vazhdim? (objektiviteti; deri në 5 pika)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_dismiss",
                seeds=[("kodi_proc_penale", "290"), ("kodi_proc_penale", "291"),
                       ("kodi_proc_penale", "326"), ("kodi_proc_penale", "327"),
                       ("kodi_proc_penale", "328"), ("kodi_proc_penale", "329"),
                       ("kodi_proc_penale", "329/a")],
                semi_in_piu_al=[("kodi_penal", "1"), ("kodi_penal", "66")],
                extra="pushim mosfillim pezullim procedimi", max_tokens=max_tokens)


def stress_test(backend, index, *, text, max_tokens=2600):
    """Test objektiviteti — stress-test a prosecutor work-product from the defense side."""
    if _lingua() == "it":
        system = (
            "Sei il DIFENSORE più bravo che legge un ATTO DEL PUBBLICO MINISTERO (richiesta di rinvio a giudizio, "
            "richiesta di misura, analisi) e cerca ogni debolezza PRIMA che il PM lo depositi. Fondati sul testo e "
            "sugli articoli forniti — non inventare. Sezioni (markdown):\n"
            "### \U0001f6e1️ Debolezze degli elementi — quale elemento resta non provato o fragile\n"
            "### ⚖️ Controdeduzioni — cosa solleverà la difesa su ogni punto\n"
            "### \U0001f6a8 Nullità e inutilizzabilità — atti senza autorizzazione, termini scaduti, avvisi omessi, diritti violati\n"
            "### \U0001f50e Elementi a discarico — cosa cercare a favore dell'indagato\n"
            "### ✅ Come rafforzare l'atto — cosa completare prima del deposito\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=text, system=system, callsite="pros_stress",
                    seeds=_cpp("178", "180", "181", "191", "407", "405", "415-bis"), intro=_P["it"]["stress"],   # v9.404: + 405, 415-bis
                    extra="nullità inutilizzabilità prova termini", max_tokens=max_tokens)
    system = (
        "Ti je AVOKATI MBROJTËS më i zoti, që lexon një AKT TË PROKURORISË (aktakuzë, kërkesë mase, "
        "analizë) dhe kërkon çdo dobësi PARA se ta paraqesë prokurori. Bazohu te teksti dhe te nenet e "
        "dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f6e1️ Dobësitë e provave — cili element mbetet i paprovuar ose i dobët\n"
        "### ⚖️ Kundër-argumentet — çfarë do të ngrejë mbrojtja për çdo pikë\n"
        "### \U0001f6a8 Pavlefshmëritë procedurale — veprime pa autorizim, afate të shkelura, të drejta të cenuara\n"
        "### \U0001f50e Provat shfajësuese — çka duhet kërkuar në favor të të pandehurit\n"
        "### ✅ Si të forcohet akti — çka duhet plotësuar para paraqitjes\n"
        + _TETRA)
    # v9.627 — lo stress test albanese NON aveva nessun seme (l'italiano sì): la difesa che legge l'atto cercava le nullità e la prova
    # inutilizzabile senza le norme — l'audit AL del 12 ott: «dispozita e Kodit Penal mbi ndarjen krim/kundërvajtje penale … nuk
    # është në korpusin e dhënë», e i rinvii del KPP 331 (34/a, 34/b…) «vetëm si referenca». In AGGIUNTA ai 16: la ricerca del reato
    # dell'atto resta intera
    return _gen(backend, index, facts=text, system=system, callsite="pros_stress",
                seeds=None, intro=_P["sq"]["stress"], extra="dobësi pavlefshmëri provë",
                max_tokens=max_tokens,
                semi_in_piu_al=[("kodi_proc_penale", n) for n in ("128", "129", "130", "131", "151", "34/a", "331")]
                + [("kodi_penal", "1")])


# ───────────────────────── (ii) CITIZEN-FACING ─────────────────────────

def citizen_complaint(backend, index, *, facts, max_tokens=2800):
    """Kallëzim penal builder + office router (Prokuroria vs SPAK) + attachments."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta un CITTADINO a preparare una DENUNCIA o una QUERELA corretta (ausilio, non "
            "consulenza legale ufficiale). Dal racconto, redigi l'atto COMPLETO e strutturato, FONDATO sui fatti e "
            "sugli articoli forniti. NON inventare articoli. Dove manca un dato, lascia [___]. Sezioni (markdown):\n"
            "### \U0001f4dd LA DENUNCIA / LA QUERELA — testo pronto: chi la presenta, i fatti (chi/cosa/quando/dove), il danno, le prove, le persone coinvolte (se note), la richiesta di procedere e di essere informato dell'eventuale richiesta di archiviazione. Di' se il reato è procedibile a QUERELA (con il suo termine) o d'ufficio (DENUNCIA)\n"
            "### \U0001f4cd Dove si presenta — alla Procura della Repubblica presso il Tribunale competente o a un ufficio di Polizia o dei Carabinieri; per mafia e terrorismo la competenza è della procura distrettuale; per le frodi al bilancio dell'Unione europea la Procura europea (EPPO) — spiega in breve perché\n"
            "### \U0001f4ce Documenti da allegare — elenco concreto secondo il tipo di reato\n"
            "### ⚖️ I tuoi diritti come persona offesa — in breve: informazioni, difensore, costituzione di parte civile, opposizione all'archiviazione\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_complaint",
                    # v9.404: + simulazione di reato e calunnia (c.p. 367, 368: la dichiarazione di chi denuncia) e la restituzione
                    # delle cose sequestrate (c.p.p. 262, 263)
                    seeds=_cpp("333", "336", "337", "90", "90-bis", "101", "408", "262", "263") + _cp("124", "367", "368"),
                    intro=_P["it"]["citt"], extra="denuncia querela persona offesa diritti", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të përgatisë një KALLËZIM PENAL të saktë (ndihmesë, jo "
        "këshillë ligjore zyrtare). Nga rrëfimi, harto aktin TË PLOTË dhe të strukturuar, TË BAZUAR te faktet dhe te "
        "nenet e dhëna. MOS shpik nene. Ku mungon një e dhënë, lër [___]. Së PARI përcakto RRUGËN sipas veprës (v9.642):\n"
        "• kur vepra është ndër ato të nenit 59 KPP (viktima akuzuese: p.sh. fyerja, shpifja, rrahja dhe dëmtimet e lehta, "
        "ndërhyrja në jetën private) → NUK është kallëzim në prokurori: është KËRKESË E VIKTIMËS AKUZUESE që paraqitet "
        "drejtpërdrejt në GJYKATË (neni 59 dhe 284/5), ku viktima vërteton akuzën si palë dhe kërkon shpërblimin e dëmit;\n"
        "• kur vepra është ndër ato të nenit 284/1 KPP → ndjekja fillon vetëm me ANKIMIN e viktimës, te prokurori ose te "
        "policia gjyqësore (mund të tërhiqet në çdo fazë);\n"
        "• në rastet e tjera → KALLËZIM te prokurori ose te policia gjyqësore (neni 283).\n"
        "Jep (markdown):\n"
        "### \U0001f9ed Rruga — cili akt dhe ku, me nenin (deri në 3 rreshta)\n"
        "### \U0001f4dd AKTI — teksti gati për dorëzim: kush e paraqet, të dhënat, RRETHANAT (kush/çfarë/kur/ku), dëmi, "
        "provat, personat e përfshirë (nëse dihen) dhe KËRKESA; vendi dhe data [___]\n"
        "### \U0001f4cd Ku dorëzohet — gjykata ose prokuroria kompetente sipas vendit; SPAK vetëm kur vepra është ndër ato të "
        "nenit 75/a KPP (shpjego shkurt pse)\n"
        "### \U0001f4ce Dokumentet për t'u bashkangjitur — lista konkrete sipas llojit të veprës\n"
        "### ⚖️ Të drejtat e tua si i dëmtuar — shkurt (neni 58 KPP)\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_complaint",
                seeds=[("kodi_proc_penale", "283"), ("kodi_proc_penale", "284"),
                       ("kodi_proc_penale", "59"), ("kodi_proc_penale", "58"),
                       ("kodi_proc_penale", "290")],
                semi_in_piu_al=[("kodi_penal", "66")],
                intro=_P["sq"]["citt"], extra="kallëzim ankim viktima akuzuese i dëmtuar të drejtat",
                max_tokens=max_tokens)


def victim_rights(backend, index, *, facts, max_tokens=2400):
    """Të drejtat e viktimës + shpjegim i fazave — plain-language."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che spiega a un CITTADINO, PERSONA OFFESA da un reato, i suoi diritti e le fasi del "
            "processo penale, in modo semplice e chiaro (ausilio, non consulenza ufficiale). Fondati sui fatti e sugli "
            "articoli forniti — non inventare. Sezioni (markdown):\n"
            "### ⚖️ I tuoi diritti — cosa puoi chiedere (informazioni sul procedimento, nominare un difensore, presentare memorie e indicare elementi di prova, essere avvisato della richiesta di archiviazione e opporti, comunicazioni sulla scarcerazione o evasione nei delitti con violenza alla persona, costituirti parte civile per il risarcimento)\n"
            "### \U0001f5fa️ Le fasi e cosa aspettarti — indagini preliminari, archiviazione o azione penale, udienza preliminare, dibattimento — in parole semplici\n"
            "### ⏰ I termini che ti riguardano — cosa succede quando e entro quanto puoi agire (verifica sulle norme, non inventare numeri)\n"
            "### ✅ I tuoi prossimi passi — concreti\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_victim",
                    # v9.404: + il patrocinio a spese dello Stato (d.P.R. 115/2002 art. 76, anche in deroga ai limiti di reddito)
                    # e il deposito telematico (c.p.p. 111-bis)
                    seeds=_cpp("90", "90-bis", "90-ter", "101", "74", "408", "410", "335", "111-bis") + [("tu_spese_giustizia", "76")],
                    intro=_P["it"]["vitt"], extra="persona offesa diritti informazioni fasi termini", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që i shpjegon një QYTETARI TË DËMTUAR të drejtat dhe fazat e procesit penal, "
        "thjesht dhe qartë (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos "
        "shpik. Jep (markdown):\n"
        "### ⚖️ Të drejtat e tua — çfarë mund të kërkosh (informim, akses në akte, kërkim provash, "
        "njoftim për arrestin/lirimin, ankim, dëmshpërblim si paditës civil) — bazuar në nenin 58 KPP\n"
        "### \U0001f5fa️ Fazat & çfarë presin — hetimi paraprak, vendimi (akuzë/pushim), gjykimi — thjesht\n"
        "### ⏰ Afatet që të interesojnë — kur pritet çfarë dhe brenda sa kohe mund të veprosh (verifiko, mos shpik numra)\n"
        "### ✅ Hapat e tu të radhës — konkret\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_victim",
                seeds=[("kodi_proc_penale", "58"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "329"), ("kodi_proc_penale", "323")],
                # v9.403: KPP 291 — il ricorso contro il decreto di non avvio del procedimento (10 giorni dalla notifica):
                # nell'audit del 29 set il termine era «non dato nei testi»
                # v9.618: + il calcolo dei termini; v9.619: + KPP 324 (proroga delle indagini) e 329/a (richiesta di archiviazione al
                # giudice), che il 327 richiama — nel ri-audit «il testo del 329/a e del 324 non è nel mio corpus»
                semi_in_piu_al=[("kodi_proc_penale", "291"), ("kodi_proc_penale", "144"), ("kodi_proc_penale", "324"),
                                ("kodi_proc_penale", "329/a"),
                                # v9.642: la vittima-accusatrice (KPP 59) e la parte civile nel processo penale (61)
                                ("kodi_proc_penale", "59"), ("kodi_proc_penale", "61")],
                intro=_P["sq"]["vitt"], extra="të drejtat i dëmtuar faza afati",
                max_tokens=max_tokens)


def dismissal_appeal(backend, index, *, facts, max_tokens=2600):
    """Ankim kundër pushimit/mosfillimit — decode + draft the victim's appeal. SENSITIVE deadline."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta una PERSONA OFFESA a capire una RICHIESTA o un PROVVEDIMENTO DI ARCHIVIAZIONE "
            "e a preparare l'OPPOSIZIONE alla richiesta di archiviazione — oppure, se l'archiviazione è già stata "
            "disposta con un vizio, il RECLAMO per nullità (ausilio, non consulenza ufficiale). Fondati sui fatti e "
            "sugli articoli forniti — non inventare. ⚠️ I TERMINI sono decisivi — sottolinea che vanno verificati con "
            "un avvocato e sulle norme. Sezioni (markdown):\n"
            "### \U0001f50e Cosa dice il provvedimento — spiegazione semplice delle ragioni dell'archiviazione\n"
            "### ⚖️ C'è base per opporsi — i punti deboli; ricorda che l'opposizione deve indicare, a pena di inammissibilità, l'oggetto dell'investigazione suppletiva e i relativi elementi di prova\n"
            "### \U0001f4dd L'OPPOSIZIONE (o il RECLAMO) — testo strutturato, rivolto al giudice competente\n"
            "### ⏰ Il termine — entro quando va presentata (VERIFICA sulle norme/con l'avvocato — non tardare)\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_appeal",
                    seeds=_cpp("408", "409", "410", "410-bis", "411"),
                    intro=_P["it"]["app"], extra="opposizione archiviazione termine reclamo nullità", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR TË DËMTUAR të kuptojë një vendim që mbyll ose ndal procedimin dhe të "
        "përgatisë ANKIMIN (ndihmesë, jo këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos shpik. Dallo aktin "
        "(v9.642):\n"
        "• VENDIM PËR MOSFILLIM (neni 291) → ankim brenda 10 ditëve nga njoftimi, në gjykatë (gjyqtari që gjykon kërkesat "
        "gjatë hetimeve paraprake);\n"
        "• VENDIM PËR PUSHIM nga prokurori (neni 328, kundërvajtje) → ankim brenda 10 ditëve nga marrja dijeni, te gjyqtari i "
        "seancës paraprake (neni 329);\n"
        "• VENDIM PËR PEZULLIMIN E HETIMEVE (neni 326, autori i panjohur) → ankim brenda 10 ditëve nga marrja dijeni, te "
        "gjyqtari i seancës paraprake;\n"
        "• KËRKESË E PROKURORIT PËR PUSHIM (neni 329/a, krim) → viktima njoftohet dhe parashtron pikëpamjet para gjyqtarit; "
        "kundër vendimit të gjyqtarit për pushim (neni 329/6) ankohet në gjykatën e apelit.\n"
        "⚠️ AFATET janë vendimtare: llogarite datën e fundit nga data e njoftimit që jep qytetari dhe thuaje qartë; nëse ka "
        "kaluar, thuaje hapur. Jep (markdown):\n"
        "### \U0001f50e Çfarë thotë vendimi — shpjegim i thjeshtë (deri në 5 rreshta)\n"
        "### ⚖️ A ka bazë ankimi — pikat e dobëta të vendimit, me nenin\n"
        "### \U0001f4dd ANKIMI — teksti i strukturuar, drejtuar gjykatës kompetente (data [___])\n"
        "### ⏰ Afati — data e fundit dhe ku depozitohet\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_appeal",
                seeds=[("kodi_proc_penale", "291"), ("kodi_proc_penale", "292"),
                       ("kodi_proc_penale", "326"), ("kodi_proc_penale", "328"),
                       ("kodi_proc_penale", "329"), ("kodi_proc_penale", "329/a"),
                       ("kodi_proc_penale", "284")],
                semi_in_piu_al=[("kodi_proc_penale", "58"), ("kodi_proc_penale", "144")],
                intro=_P["sq"]["app"], extra="ankim pushim mosfillim pezullim afati",
                max_tokens=max_tokens)


def delay_complaint(backend, index, *, facts, max_tokens=2400):
    """Ankesa për vonesa — escalation to the office + Avokati i Popullit + doc-copy request."""
    if _lingua() == "it":
        system = (
            "Sei l'assistente che aiuta un CITTADINO, PERSONA OFFESA, a sollecitare un procedimento penale fermo "
            "(ausilio, non consulenza ufficiale). Fondati sui fatti e sugli articoli forniti — non inventare. "
            "Sezioni (markdown):\n"
            "### \U0001f4e8 Istanza al Pubblico Ministero — testo che sollecita la definizione e chiede informazioni sullo stato del procedimento, richiamando i termini delle indagini preliminari\n"
            "### \U0001f3db️ Richiesta di avocazione al Procuratore generale — quando i termini sono scaduti senza che il PM abbia chiesto l'archiviazione o esercitato l'azione penale: testo breve\n"
            "### \U0001f4c4 Richiesta di copie degli atti — il testo, e quali atti si possono ottenere e quando\n"
            "### ✅ Consigli pratici — come depositarle (protocollo, PEC) e cosa conservare\n"
            + _TETRA_IT)
        return _gen(backend, index, facts=facts, system=system, callsite="pros_delay",
                    seeds=_cpp("335", "405", "406", "407", "412", "413", "116"),
                    intro=_P["it"]["del"], extra="termini indagini avocazione sollecito copie atti", max_tokens=max_tokens)
    system = (
        "Ti je ndihmës që e ndihmon një QYTETAR të ankohet për VONESA në hetim/procedim (ndihmesë, jo "
        "këshillë zyrtare). Bazohu te faktet dhe te nenet e dhëna — mos shpik. Jep (markdown):\n"
        "### \U0001f4e8 Ankesa te Prokuroria — teksti drejtuar prokurorit/kryeprokurorit, që kërkon "
        "përshpejtim dhe informim mbi ecurinë (referto afatin e hetimit, neni 323/324 KPP)\n"
        "### \U0001f3db️ Ankesa te Avokati i Popullit — teksti i shkurtër i ankesës për vonesë/mosveprim\n"
        "### \U0001f4c4 Kërkesë për kopje aktesh — teksti për të marrë kopje të akteve të çështjes\n"
        "### ✅ Këshilla praktike — si t'i protokollosh dhe çka të ruash\n"
        + _TETRA)
    return _gen(backend, index, facts=facts, system=system, callsite="pros_delay",
                seeds=[("kodi_proc_penale", "323"), ("kodi_proc_penale", "324"),
                       ("kodi_proc_penale", "58")],
                # v9.642: la registrazione della notizia di reato (287), i 15 giorni per il non avvio (291), il ricorso contro
                # la proroga delle indagini (325)
                semi_in_piu_al=[("kodi_proc_penale", "287"), ("kodi_proc_penale", "291"), ("kodi_proc_penale", "325")],
                intro=_P["sq"]["del"], extra="vonesa ankesa afati hetimit",
                max_tokens=max_tokens)
