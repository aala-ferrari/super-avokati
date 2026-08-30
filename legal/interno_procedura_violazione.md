# Procedura in caso di violazione dei dati

**Documento interno — il manuale da aprire alle tre di notte**

Art. 33-34 GDPR · Ligji nr. 124/2024 · versione 2026-08-31

---

> ⚠️ **BOZZA DA FAR VERIFICARE.** Base di lavoro. Ma i comandi qui dentro sono
> **veri e provati**: una procedura che non si può eseguire non è una
> procedura, è un tema.

---

## L'orologio parte prima di quanto credi

**Le 72 ore decorrono da quando *vieni a conoscenza*** della violazione — non
da quando finisci di capirla. Se alle 23:00 di venerdì noti qualcosa di strano,
l'orologio è già partito.

**Non aspettare di aver capito tutto per notificare.** La legge consente una
notifica **in fasi**: si comunica quello che si sa e si integra dopo. Una
notifica incompleta nei termini vale infinitamente più di una perfetta in
ritardo.

⚠️ **Come responsabile verso gli studi il tuo termine è più stretto**:
l'accordo che hai firmato dice **24 ore**, perché loro devono poi rispettare le
proprie 72.

---

## Fase 1 — Contenere (subito, prima di ogni analisi)

Nell'ordine, e senza discutere:

```bash
# 1. sospendere l'utenza compromessa (non cancellarla: servono le prove)
ssh root@31.220.90.246
docker exec super-avvocato python3 -c "
import sqlite3, glob
c = sqlite3.connect(glob.glob('/app/data/*.db')[0])
c.execute(\"UPDATE users SET status='suspended' WHERE username=?\", ('UTENZA',))
c.commit()"

# 2. se è compromesso il server: chiudere l'accesso lasciando in piedi il servizio
ufw deny 22

# 3. se sono compromesse le credenziali del motore: revocarle
#    → nuovo token dal proprio account, poi /opt/super-avvocato.env e run.sh
```

**Non cancellare niente.** Log, sessioni, file sospetti: sono le prove con cui
dimostrerai cosa è successo e — soprattutto — **cosa non è successo**.

---

## Fase 2 — Capire l'estensione (le prime ore)

La domanda che conta non è «siamo stati bucati», è **«quali clienti sono stati
esposti»**. Senza risposta si è costretti ad avvisarli tutti, e questo distrugge
la fiducia molto più della violazione.

```bash
# CHI ha aperto QUALI fascicoli, e da dove — è per questo che esiste il registro
docker exec super-avvocato python3 -c "
import sqlite3, glob
c = sqlite3.connect(glob.glob('/app/data/*.db')[0]); c.row_factory = sqlite3.Row
for r in c.execute('''SELECT ts, username, case_id, action, ip
                      FROM case_access_log
                      WHERE ts > datetime('now','-7 days')
                      ORDER BY id DESC'''):
    print(dict(r))"

# accessi riusciti e falliti al server
grep -E 'Accepted|Failed' /var/log/auth.log | tail -60

# tentativi di login all'applicazione
docker logs super-avvocato --since 168h 2>&1 | grep -iE 'failed login|login bloccato'

# cosa ha chiesto al motore l'utenza sospetta
docker exec super-avvocato python3 -c "
import sqlite3, glob
c = sqlite3.connect(glob.glob('/app/data/*.db')[0])
for r in c.execute('''SELECT timestamp, callsite, case_id FROM ai_audit_log
                      WHERE user_id=? ORDER BY id DESC LIMIT 100''', (ID,)):
    print(r)"
```

**Da mettere per iscritto, subito, mentre si guarda:**

| | |
|---|---|
| Quando è iniziata / quando l'abbiamo saputo | |
| Cosa è successo, in una frase | |
| **Quali** interessati e **quanti** | |
| **Quali** categorie di dati (ci sono dati giudiziari?) | |
| Conseguenze probabili per gli interessati | |
| Cosa abbiamo già fatto per contenere | |

---

## Fase 3 — Notificare

### 3a. Agli studi coinvolti — entro **24 ore**

Sono loro i titolari: devono poter rispettare le proprie 72 ore. Scrivere
**anche se il quadro è parziale**, dicendo che è parziale.

> Oggetto: **Comunicazione di violazione dei dati — [data]**
>
> Vi informiamo che il [data/ora] abbiamo rilevato [cosa]. Risultano
> interessati [quali dati, quali fascicoli]. Abbiamo immediatamente [azioni].
>
> In qualità di titolari del trattamento, valutate la notifica all'autorità nei
> vostri termini di legge. Restiamo a disposizione per ogni informazione utile.
>
> Aggiorneremo questa comunicazione entro [data].

### 3b. All'autorità — entro **72 ore**

- **Albania** — Komisioneri për të Drejtën e Informimit dhe Mbrojtjen e të
  Dhënave Personale (IDP), `idp.al`
- **Italia** — Garante per la protezione dei dati personali, `garanteprivacy.it`
  (se sono coinvolti studi o interessati italiani)

⚠️ **Se si supera il termine, notificare comunque** e spiegare il ritardo: è
espressamente previsto. Il silenzio è molto peggio.

### 3c. Agli interessati — quando il rischio è elevato

Se ci sono **dati giudiziari o sensibili**, il rischio elevato è la regola, non
l'eccezione. Va fatto **senza ritardo**, in linguaggio semplice: cosa è
successo, quali dati, cosa stiamo facendo, cosa possono fare loro.

Non serve se i dati erano cifrati **e** la chiave non è compromessa.
⚠️ **Attenzione**: oggi i documenti **non sono cifrati a riposo** — questa
esenzione **non si applica** ai file dei fascicoli. Vale per i backup, che sono
cifrati.

---

## Fase 4 — Registrare (obbligatorio anche se non si notifica)

**Ogni** violazione va documentata, comprese quelle che non richiedono
notifica: è l'autorità a giudicare se la valutazione era corretta, e senza
traccia scritta non si può dimostrare di averla fatta.

Tenere in `legal/violazioni/AAAA-MM-GG.md`: fatti, dati coinvolti, valutazione
del rischio, decisione su notifica **e il perché**, misure adottate.

---

## Cosa è già pronto per aiutarti

| Serve per | C'è |
|---|---|
| sapere chi ha aperto cosa | `case_access_log` (24 mesi) |
| ricostruire l'uso del motore | `ai_audit_log` (12 mesi) — **verificato: nessun contenuto di fascicolo, solo impronte** |
| dimostrare cosa è stato accettato | `legal_acceptances` (10 anni) |
| bloccare la forza bruta | freno 5 per utenza / 20 per rete |
| escludere lo scenario «hanno letto tutto» | backup cifrati; motore confinato |

## Cosa NON c'è — sapendolo prima, non durante

1. **Nessun avviso automatico**: nessuno ti scrive se qualcosa va storto. La
   rilevazione oggi dipende da te che guardi i log. *Da migliorare.*
2. **`case_access_log` è partito il 30 agosto 2026**: prima di quella data non
   esiste storico degli accessi ai fascicoli.
3. **Documenti non cifrati a riposo**: l'esenzione dalla comunicazione agli
   interessati non si applica ai file.
4. **Un solo amministratore.** Se il server è compromesso e tu non sei
   raggiungibile, non c'è nessun altro che possa contenere. ⚠️ **Questo è un
   rischio organizzativo, non tecnico**, ed è quello che una procedura non può
   risolvere da sola.
