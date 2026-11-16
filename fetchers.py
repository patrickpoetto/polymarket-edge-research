"""Fetcher di dati Polymarket condivisi dai moduli di edge_lab.

Tre fonti, tutte pubbliche, nessuna chiave richiesta:
- gamma-api.polymarket.com/events: anagrafica eventi/mercati (chiusi o aperti)
- data-api.polymarket.com/v2/activity: storico trade/redeem di un wallet
- clob.polymarket.com/prices-history: serie storica prezzi di un token/mercato

Validato nella notte di ricerca del 2026-11-05 (vedi README.md).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; edge_lab/1.0)"}
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_API_V2_ACTIVITY = "https://data-api.polymarket.com/v2/activity"
DATA_API_V2_LEADERBOARD = "https://data-api.polymarket.com/v2/leaderboard"
CLOB_PRICES_HISTORY = "https://clob.polymarket.com/prices-history"


def fetch_events(tag_slug: str, closed: Optional[bool] = True, max_pages: int = 50) -> List[Dict]:
    """Eventi Polymarket per tag_slug, paginati (offset-based, max 100/pagina)."""
    out: List[Dict] = []
    offset = 0
    limit = 100
    for _ in range(max_pages):
        params = {"tag_slug": tag_slug, "limit": limit, "offset": offset}
        if closed is not None:
            params["closed"] = "true" if closed else "false"
        r = requests.get(GAMMA_EVENTS, params=params, headers=HEADERS, timeout=20)
        data = r.json()
        if not data:
            break
        out.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return out


def fetch_wallet_activity(wallet: str, max_rows: Optional[int] = None) -> List[Dict]:
    """Storico completo trade+redeem di un wallet via Data API v2 (cursore).

    Se max_rows è impostato, si ferma appena lo supera (utile per scartare
    velocemente i market maker senza scaricare milioni di righe — vedi
    screening.py).
    """
    rows: List[Dict] = []
    cursor = None
    while True:
        params = {"user": wallet.lower(), "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(DATA_API_V2_ACTIVITY, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data", [])
        rows.extend(data)
        if max_rows and len(rows) > max_rows:
            break
        pagination = payload.get("pagination", {})
        if not pagination.get("has_more") or not data:
            break
        cursor = pagination.get("next_cursor")
        if not cursor:
            break
        time.sleep(0.05)
    return rows


def fetch_leaderboard(category: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Classifica pubblica Polymarket (all-time). category='sports' filtra per sport."""
    params = {"limit": limit}
    if category:
        params["category"] = category
    r = requests.get(DATA_API_V2_LEADERBOARD, params=params, headers=HEADERS, timeout=20)
    return r.json().get("data", [])


_price_history_cache: Dict[str, List[Dict]] = {}


def get_price_history(token_id: str, start_ts: Optional[int] = None, end_ts: Optional[int] = None,
                       fidelity: int = 60) -> List[Dict]:
    """Serie storica prezzi di un token CLOB. Cache in-process per evitare richieste ripetute."""
    cache_key = f"{token_id}:{start_ts}:{end_ts}:{fidelity}"
    if cache_key in _price_history_cache:
        return _price_history_cache[cache_key]
    params = {"market": token_id, "fidelity": fidelity}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    if start_ts is None and end_ts is None:
        params["interval"] = "max"
    try:
        r = requests.get(CLOB_PRICES_HISTORY, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        hist = r.json().get("history", [])
    except Exception:
        # Do NOT cache a transient failure (timeout, rate limit, bad gateway) as an
        # empty history: the old code cached `[]` here unconditionally, so one
        # network hiccup permanently and silently poisoned this token/window for the
        # rest of the process, quietly shrinking closing_line_value()'s sample
        # (price_before() returns None -> caller does `continue`) with no error ever
        # surfaced. A real empty-but-successful response is still cached normally.
        return []
    _price_history_cache[cache_key] = hist
    return hist


def price_before(token_id: str, cutoff_ts: int, lookback_days: int = 2) -> Optional[float]:
    """Ultimo prezzo noto di un token prima di cutoff_ts (es. il kickoff di una partita)."""
    hist = get_price_history(token_id, start_ts=cutoff_ts - lookback_days * 86400, end_ts=cutoff_ts)
    if not hist:
        return None
    return hist[-1]["p"]


def kickoff_timestamp(event_slug: str) -> Optional[int]:
    """Orario di inizio partita (gameStartTime) di un evento, dato il suo slug."""
    try:
        r = requests.get(GAMMA_EVENTS, params={"slug": event_slug}, headers=HEADERS, timeout=15)
        ev = r.json()
    except Exception:
        return None
    if not ev:
        return None
    for m in ev[0].get("markets", []):
        gst = m.get("gameStartTime")
        if gst:
            # gameStartTime arrives as e.g. "2026-09-23 08:00:00+00" (UTC, no colon
            # in the offset). The naive-datetime .timestamp() call this used to make
            # here interprets the string in the LOCAL system timezone, not UTC — on
            # any machine not set to UTC, kickoff would silently be off by the local
            # UTC offset. That's exactly the kind of in-play-contamination bug the
            # README calls out as already found-and-fixed once; parse as UTC
            # explicitly so entry_ts < kickoff in closing_line_value() is correct
            # regardless of the host machine's timezone.
            dt = datetime.strptime(gst.replace("+00", ""), "%Y-%m-%d %H:%M:%S")
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
    return None
