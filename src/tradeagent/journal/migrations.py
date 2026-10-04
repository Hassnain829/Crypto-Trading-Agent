"""Journal schema migrations, applied in order. Never edit a released migration; add a new one.

Each entry is (version, name, sql). Later phases add their own tables (snapshots, candles,
trades, ...) as new migrations when those tables are designed.
"""

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial",
        """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,              -- milliseconds since epoch, UTC
    level TEXT NOT NULL,              -- INFO / WARNING / ERROR
    source TEXT NOT NULL,             -- e.g. doctor, reader, watchdog
    message TEXT NOT NULL,
    data_json TEXT
);
CREATE INDEX idx_events_ts ON events (ts);

-- Dashboard overrides of settings.yaml values (Phase 4).
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE settings_audit (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    key TEXT NOT NULL,
    old_json TEXT,
    new_json TEXT,
    source TEXT NOT NULL              -- dashboard / cli / research
);
""",
    ),
    (
        2,
        "snapshots",
        """
CREATE TABLE indicator_settings (
    signal_version INTEGER PRIMARY KEY,
    settings_hash TEXT NOT NULL UNIQUE,   -- sha256 of the canonical inputs JSON
    settings_json TEXT NOT NULL,          -- indicator inputs per layout and chart
    created_at INTEGER NOT NULL
);

CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,                 -- agent symbol, e.g. XRP
    timeframe TEXT NOT NULL,              -- 5m, 15m, 1h, 4h
    bar_time INTEGER NOT NULL,            -- candle open time, ms UTC
    signal_version INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,   -- TradingView's candle
    values_json TEXT NOT NULL,            -- {indicator: {field: value}}
    problems_json TEXT,                   -- NULL when the snapshot passed validation
    read_at INTEGER NOT NULL,             -- Binance server time, ms
    latency_ms INTEGER NOT NULL,          -- read_at minus the candle close time
    UNIQUE (symbol, timeframe, bar_time, signal_version)
);
CREATE INDEX idx_snapshots_bar ON snapshots (symbol, timeframe, bar_time);
""",
    ),
    (
        3,
        "shadow",
        """
ALTER TABLE snapshots ADD COLUMN source TEXT NOT NULL DEFAULT 'live';   -- live | backfill

CREATE TABLE candles (                     -- Binance USDT-M, closed candles only
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time INTEGER NOT NULL,            -- ms UTC
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, open_time)
) WITHOUT ROWID;

CREATE TABLE funding (
    symbol TEXT NOT NULL,
    funding_time INTEGER NOT NULL,         -- ms UTC
    rate REAL NOT NULL,
    PRIMARY KEY (symbol, funding_time)
) WITHOUT ROWID;

CREATE TABLE market_info (
    symbol TEXT PRIMARY KEY,
    tick_size REAL, step_size REAL, min_qty REAL, min_notional REAL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE variants (
    id TEXT PRIMARY KEY,
    params_json TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    role TEXT NOT NULL,                    -- baseline | challenger | retired
    parent TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE setups (                      -- trigger events and what happened to them, per variant
    id INTEGER PRIMARY KEY,
    variant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    side TEXT NOT NULL,                    -- long | short
    trigger_time INTEGER NOT NULL,         -- open time of the trigger candle
    status TEXT NOT NULL,                  -- pending | confirmed | expired | cancelled
    confirm_time INTEGER,
    signal_version INTEGER NOT NULL,
    UNIQUE (variant_id, symbol, timeframe, side, trigger_time)
);
CREATE INDEX idx_setups_pending ON setups (variant_id, symbol, timeframe, status);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    book TEXT NOT NULL,                    -- exploration | paper | live
    variant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    side TEXT NOT NULL,
    setup_id INTEGER,
    signal_version INTEGER NOT NULL,
    trigger_time INTEGER NOT NULL,
    confirm_time INTEGER NOT NULL,         -- open time of the confirming candle
    entry_time INTEGER NOT NULL,           -- open time of the 1m candle used for the entry
    taken INTEGER NOT NULL,                -- 1 = the rules take it; 0 = counterfactual (filtered out)
    reason TEXT,                           -- why it was filtered out or invalid
    exit_mode TEXT NOT NULL,               -- fixed | hybrid
    entry_ref REAL NOT NULL,               -- expected entry price (before slippage)
    stop_initial REAL NOT NULL,
    target REAL,
    status TEXT NOT NULL,                  -- open | closed | invalid
    exit_time INTEGER,
    exit_reason TEXT,
    r_gross REAL, fees_r REAL, slippage_r REAL, funding_r REAL, r_net REAL, mfe_r REAL, mae_r REAL,
    ambiguous INTEGER NOT NULL DEFAULT 0,  -- stop and target touched inside the same 1m candle
    context_json TEXT NOT NULL,            -- indicator values, HTF state and filter results at confirmation
    state_json TEXT NOT NULL,              -- simulator state
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (book, variant_id, symbol, timeframe, side, confirm_time)
);
CREATE INDEX idx_trades_status ON trades (book, status);
CREATE INDEX idx_trades_variant ON trades (book, variant_id, status);

CREATE TABLE engine_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""",
    ),
    (
        4,
        "accounts",
        """
CREATE TABLE account_state (
    account TEXT PRIMARY KEY,              -- paper (live is added in Phase 6)
    balance REAL NOT NULL,                 -- realized balance in USDT
    day TEXT,                              -- current UTC day (YYYY-MM-DD)
    day_start_balance REAL,
    last_entry_time INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE account_trades (              -- every baseline signal the account saw: opened or rejected
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,
    trade_id INTEGER NOT NULL,             -- the exploration trade it follows (same signal, same fills)
    variant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,                  -- open | closed | rejected
    reject_reason TEXT,
    entry_time INTEGER NOT NULL,
    entry_fill REAL, stop REAL,
    qty REAL, notional REAL, leverage REAL, risk_usd REAL,
    balance_before REAL,
    exit_time INTEGER, exit_reason TEXT,
    pnl_usd REAL, fees_usd REAL, funding_usd REAL, r_net REAL, account_pct REAL, balance_after REAL,
    notes TEXT,                            -- e.g. size reduced by the leverage cap
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (account, trade_id)
);
CREATE INDEX idx_account_trades_status ON account_trades (account, status);
""",
    ),
    (
        5,
        "account baseline",
        """
-- The variant the account follows. A newly promoted baseline is followed from its promotion on.
ALTER TABLE account_state ADD COLUMN baseline TEXT;
""",
    ),
    (
        6,
        "trade drawings",
        """
CREATE TABLE trade_drawings (              -- paper trades drawn on the TradingView charts
    account_trade_id INTEGER PRIMARY KEY,
    layout_id TEXT NOT NULL,               -- AGENT layout the drawing was made in
    shape_ids TEXT NOT NULL,               -- JSON list of TradingView drawing ids (position tool, result label)
    drawn_state TEXT NOT NULL,             -- open | closed: the paper trade's status when it was drawn
    updated_at INTEGER NOT NULL
);
""",
    ),
    (
        7,
        "forward test start",
        """
-- When the current forward test started (paper-reset --from-now); NULL = the account replays history.
ALTER TABLE account_state ADD COLUMN started_at INTEGER;
""",
    ),
    (
        8,
        "dashboard",
        """
CREATE TABLE agent_status (                -- the agent's heartbeat and start info, read by the dashboard
    key TEXT PRIMARY KEY,                  -- agent | heartbeat
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE baseline_history (            -- every strategy version the paper account followed
    version TEXT PRIMARY KEY,              -- v0, v1, v2, ...
    variant_id TEXT,
    adopted_at INTEGER NOT NULL,           -- ms UTC
    summary TEXT NOT NULL,
    expectancy_r REAL,                     -- net R per trade on the evidence it was chosen on
    trades INTEGER,
    paper_return_pct REAL,                 -- the paper account replayed on the same history
    evidence TEXT
);
-- The versions chosen before this table existed (docs/research/2026-10-03-strategy-review.md, ~100 days).
INSERT INTO baseline_history VALUES
    ('v0', NULL, 1790899200000, 'The video checklist: Q-Trend arrow, Klinger colour and candle colour; 10-candle swing stop; 1.5R target; market entry',
     -0.159, 1104, -52.7, 'Strategy review 2026-10-03, ~100 days of history'),
    ('v1', NULL, 1790985600000, 'v0, but skip setups whose swing stop is closer than 1% (costs eat tight stops)',
     -0.030, 590, -18.6, 'Strategy review 2026-10-03, ~100 days of history'),
    ('v2', 'v0-773ea9', 1790989200000, 'Stops of at least 1.5% and limit-order entries (maker fee, no slippage)',
     0.116, 260, 19.5, 'Strategy review 2026-10-03, ~100 days of history; positive in all four sub-periods');
""",
    ),
]
