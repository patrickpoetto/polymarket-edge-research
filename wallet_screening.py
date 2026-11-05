"""Screening quantitativo di wallet Polymarket: filtra i market maker, misura
la vera abilità con il Closing Line Value (CLV).

Metodo validato nella notte di ricerca del 2026-11-05 su 170 wallet della
classifica pubblica (12 sopravvissuti ai filtri, 0/12 con CLV positivo —
vedi README.md). Nessuno di questi due passaggi garantisce di trovare un
wallet "buono": il risultato onesto può benissimo essere "nessuno".
"""

from __future__ import annotations

import random
import statistics
import time
from collections import Counter
from typing import Dict, List, Optional

from fetchers import fetch_wallet_activity, fetch_leaderboard, kickoff_timestamp, price_before

MAX_ROWS_BEFORE_MM_ABORT = 50_000  # oltre questa soglia: market maker quasi certo, non vale scaricare tutto


def candidate_pool(limit: int = 100, include_sports: bool = True) -> List[Dict]:
    """Unione deduplicata classifica all-time + classifica 'sports'."""
    pool = {c["user_id"]: c for c in fetch_leaderboard(limit=limit)}
    if include_sports:
        for c in fetch_leaderboard(category="sports", limit=limit):
            pool.setdefault(c["user_id"], c)
    return list(pool.values())


def analyze_wallet_activity(rows: List[Dict]) -> Dict:
    """Statistiche aggregate di uno storico wallet: mercati, taglia bet, ROI grezzo, mix azioni."""
    markets = Counter()
    actions = Counter()
    buy_sizes = []
    buy_total = out_total = 0.0

    for a in rows:
        t = a.get("type", "UNKNOWN")
        actions[t] += 1
        title = a.get("title") or a.get("condition_id", "Unknown")
        markets[title] += 1
        size = float(a.get("size", 0) or 0)
        price = float(a.get("price", 0) or 0)
        usdc = float(a.get("usdc_size", size * price) or 0)
        if t == "TRADE":
            if (a.get("side") or "").upper() == "BUY":
                buy_sizes.append(usdc)
                buy_total += usdc
            else:
                out_total += usdc
        elif t == "REDEEM":
            out_total += usdc

    med = statistics.median(buy_sizes) if buy_sizes else 0
    return {
        "n_rows": len(rows),
        "n_markets": len(markets),
        "max_single_market": markets.most_common(1)[0][1] if markets else 0,
        "actions": dict(actions),
        "buy_median": med,
        "buy_total": buy_total,
        "out_total": out_total,
        "roi_grezzo": (out_total - buy_total) / buy_total * 100 if buy_total else None,
    }


def passes_market_maker_filters(stats: Dict, min_markets: int = 20, min_bet_median: float = 5.0,
                                 max_merge_ratio: float = 0.05, max_single_market: int = 50) -> tuple[bool, List[str]]:
    """Filtri anti-market-maker (soglie validate stanotte). Ritorna (passa, motivi_scarto)."""
    reasons = []
    if stats["n_markets"] < min_markets:
        reasons.append(f"mercati distinti troppo pochi ({stats['n_markets']}<{min_markets})")
    if stats["buy_median"] < min_bet_median:
        reasons.append(f"taglia bet mediana troppo piccola (${stats['buy_median']:.2f}<{min_bet_median})")
    merge_count = stats["actions"].get("MERGE", 0)
    if stats["n_rows"] and merge_count > max_merge_ratio * stats["n_rows"]:
        reasons.append(f"MERGE significativo ({merge_count}/{stats['n_rows']}) — probabile market maker")
    if stats["max_single_market"] > max_single_market:
        reasons.append(f"singolo mercato tradato {stats['max_single_market']} volte (>{max_single_market})")
    return (len(reasons) == 0), reasons


def screen_candidates(candidates: List[Dict], verbose: bool = True) -> List[Dict]:
    """Scarica e filtra una lista di wallet candidati (da candidate_pool). Ritorna tutti i risultati,
    con entry['verdict'] = 'SOPRAVVISSUTO' o 'SCARTATO: <motivo>'."""
    results = []
    for i, c in enumerate(candidates):
        wallet = c["user_id"]
        if verbose:
            print(f"[{i+1}/{len(candidates)}] {wallet} pnl=${c.get('pnl', 0):.0f}", flush=True)
        try:
            rows = fetch_wallet_activity(wallet, max_rows=MAX_ROWS_BEFORE_MM_ABORT)
        except Exception as e:
            results.append({"wallet": wallet, "verdict": f"SCARTATO: errore_fetch:{e}"})
            continue
        entry = {"wallet": wallet, "pnl_leaderboard": c.get("pnl"), "n_rows_fetched": len(rows)}
        if len(rows) > MAX_ROWS_BEFORE_MM_ABORT:
            entry["verdict"] = "SCARTATO: >50k operazioni, market maker quasi certo"
            results.append(entry)
            continue
        stats = analyze_wallet_activity(rows)
        entry["stats"] = stats
        ok, reasons = passes_market_maker_filters(stats)
        entry["verdict"] = "SOPRAVVISSUTO" if ok else "SCARTATO: " + "; ".join(reasons)
        results.append(entry)
        if verbose:
            print(f"  -> {entry['verdict']}", flush=True)
        time.sleep(0.1)
    return results


def closing_line_value(wallet_rows: List[Dict], sample_size: int = 30, max_checked: int = 120,
                        seed: int = 42, verbose: bool = True) -> Dict:
    """Il test vero: CLV = prezzo_di_chiusura - prezzo_d'ingresso su trade PRE-MATCH puliti.

    Positivo e sistematico = skill reale (comprava a sconto rispetto a dove si è
    chiuso il mercato). SOLO trade con entry_ts < kickoff contano — i trade
    in-play falsano il confronto (vedi README.md, errore trovato e corretto
    nella notte del 2026-11-05).
    """
    random.seed(seed)
    trades = [r for r in wallet_rows if r.get("type") == "TRADE" and r.get("side") == "BUY"
              and r.get("event_slug") and r.get("token_id")]
    random.shuffle(trades)

    clv_rows = []
    checked = 0
    for t in trades:
        if len(clv_rows) >= sample_size or checked >= max_checked:
            break
        checked += 1
        entry_price, entry_ts = t.get("price"), t.get("timestamp")
        if entry_price is None or entry_ts is None:
            continue
        kickoff = kickoff_timestamp(t["event_slug"])
        if kickoff is None or entry_ts >= kickoff:
            continue  # niente kickoff noto, o trade in-play: scarta
        closing = price_before(t["token_id"], kickoff)
        if closing is None:
            continue
        clv_rows.append({
            "title": t.get("title", ""), "entry_price": entry_price, "closing_price": closing,
            "clv": closing - entry_price,
        })
        time.sleep(0.1)

    avg_clv = sum(r["clv"] for r in clv_rows) / len(clv_rows) if clv_rows else None
    n_positive = sum(1 for r in clv_rows if r["clv"] > 0)
    result = {
        "n_trades_tested": len(clv_rows), "n_checked": checked,
        "avg_clv": avg_clv, "n_positive": n_positive,
        "share_positive": n_positive / len(clv_rows) if clv_rows else None,
        "rows": clv_rows,
    }
    if verbose:
        print(f"CLV: n={len(clv_rows)} medio={avg_clv} positivi={n_positive}/{len(clv_rows) if clv_rows else 0}")
    return result


def has_demonstrable_edge(clv_result: Dict) -> bool:
    """Soglia concordata nella notte del 2026-11-05: CLV medio chiaramente positivo
    E maggioranza dei trade con ingresso migliore della chiusura."""
    if not clv_result.get("avg_clv") or clv_result["n_trades_tested"] < 10:
        return False
    return clv_result["avg_clv"] > 0 and (clv_result.get("share_positive") or 0) > 0.5
