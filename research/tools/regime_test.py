r"""Market regime (HMM) and volatility (Kalman filter) as risk-size factors for v4 (2026-10-29). Research only.

The user asked to test two ideas from the ML repo mfrdixon/ML_Finance_Codes (chapter 7). Plan, written before the
results: research/notes/2026-10-29-regime-plan.md. The repo's code needs Python 3.6 / PyMC3, so both models are written
here in numpy:
- a Gaussian hidden Markov model (full covariances, Baum-Welch, 5 starts) on BTC's daily or 4h log return and log
  high/low range, fitted on 2020-01 to 2022-09 only; a trade reads the FILTERED probability at the last closed candle
  before its fill (never the smoothed or Viterbi path, which look ahead);
- a Kalman local-level filter on the log daily realized variance (from 4h returns), noise fitted on 2020-01 to 2022-09;
  the filtered level's percentile against the previous 365 days.
Plus the coin's 24 h volatility against its last 30 days. Trades: v4's 4 years and since 2026-08-01 with the fixed
plan's R (data/research/exit_tp/trades.csv, exit_tp_data.py). Candles: data/research/outside.db (Binance 1d/4h).

    .venv\Scripts\python -u research\tools\regime_test.py
"""
from __future__ import annotations

import calendar
import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAY, H4 = 86_400_000, 14_400_000
FIT_END = 1664582400000  # 2022-10-01: the models learn only from the data before the trades
REFIT_END = 1727740800000  # 2024-10-01: the robustness refit, used for 2024-26 and since Aug
SPLIT = 1727740800000
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


e2 = _load("engine2_check")


class HMM:
    """Gaussian hidden Markov model with full covariances, fitted by Baum-Welch (scaled forward-backward). States are
    ordered by their mean of the second input (the range): 0 = calmest."""

    def __init__(self, k: int):
        self.k = k

    def _logb(self, x: np.ndarray) -> np.ndarray:
        out = np.empty((len(x), self.k))
        for j in range(self.k):
            chol = np.linalg.cholesky(self.cov[j])
            z = np.linalg.solve(chol, (x - self.mu[j]).T)
            out[:, j] = -0.5 * (z ** 2).sum(0) - np.log(np.diag(chol)).sum() - 0.5 * x.shape[1] * np.log(2 * np.pi)
        return out

    def _forward(self, x: np.ndarray):
        logb = self._logb(x)
        m = logb.max(1, keepdims=True)
        b = np.exp(logb - m)
        alpha, c = np.empty_like(b), np.empty(len(x))
        a = self.pi * b[0]
        for t in range(len(x)):
            if t:
                a = (alpha[t - 1] @ self.a) * b[t]
            c[t] = a.sum()
            alpha[t] = a / c[t]
        return alpha, b, c, float(np.log(c).sum() + m.sum())

    def _fit_once(self, x: np.ndarray, resp: np.ndarray, iters: int = 300) -> float:
        k, d = self.k, x.shape[1]
        self.pi = np.full(k, 1 / k)
        self.a = np.full((k, k), 0.1 / max(k - 1, 1)) + np.eye(k) * (0.9 - 0.1 / max(k - 1, 1))
        self._m_step(x, resp)
        last = -np.inf
        for _ in range(iters):
            alpha, b, c, ll = self._forward(x)
            beta = np.empty_like(alpha)
            beta[-1] = 1.0
            for t in range(len(x) - 2, -1, -1):
                beta[t] = (self.a @ (b[t + 1] * beta[t + 1])) / c[t + 1]
            gamma = alpha * beta
            gamma /= gamma.sum(1, keepdims=True)
            w = b[1:] * beta[1:] / c[1:, None]
            xi = self.a * (alpha[:-1].T @ w)
            self.pi = gamma[0]
            self.a = xi / xi.sum(1, keepdims=True)
            self._m_step(x, gamma)
            if ll - last < 1e-7 * abs(ll):
                break
            last = ll
        return self._forward(x)[3]

    def _m_step(self, x: np.ndarray, resp: np.ndarray) -> None:
        n = resp.sum(0) + 1e-9
        self.mu = (resp.T @ x) / n[:, None]
        self.cov = np.array([((resp[:, j, None] * (x - self.mu[j])).T @ (x - self.mu[j])) / n[j] + 1e-4 * np.eye(x.shape[1])
                             for j in range(self.k)])

    def fit(self, x: np.ndarray, starts: int = 5) -> "HMM":
        best = None
        order = np.argsort(np.argsort(x[:, 1]))  # start from range quantile groups, then random responsibilities
        for s in range(starts):
            if s == 0:
                resp = np.eye(self.k)[np.minimum(order * self.k // len(x), self.k - 1)]
            else:
                resp = np.random.default_rng(s).dirichlet(np.ones(self.k), size=len(x))
            ll = self._fit_once(x, resp)
            if best is None or ll > best[0]:
                best = (ll, self.pi.copy(), self.a.copy(), self.mu.copy(), self.cov.copy())
        _, self.pi, self.a, self.mu, self.cov = best
        o = np.argsort(self.mu[:, 1])
        self.pi, self.a, self.mu, self.cov = self.pi[o], self.a[np.ix_(o, o)], self.mu[o], self.cov[o]
        return self

    def filtered(self, x: np.ndarray) -> np.ndarray:
        """P(state at t | inputs up to t) for every t."""
        return self._forward(x)[0]


def kalman(y: np.ndarray, q: float, r: float) -> tuple[np.ndarray, float]:
    """Local-level filter: level_t = level_t-1 + N(0, q), y_t = level_t + N(0, r). (filtered levels, log-likelihood)."""
    x, p, ll = y[0], r, 0.0
    out = np.empty(len(y))
    for t, yt in enumerate(y):
        p += q
        s = p + r
        e = yt - x
        ll -= 0.5 * (np.log(2 * np.pi * s) + e * e / s)
        x += p / s * e
        p *= r / s
        out[t] = x
    return out, ll


def candles(conn: sqlite3.Connection, coin: str, tf: str) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT time, open, high, low, close FROM candles WHERE symbol = ? AND tf = ? ORDER BY time",
                           conn, params=(coin, tf))
    return df.drop_duplicates("time").reset_index(drop=True)


def hmm_inputs(df: pd.DataFrame) -> np.ndarray:
    lr = np.log(df["close"] / df["close"].shift(1))
    rng = np.log(df["high"] / df["low"])
    return np.column_stack([lr.fillna(0).to_numpy(), rng.to_numpy()])


def hmm_probs(df: pd.DataFrame, step: int, k: int, fit_end: int) -> tuple[np.ndarray, np.ndarray, HMM]:
    """(close times, filtered P(state), the model): fitted on the candles closed before fit_end, standardized with
    that sample's mean and spread."""
    x = hmm_inputs(df)[1:]
    close = df["time"].to_numpy()[1:] + step
    train = close <= fit_end
    mean, sd = x[train].mean(0), x[train].std(0)
    z = (x - mean) / sd
    model = HMM(k).fit(z[train])
    return close, model.filtered(z), model


def daily_rv(df4: pd.DataFrame) -> pd.Series:
    """Log realized variance of each UTC day from its 4h log returns (days with all six candles)."""
    lr = np.log(df4["close"] / df4["close"].shift(1))
    day = df4["time"] // DAY * DAY
    g = pd.DataFrame({"day": day, "r2": lr ** 2}).iloc[1:].groupby("day")["r2"].agg(["sum", "size"])
    g = g[g["size"] == 6]
    return np.log(g["sum"] + 1e-10)


def vol_percentile(df4: pd.DataFrame, fit_end: int, window: int = 365) -> tuple[np.ndarray, np.ndarray]:
    """(close times of the days, percentile of the Kalman-filtered log variance against the previous `window` days)."""
    y = daily_rv(df4)
    close = y.index.to_numpy() + DAY
    yy = y.to_numpy()
    train = yy[close <= fit_end]
    best = None
    for q in np.geomspace(1e-4, 1.0, 25):
        for r in np.geomspace(1e-2, 10.0, 25):
            ll = kalman(train, q, r)[1]
            if best is None or ll > best[0]:
                best = (ll, q, r)
    level = kalman(yy, best[1], best[2])[0]
    pct = np.full(len(level), np.nan)
    for i in range(window, len(level)):
        pct[i] = (level[i - window:i] < level[i]).mean()
    return close, pct


def vol_ratio(df4: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(close times, realized vol of the last six 4h candles / its median over the 180 candles before)."""
    lr = np.log(df4["close"] / df4["close"].shift(1))
    rv = np.sqrt((lr ** 2).rolling(6).sum())
    base = rv.shift(6).rolling(180).median()
    return df4["time"].to_numpy() + H4, (rv / base).to_numpy()


def at(close: np.ndarray, values: np.ndarray, t: np.ndarray) -> np.ndarray:
    """The value of the last candle closed at or before each t."""
    i = np.searchsorted(close, t, side="right") - 1
    out = values[np.maximum(i, 0)].astype(float)
    out[i < 0] = np.nan
    return out


def account(df: pd.DataFrame, mult: np.ndarray, a_risk: float = 0.03, b_risk: float = 0.02, start: float = 150.0) -> tuple:
    """engine2_check.account with each trade's risk multiplied by `mult` (same order of trades)."""
    bal = peak = start
    dd = 0.0
    open_: list[tuple] = []
    n = 0
    for row in df.assign(m=mult).sort_values("entry_time").itertuples(index=False):
        for pos in sorted([p for p in open_ if p[0] <= row.entry_time]):
            bal += pos[3] * pos[4]
            peak = max(peak, bal)
            dd = max(dd, 1 - bal / peak)
        open_ = [p for p in open_ if p[0] > row.entry_time]
        on_coin = [p for p in open_ if p[1] == row.symbol]
        if any(p[2] != row.side for p in on_coin) or len(on_coin) >= 2:
            continue
        if len(open_) >= 5 and on_coin:
            continue
        want = bal * (a_risk if row.quality == "A" else b_risk) * row.m
        room = 0.12 * bal - sum(p[3] for p in open_)
        risk = min(want, room)
        if risk < 0.25 * want:
            continue
        open_.append((row.exit_time, row.symbol, row.side, risk, row.r))
        n += 1
    for pos in sorted(open_):
        bal += pos[3] * pos[4]
        peak = max(peak, bal)
        dd = max(dd, 1 - bal / peak)
    return n, bal, dd


def clustered_t(diff_mask_r: np.ndarray, hi: np.ndarray, lo: np.ndarray, day: np.ndarray) -> float:
    """t of mean(R | hi) - mean(R | lo), resampling days (a block bootstrap of whole days, fixed seed)."""
    rng = np.random.default_rng(7)
    days = np.unique(day)
    idx = {d: np.nonzero(day == d)[0] for d in days}
    obs = diff_mask_r[hi].mean() - diff_mask_r[lo].mean()
    draws = []
    for _ in range(1000):
        pick = np.concatenate([idx[d] for d in rng.choice(days, len(days))])
        h, l = pick[hi[pick]], pick[lo[pick]]
        if len(h) and len(l):
            draws.append(diff_mask_r[h].mean() - diff_mask_r[l].mean())
    return obs / np.std(draws)


def main() -> None:
    tr = pd.read_csv(ROOT / "data" / "research" / "exit_tp" / "trades.csv")
    tr = tr[(tr["sample"] == "aug") | ((tr["sample"] == "4y") & tr["v4"])].reset_index(drop=True)
    t = tr["entry_time"].to_numpy()
    conn = sqlite3.connect(f"file:{(ROOT / 'data/research/outside.db').as_posix()}?mode=ro", uri=True)
    btc1d, btc4h = candles(conn, "BTC", "1d"), candles(conn, "BTC", "4h")
    out = []
    say = lambda s="": (print(s, flush=True), out.append(s))

    # the factors, each read at the last candle closed before the fill
    f = pd.DataFrame(index=tr.index)
    models = {}
    for name, df, step, k, fit_end in (("F1 HMM2 daily", btc1d, DAY, 2, FIT_END), ("F2 HMM3 daily", btc1d, DAY, 3, FIT_END),
                                      ("F3 HMM2 4h", btc4h, H4, 2, FIT_END), ("F1b HMM2 daily refit", btc1d, DAY, 2, REFIT_END),
                                      ("F2b HMM3 daily refit", btc1d, DAY, 3, REFIT_END), ("F3b HMM2 4h refit", btc4h, H4, 2, REFIT_END)):
        close, p, model = hmm_probs(df, step, k, fit_end)
        models[name] = model
        probs = np.column_stack([at(close, p[:, j], t) for j in range(k)])
        f[name] = probs.argmax(1) if k == 3 else (probs[:, -1] > 0.5).astype(int)
        f[name + " p"] = probs[:, -1]
        raw = hmm_inputs(df)[1:]
        state = p.argmax(1)
        ranges = [np.expm1(raw[state == j, 1]).mean() * 100 if (state == j).any() else float("nan") for j in range(k)]
        say(f"{name}: high-low range a candle by filtered state (calm..volatile) {np.round(ranges, 2).tolist()}%;"
            f" share of candles {np.round(np.bincount(state, minlength=k) / len(state), 2).tolist()};"
            f" stay probabilities {np.round(np.diag(model.a), 3).tolist()};"
            f" volatile state on {f[name].mean() if k == 2 else (f[name] == 2).mean():.0%} of trades")
    close, pct = vol_percentile(btc4h, FIT_END)
    f["F4 BTC vol pct"] = at(close, pct, t)
    for c in ("XRP", "SOL", "ETH"):
        d4 = candles(conn, c, "4h")
        sel = (tr["symbol"] == c).to_numpy()
        close, pct = vol_percentile(d4, FIT_END)
        f.loc[sel, "F5 coin vol pct"] = at(close, pct, t[sel])
        close, ratio = vol_ratio(d4)
        f.loc[sel, "F6 coin 24h/30d"] = at(close, ratio, t[sel])

    four = (tr["sample"] == "4y").to_numpy()
    h1, h2, aug = four & (t < SPLIT), four & (t >= SPLIT), (tr["sample"] == "aug").to_numpy()
    cut6 = np.nanquantile(f.loc[h1, "F6 coin 24h/30d"], [1 / 3, 2 / 3])

    def thirds(v: np.ndarray, cuts) -> np.ndarray:
        b = np.digitize(v, cuts)
        b[np.isnan(v)] = -1  # no value: no bucket
        return b

    buckets = {  # factor -> (bucket of every trade: 0 calm .. 2 volatile, -1 none; names)
        "F1 HMM2 daily": (f["F1 HMM2 daily"].to_numpy() * 2, ["calm", "", "volatile"]),
        "F2 HMM3 daily": (f["F2 HMM3 daily"].to_numpy(), ["calm", "middle", "volatile"]),
        "F3 HMM2 4h": (f["F3 HMM2 4h"].to_numpy() * 2, ["calm", "", "volatile"]),
        "F4 BTC vol pct": (thirds(f["F4 BTC vol pct"].to_numpy(), [1 / 3, 2 / 3]), ["low", "mid", "high"]),
        "F5 coin vol pct": (thirds(f["F5 coin vol pct"].to_numpy(), [1 / 3, 2 / 3]), ["low", "mid", "high"]),
        "F6 coin 24h/30d": (thirds(f["F6 coin 24h/30d"].to_numpy(), cut6), ["low", "mid", "high"]),
        "F1b HMM2 daily refit": (f["F1b HMM2 daily refit"].to_numpy() * 2, ["calm", "", "volatile"]),
        "F2b HMM3 daily refit": (f["F2b HMM3 daily refit"].to_numpy(), ["calm", "middle", "volatile"]),
        "F3b HMM2 4h refit": (f["F3b HMM2 4h refit"].to_numpy() * 2, ["calm", "", "volatile"]),
    }
    r = tr["r_plan"].to_numpy()
    day = t // DAY
    say("")
    say(f"v4 trades: 4 years {four.sum()} (2022-24 {h1.sum()}, 2024-26 {h2.sum()}), since Aug {aug.sum()}; R a trade of the fixed plan"
        f" (4y {r[four].mean():+.3f}, Aug {r[aug].mean():+.3f}); F6 cut points from 2022-24: {np.round(cut6, 2).tolist()}")
    say("factor / bucket: trades and R a trade | 4 years | 2022-24 | 2024-26 | since Aug")
    for name, (b, labels) in buckets.items():
        ok = b >= 0
        say(f"{name}:")
        for j, lab in enumerate(labels):
            if not lab:
                continue
            m = (b == j) & ok
            cells = []
            for w in (four, h1, h2, aug):
                g = m & w
                cells.append(f"{g.sum():4d} {r[g].mean() if g.any() else float('nan'):+.3f}")
            say(f"   {lab:9} " + " | ".join(cells))
        hi, lo = (b == 2) & ok, (b == 0) & ok
        diffs = [r[hi & w].mean() - r[lo & w].mean() if (hi & w).any() and (lo & w).any() else float("nan") for w in (four, h1, h2, aug)]
        tt = clustered_t(r[four], hi[four], lo[four], day[four])
        same = np.sign(diffs[1]) == np.sign(diffs[2]) == np.sign(diffs[3])
        say(f"   high - low: 4y {diffs[0]:+.3f} (t {tt:+.1f}) | 2022-24 {diffs[1]:+.3f} | 2024-26 {diffs[2]:+.3f} | Aug {diffs[3]:+.3f}"
            f"  -> {'PASS' if same and abs(tt) >= 2 else 'fail'}")

    # tier B only: does a factor add anything beyond tier A?
    say("")
    say("tier B trades only (high - low): 4y | 2022-24 | 2024-26 | Aug")
    bq = (tr["quality"] == "B").to_numpy()
    for name, (b, _labels) in buckets.items():
        hi, lo = (b == 2) & bq, (b == 0) & bq
        say(f"   {name:22} " + " | ".join(f"{r[hi & w].mean() - r[lo & w].mean():+.3f}" for w in (four, h1, h2, aug)))

    # sizing in the account at the same average risk
    say("")
    df = pd.DataFrame({"symbol": tr["symbol"], "side": tr["side"], "entry_time": tr["entry_time"], "exit_time": tr["x_plan"],
                       "r": r, "quality": tr["quality"]})
    check = [e2.account(df[w])[1:] == account(df[w], np.ones(w.sum()))[1:] for w in (four, h1, h2, aug)]
    say(f"account check (all multipliers 1 = engine2_check.account): {all(check)}")
    say("account at the user's rules, $150: 4 years | 2022-24 | 2024-26 | since Aug")
    rows = [("now (A 3% / B 2%)", np.ones(len(tr)))]
    for name in ("F1 HMM2 daily", "F2 HMM3 daily", "F3 HMM2 4h", "F4 BTC vol pct", "F5 coin vol pct", "F6 coin 24h/30d"):
        b = buckets[name][0]
        rows.append((f"size by {name}", np.select([b == 0, b == 2], [0.75, 1.25], 1.0)))
    for label, mult in rows:
        cells = []
        for w in (four, h1, h2, aug):
            m = mult[w] / mult[w].mean()  # the same average risk as now
            n, bal, dd = account(df[w], m)
            cells.append(f"${bal:,.0f} DD {dd:.0%}")
        say(f"   {label:28} " + " | ".join(cells))
    text = "\n".join(out)
    (ROOT / "data" / "research" / "regime_test.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
