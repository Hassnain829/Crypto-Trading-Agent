"""RAM and CPU usage of the machine, TradingView and the agent."""

from __future__ import annotations

import os

import psutil


def tradingview_mb() -> float:
    """Memory of all TradingView Desktop processes together, in MB."""
    total = 0.0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            if (proc.info["name"] or "").lower().startswith("tradingview"):
                total += proc.info["memory_info"].rss / 2**20
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def usage() -> dict[str, float]:
    vm = psutil.virtual_memory()
    agent = psutil.Process(os.getpid())
    return {
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_used_pct": vm.percent,
        "tradingview_mb": round(tradingview_mb()),
        "agent_mb": round(agent.memory_info().rss / 2**20),
        "cpu_pct": psutil.cpu_percent(interval=0.5),
    }
