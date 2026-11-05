# edge_lab

Ricerca di un edge riproducibile sui mercati sportivi di Polymarket. Progetto
separato da `scalata` (quello resta per le scalate manuali di Pat basate
sulla sua conoscenza calcistica).

## Stato: notte di ricerca del 2026-11-05 — tre fronti, tutti con verdetto onesto negativo

Nessuna scorciatoia trovata finora. Non significa che non ci sia niente da
trovare, significa che tre strade ragionevoli sono state testate con rigore
e nessuna ha retto.

### 1. Copiare un wallet profittevole — nessuno trovato

170 wallet candidati (classifica pubblica Polymarket, top-100 all-time +
top-100 categoria sports). Filtrati per escludere i market maker (mercato
singolo tradato >50 volte, taglia bet mediana <$5, operazioni MERGE >5% —
firma di chi compra entrambi i lati di un mercato): **12 sopravvissuti**.

Su tutti e 12, test decisivo = **Closing Line Value** (prezzo d'ingresso vs
ultimo prezzo prima del kickoff, solo trade pre-match): **0/12 mostrano CLV
medio positivo con maggioranza di trade migliori della chiusura**. Alcuni
avevano ROI grezzo molto alto (es. +34%, +28%) ma CLV comunque negativo — il
profitto grezzo non riflette abilità di ingresso, probabilmente varianza o
size, non skill.

Codice: `wallet_screening.py` (`candidate_pool`, `screen_candidates`,
`closing_line_value`, `has_demonstrable_edge`).

### 2. Strategie pubblicate (arbitraggio, market making, copy-trading, bias di quota)

Verificate leggendo direttamente il codice/risultati di repository pubblici
con backtest reali su dati calcio (non solo riassunti, i file sono stati
clonati e ispezionati):

- **Arbitraggio cross-market stesso evento**: 369 opportunità viste in 2
  giorni, **0 eseguibili** — hold period taker di 1 secondo sui mercati calcio.
- **Market making in-play**: -$23.055 su 13 giorni di replay, 12/13 in perdita.
- **Copy-trading con ritardo**: wallet originali +$2,33/$10, copiati con
  1-5s di ritardo ~$0/$10.
- **Favorite-longshot bias come regola di trading**: 35.000 mercati, dopo
  correzione statistica ≈$0/$1.
- **Unico caso vagamente positivo**: un bot di arbitraggio puro reale
  (wallet pubblico verificabile on-chain, `kachence/polymm`), +$5k netti,
  **ritirato dall'autore perché diventato troppo lento per difendere l'edge**.
  Conferma l'ipotesi catch-22 latenza/liquidità già in `scalata`
  (`project-scalata-idea-latenza`).

### 3. Il segnale O/U gol di Pat — non regge su campione più ampio

Pat aveva trovato +5,6% ROI sui suoi 29 trade O/U gol personali (contro
-5,4% su moneyline/spread). Testato con **due metodi indipendenti** su
campione più ampio:

- Metodo semplice (300 oss. O/U gol, Serie A+Bundesliga, prezzo di chiusura
  vs esito reale): ROI -3,1%, **t=-1,45, non significativo**.
- Metodo rigoroso stile torneo (9.096 mercati raccolti, 61 configurazioni,
  soglia Bonferroni, split train/holdout): un falso segnale clamoroso (t
  fino a +28) smascherato come **mercati-ombra su linee di gol assurde
  (6.5-8.5 gol) con 32% di volume totale <$50** — mai scambiati per davvero.
  Isolando solo le linee liquide (2.5-4.5 gol): ROI +14,8% ma **t=+1,73, non
  significativo**.

Entrambi convergono: il segnale originale era quasi certamente rumore
statistico su campione piccolo (29 bet).

## La lezione di metodo più importante, trovata due volte in modi diversi

Un t-stat enorme non è una prova, è un campanello d'allarme da verificare:

1. **Leak nel filtro** (`benaticak-alt/polylab`, repo di terzi verificato
   clonandolo): un +18% ROI a t=+8,36 su 14.217 osservazioni era un
   artefatto — il filtro per volume finale ≥$25k selezionava
   inconsapevolmente mercati dove un upset era già successo (gli upset
   attirano volume tardivo). Smontato ritestando la stessa regola sui
   mercati esclusi dal filtro: ROI -9,7%/-13,7%/-26,4%.
2. **Mercati-ombra** (trovato stanotte, punto 3 sopra): un t fino a +28 su
   mercati mai scambiati per davvero (volume reale <$50).

`backtest.py` in questo repo incorpora entrambe le protezioni come pratica
di default: `run_tournament()` fa lo split train/holdout corretto per tempo
e applica la correzione Bonferroni; `selection_bias_check()` è pensato
apposta per ripetere il test di tipo (1) su qualunque filtro si usi in
futuro; il parametro `min_liquidity` di `run_tournament()` copre il tipo (2).

## Struttura del repo

- `fetchers.py` — wrapper puliti per gamma-api (eventi), data-api v2
  (attività wallet, classifica), clob (storico prezzi). Nessuna chiave
  richiesta, tutto pubblico.
- `wallet_screening.py` — pipeline di screening wallet (filtri anti-market-
  maker + test CLV), validata su 170 wallet reali.
- `backtest.py` — framework di torneo rigoroso (train/holdout, t-stat,
  Bonferroni, test di selection-bias), implementazione originale ispirata
  al metodo (non al codice) di `benaticak-alt/polylab`.

## Come continuare da qui

Non rifare un giro "a caso" di nuove idee senza una ragione — è esattamente
il modo in cui si fabbricano falsi positivi (più ipotesi testate senza
correzione, più probabilità che una sembri funzionare per puro caso). Idee
concrete con una ragione dietro, non ancora provate:

- Mercati/competizioni non ancora testate con lo stesso rigore (solo
  Serie A, Bundesliga, FA Cup toccate finora).
- Mercati non calcistici ma dove Pat ha comunque un vantaggio di
  informazione reale (se esiste).
- Ripetere lo screening wallet periodicamente — la classifica cambia, un
  wallet con CLV vero potrebbe comparire in futuro anche se stanotte non
  c'era.
