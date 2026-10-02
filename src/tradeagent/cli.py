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

    args = parser.parse_args(argv)
    if args.command == "doctor":
        from tradeagent.doctor import main as doctor_main

        return doctor_main(offline=args.offline)
    parser.error(f"unknown command: {args.command}")
    return 2
