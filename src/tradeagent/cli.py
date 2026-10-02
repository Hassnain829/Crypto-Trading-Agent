"""Command line entry point: python -m tradeagent <command>."""

from __future__ import annotations

import argparse
import sys

from tradeagent import __version__


def main(argv: list[str] | None = None) -> int:
    # TradingView names contain emoji; never crash on a console that cannot print them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="tradeagent", description="Crypt-AI-Trading agent")
    parser.add_argument("--version", action="version", version=f"tradeagent {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="check that everything is installed and connected")
    doctor.add_argument("--offline", action="store_true", help="skip the Binance network check")
    commands.add_parser("tv-status", help="show the AGENT tabs and their charts")
    commands.add_parser("snapshot", help="read the last closed candle of every chart once and store it")
    commands.add_parser("reader", help="run the signal reader at every candle close (Ctrl+C to stop)")
    cov = commands.add_parser("coverage", help="snapshot coverage and latency for the last hours")
    cov.add_argument("--hours", type=float, default=48)
    rep = commands.add_parser("repaint-audit", help="re-read stored snapshots and report values that changed")
    rep.add_argument("--hours", type=float, default=24)
    rep.add_argument("--limit", type=int, default=100, help="max snapshots per symbol and timeframe")
    show = commands.add_parser("show", help="print the newest snapshots with all indicator values")
    show.add_argument("--symbol")
    show.add_argument("--tf", dest="timeframe")
    show.add_argument("--last", type=int, default=1)
    ver = commands.add_parser("verify-candles", help="compare stored candles with Binance's candles")
    ver.add_argument("--count", type=int, default=20)
    commands.add_parser("agent", help="run the full agent 24/7: reader + market data + shadow engine (Ctrl+C to stop)")
    commands.add_parser("market-sync", help="sync Binance candles, funding and market info now")
    commands.add_parser("backfill-snapshots", help="store snapshots for the history loaded in TradingView")
    commands.add_parser("shadow-run", help="process new snapshots and move open shadow trades forward once")
    commands.add_parser("shadow-report", help="results per variant in the exploration book")
    reset = commands.add_parser("shadow-reset", help="delete exploration trades so history can be replayed")
    reset.add_argument("--yes", action="store_true")
    trades = commands.add_parser("trades", help="list shadow trades (or one trade in detail with --id)")
    trades.add_argument("--variant")
    trades.add_argument("--symbol")
    trades.add_argument("--last", type=int, default=20)
    trades.add_argument("--id", dest="trade_id", type=int)
    vt = commands.add_parser("verify-trades", help="re-compute random shadow trades independently from raw data")
    vt.add_argument("--count", type=int, default=20)
    commands.add_parser("paper-report", help="paper account results and the go-live gate")
    pr = commands.add_parser("paper-reset", help="delete the paper account history so it can be replayed")
    pr.add_argument("--yes", action="store_true")
    ks = commands.add_parser("kill-switch", help="show or set the kill switch")
    ks.add_argument("mode", nargs="?", choices=["off", "pause", "close_all"])

    args = parser.parse_args(argv)
    if args.command == "doctor":
        from tradeagent.doctor import main as doctor_main

        return doctor_main(offline=args.offline)

    from tradeagent.tv import commands as tv

    if args.command == "tv-status":
        return tv.tv_status()
    if args.command == "snapshot":
        return tv.snapshot_once()
    if args.command == "reader":
        return tv.run_reader()
    if args.command == "coverage":
        return tv.coverage_report(args.hours)
    if args.command == "repaint-audit":
        return tv.repaint_report(args.hours, args.limit)
    if args.command == "show":
        return tv.show_snapshots(args.symbol, args.timeframe, args.last)
    if args.command == "verify-candles":
        return tv.verify_candles(args.count)

    from tradeagent import shadow_commands as shadow

    if args.command == "agent":
        return shadow.run_agent()
    if args.command == "market-sync":
        return shadow.market_sync()
    if args.command == "backfill-snapshots":
        return shadow.backfill()
    if args.command == "shadow-run":
        return shadow.shadow_run()
    if args.command == "shadow-report":
        return shadow.shadow_report()
    if args.command == "shadow-reset":
        return shadow.shadow_reset(args.yes)
    if args.command == "trades":
        return shadow.list_trades(args.variant, args.symbol, args.last, args.trade_id)
    if args.command == "verify-trades":
        return shadow.verify_trades(args.count)
    if args.command == "paper-report":
        return shadow.paper_report()
    if args.command == "paper-reset":
        return shadow.paper_reset(args.yes)
    if args.command == "kill-switch":
        return shadow.kill_switch(args.mode)
    parser.error(f"unknown command: {args.command}")
    return 2
