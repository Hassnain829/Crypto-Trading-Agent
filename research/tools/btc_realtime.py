r"""BTC's move known at the decision time, and the design's trades on XRP/SOL/ETH (2026-10-23). Research only.

    .venv\Scripts\python -u research\tools\btc_realtime.py > data\research\btc_realtime.txt

The user's point: BTC leads the market, so when BTC falls the alts fall. Only what is known at the decision can be used.
Rules fixed before looking:
- BTC's move from the UTC day's open to the decision, and over the 4 h and 12 h before it
- 'down' = -2% or more, 'up' = +2% or more
- trades with BTC's move vs against it vs flat
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("patterns_account", HERE / "patterns_account.py")
pa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pa)


def main() -> None:
    btc = pa.candles15("BTC")
    t_open = ((btc.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
    close = btc["close"].to_numpy(dtype=float)
    opens = btc["open"].to_numpy(dtype=float)

    def price_at(ms: np.ndarray) -> np.ndarray:  # the last 15m close at or before ms
        i = np.searchsorted(t_open + 900_000, ms, side="right") - 1
        return close[np.clip(i, 0, len(close) - 1)]

    def day_open(ms: np.ndarray) -> np.ndarray:
        start = ms // 86_400_000 * 86_400_000
        i = np.searchsorted(t_open, start)
        return opens[np.clip(i, 0, len(opens) - 1)]

    for label, path, vid, syms in (("the design, 4 years, XRP/SOL/ETH", pa.REPLAY / "journal-news.db", "v0-e78944", None),
                                   ("v0 (5m + 15m), 3 years, XRP/SOL/ETH (not seen)", pa.REPLAY / "journal-long-board.db",
                                    "v0-773ea9", ["XRP", "SOL", "ETH"])):
        tr = pa.load_trades(path, vid, symbols=syms)
        t = tr["decision"].to_numpy()
        now = price_at(t)
        moves = {"since the UTC day's open": now / day_open(t) - 1,
                 "over the last 4 h": now / price_at(t - 4 * 3_600_000) - 1,
                 "over the last 12 h": now / price_at(t - 12 * 3_600_000) - 1}
        r, d = tr["r_net"].to_numpy(), tr["d"].to_numpy()
        mid = int(np.median(t))
        print(f"\n######## {label}: {len(tr)} trades ########")
        for name, m in moves.items():
            big = np.abs(m) >= 0.02
            with_ = big & (np.sign(m) == d)
            against = big & (np.sign(m) == -d)
            print(f"   BTC {name}, at least 2% (known at the decision):")
            for g, mask in (("with BTC", with_), ("against BTC", against), ("BTC flat", ~big)):
                print(f"      {g:12} {pa.split_line(r, t, mask, mid)}")


if __name__ == "__main__":
    main()
