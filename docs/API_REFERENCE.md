# football-data.org v4 — Reference Sheet (endpoint usati nel progetto)

> Base URL: `https://api.football-data.org/v4`
> Auth header: `X-Auth-Token: YOUR_KEY`
> Piano Free: **10 richieste/minuto** (nessun tetto giornaliero), gestito lato
> client da `FootballDataClient` (`modules/api_client.py`) con una sliding
> window locale.

---

## Competizioni disponibili nel piano Free

| Codice | Nome              | ID   | Chiave config          |
|--------|-------------------|------|-------------------------|
| PL     | Premier League    | 2021 | `premier_league`        |
| PD     | La Liga           | 2014 | `la_liga`                |
| SA     | Serie A           | 2019 | `serie_a`                |
| BL1    | Bundesliga        | 2002 | `bundesliga`             |
| FL1    | Ligue 1           | 2015 | `ligue_1`                |
| CL     | Champions League  | 2001 | `champions`              |
| WC     | FIFA World Cup    | 2000 | `world_cup`              |
| EC     | UEFA Euro         | 2018 | `euro`                   |

**Non incluse nel piano Free:** Europa League, Conference League, FA Cup,
Coppa Italia, Copa del Rey, Nations League. **Non disponibili su nessun
piano:** infortuni e formazioni (lineups) — la sezione "infortuni" del
report viene quindi sempre generata come "nessun infortunio noto".

---

## GET /competitions/{code}/matches

Partite di una competizione in un intervallo di date.

**Parametri usati:**

| Parametro  | Tipo   | Uso                          |
|------------|--------|-------------------------------|
| `dateFrom` | string | Data inizio `YYYY-MM-DD`      |
| `dateTo`   | string | Data fine `YYYY-MM-DD`        |

**Uso nel progetto:**
- Venerdì (`friday_full_fetch`): `dateFrom`=venerdì, `dateTo`=lunedì → 1 call
  per competizione (tutte le 8 competizioni).
- Lun-gio (`international_daily_fetch`): `dateFrom`=`dateTo`=oggi → 1 call per
  torneo internazionale attivo (`world_cup`, `euro`).

**Struttura response (campi rilevanti):**
```json
{
  "matches": [
    {
      "id": 497569,
      "utcDate": "2026-06-11T19:00:00Z",
      "status": "SCHEDULED",
      "matchday": 1,
      "stage": "GROUP_STAGE",
      "group": "Group A",
      "homeTeam": { "id": 773, "name": "Mexico" },
      "awayTeam": { "id": 3922, "name": "Canada" },
      "score": { "fullTime": { "home": null, "away": null } }
    }
  ]
}
```

**Status rilevanti:** `SCHEDULED`, `TIMED` → mappati a `NS` nel DB;
`FINISHED` → mappato a `FT`. Partite con `homeTeam`/`awayTeam` ancora `null`
(fasi finali da sorteggiare) vengono scartate da `_build_fixture_row`.

---

## GET /competitions/{code}/standings

Classifica della stagione corrente (1 call per competizione).

**Struttura response (campi rilevanti):**
```json
{
  "standings": [
    {
      "type": "TOTAL",
      "group": "Group A",
      "table": [
        {
          "position": 1,
          "team": { "id": 773, "name": "Mexico" },
          "playedGames": 3,
          "form": "W,W,D",
          "goalsFor": 5,
          "goalsAgainst": 1
        }
      ]
    },
    { "type": "HOME", "table": [ ... ] },
    { "type": "AWAY", "table": [ ... ] }
  ]
}
```

**Note importanti:**
- I campionati con girone unico restituiscono di norma 3 tabelle: `TOTAL`,
  `HOME`, `AWAY`.
- I tornei a gironi (Mondiale, Europei in fase a gruppi) restituiscono **solo**
  `TOTAL`, una tabella per gruppo (`group: "Group A"`, `"Group B"`, ...).
- `_build_standings_cache` usa `HOME`/`AWAY` quando disponibili, altrimenti
  usa i valori `TOTAL` come fallback per entrambi (caso Mondiale/Europei).
- `form` è una stringa CSV tipo `"W,W,D,L,W"` → ripulita rimuovendo le virgole.

---

## GET /matches/{id}/head2head

Ultimi N scontri diretti per una partita specifica.

**Parametri:**

| Parametro | Tipo    | Note                       |
|-----------|---------|----------------------------|
| `limit`   | integer | Numero di precedenti (5)   |

**Struttura response:** stessa struttura di `/competitions/{code}/matches`
(lista `matches`), usata da `_summarize_h2h` per produrre una stringa tipo:
`"Italia 2-1 Brasile | Brasile 0-0 Italia | ..."`.

---

## Gestione errori e rate limit

`FootballDataClient._get`:
- `200` → JSON body
- `429` → attende `Retry-After` secondi e ritenta
- `5xx` → retry con backoff esponenziale (max 2 tentativi)
- `404` → `None` (nessun dato)
- altri codici → log errore, `None`

Ogni chiamata viene loggata su Supabase (`api_usage_log`) a scopo di
monitoraggio, ma **non** determina un blocco per quota giornaliera (a
differenza della vecchia integrazione API-Football): il limite è solo le
10 richieste/minuto, applicate lato client prima di ogni request.

---

## Stima chiamate per settimana

| Job                          | Chiamate stimate                                  |
|-------------------------------|----------------------------------------------------|
| `friday_full_fetch`            | 8 (matches) + N (standings, solo leghe con partite) + M (H2H, 1/partita) |
| `daily_refresh` (sab/dom)       | 1 standings per lega con partite quel giorno      |
| `international_daily_fetch` (lun-gio) | 1 matches + 1 standings per torneo attivo, + H2H per partita del giorno |

Con il rate limit di 10 req/min, eventuali picchi (es. molte H2H di fila)
vengono semplicemente rallentati dal client, senza errori né perdita di dati.
