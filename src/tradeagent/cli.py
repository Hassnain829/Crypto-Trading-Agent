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
    dash = commands.add_parser("dashboard", help="open the web dashboard (http://127.0.0.1:8080)")
    dash.add_argument("--host", default="127.0.0.1", help="0.0.0.0 makes it reachable from other devices (no password!)")
    dash.add_argument("--port", type=int, default=8080)
    dash.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    dash.add_argument("--no-agent", action="store_true",
                      help="do not start the agent or restart it after a crash (the Overview buttons still work)")
    commands.add_parser("market-sync", help="sync the trading venue's candles, funding and market info now")
    commands.add_parser("venues", help="list the trading venues, who may use them and their fees")
    vr = commands.add_parser("venue-replay", help="replay the stored signals with another venue's prices (on a copy)")
    vr.add_argument("venue", help="e.g. coinbase-us, kraken-futures, bitget")
    vr.add_argument("--balance", type=float, action="append", help="demo starting balance to test (repeatable)")
    bf = commands.add_parser("backfill-snapshots", help="store snapshots for the history loaded in TradingView")
    bf.add_argument("--bars", type=int, help="load this much history on every chart first (Essential: up to 10000)")
    commands.add_parser("shadow-run", help="process new snapshots and move open shadow trades forward once")
    sr = commands.add_parser("shadow-report", help="results per variant in the exploration book")
    sr.add_argument("--halves", action="store_true", help="also show each half of the history (stability check)")
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
    pr = commands.add_parser("paper-reset", help="delete the paper account history (replay, or --from-now)")
    pr.add_argument("--yes", action="store_true")
    pr.add_argument("--from-now", action="store_true", help="restart at the starting balance, new signals only")
    dr = commands.add_parser("draw-trades", help="draw the paper trades on the TradingView charts now")
    dr.add_argument("--clear", action="store_true", help="remove every drawing the agent made")
    ks = commands.add_parser("kill-switch", help="show or set the kill switch")
    ks.add_argument("mode", nargs="?", choices=["off", "pause", "close_all"])
    ej = commands.add_parser("export-journal", help="write a complete copy of the journal (safe while the agent runs)")
    ej.add_argument("path", nargs="?", default="data/transfer/journal.db")
    commands.add_parser("research-pack", help="write the research pack Claude reads (research/packs/)")
    exp = commands.add_parser("experiment", help="learning loop: list, propose, try, screen, evaluate, stop, lesson")
    exp_cmd = exp.add_subparsers(dest="action", required=True)
    el = exp_cmd.add_parser("list", help="experiments and their numbers")
    el.add_argument("--all", action="store_true", help="also the decided ones")
    ep = exp_cmd.add_parser("propose", help="record proposals from a JSON file (or - for stdin) and screen them")
    ep.add_argument("file")
    ep.add_argument("--source", default="claude", choices=["claude", "user"])
    ep.add_argument("--no-screen", action="store_true", help="leave the history screen to the agent")
    et = exp_cmd.add_parser("try", help="replay the history with one change, without recording it")
    et.add_argument("path", help="e.g. filters.min_stop_pct")
    et.add_argument("value", help="a JSON value, e.g. 1.25, true, \"15m\" or [13,21]")
    es = exp_cmd.add_parser("screen", help="screen the proposals waiting for their history replay")
    es.add_argument("--id", type=int, action="append")
    exp_cmd.add_parser("evaluate", help="judge the running experiments now (the agent does this every hour)")
    ex_stop = exp_cmd.add_parser("stop", help="stop an experiment")
    ex_stop.add_argument("id", type=int)
    ex_stop.add_argument("--reason", required=True)
    ex_lesson = exp_cmd.add_parser("lesson", help="add a lesson to an experiment (and research/lessons.md)")
    ex_lesson.add_argument("id", type=int)
    ex_lesson.add_argument("text")
    ex_promote = exp_cmd.add_parser("promote", help="promote a winner by hand (writes config/setups.yaml)")
    ex_promote.add_argument("id", type=int)
    ex_promote.add_argument("--yes", action="store_true")
    ex_promote.add_argument("--early", action="store_true", help="also before it has won twice (recorded as early)")

    args = parser.parse_args(argv)
    if args.command == "dashboard":
        from tradeagent.dashboard.app import run as run_dashboard

        run_dashboard(args.host, args.port, open_browser=not args.no_browser, start_agent=not args.no_agent)
        return 0
    if args.command == "doctor":
        from tradeagent.doctor import main as doctor_main

        return doctor_main(offline=args.offline)
    if args.command == "venues":
        from tradeagent.venues import NOT_YET, VENUES

        for v in VENUES.values():
            print(f"{v.id:<15} {v.label}\n{'':<15} who: {v.who}\n{'':<15} fees: {v.fee_note}")
        for venue_id, note in NOT_YET.items():
            print(f"{venue_id:<15} not usable yet: {note}")
        return 0
    if args.command == "venue-replay":
        from tradeagent.venue_replay import venue_replay

        return venue_replay(args.venue, args.balance or [150.0])
    if args.command == "export-journal":
        import sqlite3
        from pathlib import Path

        from tradeagent.config import load_settings

        settings = load_settings()
        out = Path(args.path) if Path(args.path).is_absolute() else settings.root / args.path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        src = sqlite3.connect(f"file:{settings.resolve(settings.journal.path)}?mode=ro", uri=True)
        dst = sqlite3.connect(out)
        src.backup(dst)  # includes what is still in the -wal file; consistent even while the agent writes
        dst.close()
        src.close()
        print(f"journal copied to {out} ({out.stat().st_size / 1e6:.0f} MB). On the new computer put it at data\\journal.db.")
        return 0
    if args.command in ("research-pack", "experiment"):
        from tradeagent.learning import commands as learning

        if args.command == "research-pack":
            return learning.research_pack()
        return {
            "list": lambda: learning.experiment_list(args.all),
            "propose": lambda: learning.experiment_propose(args.file, args.source, not args.no_screen),
            "try": lambda: learning.experiment_try(args.path, args.value),
            "screen": lambda: learning.experiment_screen(args.id),
            "evaluate": learning.experiment_evaluate,
            "stop": lambda: learning.experiment_stop(args.id, args.reason),
            "lesson": lambda: learning.experiment_lesson(args.id, args.text),
            "promote": lambda: learning.experiment_promote(args.id, args.yes, args.early),
        }[args.action]()

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
        return shadow.backfill(args.bars)
    if args.command == "shadow-run":
        return shadow.shadow_run()
    if args.command == "shadow-report":
        return shadow.shadow_report(args.halves)
    if args.command == "shadow-reset":
        return shadow.shadow_reset(args.yes)
    if args.command == "trades":
        return shadow.list_trades(args.variant, args.symbol, args.last, args.trade_id)
    if args.command == "verify-trades":
        return shadow.verify_trades(args.count)
    if args.command == "paper-report":
        return shadow.paper_report()
    if args.command == "paper-reset":
        return shadow.paper_reset(args.yes, args.from_now)
    if args.command == "draw-trades":
        return shadow.draw_trades(args.clear)
    if args.command == "kill-switch":
        return shadow.kill_switch(args.mode)
    parser.error(f"unknown command: {args.command}")
    return 2
