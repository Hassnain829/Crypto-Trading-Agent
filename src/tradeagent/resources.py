"""RAM and CPU usage of the machine, TradingView and the agent."""

from __future__ import annotations

import os

import psutil


def tradingview_mb() -> float:
    """Memory of all TradingView Desktop processes together, in MB: what they hold (private bytes on Windows), not
    only what is in RAM. When RAM runs short Windows moves part of it to the page file, and the working set (rss)
    hid that: on 2026-10-21 rss said 2.4 GB while TradingView held 4.5 GB, so the 4000 MB restart never came."""
    total = 0.0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            if (proc.info["name"] or "").lower().startswith("tradingview"):
                mem = proc.info["memory_info"]
                total += getattr(mem, "private", mem.rss) / 2**20
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
