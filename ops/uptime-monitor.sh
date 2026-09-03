#!/bin/bash
# Uptime monitor ecosistema AALA — versione severa (31/08/2026).
#
# ⚠️ PERCHE' E' STATO RISCRITTO. La versione precedente accettava qualunque
# codice 2xx o 3xx senza seguire il redirect. Il 31 agosto 2026 questo l'ha
# tenuta cieca su DUE siti irraggiungibili insieme: aala.global e
# auto.aala.global rimandavano tutti i visitatori a `https://localhost:3000/it`
# e `https://localhost:3001/sq` — cioe' al computer di chi guardava. Il
# monitor li dava per vivi, perche' un 307 e' pur sempre una risposta.
# Googlebot prendeva 500 e nessuno lo sapeva.
#
# Adesso un sito e' "vivo" solo se supera TUTTE e quattro le prove:
#   1. seguendo i redirect si arriva a un **200**;
#   2. si finisce ancora **sul dominio giusto** (e' questa che prende il
#      redirect verso localhost, e nessun'altra);
#   3. il corpo contiene un **marcatore** noto — cioe' e' davvero la pagina
#      che ci aspettiamo, non una pagina d'errore che risponde 200;
#   4. il corpo ha una **dimensione minima** — un guscio HTML vuoto passa i
#      controlli precedenti ma non e' un sito.
#
# Prima di gridare al lupo riprova una volta dopo 20 secondi: le prove sono
# piu' severe, quindi anche piu' facili da far fallire da un singolo
# singhiozzo di rete, e un allarme che grida per niente si impara a ignorare.
#
# Manda l'email solo sui CAMBI di stato (up->down, down->up), e dice SEMPRE
# quale delle quattro prove e' fallita: "e' giu'" senza il motivo costringe a
# ricominciare l'indagine da zero.
#
# Cron ogni 5 minuti.

# Un giro solo per volta. Con 9 controlli, due tentativi ciascuno e 20s di
# attesa fra i due, un guasto generale farebbe durare il giro piu' dei 5
# minuti del cron: senza lucchetto i giri si accavallerebbero proprio nel
# momento peggiore, cioe' mentre tutto e' gia' rotto.
exec 9>/var/lock/uptime-monitor.lock
flock -n 9 || { echo "$(date '+%F %T') giro precedente ancora in corso, salto"; exit 0; }

KEY=$(grep -E '^RESEND_API_KEY=' /var/www/apps/aala/.env.local | cut -d= -f2- | tr -d '" ')
FROM="AALA Monitor <njoftim@aala.global>"
TO="info@aala.global"
STATE=/var/lib/uptime-monitor
mkdir -p "$STATE"

# nome | url | dominio_finale_atteso | marcatore (regex) | byte minimi
#
# Il dominio finale e' la prova che vale piu' di tutte: un sito che rimanda
# altrove — a localhost, a un dominio scaduto, a una pagina di parcheggio —
# non e' online, per quanto risponda.
CHECKS=(
  "aala.global|https://aala.global|aala.global|AALA|40000"
  "aala.global/servizi|https://aala.global/it/servizi/legal|aala.global|Super Avokati|40000"
  "superavokati.ai|https://superavokati.ai|superavokati.ai|Super Avokati|20000"
  "superavokati.ai/verifikimi|https://superavokati.ai/verifikimi|superavokati.ai|verifikojm|8000"
  "superavokati.ai/legale|https://superavokati.ai/legale|superavokati.ai|Kushtet|5000"
  "auto.aala.global|https://auto.aala.global|auto.aala.global|Auto Rental|8000"
  "taxi.aala.global|https://taxi.aala.global|taxi.aala.global|Taxi|5000"
  "api.taxi.aala.global|https://api.taxi.aala.global/health|api.taxi.aala.global|\"ok\":true|10"
  "crm.aala.global|https://crm.aala.global|crm.aala.global|Medical Albania|3000"
  "nabuel.com|https://nabuel.com|nabuel.com|Nabuel|3000"
  "corea.aala.global|https://corea.aala.global|corea.aala.global|encar|40000"
  "corea.aala.global/cars|https://corea.aala.global/sq/cars|corea.aala.global|encar|40000"
)

send_alert() {
  local subj="$1" body="$2"
  if [ -z "$KEY" ]; then
    echo "$(date '+%F %T') ⚠️ RESEND_API_KEY assente: nessun allarme puo' partire"
    return 1
  fi
  # le virgolette nel corpo romperebbero il JSON
  body=$(printf '%s' "$body" | sed 's/"/\\"/g')
  subj=$(printf '%s' "$subj" | sed 's/"/\\"/g')
  local risposta
  risposta=$(curl -s -m 20 -X POST https://api.resend.com/emails \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d "{\"from\":\"$FROM\",\"to\":[\"$TO\"],\"subject\":\"$subj\",\"html\":\"<p>$body</p>\"}" 2>&1)
  # Resend risponde con un {"id":"..."} se ha preso in carico l'email.
  # Qualunque altra cosa e' un invio NON avvenuto, e va scritto nel log:
  # un allarme che fallisce in silenzio e' peggio di nessun allarme, perche'
  # il silenzio si legge come «tutto bene».
  if ! printf '%s' "$risposta" | grep -q '"id"'; then
    echo "$(date '+%F %T') ⚠️ RISPOSTA RESEND inattesa, email NON partita: $(printf '%s' "$risposta" | head -c 300)"
    return 1
  fi
  return 0
}

# Esegue le quattro prove. Stampa "" se tutto bene, altrimenti il motivo.
verifica() {
  local url="$1" dominio="$2" marcatore="$3" minimo="$4"
  local corpo=$(mktemp)
  local r code fine size host

  r=$(curl -sL --max-redirs 5 -m 25 -o "$corpo" \
      -w '%{http_code}|%{url_effective}|%{size_download}' "$url" 2>/dev/null)
  IFS='|' read -r code fine size <<< "$r"

  if [ -z "$code" ] || [ "$code" = "000" ]; then
    rm -f "$corpo"; echo "nessuna risposta (rete o timeout a 25s)"; return
  fi
  if [ "$code" != "200" ]; then
    rm -f "$corpo"; echo "HTTP $code (atteso 200) — finito su $fine"; return
  fi

  # dominio finale: e' questa la prova che smaschera il redirect a localhost
  host=$(printf '%s' "$fine" | sed -E 's#^[a-z]+://##; s#[/:].*$##')
  if [ "$host" != "$dominio" ]; then
    rm -f "$corpo"
    echo "rimanda FUORI DOMINIO: atteso $dominio, arrivato su $host ($fine)"; return
  fi

  if [ "${size:-0}" -lt "$minimo" ]; then
    rm -f "$corpo"; echo "pagina troppo piccola: $size byte (minimo $minimo)"; return
  fi
  if ! grep -qE "$marcatore" "$corpo" 2>/dev/null; then
    rm -f "$corpo"
    echo "risponde 200 ma NON e' la pagina attesa (manca «$marcatore»)"; return
  fi

  rm -f "$corpo"
  echo ""
}

TEST_MODE="$1"
GUASTI=0

for row in "${CHECKS[@]}"; do
  IFS='|' read -r name url dominio marcatore minimo <<< "$row"

  motivo=$(verifica "$url" "$dominio" "$marcatore" "$minimo")
  # Seconda occasione: le prove severe sono anche piu' fragili a un
  # singhiozzo di rete, e un allarme che grida per niente viene ignorato.
  if [ -n "$motivo" ]; then
    sleep 20
    motivo=$(verifica "$url" "$dominio" "$marcatore" "$minimo")
  fi

  if [ -z "$motivo" ]; then cur=up; else cur=down; GUASTI=$((GUASTI+1)); fi
  file="$STATE/$(printf '%s' "$name" | tr '/' '_')"
  prev=$(cat "$file" 2>/dev/null || echo up)
  echo "$cur" > "$file"

  if [ "$cur" != "$prev" ]; then
    if [ "$cur" = down ]; then
      send_alert "🔴 DOWN: $name" \
        "<b>$name</b> non supera il controllo.<br><br>Motivo: <b>$motivo</b><br>URL: $url<br>$(date '+%F %T')"
    else
      send_alert "🟢 Tornato su: $name" \
        "<b>$name</b> risponde di nuovo correttamente — $(date '+%F %T')"
    fi
    echo "$(date '+%F %T') CAMBIO $name: $prev -> $cur ${motivo:+($motivo)}"
  elif [ "$cur" = down ]; then
    # Resta giu': niente email (non si fa spam), ma nel log ci va sempre.
    echo "$(date '+%F %T') ancora giu' $name ($motivo)"
  fi

  [ "$TEST_MODE" = "verbose" ] && printf '  %-24s %s\n' "$name" "${motivo:-OK}"
done

if [ "$TEST_MODE" = "test" ]; then
  send_alert "✅ Test monitor AALA" \
    "Monitoraggio attivo su ${#CHECKS[@]} controlli — $(date '+%F %T').<br>Ora segue i redirect, verifica il dominio d'arrivo, il contenuto e la dimensione. Riceverai un'email solo quando qualcosa cambia."
  if [ $? -eq 0 ]; then
    echo "✅ email di prova PARTITA verso $TO"
  else
    echo "❌ email di prova NON partita — vedi la riga qui sopra"
    exit 1
  fi
fi

exit 0
