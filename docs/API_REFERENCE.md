# API-Football v3 — Reference Sheet (endpoint usati nel progetto)

> Estratto dalla documentazione ufficiale v3.9.3. Solo gli endpoint effettivamente usati.
> Base URL: `https://v3.football.api-sports.io`
> Auth header: `x-apisports-key: YOUR_KEY`

---

## /status (NON conta sulla quota)

```
GET /status
```
Restituisce le call rimanenti oggi. Chiamare all'inizio di ogni job.

**Response:**
```json
{
  "response": {
    "subscription": { "plan": "Free", "active": true },
    "requests": { "current": 12, "limit_day": 100 }
  }
}
```

---

## /fixtures

```
GET /fixtures
```

**Parametri usati nel progetto:**

| Parametro | Tipo    | Uso                                                    |
|-----------|---------|--------------------------------------------------------|
| `league`  | integer | ID della competizione                                  |
| `season`  | integer | Anno stagione (es. 2025)                               |
| `from`    | string  | Data inizio YYYY-MM-DD                                 |
| `to`      | string  | Data fine YYYY-MM-DD                                   |
| `ids`     | string  | Max 20 fixture ID separati da `-` (batch fetch)        |
| `timezone`| string  | Es. `Europe/Rome`                                      |

**Update frequency:** ogni 15 secondi
**Recommended calls:** 1/giorno (nessuna partita in corso)

**Uso nel progetto:**
- Venerdì: `?league=39&season=2025&from=2025-08-22&to=2025-08-25` → 1 call per competizione
- Sab/dom refresh: `?ids=ID1-ID2-ID3-...` → 1 call per 20 partite

**Struttura response (campi rilevanti):**
```json
{
  "fixture": {
    "id": 215662,
    "date": "2020-02-06T14:00:00+00:00",
    "status": { "short": "NS", "elapsed": null }
  },
  "league": {
    "id": 39,
    "name": "Premier League",
    "season": 2019,
    "round": "Regular Season - 14"
  },
  "teams": {
    "home": { "id": 967, "name": "Arsenal", "winner": null },
    "away": { "id": 968, "name": "Chelsea", "winner": null }
  },
  "goals": { "home": null, "away": null }
}
```

**Status codes rilevanti:**
- `NS` = Not Started (partita futura — quello che ci interessa)
- `FT` = Full Time
- `PST` = Postponed
- `CANC` = Cancelled
- `TBD` = Data da definire

---

## /standings

```
GET /standings?league={id}&season={year}
```

**Parametri:**

| Parametro | Tipo    | Note              |
|-----------|---------|-------------------|
| `league`  | integer | ID lega           |
| `season`  | integer | Anno (richiesto)  |

**Update frequency:** ogni ora
**Recommended calls:** 1/giorno

**Struttura response (campi rilevanti):**
```json
{
  "response": [{
    "league": {
      "standings": [[
        {
          "rank": 1,
          "team": { "id": 40, "name": "Liverpool" },
          "points": 70,
          "goalsDiff": 41,
          "form": "WWWWW",
          "all": { "played": 24, "win": 23, "draw": 1, "lose": 0 },
          "goals": { "for": 56, "against": 15 }
        }
      ]]
    }
  }]
}
```

**Nota:** `standings[0]` è il gruppo principale. Per coppe con gironi ci sono più array.

---

## /fixtures/headtohead

```
GET /fixtures/headtohead?h2h={team1_id}-{team2_id}&last=5
```

**Parametri:**

| Parametro | Tipo    | Note                          |
|-----------|---------|-------------------------------|
| `h2h`     | string  | `ID1-ID2` (richiesto)         |
| `last`    | integer | Ultimi N scontri (usare 5)    |

**Update frequency:** ogni 15 secondi
**Recommended calls:** 1/giorno

**Struttura response:** stessa struttura di `/fixtures`

---

## /injuries

```
GET /injuries
```

**Parametri (usare uno dei seguenti):**

| Parametro | Tipo    | Note                                          |
|-----------|---------|-----------------------------------------------|
| `league`  | integer | + `season` richiesto → tutti gli infortuni    |
| `ids`     | string  | Max 20 fixture IDs separati da `-`            |
| `fixture` | integer | Singola partita                               |

**Update frequency:** ogni 4 ore
**Recommended calls:** 1/giorno

**Tipi di infortuni:**
- `"Missing Fixture"` → il giocatore NON giocherà (certo)
- `"Questionable"` → incerto, potrebbe giocare

**Struttura response:**
```json
{
  "response": [{
    "player": {
      "id": 865,
      "name": "D. Costa",
      "type": "Missing Fixture",
      "reason": "Broken ankle"
    },
    "team": { "id": 157, "name": "Bayern Munich" },
    "fixture": { "id": 686314 }
  }]
}
```

---

## /fixtures/lineups

```
GET /fixtures/lineups?fixture={id}
```

**Update frequency:** ogni 15 minuti
**Recommended calls:** 1/giorno (disponibili ~60 min prima del match)

**Uso nel progetto:** refresh sab/dom per partite imminenti (< 2 ore al fischio)

---

## /fixtures/statistics (NON usato nel fetch principale)

```
GET /fixtures/statistics?fixture={id}
```
Statistiche post-partita. Non disponibili per partite non ancora giocate.
Utile solo per aggiornare i dati storici del modello ML (futuro).

---

## /leagues (chiamata di bootstrap, 1 volta)

```
GET /leagues?current=true
```
Restituisce tutte le leghe attive con il loro `coverage` object.

**Coverage object da verificare prima di chiamare endpoint downstream:**
```json
"coverage": {
  "fixtures": { "events": true, "lineups": true, "statistics_fixtures": false },
  "standings": true,
  "injuries": true,
  "predictions": true
}
```
Se `injuries: false` per una competizione → non chiamare `/injuries` per quella lega.

---

## Response wrapper universale

Ogni endpoint restituisce sempre questa struttura:
```json
{
  "get": "fixtures",
  "parameters": { "league": "39" },
  "errors": [],
  "results": 10,
  "paging": { "current": 1, "total": 1 },
  "response": [ ... ]
}
```

**Logica di parsing:**
```python
def safe_parse(raw_response: dict) -> list:
    if raw_response.get("errors"):
        return []
    if raw_response.get("paging", {}).get("total", 1) > 1:
        # Attenzione: ci sono più pagine
        pass
    return raw_response.get("response", [])
```

---

## Budget call — riepilogo pratico

| Giorno   | Operazione                            | Call stimate |
|----------|---------------------------------------|--------------|
| Venerdì  | fixtures × 14 comp. (11 club + 3 int.)| 14           |
| Venerdì  | standings × 14 comp.                  | 14           |
| Venerdì  | H2H × ~48 partite                     | 48           |
| Venerdì  | injuries × 14 comp.                   | 14           |
| Venerdì  | **Totale worst case**                 | **~90**      |
| Sabato   | injuries batch + lineups              | ~10          |
| Domenica | injuries batch + lineups              | ~10          |
| **TOT**  | **Settimana completa**                | **~110**     |

### Perché il budget non esplode con i tornei internazionali

Mondiali, Euro e Nations League **non si sovrappongono mai** alle giornate di campionato:

- **Mondiali / Euro** (giugno-luglio): i campionati nazionali sono finiti da settimane. Le call per Premier League, Serie A ecc. restituiscono lista vuota → 0 call effettive.
- **Nations League** (soste internazionali settembre/ottobre/novembre): i campionati si fermano esattamente in quelle settimane. Stessa cosa.

In pratica il venerdì di una settimana con Mondiali assomiglia a:
- Fixtures × 1 (solo world_cup) → 1 call
- Standings → 1 call
- H2H × ~8 partite → 8 call
- Injuries → 1 call

Totale: **~11 call**, molto sotto il limite. Il budget non si somma mai.

**Nota:** Le coppe europee (Champions, Europa, Conference) non giocano nelle settimane di Nations League, quindi anche quelle si azzerano automaticamente.

