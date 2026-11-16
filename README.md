# edge_lab

Quantitative research into whether a reproducible statistical edge exists on
Polymarket's sports-betting markets. The short answer, after a focused
research push, is **not yet** — but the negative result is itself the point:
this repo is a record of rigorous testing methodology, not a trading bot.

Three independent approaches were tested with real data and real statistical
controls. All three came back honestly negative. A fourth finding — how two
different near-miss "false positives" were caught and debunked — is arguably
the most useful output of the project, because the same failure modes
(selection-bias leaks, thin "shadow" markets producing inflated t-stats) are
exactly the kind of mistake that makes amateur backtests look profitable when
they aren't.

## Why this is here

Negative results are normally invisible — nobody publishes "I tried this and
it didn't work." But the discipline required to *prove* something doesn't
work (proper train/holdout splits, multiple-testing correction, bias
detection) is the same discipline that matters when something eventually
does. This repo demonstrates that process end to end: data collection,
hypothesis testing, statistical correction, and — critically — auditing your
own false positives instead of reporting them as wins.

## What was tested

### 1. Copy-trading a profitable wallet — none found

170 candidate wallets were pulled from Polymarket's public leaderboard (top
100 all-time + top 100 in the sports category). A market-maker filter
removed wallets showing classic liquidity-provision signatures (a single
market traded >50 times, median bet size <$5, >5% `MERGE` operations — i.e.
buying both sides of a market). **12 wallets survived the filter.**

Each of the 12 was tested with **Closing Line Value (CLV)**: entry price vs.
the last price before kickoff, pre-match trades only. **0 of 12 showed both
a positive average CLV and a majority of trades beating the closing price.**
Some had very high raw ROI (e.g. +34%, +28%), but negative CLV — meaning the
raw profit most likely reflects variance or bet sizing, not entry skill.

Code: `wallet_screening.py` (`candidate_pool`, `screen_candidates`,
`closing_line_value`, `has_demonstrable_edge`).

### 2. Published strategies (arbitrage, market-making, copy-trading, bias exploitation)

Verified by cloning and inspecting third-party repos directly — not by
trusting their README claims:

- **Same-event cross-market arbitrage**: 369 opportunities observed over 2
  days, **0 executable** once a realistic 1-second taker hold time on
  soccer markets is applied.
- **In-play market making**: -$23,055 over a 13-day replay, losing on 12 of
  13 days.
- **Delayed copy-trading**: source wallets earned +$2.33 per $10 wagered;
  copying the same trades 1-5 seconds late returned ~$0 per $10.
- **Favorite-longshot bias as a trading rule**: 35,000 markets, ≈$0 per $1
  wagered after correcting for multiple testing.
- **One partial positive**: a real, on-chain-verifiable pure-arbitrage bot
  (`kachence/polymm`) netted +$5k before its author shut it down because it
  had become too slow to defend its edge — a latency/liquidity catch-22
  consistent with findings from a related manual-trading project.

### 3. A personal betting pattern — doesn't survive a larger sample

A trader's personal sample of 29 over/under-goals bets showed +5.6% ROI
(vs. -5.4% on moneyline/spread bets). Tested against a much larger sample
with two independent methods:

- **Simple method** (300 observations, Serie A + Bundesliga, closing price
  vs. actual outcome): ROI -3.1%, **t = -1.45, not significant**.
- **Rigorous tournament method** (9,096 markets, 61 rule configurations,
  Bonferroni-corrected threshold, time-based train/holdout split): one
  dramatic false signal (t up to +28) was traced to **shadow markets on
  absurd goal lines (6.5-8.5 goals) where 32% of total volume was under
  $50** — i.e. markets that were never really traded. Restricting to liquid
  lines only (2.5-4.5 goals): ROI +14.8% but **t = +1.73, not significant**.

Both methods agree: the original 29-bet signal was most likely sampling
noise.

## The most important methodological lesson — found twice, two different ways

A huge t-stat is not proof of an edge; it's a reason to go dig for the bug:

1. **Filter leak** (found while auditing a third-party repo, cloned and
   inspected directly): a reported +18% ROI at t = +8.36 over 14,217
   observations turned out to be an artifact of a final-volume filter
   (≥$25k) that unintentionally selected for markets where an upset had
   *already happened* (upsets attract late volume). Disproven by re-running
   the same rule on the markets the filter excluded: ROI -9.7% / -13.7% /
   -26.4%.
2. **Shadow markets** (found independently, see finding 3 above): a t-stat
   as high as +28 on markets that were never really traded (<$50 of actual
   volume).

`backtest.py` builds both protections in as defaults rather than optional
extras: `run_tournament()` performs a time-based train/holdout split and
applies Bonferroni correction for multiple testing; `selection_bias_check()`
exists specifically to re-run finding (1)'s check against any future filter;
and the `min_liquidity` parameter of `run_tournament()` guards against
finding (2).

## Methodology summary

- **CLV screening**: filter out market-making wallets, then test genuine
  entry skill via closing-line value rather than raw PnL.
- **Tournament backtesting with Bonferroni correction**: test many candidate
  rules in parallel, keep only the ones whose train-set t-stat clears a
  threshold that scales with the number of rules tested, confirm survivors
  exactly once on a held-out, time-separated sample.
- **Selection-bias auditing**: whenever a rule "works" only inside a data
  filter, deliberately re-test it on the data the filter excluded. If it
  fails there, the filter was probably leaking information about the
  outcome, not describing a real edge.

## Repository structure

- `fetchers.py` — thin wrappers around Polymarket's public APIs: Gamma API
  (events/market metadata), Data API v2 (wallet activity, leaderboards),
  and CLOB (historical prices). No API key required; everything used is
  public.
- `wallet_screening.py` — wallet-screening pipeline (anti-market-maker
  filters + CLV test), validated against 170 real wallets.
- `backtest.py` — a rigorous tournament backtesting framework (time-based
  train/holdout split, t-statistics, Bonferroni correction, selection-bias
  check), an original implementation inspired by the *method* (not the
  code) of a third-party project audited during this research.

## Tech stack

- Python 3.13
- `requests` for all API access
- `scipy` (optional) for an exact Bonferroni/normal-quantile threshold;
  falls back to a reasonable closed-form approximation if unavailable
- Standard library only otherwise (`statistics`, `dataclasses`, `math`)

## How to run

```bash
pip install requests scipy  # scipy is optional
```

```python
from wallet_screening import candidate_pool, screen_candidates, closing_line_value
from fetchers import fetch_wallet_activity

candidates = candidate_pool(limit=100, include_sports=True)
results = screen_candidates(candidates)

survivors = [r for r in results if r["verdict"] == "SOPRAVVISSUTO"]
rows = fetch_wallet_activity(survivors[0]["wallet"])
clv = closing_line_value(rows)
```

```python
from backtest import Observation, Rule, run_tournament

observations = [Observation(price=0.62, outcome=1, close_ts=1700000000, volume=1200)]
rules = [Rule(name="example", select=lambda obs: (1, 0.01))]

result = run_tournament(rules, observations, split_ts=1700500000, min_liquidity=50)
```

No API keys or credentials are required anywhere in this codebase — every
endpoint used is public.

**Network note**: `gamma-api.polymarket.com`, `data-api.polymarket.com`, and
`clob.polymarket.com` are unreachable from some networks for reasons that
have nothing to do with this code — e.g. in Italy they're intercepted at the
ISP level by the ADM gambling-site block (AAMS/"Stop Alle Scommesse
Illegali"), which serves a certificate for `sito-inibito-giochi.adm.gov.it`
instead of the real host, so `requests` fails with a TLS hostname-mismatch
error, not a connection refusal. If you hit that, it's a network-level block
on the client side, not a dead endpoint — confirmed independently against
all three hosts and with a public DNS resolver during this review.

## Verified during this review (2026-11-16)

Re-tested end to end against live and synthetic data as part of a
portfolio-quality pass:

- All three Polymarket hosts above were unreachable from the review
  environment for the reason noted above, so the statistical modules were
  instead verified with constructed data shaped exactly like the real v2
  `/activity` and CLOB `/prices-history` payloads.
- **Found and fixed a real bug in `kickoff_timestamp()`** (`fetchers.py`):
  it parsed Polymarket's `gameStartTime` (always UTC) as a naive datetime and
  called `.timestamp()` on it, which silently interprets naive datetimes in
  the *host machine's local timezone*. On any machine not set to UTC, the
  computed kickoff time was off by the local UTC offset (confirmed: 4 hours
  on a US-Eastern host) — which is exactly the pre-match/in-play contamination
  bug this project's CLV test claims to guard against (see "filter leak" and
  "shadow markets" above), just in a place that hadn't been re-checked since
  the original research night. Fixed by parsing explicitly as UTC.
- Also fixed a smaller reliability bug in `get_price_history()`: a transient
  network error (timeout, rate limit) was cached as a permanent empty result
  for that token/window, silently shrinking any CLV sample computed
  afterwards with no error ever surfacing. Failures are no longer cached.
- The Bonferroni / t-stat / train-holdout logic in `backtest.py` was
  stress-tested with synthetic data: the exact threshold matches
  `scipy.stats.norm.ppf` to machine precision; a tournament of 1 real
  (constructed) edge plus 40 pure-noise rules correctly surfaced only the
  real one; and across 25 trials of *purely random, no-edge* data with 80
  candidate rules each (2,000 rule-trials total), an uncorrected single
  `|t| > 1.96` threshold produced a false "discovery" in 24/25 trials (128
  total), while the full Bonferroni + holdout-reconfirmation pipeline
  produced **zero** false discoveries. Train/holdout were confirmed strictly
  time-disjoint with no leakage into the Bonferroni threshold or survivor
  selection.
- `wallet_screening.py`'s market-maker filters and CLV math were checked
  against hand-computed expected values on synthetic wallets (clean wallet,
  market-maker-signature wallet, sub-$5-median wallet, balanced/all-positive
  CLV cases) and matched exactly.

## Status

Closed as of the 2026-11-05 research session with three honest negative
results and two documented false-positive post-mortems. Not abandoned —
natural next steps (untested leagues, information edges outside soccer,
periodic wallet re-screening) are open, just not yet pursued without a
concrete reason, since testing ideas at random without correction is exactly
how false positives get manufactured in the first place.
