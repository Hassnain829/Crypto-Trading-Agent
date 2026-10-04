# Moving the agent to a VPS

The agent, the dashboard and TradingView Desktop run together on one Windows machine. These steps move them to a Windows VPS.

The VPS must be in a country where the trading venue's API works. **Binance refuses US IP addresses.** The plan (2026-10-04) is Binance with a Pakistani account on a VPS with a Pakistani IP.

## 0. Choosing the VPS

| Need | Why |
|---|---|
| Windows (Server 2022, or Windows 10/11 if offered) with the licence included | TradingView Desktop and the scripts here are Windows programs |
| 4 vCPU, **8 GB RAM** (12–16 GB if you also keep VS Code with Claude Code open all the time) | TradingView uses about 2–2.7 GB, Windows about 2.5 GB, VS Code about 1 GB, the agent and dashboard about 0.3 GB |
| 80–100 GB SSD / NVMe | Journal (about 200 MB now, growing), logs, TradingView cache |
| A dedicated, static IPv4 address | The Binance API key is restricted to this address |
| RDP access, unmetered or 1 TB+ traffic, backups, a short trial or refund period | Daily use and a safe first test |

Before paying for a long period:
1. Install TradingView Desktop and check that it opens the AGENT layouts.
2. Run `python -m tradeagent doctor`. "Market data (Binance USDT-M perpetuals)" must be OK; a 451 or 403 error means the location is blocked.

## 1. The machine

- Windows 10/11 or Windows Server 2022, 8 GB RAM or more (TradingView uses about 2 GB), SSD.
- **Never sleep or hibernate:**
  ```powershell
  powercfg /change standby-timeout-ac 0
  powercfg /change hibernate-timeout-ac 0
  ```
- **Exact clock.** Some venues have no time endpoint, and live orders are signed with the time. In an admin PowerShell:
  ```powershell
  Set-Service W32Time -StartupType Automatic; Start-Service W32Time; w32tm /resync
  ```
- The machine's time zone does not matter. The dashboard setting Settings > TradingView > Time zone sets what the charts and the dashboard show, for example "Pakistan (UTC+5)".

## 2. Software

1. Python 3.14 from python.org, with "Add python.exe to PATH" ticked.
2. Git, then clone the repository and install:
   ```powershell
   git clone <your repository URL> C:\Crypt-Ai-Trading
   cd C:\Crypt-Ai-Trading
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt -e .
   ```
3. **TradingView Desktop:**
   - Install it from tradingview.com/desktop (MSIX package) and log in.
   - Your plan may allow only one device at a time; logging in on the VPS can log out the PC.
   - Open the four AGENT layouts (AGENT-XRP, AGENT-LINK, AGENT-SOL, AGENT-HTF). Their ids are in `config/settings.yaml`.
   - If the Microsoft Store build is not available on the server, update `tradingview.app_id` / `tradingview.launcher` after checking with `Get-AppxPackage *TradingView*`.

## 3. Your data and keys

- **Journal:** stop the agent on the PC (Overview > Stop), then copy `data\journal.db` to the same folder on the VPS. This keeps the history, the shadow book and the demo account. Without it the VPS starts empty and downloads market data itself.
- **Keys:** paste them again in the VPS dashboard (Settings > Exchanges), or copy `.env` over a secure channel. Never commit `.env`.
- **Binance key settings:** Enable Reading and Enable Futures; never Withdrawals. Restrict access to the VPS's static IP. The futures account must be opened on Binance first.

## 4. Check and start

```powershell
.venv\Scripts\python -m tradeagent doctor      # every line should be OK
powershell -ExecutionPolicy Bypass -File scripts\install_startup_tasks.ps1
Start-ScheduledTask -TaskName CryptAI-Dashboard
```

The dashboard starts the agent; the agent starts TradingView in debug mode and downloads the venue's market data, newest candles first.

## 5. Daily use

- **Close the remote desktop with "Disconnect", not "Sign out".** Signing out ends the programs.
- **After a VPS reboot** the logon task starts once you log in. For a start without logging in, enable automatic logon, for example with Microsoft Sysinternals Autologon.
- **The dashboard listens on 127.0.0.1 only (no password).** Open it in the VPS browser, or from your PC through an SSH tunnel (`ssh -L 8080:127.0.0.1:8080 user@vps`). Do not start it with `--host 0.0.0.0` on the internet.
- **Health check:** Overview > Agent should say Running, the snapshots should be ok, and "PC clock vs exchange" should be near 0 s.
