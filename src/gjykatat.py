"""v9.653 — I NOMI DI OGGI DEI TRIBUNALI ALBANESI, in un punto solo.

Contato sulle risposte albanesi dei 60 giorni (17 ott): 23 volte il nome vecchio contro 15 il nuovo — «Gjykata kompetente
është Gjykata e Rrethit Gjyqësor sipas vendbanimit…», «Kërkesa për regjistrim paraqitet në Gjykatën e Rrethit Gjyqësor
Tiranë» (con la ligji 80/2021 del corpus che dice «Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm»). Il modello
li ha imparati dai testi di prima; la ligji 98/2016 (nel corpus) chiama le corti «gjykata me juridiksion të përgjithshëm të
shkallës së parë / të apelit» (art. 3/2) e il «rreth gjyqësor» è solo il territorio di una corte di primo grado (art. 15/1);
il nome ufficiale delle sedi è quello del portale delle corti («Gjykata e Shkallës së Parë e Juridiksionit të Përgjithshëm
Tiranë», «Gjykata e Apelit e Juridiksionit të Përgjithshëm Durrës»). In un atto o in un consiglio su dove depositare il nome
vecchio è un errore di forma che un avvocato albanese vede subito. Un vendim di allora si cita col nome della corte che l'ha
dato, e il testo di una legge vecchia citato alla lettera resta com'è («gjykata e rrethit gjyqësor» nella 110/2018).
Il lato italiano è pulito (stessa misura: «Corte di giustizia tributaria» 9, «Commissione tributaria» 0; il «pretore»
dell'art. 6 L. 604/1966 segnalato da sé come testo storico): niente regola italiana.
Senza import: brain e gli strumenti la importano senza cicli.
"""

EMRAT_GJYKATAVE_AL = (
    "EMRAT E GJYKATAVE (forma e sotme zyrtare): gjykata e shkallës së parë quhet «Gjykata e Shkallës së Parë e Juridiksionit "
    "të Përgjithshëm [qyteti]» dhe ajo e apelit «Gjykata e Apelit e Juridiksionit të Përgjithshëm [selia]» (ligji nr. 98/2016, "
    "nenet 3 dhe 15: «rrethi gjyqësor» është vetëm territori i gjykatës së shkallës së parë); në çështjet administrative "
    "«Gjykata Administrative e Shkallës së Parë [qyteti]» dhe «Gjykata Administrative e Apelit». Në një akt, në një shkresë "
    "dhe kur thua ku depozitohet, MOS përdor emrat e vjetër «Gjykata e Rrethit Gjyqësor …» apo «Gjykata e Apelit Tiranë / "
    "Durrës / Shkodër / Vlorë / Korçë / Gjirokastër». Një vendim i vjetër cilësohet me emrin e gjykatës që e dha, dhe teksti "
    "i një ligji i cituar fjalë për fjalë mbetet ashtu si është."
)


def blloku_al() -> str:
    """La regola da accodare a un prompt di sistema, SOLO in sessione albanese (in sessione italiana: stringa vuota)."""
    try:
        from .brain import request_jurisdiction
        if (request_jurisdiction() or "AL").upper() != "AL":
            return ""
    except Exception:  # noqa: BLE001 — senza contesto di richiesta vale la regola albanese (i prompt sono albanesi)
        pass
    return "\n\n" + EMRAT_GJYKATAVE_AL
