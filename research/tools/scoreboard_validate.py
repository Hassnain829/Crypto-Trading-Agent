r"""Walk-forward validation of the proposed Bayesian factor scoreboard (2026-10-29). Research only; nothing is built.

Design: research/notes/2026-10-29-bayesian-scoreboard-design.md. Plan, written before the results:
research/notes/2026-10-29-scoreboard-validation-plan.md. At every moment the scoreboard knows only the trades closed
before it. Two tests:
1. calibration: every 30 days, for each group, the predictive probability that it beats the rest over the next 90 days,
   against what happened (Brier score against a coin flip's 0.25);
2. sizing: S0 today (tier A 3%, B 2%), S1 tier A at 3% only while P(A > B) >= 80%, S2 the 3% trades picked by a
   Bayesian linear regression on the factor flags (top 18% of the previous 300 predictions); the simple account at the
   user's rules (engine2_check.account).
Samples: v4's 4 years and since 2026-08-01 (data/research/exit_tp/trades.csv), the context of each trade from its own
journal; since Aug, the scoreboard starts with the 4-year trades closed before 2026-08-01 as its history.

    .venv\Scripts\python -u research\tools\scoreboard_validate.py
"""
from __future__ import annotations

import calendar
import importlib.util
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAY, GAP = 86_400_000, 30 * 60_000
SPLIT = 1727740800000  # 2024-10-01
AUG = calendar.timegm((2026, 8, 1, 0, 0, 0)) * 1000
CAL_START = calendar.timegm((2023, 1, 1, 0, 0, 0)) * 1000
GROUPS = ["A", "a_oi_trendline", "c_chart4h", "d_btc12h", "long", "XRP", "SOL", "ETH", "dip_found", "htf4h_with", "squeeze",
          "fear_greed_extreme", "active_24h"]
FEATURES = ["a_oi_trendline", "c_chart4h", "d_btc12h", "long", "XRP", "SOL", "dip_found", "htf4h_with", "squeeze",
            "fear_greed_extreme", "active_24h"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


e2 = _load("engine2_check")
rt = _load("regime_test")
phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))


def load() -> pd.DataFrame:
    tr = pd.read_csv(ROOT / "data" / "research" / "exit_tp" / "trades.csv")
    tr = tr[(tr["sample"] == "aug") | ((tr["sample"] == "4y") & tr["v4"])].reset_index(drop=True)
    ctx = {}
    for sample, path in (("4y", "data/replay/journal-news.db"), ("aug", "data/replay/journal-stopdip-2026-08-01.db")):
        ids = tr.loc[tr["sample"] == sample, "id"].astype(int).tolist()
        conn = sqlite3.connect(f"file:{(ROOT / path).as_posix()}?mode=ro", uri=True)
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            for tid, j in conn.execute(f"SELECT id, context_json FROM trades WHERE id IN ({','.join('?' * len(part))})", part):
                ctx[(sample, tid)] = json.loads(j or "{}")
    rows = []
    for x in tr.itertuples(index=False):
        c = ctx.get((x.sample, int(x.id)), {})
        d = 1 if x.side == "long" else -1
        reason = (c.get("quality_reason") or "").lower()
        if x.sample == "4y":
            a, ch, bt = bool(x.fa), bool(x.fc), bool(x.fd)
        else:
            a, ch, bt = ("trendline" in reason or "open interest" in reason), "chart" in reason, "btc" in reason
        htf4 = (c.get("htf") or {}).get("4h")
        fg = c.get("fear_greed")
        rows.append(dict(A=x.quality == "A", a_oi_trendline=a, c_chart4h=ch, d_btc12h=bt, long=d > 0, XRP=x.symbol == "XRP",
                         SOL=x.symbol == "SOL", ETH=x.symbol == "ETH",
                         dip_found=bool((c.get("dip_entry") or {}).get("dip_found")),
                         htf4h_with=(htf4 == "bull" and d > 0) or (htf4 == "bear" and d < 0), squeeze=bool(c.get("sqz_fire")),
                         fear_greed_extreme=fg is not None and (fg < 20 or fg > 80)))
    tr = pd.concat([tr.drop(columns=["long"]), pd.DataFrame(rows)], axis=1)
    conn = sqlite3.connect(f"file:{(ROOT / 'data/research/outside.db').as_posix()}?mode=ro", uri=True)
    tr["active_24h"] = False
    for coin in ("XRP", "SOL", "ETH"):
        close, ratio = rt.vol_ratio(rt.candles(conn, coin, "4h"))
        sel = (tr["symbol"] == coin).to_numpy()
        tr.loc[sel, "active_24h"] = rt.at(close, ratio, tr.loc[sel, "entry_time"].to_numpy()) >= 1.44
    return tr


def clusters(t: np.ndarray) -> np.ndarray:
    """Move ids: trades entered within 30 minutes of the previous entry belong to the same move (the gate's rule)."""
    order = np.argsort(t, kind="stable")
    ids = np.empty(len(t), int)
    cur, last = -1, None
    for i in order:
        if last is None or t[i] - last > GAP:
            cur += 1
        ids[i] = cur
        last = t[i]
    return ids


class Board:
    """The scoreboard over one set of trades (history first, then the sample), queried at any time."""

    def __init__(self, df: pd.DataFrame, tau: float):
        self.r = df["r_plan"].to_numpy()
        self.entry = df["entry_time"].to_numpy()
        self.exit = df["x_plan"].to_numpy()
        self.move = clusters(self.entry) + np.where(df["sample"].to_numpy() == "aug", 10 ** 6, 0)  # samples never share a move
        self.flags = {g: df[g].to_numpy(dtype=bool) for g in GROUPS}
        self.x = df[FEATURES].to_numpy(dtype=float)
        self.tau = tau

    def known(self, t: int) -> np.ndarray:
        return self.exit <= t

    def base(self, k: np.ndarray) -> tuple[float, float]:
        return (self.r[k].mean(), self.r[k].std(ddof=1)) if k.sum() >= 10 else (0.0, 1.2)

    def post(self, m: np.ndarray, mu0: float, sigma: float) -> tuple[float, float, int]:
        n_eff = len(np.unique(self.move[m]))
        if not m.any():
            return mu0, self.tau ** 2, 0
        prec = n_eff / sigma ** 2 + 1 / self.tau ** 2
        return (n_eff / sigma ** 2 * self.r[m].mean() + mu0 / self.tau ** 2) / prec, 1 / prec, n_eff

    def p_better(self, t: int, g: str) -> float:
        k = self.known(t)
        mu0, sigma = self.base(k)
        mg, vg, _ = self.post(k & self.flags[g], mu0, sigma)
        mr, vr, _ = self.post(k & ~self.flags[g], mu0, sigma)
        return phi((mg - mr) / math.sqrt(vg + vr))

    def fit(self, t: int) -> tuple[float, np.ndarray, np.ndarray] | None:
        """Bayesian ridge regression of R on the centred flags; each move counts once; intercept = the known mean."""
        k = self.known(t)
        if k.sum() < 25:
            return None
        mu0, sigma = self.base(k)
        size = pd.Series(self.move[k]).map(pd.Series(self.move[k]).value_counts()).to_numpy()
        w = 1.0 / size
        xbar = self.x[k].mean(0)
        xc = self.x[k] - xbar
        a = (xc * w[:, None]).T @ xc / sigma ** 2 + np.eye(xc.shape[1]) / self.tau ** 2
        beta = np.linalg.solve(a, (xc * w[:, None]).T @ (self.r[k] - mu0) / sigma ** 2)
        return mu0, xbar, beta


def walk(board: Board, sample: np.ndarray) -> pd.DataFrame:
    """S1 and S2 labels and the scoreboard's numbers at each sample trade's entry (only trades closed before it)."""
    out, preds, model, fitted_at = [], [], None, -1
    for i in np.argsort(board.entry, kind="stable"):
        if not sample[i]:
            continue
        t = board.entry[i]
        n_known = int(board.known(t).sum())
        if model is None or n_known - fitted_at >= 25:
            model, fitted_at = board.fit(t), n_known
        pred = None if model is None else model[0] + (board.x[i] - model[1]) @ model[2]
        recent = [p for p in preds[-300:] if p is not None]
        if pred is None or len(recent) < 50:
            s2 = "A" if board.flags["A"][i] else "B"  # no model yet: today's rule
        else:
            s2 = "A" if pred >= np.quantile(recent, 0.82) else "B"
        preds.append(pred)
        p_a = board.p_better(t, "A") if board.flags["A"][i] else float("nan")
        s1 = "A" if board.flags["A"][i] and p_a >= 0.8 else "B"
        out.append((i, s1, s2, p_a, pred))
    return pd.DataFrame(out, columns=["i", "s1", "s2", "p_a", "pred"]).set_index("i")


def calibration(board: Board, sample: np.ndarray, start: int, end: int, step: int = 30 * DAY, horizon: int = 90 * DAY) -> pd.DataFrame:
    rows = []
    for t in range(start, end, step):
        k = board.known(t)
        mu0, sigma = board.base(k)
        fut = sample & (board.entry > t) & (board.entry <= t + horizon)
        for g in GROUPS:
            f = board.flags[g]
            fg, fr = fut & f, fut & ~f
            ng, nr = len(np.unique(board.move[fg])), len(np.unique(board.move[fr]))
            if ng < 5 or nr < 5:
                continue
            mg, vg, _ = board.post(k & f, mu0, sigma)
            mr, vr, _ = board.post(k & ~f, mu0, sigma)
            p_post = phi((mg - mr) / math.sqrt(vg + vr))
            p_pred = phi((mg - mr) / math.sqrt(vg + vr + sigma ** 2 / ng + sigma ** 2 / nr))
            rows.append((t, g, p_post, p_pred, int(board.r[fg].mean() > board.r[fr].mean()), mg - mr,
                         board.r[fg].mean() - board.r[fr].mean()))
    return pd.DataFrame(rows, columns=["t", "group", "p_post", "p_pred", "won", "est_diff", "real_diff"])


def cal_report(c: pd.DataFrame, say, label: str) -> None:
    if c.empty:
        say(f"   {label}: no forecasts")
        return
    brier = ((c["p_pred"] - c["won"]) ** 2).mean()
    conf = c[(c["p_post"] >= 0.8) | (c["p_post"] <= 0.2)]
    hit = ((conf["p_post"] >= 0.8) == (conf["won"] == 1)).mean() if len(conf) else float("nan")
    corr = np.corrcoef(c["est_diff"], c["real_diff"])[0, 1] if len(c) > 2 else float("nan")
    say(f"   {label}: {len(c)} forecasts, Brier {brier:.4f} (coin flip 0.2500); confident (P >= 80% or <= 20%) {len(conf)},"
        f" came true {hit:.0%}; correlation of the estimated and the real difference {corr:+.2f}")


def main() -> None:
    out = []
    say = lambda s="": (print(s, flush=True), out.append(s))
    tr = load()
    four = (tr["sample"] == "4y").to_numpy()
    aug = (tr["sample"] == "aug").to_numpy()
    t = tr["entry_time"].to_numpy()
    say(f"v4 trades: 4 years {four.sum()}, since Aug {aug.sum()}. Flags on (4 years | since Aug):")
    say("   " + ", ".join(f"{g} {tr.loc[four, g].mean():.0%}|{tr.loc[aug, g].mean():.0%}" for g in GROUPS))
    for tau in (0.15, 0.10):
        say(f"\n######## tau {tau:.2f}R ########")
        # 4 years, the scoreboard learning from zero
        b4 = Board(tr[four].reset_index(drop=True), tau)
        s4 = np.ones(four.sum(), bool)
        w4 = walk(b4, s4)
        # since Aug, with the 4-year trades closed before Aug as history
        hist = four & (tr["x_plan"].to_numpy() <= AUG)
        df_a = pd.concat([tr[hist], tr[aug]]).reset_index(drop=True)
        ba = Board(df_a, tau)
        sa = (df_a["sample"] == "aug").to_numpy()
        wa = walk(ba, sa)

        say("1. Calibration (forecast: the group beats the rest over the next 90 days):")
        c4 = calibration(b4, s4, CAL_START, int(b4.entry.max()) - 90 * DAY)
        cal_report(c4[c4["t"] < SPLIT], say, "2023-01 to 2024-09")
        cal_report(c4[c4["t"] >= SPLIT], say, "2024-10 to 2026-07")
        ca = calibration(ba, sa, AUG, int(ba.entry.max()) - 30 * DAY, step=15 * DAY)
        cal_report(ca, say, "since Aug (every 15 days)")
        if tau == 0.15:
            say("   calibration table, 4 years (predictive forecast -> how often the group did beat the rest):")
            bins = pd.cut(c4["p_pred"], [0, 0.2, 0.35, 0.45, 0.55, 0.65, 0.8, 1.0])
            for iv, g in c4.groupby(bins, observed=True):
                say(f"      forecast {iv.left:.0%}-{iv.right:.0%}: {len(g):4d} forecasts, mean forecast {g['p_pred'].mean():.0%},"
                    f" happened {g['won'].mean():.0%}")
            say("   P(tier A beats B) as the scoreboard saw it at each year start (4 years, learning from zero):")
            for y in (2023, 2024, 2025, 2026):
                ms = calendar.timegm((y, 1, 1, 0, 0, 0)) * 1000
                say(f"      {y}-01-01: {b4.p_better(ms, 'A'):.0%} ({int(b4.known(ms).sum())} trades known)")
            say(f"      since Aug, at 2026-08-01: {ba.p_better(AUG, 'A'):.0%}; at the end: {ba.p_better(int(ba.exit.max()) + 1, 'A'):.0%}")
            end = int(b4.exit.max()) + 1
            k = b4.known(end)
            mu0, sigma = b4.base(k)
            say("   the scoreboard at the end of the 4 years (estimate, 90% range, P(beats the rest)):")
            for g in GROUPS:
                mg, vg, ne = b4.post(k & b4.flags[g], mu0, sigma)
                say(f"      {g:20} {int((k & b4.flags[g]).sum()):5d} trades {ne:5d} moves: {mg:+.3f}R"
                    f" ({mg - 1.645 * math.sqrt(vg):+.3f}..{mg + 1.645 * math.sqrt(vg):+.3f}), P {b4.p_better(end, g):.0%}")

        say("2. Sizing, the account at the user's rules from $150: 4 years | 2022-24 | 2024-26 | since Aug")
        d4 = tr[four].reset_index(drop=True)
        da = df_a[sa].reset_index(drop=True)
        wa_ = wa.sort_index()  # board index order = the order of da
        for label, q4, qa in (("S0 now (tier A 3%, B 2%)", d4["quality"], da["quality"]),
                              ("S1 A at 3% only while P(A>B) >= 80%", w4["s1"].sort_index().to_numpy(), wa_["s1"].sort_index().to_numpy()),
                              ("S2 the model picks the 3% trades", w4["s2"].sort_index().to_numpy(), wa_["s2"].sort_index().to_numpy())):
            x4 = d4.assign(quality=np.asarray(q4))
            xa = da.assign(quality=np.asarray(qa))
            cells = []
            for df in (x4, x4[x4["entry_time"] < SPLIT], x4[x4["entry_time"] >= SPLIT], xa):
                a = pd.DataFrame({"symbol": df["symbol"], "side": df["side"], "entry_time": df["entry_time"],
                                  "exit_time": df["x_plan"], "r": df["r_plan"], "quality": df["quality"]})
                _, bal, dd = e2.account(a)
                cells.append(f"${bal:,.0f} DD {dd:.0%} ({(df['quality'] == 'A').mean():.0%} at 3%)")
            say(f"   {label:38} " + " | ".join(cells))
        if tau == 0.15:
            r4 = d4["r_plan"].to_numpy()
            s2 = w4["s2"].sort_index().to_numpy() == "A"
            say(f"   R a trade of the 3% trades: S0 tier A {r4[d4['quality'] == 'A'].mean():+.3f} vs the model's picks {r4[s2].mean():+.3f}"
                f" (4 years); since Aug tier A {da['r_plan'][da['quality'] == 'A'].mean():+.3f} vs the model's"
                f" {da['r_plan'][wa_['s2'].sort_index().to_numpy() == 'A'].mean():+.3f}")
    (ROOT / "data" / "research" / "scoreboard_validate.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
