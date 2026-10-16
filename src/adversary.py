"""Kundershtari — the Adversary. Fable plays the OPPOSING counsel and attacks
a contract/act the lawyer pastes, finding every weakness before the other side
does. Additive; output citations pass the Verifikuar shield.
"""
from __future__ import annotations

from .logging_utils import get_logger

def _juris(system_prompt: str) -> str:
    """System prompt adattato alla giurisdizione della richiesta.

    Import differito: brain.py importa alcuni di questi moduli, quindi un
    import in testa creerebbe un ciclo."""
    try:
        from .brain import apply_current
        return apply_current(system_prompt)
    except Exception:  # noqa: BLE001
        return system_prompt



log = get_logger(__name__)

from .config import FABLE_MODEL_ID as FABLE_MODEL  # v9.393: nome esplicito (l'alias «fable» dipende dalla versione del CLI)

# v9.645 — RADICATO: riceve gli articoli che le clausole chiamano in causa (`web._red_team`: `semi_contratti` + il recupero del
# cervello) e cita solo da lì. Prima «MOS shpik nene — nëse citon një nen, sigurohu që është real» lo mandava a VERIFICARE sul
# web: nell'audit del 17 ott 23 minuti e 1,5 milioni di token di contesto per leggere il Codice civile da infocip.org e la legge
# sull'arbitrato da un PDF di un'università russa — e il neni 28 della legge sui consumatori citato da una versione del 2008.
# Il prompt albanese era scritto con «E» al posto di «ë» («DobEsitE», «pamEshirshEm»): riscritto; e la versione italiana.
_SYSTEM = (
    "Ti je AVOKATI I PALËS KUNDËRSHTARE \u2014 i ftohtë, i pamëshirshëm, gjenial. "
    "Të jepet një KONTRATË ose AKT i hartuar nga pala tjetër. Detyra jote: SULMOJE. "
    "Gjej çdo dobësi, kurth, paqartësi dhe çdo mbrojtje që MUNGON, dhe trego "
    "SAKTËSISHT si do ta shfrytëzoje në gjyq kundër atij që e hartoi. Ji specifik "
    "\u2014 cito klauzolën ose pikën konkrete të dobët dhe pasojën e saj. Bazohu te "
    "teksti dhe te e drejta shqiptare. Shqip, i mprehtë. Mos zbulo kurrë modelin \u2014 je "
    "'Tetramorph' i superavokati.ai.\n\n"
    "NENET: nëse të jepet blloku KONTEKST/NENE, çdo nen ose ligj që citon merret prej tij, me numrin dhe kodin "
    "ashtu si në bllok \u2014 teksti zyrtar i korpusit është aty: mos e kërko në internet. Një nen që nuk është në "
    "bllok nuk citohet me numër: thuaje me fjalë dhe shëno «për t'u verifikuar». Pa bllok: mos shpik nene.\n\n"
    "FORMA: rreth 1.200 fjalë; asnjë hyrje për kërkimin ose verifikimin \u2014 fillo me goditjen.\n\n"
    "Format (markdown): ### \u2694\ufe0f Dobësitë\n### \u26a0\ufe0f Kurthet\n"
    "### \U0001f573\ufe0f Mbrojtja që mungon\n### \U0001f4a5 Si do ta godisja"
)

_SYSTEM_IT = (
    "Sei l'AVVOCATO DELLA CONTROPARTE \u2014 freddo, spietato, geniale. "
    "Ti viene dato un CONTRATTO o un ATTO scritto dall'altra parte. Il tuo compito: ATTACCARLO. "
    "Trova ogni debolezza, trappola, ambiguità e ogni tutela che MANCA, e mostra ESATTAMENTE come la sfrutteresti "
    "in giudizio contro chi l'ha scritto. Sii specifico \u2014 cita la clausola o il punto debole e la sua "
    "conseguenza. Basati sul testo e sul diritto italiano. SOLO in italiano, tagliente. Non rivelare mai il modello "
    "\u2014 sei 'Tetramorph' di superavokati.ai.\n\n"
    "ARTICOLI: se ti viene dato il blocco CONTESTO/ARTICOLI, ogni articolo o legge che citi viene da lì, con numero e "
    "codice come nel blocco \u2014 il testo ufficiale del corpus è lì: non cercarlo sul web. Un articolo che non è nel "
    "blocco non si cita col numero: dillo a parole e segna «da verificare». Senza blocco: non inventare articoli.\n"
    "BUDGET DI RICERCA: al massimo 3 ricerche web, solo per la giurisprudenza sulle clausole; mai aprire il PDF intero "
    "di un codice o di una legge.\n\n"
    "FORMA: circa 1.200 parole; nessuna introduzione sulla ricerca o sulla verifica \u2014 comincia dall'attacco.\n\n"
    "Formato (markdown): ### \u2694\ufe0f Le debolezze\n### \u26a0\ufe0f Le trappole\n"
    "### \U0001f573\ufe0f Le tutele che mancano\n### \U0001f4a5 Come lo colpirei"
)


def attack(backend, *, text: str, context: str = "", lang: str | None = None, max_tokens: int = 2200) -> dict:
    from .second_opinion import _konteksti, _lingua
    lang = lang or _lingua()
    it = lang == "it"
    if it:
        prompt = ("DOCUMENTO DA ATTACCARE:\n" + (text or "").strip()
                  + "\n\nAttaccalo da avvocato della controparte." + _konteksti(context, "it"))
    else:
        prompt = ("DOKUMENTI PËR T\u2019U SULMUAR:\n" + (text or "").strip()
                  + "\n\nSulmoje si avokati i palës kundërshtare." + _konteksti(context, "sq"))
    md = backend.complete(
        system=_juris(_SYSTEM_IT if it else _SYSTEM),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        model_override=FABLE_MODEL,
        callsite="adversary",
        # in Albania il corpus è completo e il web portava versioni vecchie; in Italia serve alla giurisprudenza
        **({} if it else {"no_web": True}),
    )
    return {"markdown": (md or "").strip()}
