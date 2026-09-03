# RUNBOOK — se qualcosa è giù (AALA / Super Avokati)

**Server**: VPS `31.220.90.246` · accesso solo con chiave SSH: `ssh root@31.220.90.246`
**Allarmi**: il monitor (ogni 5 min, 12 controlli severi) manda email a `info@aala.global`
solo quando un sito CAMBIA stato, e dice quale prova è fallita. Stati: `/var/lib/uptime-monitor/`.

---

## 1 · Super Avokati è giù (superavokati.ai)

```bash
docker ps | grep super-avvocato          # c'è? dice "healthy"?
docker logs super-avvocato --tail 50     # cosa dice
docker restart super-avvocato            # primo tentativo (10 s)
```
Se il container è sparito o non riparte:
```bash
cd /var/www/apps/super-avvocato && ./run.sh   # lo ricrea dall'immagine buona
```
Dopo OGNI ripartenza, la prova del nove:
```bash
docker exec super-avvocato python3 tools/golden_check.py   # deve dire 302 kaluan
```
⚠️ **MAI** avviarlo multi-worker (gunicorn): i lavori in corso vivono in memoria,
un solo processo è una legge, non una svista. ⚠️ Mai riavviare durante un `docker build`.

## 2 · Gli altri siti (pm2)

| Sito | Processo | Comando |
|---|---|---|
| aala.global | `aala` | `pm2 restart aala` |
| auto.aala.global | `auto` + `auto-backend` | `pm2 restart auto auto-backend` |
| crm.aala.global | `crm-medical` | `pm2 restart crm-medical` |
| corea.aala.global | `korauto` | `pm2 restart korauto` |
| taxi.aala.global | `taxi-admin` + `taxi-backend` | `pm2 restart taxi-admin taxi-backend` |
| nabuel.com | `nabuel-gateway` | `pm2 restart nabuel-gateway` |

`pm2 ls` mostra tutto; `pm2 logs <nome> --lines 50` per capire il perché.
I database (`taxi_postgres`, `auto_postgres`, `supabase-*`, `taxi_redis`) sono
container docker con `--restart`: di norma NON si toccano.

## 3 · nginx (davanti a tutto)

```bash
nginx -t && systemctl reload nginx       # mai reload senza il test prima
```
La landing di superavokati.ai è statica: `/var/www/superavokati-landing/index.html`
(non dipende dal container — se la landing è viva e l'app no, il problema è il container).

## 4 · Backup — dove sono e come si apre

Tutti **cifrati** (AES-256), chiave in `/root/.backup-key` — **la passphrase è la
cosa da custodire FUORI dal server** (se si perde il server E la chiave, i backup
sono carta straccia).

| Cosa | Quando | Dove |
|---|---|---|
| DB Super Avokati | 04:00 | `/root/sa-backups/sa-app-*.db.gz.enc` |
| DB CRM | 04:10 | `/root/sa-backups/crm-dev-*.db.gz.enc` |
| AALA completa | 03:30 | `/opt/backups/aala-FULL-*.tar.gz.enc` |
| Copia offsite | 04:40 | ⏸ **in attesa chiave B2/S3** (`/opt/backup-offsite.sh`) |

Aprirne uno (esempio DB Super Avokati):
```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in /root/sa-backups/sa-app-YYYYMMDD-0400.db.gz.enc -out /tmp/sa.db.gz \
  -pass file:/root/.backup-key && gunzip /tmp/sa.db.gz
# poi: docker stop super-avvocato · sostituire data/app.db · docker start super-avvocato
```
**Provato per davvero il 3 set 2026** (restore drill, prod mai toccata):
decifrare **1 s** · integrità `ok` · conti utenti/casi/messaggi tornati ·
app **risorta in 26 s** da container pulito col DB del backup (status 200,
login servito) · anche l'archivio AALA FULL si apre e si legge.
Il backup è delle 04:00 → nel caso peggiore si perde la giornata in corso.

## 5 · Dove guardare i log

`/var/log/uptime-monitor.log` (il monito) · `docker logs super-avvocato` (l'app) ·
`/var/log/sa-db-backup.log`, `/var/log/aala-backup.log`, `/var/log/backup-offsite.log` (backup) ·
`/var/log/it-giurcost.log`, `/var/log/it-ga.log` (raccolta giurisprudenza notturna).

## 6 · Regole che non si discutono

- Patch al codice: **file .py copiati via scp** — mai heredoc SSH (mangia le virgolette).
- Nella conoscenza del cervello entra **solo ciò che migliora** — mai auto-ingest.
- I messaggi d'errore ai clienti non nominano mai «Claude»: **Tetramorph**.
- `effort=max` resta: **l'esattezza prima della velocità**.

*Copia gemella sul server: `/opt/RUNBOOK.md`. Aggiornata: 3 settembre 2026.*
