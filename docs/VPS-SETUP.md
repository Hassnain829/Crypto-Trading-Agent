# Moving the agent to a VPS (DatabaseMart, USA)

The agent, the dashboard and TradingView Desktop run together on one Windows machine. These steps move them to a Windows VPS. A US VPS cannot reach Binance's API, so choose a venue that works there **before** the move (Settings > Exchanges > Trading exchange, e.g. `coinbase-us`; see [phase-4b-exchange-adapter.md](phases/phase-4b-exchange-adapter.md)).

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
- **Keys:** paste them again in the VPS dashboard (Settings > Exchanges), or copy `.env` over a secure channel. Never commit `.env`. Allow only the VPS IP on the exchange's API key.

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
