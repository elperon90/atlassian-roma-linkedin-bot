# Bozza settimanale LinkedIn — Community Atlassian Roma

Ogni lunedì mattina questo repository genera in automatico la bozza del post
LinkedIn della settimana (testo + suggerimento immagine) seguendo le linee
guida editoriali in [`editorial_guidelines.md`](./editorial_guidelines.md), e
la invia su Telegram per la revisione.

**Questo progetto non pubblica nulla su LinkedIn in automatico.** La
pubblicazione resta un'azione manuale: copi il testo dal messaggio Telegram,
lo correggi se serve, e lo pubblichi tu sulla pagina. Questa è una scelta
deliberata: pubblicare via API LinkedIn richiederebbe l'approvazione di un
prodotto Developer soggetta a revisione di LinkedIn, con tempi non garantiti,
per un guadagno marginale rispetto al copia-incolla di un post a settimana.

## Come funziona

1. **Trigger settimanale** — un workflow GitHub Actions si attiva ogni lunedì
   (`.github/workflows/weekly-post.yml`).
2. **Generazione** — `scripts/generate_post.py` chiama l'API di Claude (con
   ricerca web attiva) usando le linee guida editoriali come istruzioni,
   evitando di ripetere il tema delle ultime settimane.
3. **Immagine** — se il tema lo richiede, lo script cerca una foto
   royalty-free su Unsplash; per le novità prodotto suggerisce invece quale
   screenshot ufficiale usare (citandone la fonte).
4. **Notifica** — la bozza arriva come messaggio Telegram, pronta da
   copiare.
5. **Archivio** — ogni bozza generata viene salvata in `posts/` e committata
   nel repository, sia come cronologia sia per evitare ripetizioni dei temi.

## Prerequisiti

- Un account [Anthropic](https://console.anthropic.com/) con una API key e
  credito disponibile.
- Un bot Telegram (gratuito) e l'ID della chat dove vuoi ricevere le bozze.
- (Opzionale) Una API key gratuita [Unsplash](https://unsplash.com/developers)
  per le immagini stock.

## Setup

### 1. Crea il bot Telegram

1. Apri una chat con [@BotFather](https://t.me/BotFather) su Telegram.
2. Invia `/newbot` e segui le istruzioni: otterrai un `TELEGRAM_BOT_TOKEN`
   (es. `123456789:AAA...`). **Non condividerlo con nessuno.**
3. Scrivi un messaggio qualsiasi al tuo nuovo bot (serve perché Telegram
   registri la chat).
4. Recupera il tuo `TELEGRAM_CHAT_ID`: il modo più semplice è scrivere a
   [@userinfobot](https://t.me/userinfobot), che ti risponde con il tuo ID.

### 2. Crea la API key Anthropic

Vai su [console.anthropic.com](https://console.anthropic.com/), crea una API
key e copiala: la userai come `ANTHROPIC_API_KEY`.

### 3. (Opzionale) Crea la API key Unsplash

Su [unsplash.com/developers](https://unsplash.com/developers) crea
un'applicazione gratuita: otterrai una `Access Key` da usare come
`UNSPLASH_ACCESS_KEY`. Se non la configuri, lo script salta semplicemente la
ricerca dell'immagine stock e ti segnala via Telegram quale tipo di immagine
usare a mano.

### 4. Configura i secret su GitHub

Nel repository, vai su **Settings → Secrets and variables → Actions → New
repository secret** e crea:

| Nome | Obbligatorio | Valore |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sì | la tua API key Anthropic |
| `TELEGRAM_BOT_TOKEN` | Sì | il token del bot Telegram |
| `TELEGRAM_CHAT_ID` | Sì | il tuo chat ID Telegram |
| `UNSPLASH_ACCESS_KEY` | No | la tua Access Key Unsplash |

I secret di GitHub Actions sono cifrati, visibili solo ai workflow del
repository e non compariranno mai nei log.

### 5. Abilita Dependabot e CodeQL

Sono già configurati in `.github/dependabot.yml` e
`.github/workflows/codeql.yml`. Devi solo assicurarti che, nelle impostazioni
del repository (**Settings → Code security**), "Dependabot alerts" e
"Dependabot security updates" siano attivi: GitHub te lo chiede comunque al
primo push se non lo sono già.

### 6. Testa manualmente

Prima di aspettare il lunedì, vai su **Actions → Weekly LinkedIn draft → Run
workflow** per lanciare una generazione di prova subito.

## Personalizzare

- **Orario/giorno**: modifica l'espressione cron in
  `.github/workflows/weekly-post.yml` (è in UTC; Roma è UTC+1 in inverno,
  UTC+2 in estate).
- **Tono, struttura, temi**: modifica `editorial_guidelines.md` — è il system
  prompt che guida ogni generazione.
- **Modello usato**: di default `claude-sonnet-4-6`; puoi cambiarlo
  impostando la variabile d'ambiente `ANTHROPIC_MODEL` nel workflow.

## Note di sicurezza

- Nessun secret viene mai loggato: lo script registra solo nomi di variabili
  mancanti, non i valori.
- Il workflow ha solo il permesso `contents: write`, necessario per
  archiviare le bozze: nessun accesso a issue, pull request o altro.
- Le dipendenze Python sono pinnate a versioni esatte in `requirements.txt`;
  Dependabot apre automaticamente una pull request quando è disponibile un
  aggiornamento (incluse le patch di sicurezza).
- CodeQL esegue una scansione statica del codice a ogni modifica e una volta
  a settimana.
- In caso di errore (API non raggiungibile, risposta malformata, ecc.) lo
  script tenta di avvisarti su Telegram e termina con stato di errore, così
  la Action risulta visibilmente fallita su GitHub.
- Nessuna pubblicazione automatica: la bozza richiede sempre una revisione e
  un'azione manuale da parte tua.

## Struttura del repository

```
.
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── weekly-post.yml      # genera e notifica la bozza settimanale
│       └── codeql.yml           # scansione di sicurezza del codice
├── editorial_guidelines.md      # system prompt: regole editoriali
├── posts/                       # archivio delle bozze generate
├── scripts/
│   └── generate_post.py         # script principale
├── tests/
│   └── test_generate_post.py    # test unitari (nessuna chiamata di rete)
├── requirements.txt
└── README.md
```

## Possibile evoluzione futura

Se in futuro vuoi automatizzare anche la pubblicazione su LinkedIn, serve
registrare un'app su [LinkedIn Developer](https://www.linkedin.com/developers/)
collegata alla pagina aziendale e richiedere l'accesso al prodotto che
abilita la pubblicazione sulle pagine organizzazione — un passaggio soggetto
ad approvazione di LinkedIn. L'architettura di questo repository è pensata
per poter aggiungere quel passaggio in un secondo momento senza dover
riscrivere la parte di generazione.
