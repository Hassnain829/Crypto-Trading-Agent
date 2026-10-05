# Moving the agent to a VPS

The agent, the dashboard and TradingView Desktop run together on one Windows machine. These steps move them to a Windows VPS.

The VPS must be in a country where the trading venue's API works. **Binance refuses US IP addresses.** The plan (2026-10-04) is Binance with a Pakistani account on a VPS with a Pakistani IP.

**Bought (2026-10-04):** WebAiry "Pakistan VPS 8GB", $24 a month, IP 144.225.54.201. That IP goes into the Binance API key's IP restriction in Phase 6.

**Order of the move:**
1. Set up the VPS while the PC keeps trading: sections 1, 2 and 4 up to `doctor`.
2. On the PC, commit and push, then clone on the VPS.
3. On the PC, stop the agent (Overview > Stop) and close the dashboard.
4. Copy the journal and Claude's context (section 3).
5. Start the dashboard on the VPS.

Only one computer may run the agent: both would read the same TradingView account and trade the same demo.

## 0. Choosing the VPS

| Need | Why |
|---|---|
| Windows **build 19042 or newer** (Windows Server 2022, or Windows 10 20H2+ / 11), activated, licence included | TradingView Desktop (MSIX) requires 10.0.19042. **Windows Server 2019 (build 17763) cannot install it**, and an expired evaluation edition shuts itself down regularly |
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
   - Download the MSIX from tradingview.com/desktop and install it, then log in.
   - **A server without the Microsoft Store** cannot install the MSIX by double-click (it hangs at "Hang on while we get your app's information"). Install from an admin PowerShell instead; the package needs Microsoft.VCLibs.140.00.UWPDesktop first:
     ```powershell
     Invoke-WebRequest https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx -OutFile $env:TEMP\vclibs.appx
     Add-AppxPackage $env:TEMP\vclibs.appx
     Add-AppxPackage "$env:USERPROFILE\Downloads\TradingView.msix"
     Get-AppxPackage *TradingView*     # TradingView.Desktop_n534cwy3pjxzj, as on the PC
     ```
   - Your plan may allow only one device at a time; logging in on the VPS can log out the PC.
   - Open the four AGENT layouts by id: AGENT-XRP, AGENT-ETH, AGENT-SOL and AGENT-HTF. The ids are in `config/settings.yaml`; the ETH layout may still be named "AGENT-LINK" in TradingView. The agent also opens them itself.
   - Do not change the symbol on an AGENT tab. The agent switches a coin tab back to its symbol, but the reads around the change are lost until then. Look at other charts in your own layout.
   - If the Microsoft Store build is not available on the server, update `tradingview.app_id` / `tradingview.launcher` after checking with `Get-AppxPackage *TradingView*`.

4. **Claude Code** (for `/research`, the daily research run and further development):
   - Node.js LTS from nodejs.org.
   - VS Code with the Claude Code extension.
   - The CLI: `npm install -g @anthropic-ai/claude-code`, then run `claude` once in a terminal and log in with your Pro account.
   - The agent's daily research run (Settings > Research > Daily research run) needs `claude` on the PATH. Restart VS Code and the dashboard after installing Node, so they see the new PATH.

## 3. Your data and keys

- **Journal:**
  1. On the PC run `.venv\Scripts\python -m tradeagent export-journal`. It writes a complete copy to `data\transfer\journal.db`. It is safe while the agent runs, and it includes recent data that copying the file by hand can miss (SQLite WAL).
  2. Do this after stopping the agent on the PC, so that nothing is lost in between.
  3. On the VPS, put it at `data\journal.db`.

  This keeps the history, the shadow book, the demo account and the experiments. Without it the VPS starts empty and downloads market data itself.
- **Claude's memory and this chat:**
  1. On the PC run `powershell -ExecutionPolicy Bypass -File scripts\claude_context.ps1 -Export`. It writes `data\transfer\claude-context.zip`.
  2. Copy the zip to the same folder on the VPS.
  3. On the VPS run the script with `-Import`.

  A new Claude chat in that project then reads the memory, so it knows the project's state. The old chat appears in the Claude panel's past conversations, or with `claude --resume`.
- **Research notes** (`research/`) and **settings** are in git. Settings changed in the dashboard are stored in the journal.
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
