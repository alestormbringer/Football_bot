import logging
import numpy as np
from scipy.stats import poisson

logger = logging.getLogger(__name__)


def parse_form(form_string: str, last_n: int = 5) -> float:
    """
    Converte stringa form (es. 'WWDLW') in percentuale vittorie.
    Considera solo gli ultimi N risultati.
    """
    if not form_string:
        return 0.5
    recent = form_string[-last_n:].upper()
    wins = recent.count('W')
    return wins / len(recent) if recent else 0.5


def compute_poisson_probs(
    home_attack: float,
    home_defense: float,
    away_attack: float,
    away_defense: float,
    home_advantage: float = 1.1,
    max_goals: int = 6,
) -> dict:
    """
    Calcola probabilita 1X2 usando distribuzione di Poisson bivariata.

    Parametri:
    - home_attack:   media gol segnati in casa (stagione corrente)
    - home_defense:  media gol subiti in casa
    - away_attack:   media gol segnati in trasferta
    - away_defense:  media gol subiti in trasferta
    - home_advantage: fattore moltiplicativo per il vantaggio casalingo

    Restituisce:
    {
        "home_win": 0.45,
        "draw": 0.28,
        "away_win": 0.27,
        "expected_home": 1.62,
        "expected_away": 1.14,
        "over_25": 0.52,   # probabilita Over 2.5 gol
    }
    """
    # Expected goals (xG semplificato da statistiche)
    lambda_home = home_attack * away_defense * home_advantage
    lambda_away = away_attack * home_defense

    # Clip ragionevole
    lambda_home = max(0.3, min(lambda_home, 5.0))
    lambda_away = max(0.3, min(lambda_away, 5.0))

    # Matrice di probabilita risultati esatti
    score_matrix = np.zeros((max_goals + 1, max_goals + 1))
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            score_matrix[h, a] = (
                poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
            )

    # Normalizza (la matrice troncata non somma esattamente a 1)
    score_matrix /= score_matrix.sum()

    home_win = float(np.tril(score_matrix, -1).sum())  # h > a
    draw     = float(np.trace(score_matrix))
    away_win = float(np.triu(score_matrix, 1).sum())   # a > h

    # Over 2.5
    over_25 = float(sum(
        score_matrix[h, a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h + a > 2
    ))

    return {
        "home_win":      round(home_win, 4),
        "draw":          round(draw,     4),
        "away_win":      round(away_win, 4),
        "expected_home": round(lambda_home, 2),
        "expected_away": round(lambda_away, 2),
        "over_25":       round(over_25, 4),
    }


def build_match_stats(fixture_stats_row: dict) -> dict:
    """
    Prende una riga di fixture_stats e restituisce i parametri
    pronti per compute_poisson_probs.
    """
    return {
        "home_attack":  fixture_stats_row.get("home_goals_avg", 1.2),
        "home_defense": fixture_stats_row.get("home_conceded_avg", 1.0),
        "away_attack":  fixture_stats_row.get("away_goals_avg", 1.0),
        "away_defense": fixture_stats_row.get("away_conceded_avg", 1.2),
    }


def adjust_for_injuries(probs: dict, home_injury_count: int, away_injury_count: int) -> dict:
    """
    Aggiustamento euristico delle probabilita in base agli infortuni.
    Ogni infortunio pesante (tipo "Missing Fixture") riduce leggermente
    la forza offensiva della squadra colpita.
    """
    penalty = 0.02  # per ogni infortunio "Missing Fixture"

    home_penalty = min(home_injury_count * penalty, 0.10)
    away_penalty = min(away_injury_count * penalty, 0.10)

    home_win = probs["home_win"] - home_penalty + away_penalty * 0.5
    away_win = probs["away_win"] - away_penalty + home_penalty * 0.5
    draw     = 1.0 - home_win - away_win

    # Mantieni valori nel range [0.05, 0.90]
    home_win = max(0.05, min(0.90, home_win))
    away_win = max(0.05, min(0.90, away_win))
    draw     = max(0.05, min(0.80, draw))

    # Rinormalizza
    total = home_win + draw + away_win
    return {
        **probs,
        "home_win": round(home_win / total, 4),
        "draw":     round(draw / total, 4),
        "away_win": round(away_win / total, 4),
    }
