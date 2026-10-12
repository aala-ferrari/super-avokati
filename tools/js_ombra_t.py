"""v9.630 — le chiamate a `t(...)` (la traduzione del client) che finiscono su una `t` LOCALE.

In app.js `t()` traduce. Una variabile o un parametro di nome `t` in una funzione la nasconde in TUTTA la funzione (`var` vale
per l'intera funzione, anche prima della riga dove compare): `t("…")` lancia «t is not a function» e tutto ciò che segue nella
funzione non gira più. Il 12 ott ha spento così, dal 19 agosto, il redattore degli atti notarili dall'interfaccia: `showMust()`
aveva `var t = types.filter(…)[0]` e poi `t("Klauzolat e detyrueshme:")` → il gestore del pulsante «Harto aktin» non veniva mai
agganciato. Gli audit chiamano l'API e non se ne accorgono.

Analisi statica senza dipendenze: tokenizzatore (stringhe, template con `${…}`, commenti, regex), ambiti di funzione e di freccia,
dichiarazioni (parametri, var, let, const, function). Per ogni chiamata `t(` si cerca la dichiarazione più vicina: se non è la
`function t(` della traduzione, è un difetto. Uso: python3 tools/js_ombra_t.py static/app.js [altri.js] → righe dei difetti,
esce 1 se ce ne sono."""
import re
import sys

_ID = re.compile(r"[A-Za-z_$][\w$]*")
_PUNT = ["===", "!==", "**=", "...", "=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=",
         "%=", "&=", "|=", "^=", "<<", ">>"]
_REGEX_DOPO = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void",
                                              "throw", "=>", "==", "===", "!=", "!==", "&&", "||", "??", "+=", "-="}


def tokenize(src):
    """[(tipo, valore, riga)] con tipo in id/punt/str/num/re; le espressioni dei template diventano token normali."""
    out = []
    i, n, riga = 0, len(src), 1
    stack = []          # contesti dei template aperti: profondità di graffe dentro ${…}

    def ultimo():
        for k in range(len(out) - 1, -1, -1):
            return out[k]
        return None

    while i < n:
        c = src[i]
        if c == "\n":
            riga += 1; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            riga += src.count("\n", i, j); i = j; continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    riga += 1
                j += 1
            out.append(("str", src[i:j + 1], riga)); i = j + 1; continue
        if c == "`" or (c == "}" and stack and stack[-1] == 0):
            # inizio di un template, o ripresa dopo una ${…}
            if c == "}":
                stack.pop()
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2; continue
                if src[j] == "\n":
                    riga += 1
                if src[j] == "`":
                    break
                if src.startswith("${", j):
                    break
                j += 1
            if j < n and src.startswith("${", j):
                out.append(("str", src[i:j], riga)); stack.append(0); i = j + 2
            else:
                out.append(("str", src[i:j + 1], riga)); i = j + 1
            continue
        if c == "{" and stack:
            stack[-1] += 1
        elif c == "}" and stack:
            stack[-1] -= 1
        if c == "/":
            u = ultimo()
            if u is None or (u[0] == "punt" and u[1] in _REGEX_DOPO) or (u[0] == "id" and u[1] in _REGEX_DOPO):
                j, classe = i + 1, False
                while j < n:
                    if src[j] == "\\":
                        j += 2; continue
                    if src[j] == "[":
                        classe = True
                    elif src[j] == "]":
                        classe = False
                    elif src[j] == "/" and not classe:
                        break
                    elif src[j] == "\n":
                        break
                    j += 1
                j += 1
                while j < n and (src[j].isalpha()):
                    j += 1
                out.append(("re", src[i:j], riga)); i = j; continue
        m = _ID.match(src, i)
        if m:
            out.append(("id", m.group(0), riga)); i = m.end(); continue
        if c.isdigit():
            m = re.match(r"\d[\w.]*", src[i:])
            out.append(("num", m.group(0), riga)); i += len(m.group(0)); continue
        for p in _PUNT:
            if src.startswith(p, i):
                out.append(("punt", p, riga)); i += len(p); break
        else:
            out.append(("punt", c, riga)); i += 1
    return out


class Ambito:
    def __init__(self, padre, tipo, riga):
        self.padre, self.tipo, self.riga = padre, tipo, riga
        self.nomi = {}          # nome → (genere, riga)


def _params(toks, a, b):
    """Gli identificatori dei parametri fra i token a..b (esclusi), senza i valori predefiniti."""
    nomi, prof, attesa = [], 0, True
    for k in range(a, b):
        t, v, _ = toks[k]
        if t == "punt" and v in "([{":
            prof += 1
        elif t == "punt" and v in ")]}":
            prof -= 1
        elif t == "punt" and v == "," and prof == 0:
            attesa = True; continue
        elif t == "punt" and v == "=" and prof == 0:
            attesa = False
        elif t == "id" and attesa and prof >= 0:
            nomi.append(v); attesa = False if prof == 0 else attesa
    return nomi


def analizza(src):
    toks = tokenize(src)
    radice = Ambito(None, "radice", 0)
    # 1) i corpi delle funzioni: indice del token «{» → (parametri, riga); frecce con corpo espressione: (inizio, fine)
    corpi, espr = {}, []
    k = 0
    while k < len(toks):
        t, v, r = toks[k]
        if t == "id" and v == "function":
            j = k + 1
            if j < len(toks) and toks[j][0] == "id":
                j += 1
            if j < len(toks) and toks[j][1] == "(":
                prof, q = 0, j
                while q < len(toks):
                    if toks[q][1] == "(":
                        prof += 1
                    elif toks[q][1] == ")":
                        prof -= 1
                        if prof == 0:
                            break
                    q += 1
                if q + 1 < len(toks) and toks[q + 1][1] == "{":
                    corpi[q + 1] = (_params(toks, j + 1, q), r)
        if t == "punt" and v == "=>":
            # parametri
            if toks[k - 1][1] == ")":
                prof, q = 0, k - 1
                while q >= 0:
                    if toks[q][1] == ")":
                        prof += 1
                    elif toks[q][1] == "(":
                        prof -= 1
                        if prof == 0:
                            break
                    q -= 1
                params = _params(toks, q + 1, k - 1)
            else:
                params = [toks[k - 1][1]] if toks[k - 1][0] == "id" else []
            if k + 1 < len(toks) and toks[k + 1][1] == "{":
                corpi[k + 1] = (params, r)
            else:
                prof, q = 0, k + 1
                while q < len(toks):
                    vv = toks[q][1]
                    if vv in "([{":
                        prof += 1
                    elif vv in ")]}":
                        if prof == 0:
                            break
                        prof -= 1
                    elif vv in (",", ";") and prof == 0:
                        break
                    q += 1
                espr.append((k + 1, q, params, r))
        k += 1
    # 2) gli ambiti: un token appartiene all'ambito più interno che lo contiene
    amb_tok = [None] * len(toks)
    pila = [(radice, None)]                # (ambito, indice della «{» che lo chiude se è un corpo)
    graffe = []                            # per ogni «{» aperta: True se apre un corpo di funzione
    espr_ini = {}
    for (a, b, params, r) in espr:
        espr_ini.setdefault(a, []).append((b, params, r))
    espr_aperte = []                       # (fine, ambito)
    for k, (t, v, r) in enumerate(toks):
        while espr_aperte and k >= espr_aperte[-1][0]:
            espr_aperte.pop(); pila.pop()
        for (b, params, rr) in espr_ini.get(k, []):
            nuovo = Ambito(pila[-1][0], "freccia", rr)
            for p in params:
                nuovo.nomi.setdefault(p, ("parametro", rr))
            pila.append((nuovo, None)); espr_aperte.append((b, nuovo))
        if t == "punt" and v == "{":
            if k in corpi:
                params, rr = corpi[k]
                nuovo = Ambito(pila[-1][0], "funzione", rr)
                for p in params:
                    nuovo.nomi.setdefault(p, ("parametro", rr))
                pila.append((nuovo, k)); graffe.append(True)
            else:
                graffe.append(False)
        elif t == "punt" and v == "}":
            if graffe and graffe.pop():
                pila.pop()
        amb_tok[k] = pila[-1][0]
    # 3) le dichiarazioni (var/let/const/function NOME) nell'ambito di funzione che le contiene
    for k, (t, v, r) in enumerate(toks):
        if t != "id":
            continue
        if v in ("var", "let", "const") and k + 1 < len(toks):
            # nomi dopo var e dopo le virgole a profondità 0 fino al «;»
            prof, q, attesa = 0, k + 1, True
            while q < len(toks):
                tt, vv, _ = toks[q]
                if vv in "([{":
                    prof += 1
                elif vv in ")]}":
                    if prof == 0:
                        break
                    prof -= 1
                elif vv == ";" and prof == 0:
                    break
                elif vv == "," and prof == 0:
                    attesa = True; q += 1; continue
                elif tt == "id" and attesa and prof == 0:
                    if vv not in ("in", "of"):
                        amb_tok[k].nomi.setdefault(vv, (v, r))
                    attesa = False
                elif vv == "=" and prof == 0:
                    attesa = False
                q += 1
        elif v == "function" and k + 1 < len(toks) and toks[k + 1][0] == "id":
            amb = amb_tok[k]
            amb.nomi.setdefault(toks[k + 1][1], ("function", r))
    # 4) le chiamate t(
    difetti = []
    for k, (t, v, r) in enumerate(toks):
        if t == "id" and v == "t" and k + 1 < len(toks) and toks[k + 1][1] == "(" and not (k and toks[k - 1][1] in (".", "?.")):
            if k and toks[k - 1][0] == "id" and toks[k - 1][1] == "function":
                continue
            a = amb_tok[k]
            while a is not None and "t" not in a.nomi:
                a = a.padre
            if a is not None and a.nomi["t"][0] != "function":
                difetti.append((r, a.nomi["t"][0], a.nomi["t"][1], a.tipo, a.riga))
    return difetti


def main(argv):
    tot = 0
    for f in argv or ["static/app.js"]:
        src = open(f, encoding="utf-8").read()
        d = analizza(src)
        for (r, genere, rd, tipo, ra) in d:
            print(f"{f}:{r}: t(…) su una «t» locale ({genere}, riga {rd}, {tipo} della riga {ra})")
        tot += len(d)
    print(f"chiamate t() nascoste: {tot}")
    return 1 if tot else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
