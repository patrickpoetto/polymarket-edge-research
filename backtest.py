"""Framework di backtest rigoroso per regole di trading su mercati Polymarket.

Implementazione originale (non copiata da nessun repository di terzi) dello
stesso standard metodologico validato nella notte di ricerca del 2026-11-05:

1. Split train/holdout per TEMPO (mai casuale puro su eventi correlati — una
   partita e i suoi mercati derivati non vanno spezzati tra le due metà).
2. Ogni regola si misura con un t-stat su train; sopravvive solo chi supera
   una soglia corretta per test multipli (Bonferroni: |t| > soglia cresce con
   il numero di regole testate in parallelo).
3. I sopravvissuti si rileggono UNA SOLA VOLTA su holdout. Mai iterare sulla
   base dell'esito holdout — altrimenti l'holdout diventa train e la
   correzione per test multipli non vale più niente.
4. Prima di fidarsi di un t-stat enorme, controllare SEMPRE il volume/la
   liquidità reale dei mercati coinvolti — un t enorme su mercati-ombra mai
   scambiati per davvero è il modo più comune di fabbricare un falso segnale
   (vedi README.md, due casi reali trovati e smontati la stessa notte: un
   leak da filtro-volume-finale e un caso di mercati-ombra su linee assurde).

Uso tipico: costruisci una lista di `Observation` (prezzo di chiusura, esito,
timestamp, eventuali metadati come volume/competizione), definisci una lista
di regole candidate, chiama `run_tournament`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Observation:
    """Un mercato risolto: prezzo di chiusura pre-evento, esito reale (1/0), timestamp di chiusura."""
    price: float          # prezzo "Yes" di chiusura, in [0,1]
    outcome: int           # 1 se Yes ha vinto, 0 altrimenti
    close_ts: int           # timestamp di risoluzione/chiusura (per lo split train/holdout)
    volume: Optional[float] = None   # volume totale scambiato — usalo per i filtri di liquidità
    meta: Dict = field(default_factory=dict)   # es. {"competition": "Serie A", "line": 2.5}


@dataclass
class Rule:
    name: str
    # select ritorna None se la regola non si applica a quell'osservazione,
    # altrimenti (side, cost) dove side=1 compra Yes, side=0 compra No, cost
    # è lo slippage/spread stimato da aggiungere al prezzo d'ingresso.
    select: Callable[[Observation], Optional[tuple]]


def trade_roi(obs: Observation, side: int, cost: float = 0.01) -> Optional[float]:
    """ROI su $1 di puntata, comprando 'side' al prezzo di chiusura + cost. None se il prezzo è troppo estremo."""
    q = (obs.price if side == 1 else 1 - obs.price) + cost
    if q >= 0.995 or q <= 0.005:
        return None
    won = (obs.outcome == 1) == (side == 1)
    return (1 - q) / q if won else -1.0


def t_statistic(rois: List[float]) -> Optional[float]:
    n = len(rois)
    if n < 2:
        return None
    mean = sum(rois) / n
    var = sum((r - mean) ** 2 for r in rois) / (n - 1)
    if var == 0:
        return None
    se = math.sqrt(var / n)
    return mean / se if se else None


def bonferroni_threshold(n_rules: int, alpha: float = 0.05) -> float:
    """Soglia |t| approssimata per n_rules test paralleli (approssimazione normale,
    sufficiente per n grandi; per n piccoli è leggermente conservativa)."""
    import statistics as _s
    p = alpha / max(n_rules, 1)
    # inversa approssimata della normale standard (Acklam-free, buona a 3 decimali)
    # fallback semplice: usa un t critico via scipy se disponibile, altrimenti approssimazione.
    try:
        from scipy import stats
        return float(abs(stats.norm.ppf(p / 2)))
    except ImportError:
        # approssimazione rozza ma ragionevole per alpha/n tipici (0.0001-0.05)
        return 1.96 + 1.5 * math.log10(max(n_rules, 1))


def evaluate_rule(rule: Rule, observations: List[Observation], cost: float = 0.01) -> Dict:
    rois = []
    for obs in observations:
        sel = rule.select(obs)
        if sel is None:
            continue
        side, rule_cost = sel if isinstance(sel, tuple) else (sel, cost)
        roi = trade_roi(obs, side, rule_cost)
        if roi is not None:
            rois.append(roi)
    if not rois:
        return {"rule": rule.name, "n": 0, "roi": None, "t": None}
    mean_roi = sum(rois) / len(rois)
    return {"rule": rule.name, "n": len(rois), "roi": mean_roi, "t": t_statistic(rois)}


def run_tournament(rules: List[Rule], observations: List[Observation], split_ts: int,
                    alpha: float = 0.05, min_liquidity: Optional[float] = None,
                    verbose: bool = True) -> Dict:
    """Esegue il torneo completo: filtro liquidità -> train -> soglia Bonferroni -> holdout (una volta sola)."""
    obs = observations
    if min_liquidity is not None:
        before = len(obs)
        obs = [o for o in obs if o.volume is not None and o.volume >= min_liquidity]
        if verbose:
            print(f"Filtro liquidità (volume>={min_liquidity}): {before} -> {len(obs)} osservazioni")

    train = [o for o in obs if o.close_ts < split_ts]
    holdout = [o for o in obs if o.close_ts >= split_ts]
    if verbose:
        print(f"Train: {len(train)}  Holdout: {len(holdout)}")

    threshold = bonferroni_threshold(len(rules), alpha)
    if verbose:
        print(f"Soglia Bonferroni per {len(rules)} regole: |t| > {threshold:.2f}")

    train_results = [evaluate_rule(r, train) for r in rules]
    survivors_names = {
        res["rule"] for res in train_results
        if res["t"] is not None and abs(res["t"]) > threshold
    }
    survivor_rules = [r for r in rules if r.name in survivors_names]
    if verbose:
        print(f"Sopravvissuti su train: {len(survivor_rules)}/{len(rules)}")

    holdout_results = [evaluate_rule(r, holdout) for r in survivor_rules]

    confirmed = [
        res for res in holdout_results
        if res["t"] is not None and abs(res["t"]) > 1.96 and res["roi"] and res["roi"] > 0
    ]
    if verbose:
        print(f"Confermati su holdout (|t|>1.96, ROI>0): {len(confirmed)}/{len(survivor_rules)}")
        for c in confirmed:
            print(f"  {c['rule']}: n={c['n']} roi={c['roi']:+.3f} t={c['t']:+.2f}")
        if not confirmed and survivor_rules:
            print("  Nessuno confermato — i 'sopravvissuti' su train erano probabilmente rumore.")

    return {
        "threshold": threshold, "train_results": train_results,
        "holdout_results": holdout_results, "confirmed": confirmed,
    }


def selection_bias_check(rule: Rule, excluded_observations: List[Observation]) -> Dict:
    """Testa la stessa regola su un campione ESCLUSO dai filtri usati per costruire il dataset
    principale (es. mercati sotto una soglia di volume). Se la regola 'funziona' solo dentro
    al filtro e fallisce fuori, il filtro probabilmente perde informazione (leak), non il
    caso — vedi README.md per due esempi reali di questo meccanismo."""
    return evaluate_rule(rule, excluded_observations)
