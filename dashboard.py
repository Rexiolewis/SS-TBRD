from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from bot_control import BOT_LOG_FILE, force_stop_bot, get_bot_pid, is_bot_running, request_stop_bot, start_bot
from config import settings
from data.binance_client import BinanceSpotClient
from execution.manual_paper_broker import ManualPaperBroker
from fundamental.fundamental_filters import FundamentalFilters
from risk.circuit_breaker import CircuitBreaker
from risk.risk_manager import RiskDecision, RiskManager
from strategy.backtester import run_short_backtest
from strategy.indicators import add_indicators
from strategy.prediction_calculator import calculate_short_trade_plan
from strategy.signal_engine import SpotLongEngine


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Crypto Short Bot",
    page_icon="📉",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── top status badges ── */
.badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: .3px;
}
.badge-green  { background:#16a34a; color:#fff; }
.badge-red    { background:#dc2626; color:#fff; }
.badge-yellow { background:#d97706; color:#fff; }
.badge-gray   { background:#374151; color:#9ca3af; }

/* ── signal banner ── */
.signal-buy {
    background: linear-gradient(135deg,#14532d,#16a34a);
    color:#fff; padding:14px 20px; border-radius:10px;
    font-size:22px; font-weight:800; text-align:center;
    letter-spacing:1px; border:1px solid #22c55e;
}
.signal-wait {
    background: linear-gradient(135deg,#1e293b,#334155);
    color:#94a3b8; padding:14px 20px; border-radius:10px;
    font-size:22px; font-weight:800; text-align:center;
    letter-spacing:1px; border:1px solid #475569;
}

/* ── score bar labels ── */
.cat-label {
    font-size: 12px;
    color: #94a3b8;
    margin-bottom: 2px;
}

/* ── section divider ── */
.section-title {
    font-size:13px; font-weight:600; color:#64748b;
    text-transform:uppercase; letter-spacing:.8px;
    border-bottom:1px solid #1e293b; padding-bottom:4px;
    margin-bottom:8px;
}

/* ── halted banner ── */
.halted-banner {
    background:linear-gradient(135deg,#78350f,#d97706);
    color:#fff; padding:12px 18px; border-radius:8px;
    font-weight:700; font-size:15px;
    border:1px solid #f59e0b;
}
.clear-banner {
    background:linear-gradient(135deg,#14532d,#16a34a);
    color:#fff; padding:12px 18px; border-radius:8px;
    font-weight:700; font-size:14px;
    border:1px solid #22c55e;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=20)
def load_market(symbol, interval, confirm_interval, candle_limit, testnet):
    client = BinanceSpotClient(testnet=testnet)
    df_1m = client.get_klines(symbol, interval, candle_limit)
    df_5m = client.get_klines(symbol, confirm_interval, candle_limit)
    order_book = client.get_order_book(symbol, limit=20)
    return df_1m, df_5m, order_book


def tail_text(path: Path, lines: int = 25) -> str:
    if not path.exists():
        return "No log yet."
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:]) if content else "No log yet."


def load_account_balance(asset: str = "USDT") -> dict:
    client = BinanceSpotClient(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=settings.binance_testnet,
    )
    return client.get_asset_balance(asset)


def score_pct_color(pct: float) -> str:
    if pct >= 0.65:
        return "#22c55e"
    if pct >= 0.35:
        return "#f59e0b"
    return "#ef4444"


def build_chart(df: pd.DataFrame, signal) -> go.Figure:
    chart_df = add_indicators(df).dropna(subset=["ema_9", "ema_21", "rsi_14"])
    tail_df = chart_df.tail(120)

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.62, 0.20, 0.18],
        vertical_spacing=0.015,
    )

    # ── Bollinger Bands (shaded area) ────────────────────────────────────────
    if "bb_upper" in tail_df.columns:
        fig.add_trace(go.Scatter(
            x=tail_df["open_time"], y=tail_df["bb_upper"],
            name="BB Upper", line=dict(color="rgba(148,163,184,0.35)", width=1),
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=tail_df["open_time"], y=tail_df["bb_lower"],
            name="BB Lower", fill="tonexty",
            fillcolor="rgba(148,163,184,0.06)",
            line=dict(color="rgba(148,163,184,0.35)", width=1),
            showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=tail_df["open_time"], y=tail_df["bb_mid"],
            name="BB Mid (SMA20)", line=dict(color="rgba(148,163,184,0.55)", width=1, dash="dot"),
        ), row=1, col=1)

    # ── Candlesticks ──────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=tail_df["open_time"],
        open=tail_df["open"], high=tail_df["high"],
        low=tail_df["low"], close=tail_df["close"],
        name="Price",
        increasing=dict(line=dict(color="#22c55e"), fillcolor="#16a34a"),
        decreasing=dict(line=dict(color="#ef4444"), fillcolor="#dc2626"),
    ), row=1, col=1)

    # ── EMAs ─────────────────────────────────────────────────────────────────
    for name, col_name, color, width in [
        ("EMA 9",  "ema_9",  "#3b82f6", 1.2),
        ("EMA 21", "ema_21", "#a78bfa", 1.5),
        ("EMA 50", "ema_50", "#fb923c", 2.0),
    ]:
        if col_name in tail_df.columns:
            fig.add_trace(go.Scatter(
                x=tail_df["open_time"], y=tail_df[col_name],
                name=name, line=dict(color=color, width=width),
            ), row=1, col=1)

    # ── VWAP ─────────────────────────────────────────────────────────────────
    if "vwap" in tail_df.columns:
        fig.add_trace(go.Scatter(
            x=tail_df["open_time"], y=tail_df["vwap"],
            name="VWAP", line=dict(color="#f472b6", width=1.5, dash="dot"),
        ), row=1, col=1)

    # ── Signal levels ─────────────────────────────────────────────────────────
    if signal.entry_price and signal.entry_price > 0:
        for label, price, color in [
            ("Entry", signal.entry_price, "#2563eb"),
            ("TP",    signal.take_profit_price, "#16a34a"),
            ("Stop",  signal.stop_price, "#dc2626"),
        ]:
            if price and price > 0:
                fig.add_hline(
                    y=price, row=1, col=1,
                    line_dash="dash", line_color=color, line_width=1.5,
                    annotation_text=f"  {label}: {price:.2f}",
                    annotation_font_color=color,
                    annotation_position="right",
                )

    # ── Volume bars ───────────────────────────────────────────────────────────
    vol_colors = [
        "rgba(239,68,68,0.55)" if c < o else "rgba(34,197,94,0.55)"
        for c, o in zip(tail_df["close"], tail_df["open"])
    ]
    fig.add_trace(go.Bar(
        x=tail_df["open_time"], y=tail_df["volume"],
        name="Volume", marker_color=vol_colors, showlegend=False,
    ), row=2, col=1)

    # ── RSI ───────────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=tail_df["open_time"], y=tail_df["rsi_14"],
        name="RSI 14", line=dict(color="#22d3ee", width=1.5), showlegend=False,
    ), row=3, col=1)
    fig.add_hrect(y0=70, y1=100, row=3, col=1, fillcolor="rgba(239,68,68,0.08)", line_width=0)
    fig.add_hrect(y0=0,  y1=30,  row=3, col=1, fillcolor="rgba(34,197,94,0.08)", line_width=0)
    for level, color in [(70, "rgba(239,68,68,0.45)"), (50, "rgba(148,163,184,0.3)"), (30, "rgba(34,197,94,0.45)")]:
        fig.add_hline(y=level, row=3, col=1, line_dash="dot", line_color=color, line_width=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        height=760,
        template="plotly_dark",
        margin=dict(l=10, r=80, t=15, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="left", x=0, font=dict(size=11),
        ),
        plot_bgcolor="rgba(15,23,42,0.6)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(gridcolor="rgba(51,65,85,0.5)", showgrid=True)
    fig.update_yaxes(gridcolor="rgba(51,65,85,0.5)", showgrid=True)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol",   row=2, col=1)
    fig.update_yaxes(title_text="RSI",   row=3, col=1)
    return fig


def render_score_breakdown(breakdown: dict | None, total_score: int, max_score: int):
    """Render per-category score bars inside the current column."""
    categories = [
        ("Trend",       "trend",        6),
        ("Momentum",    "momentum",     5),
        ("Structure",   "structure",    4),
        ("Volume",      "volume",       3),
        ("Patt/Mkst",   "pattern_mkst", 2),
    ]
    bd = breakdown or {}
    for label, key, cat_max in categories:
        pts = bd.get(key, 0)
        pct = pts / cat_max
        color = score_pct_color(pct)
        bar_fill = int(pct * 12)
        bar_empty = 12 - bar_fill
        bar_str = "█" * bar_fill + "░" * bar_empty
        st.markdown(
            f"<div class='cat-label'>"
            f"<span style='color:{color};font-weight:700'>{bar_str}</span>"
            f"  {label} <span style='color:{color}'>{pts}/{cat_max}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # Bot status pill
    bot_running = is_bot_running()
    bot_pid = get_bot_pid()

    status_class = "badge-green" if bot_running else "badge-red"
    status_text = f"● RUNNING  PID {bot_pid}" if bot_running else "● STOPPED"
    st.markdown(f"<span class='badge {status_class}'>{status_text}</span>", unsafe_allow_html=True)
    st.caption(f"Mode: **{settings.trading_mode}**  |  Live: **{settings.enable_live_trading}**")
    if settings.enable_live_trading:
        st.warning("⚠️ Live trading is ON in .env")
    st.divider()

    # Account balance
    st.markdown("<div class='section-title'>Account</div>", unsafe_allow_html=True)
    account_env = "TESTNET" if settings.binance_testnet else "REAL BINANCE"
    st.caption(f"Account endpoint: **{account_env}**")
    if not settings.binance_api_key or not settings.binance_api_secret:
        st.info("Add BINANCE_API_KEY and BINANCE_API_SECRET in .env to show USDT balance.")
    else:
        if "account_balance" not in st.session_state:
            try:
                st.session_state.account_balance = load_account_balance("USDT")
                st.session_state.account_balance_error = ""
            except Exception as exc:
                st.session_state.account_balance = None
                st.session_state.account_balance_error = str(exc)

        if st.button("Refresh USDT Balance", use_container_width=True):
            try:
                st.session_state.account_balance = load_account_balance("USDT")
                st.session_state.account_balance_error = ""
            except Exception as exc:
                st.session_state.account_balance = None
                st.session_state.account_balance_error = str(exc)

        balance = st.session_state.get("account_balance")
        if balance:
            st.metric("USDT available", f"${balance['free']:,.2f}")
            st.caption(f"Locked: ${balance['locked']:,.2f} | Total: ${balance['total']:,.2f}")
        elif st.session_state.get("account_balance_error"):
            st.error(f"Balance error: {st.session_state.account_balance_error}")

    st.divider()

    # Start / Stop
    st.markdown("<div class='section-title'>Bot Control</div>", unsafe_allow_html=True)
    c_start, c_stop = st.columns(2)
    with c_start:
        if st.button("▶ Start", disabled=bot_running, use_container_width=True):
            res = start_bot()
            st.success(f"Started PID {res['pid']}") if res["ok"] else st.info(res["reason"])
            st.rerun()
    with c_stop:
        if st.button("■ Stop", disabled=not bot_running, use_container_width=True):
            res = request_stop_bot()
            st.info(res["reason"])
            st.rerun()
    with st.expander("Bot log", expanded=False):
        st.code(tail_text(BOT_LOG_FILE), language="text")
        if st.button("⚡ Force Kill", disabled=not bot_running, use_container_width=True, type="primary"):
            res = force_stop_bot()
            st.warning(res["reason"]) if res["ok"] else st.info(res["reason"])
            st.rerun()

    st.divider()

    # Market
    st.markdown("<div class='section-title'>Market</div>", unsafe_allow_html=True)
    symbol = st.text_input("Symbol", settings.symbol).upper().strip()
    interval = st.selectbox("Entry interval", ["1m", "3m", "5m", "15m"], index=0)
    confirm_interval = st.selectbox("Confirm interval", ["5m", "15m", "30m", "1h"], index=0)
    candle_limit = st.slider("Candles", 80, 500, settings.candle_limit, step=10)

    st.divider()

    # Trade plan
    st.markdown("<div class='section-title'>Trade Plan</div>", unsafe_allow_html=True)
    target_profit = st.number_input("Target net profit $", 0.10, value=settings.target_profit_usd, step=0.10)
    max_loss = st.number_input("Max loss $", 0.5, value=settings.max_loss_usd, step=0.5)
    account_equity = st.number_input("Paper equity $", 10.0, value=100.0, step=10.0)
    leverage = st.number_input("Leverage ×", 1, 20, settings.leverage)
    min_score = st.slider("Buy score threshold", 5, 20, settings.min_score_to_buy)

    st.divider()

    # Circuit breaker params
    st.markdown("<div class='section-title'>Circuit Breaker</div>", unsafe_allow_html=True)
    cb_drop_pct = st.number_input("Halt if drop ≥ %", 0.5, 10.0, float(settings.cb_drop_pct), step=0.5)
    cb_window = st.slider("Drop window (candles)", 2, 20, settings.cb_window)
    cb_atr_mult = st.number_input("ATR spike ×", 1.5, 10.0, float(settings.cb_atr_mult), step=0.5)
    cb_cooldown = st.slider("Cooldown (s)", 30, 1800, settings.cb_cooldown, step=30)


if not symbol:
    st.stop()

# ── Load data ─────────────────────────────────────────────────────────────────

try:
    df_1m, df_5m, order_book = load_market(
        symbol, interval, confirm_interval, candle_limit, settings.market_data_testnet
    )
except Exception as exc:
    st.error(f"Failed to load market data: {exc}")
    st.stop()

latest_price = float(df_1m.iloc[-1]["close"])
prev_close   = float(df_1m.iloc[-2]["close"])
price_change_pct = (latest_price - prev_close) / prev_close * 100

# Run signal engine
engine = SpotLongEngine(
    min_score=min_score,
    target_profit_usd=target_profit,
    max_loss_usd=max_loss,
    fee_rate=settings.fee_rate,
)
risk = RiskManager(
    max_loss_usd=max_loss,
    target_profit_usd=target_profit,
    leverage=leverage,
    daily_max_loss_usd=settings.daily_max_loss_usd,
    max_consecutive_losses=settings.max_consecutive_losses,
)
decision = RiskDecision(allow=False, reason="Pending evaluation", quantity=0.0, notional_usd=100.0)

try:
    preliminary = engine.evaluate(df_1m, df_5m, order_book, position_size_usd=100)
    if preliminary.entry_price > 0 and preliminary.stop_price > 0:
        decision = risk.can_trade(preliminary.entry_price, preliminary.stop_price, account_equity)
    signal = (
        engine.evaluate(df_1m, df_5m, order_book, position_size_usd=decision.notional_usd)
        if decision.allow else preliminary
    )
except Exception as exc:
    st.error(f"Signal engine error: {exc}")
    signal = preliminary if "preliminary" in dir() else None
    st.stop()

# Run circuit breaker
cb = CircuitBreaker(
    drop_pct=cb_drop_pct,
    drop_window=cb_window,
    atr_mult=cb_atr_mult,
    cascade_candles=settings.cb_cascade,
    cooldown_sec=cb_cooldown,
)
cb_status = cb.check(df_1m)

# ── Top header row ────────────────────────────────────────────────────────────

h1, h2, h3, h4, h5 = st.columns([2.5, 2, 2.5, 2, 1])

with h1:
    st.markdown(
        f"<div style='font-size:28px;font-weight:800;'>"
        f"{symbol} "
        f"<span style='color:{'#22c55e' if price_change_pct >= 0 else '#ef4444'}'>"
        f"${latest_price:,.2f}</span></div>"
        f"<div style='font-size:13px;color:{'#22c55e' if price_change_pct >= 0 else '#ef4444'}'>"
        f"{'▲' if price_change_pct >= 0 else '▼'} {abs(price_change_pct):.3f}% vs prev candle</div>",
        unsafe_allow_html=True,
    )

with h2:
    bot_badge = "badge-green" if bot_running else "badge-red"
    market_label = "TESTNET" if settings.market_data_testnet else "LIVE SPOT"
    bot_label = "● RUNNING" if bot_running else "● STOPPED"
    st.markdown(
        f"<div style='font-size:12px;color:#64748b;margin-bottom:4px'>BOT STATUS</div>"
        f"<span class='badge {bot_badge}' style='font-size:14px'>{bot_label}</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"Market data: {market_label}")

with h3:
    if cb_status["halted"]:
        resume_min = cb_status["resume_in"] // 60
        resume_sec = cb_status["resume_in"] % 60
        st.markdown(
            f"<div style='font-size:12px;color:#64748b;margin-bottom:4px'>CIRCUIT BREAKER</div>"
            f"<span class='badge badge-yellow'>⚡ HALTED — {resume_min}m {resume_sec:02d}s</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='font-size:12px;color:#64748b;margin-bottom:4px'>CIRCUIT BREAKER</div>"
            "<span class='badge badge-green'>✓ CLEAR</span>",
            unsafe_allow_html=True,
        )

with h4:
    sig_color = "#22c55e" if signal.action == "BUY" else "#94a3b8"
    st.markdown(
        f"<div style='font-size:12px;color:#64748b;margin-bottom:4px'>SIGNAL</div>"
        f"<span style='font-size:20px;font-weight:800;color:{sig_color}'>{signal.action}</span>"
        f"<span style='color:#64748b;font-size:13px'> {signal.score}/{signal.max_score} "
        f"({signal.confidence}%)</span>",
        unsafe_allow_html=True,
    )

with h5:
    if st.button("⟳ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ── Circuit breaker alert (when triggered) ────────────────────────────────────

if cb_status["halted"]:
    st.markdown(
        f"<div class='halted-banner'>"
        f"⚡ CIRCUIT BREAKER ACTIVE — {cb_status['reason']}<br>"
        f"<span style='font-weight:400;font-size:13px'>"
        f"New entries halted. Auto-resumes in {cb_status['resume_in']}s once conditions stabilize."
        f"</span></div>",
        unsafe_allow_html=True,
    )

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_analysis, tab_simulator, tab_backtest, tab_history = st.tabs([
    "📊 Market Analysis",
    "🖊 Trade Simulator",
    "📈 Backtest",
    "📋 History",
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — MARKET ANALYSIS
# ════════════════════════════════════════════════════════════════════════════════

with tab_analysis:

    # ── Signal banner + score breakdown ──────────────────────────────────────
    left_col, mid_col, right_col = st.columns([3, 3, 2])

    with left_col:
        banner_class = "signal-buy" if signal.action == "BUY" else "signal-wait"
        banner_icon = "🟢" if signal.action == "BUY" else "⏸"
        st.markdown(
            f"<div class='{banner_class}'>{banner_icon} {signal.action}</div>",
            unsafe_allow_html=True,
        )
        st.caption(signal.setup)

        st.markdown("<div class='section-title' style='margin-top:12px'>Score Breakdown</div>",
                    unsafe_allow_html=True)
        render_score_breakdown(signal.score_breakdown, signal.score, signal.max_score)

    with mid_col:
        st.markdown("<div class='section-title'>Trade Plan</div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        m1.metric("Entry",        f"{signal.entry_price:.4f}")
        m2.metric("Take Profit",  f"{signal.take_profit_price:.4f}",
                  delta=f"${signal.estimated_net_profit_usd:.2f}")
        m3, m4 = st.columns(2)
        m3.metric("Stop Loss",    f"{signal.stop_price:.4f}",
                  delta=f"-${signal.estimated_stop_loss_usd:.2f}", delta_color="inverse")
        m4.metric("Risk/Reward",  f"{signal.risk_reward_ratio:.2f}")

        st.markdown("<div class='section-title' style='margin-top:12px'>Position</div>",
                    unsafe_allow_html=True)
        p1, p2 = st.columns(2)
        p1.metric("Notional",  f"${decision.notional_usd:.2f}")
        p2.metric("Quantity",  f"{signal.quantity:.6f}")

    with right_col:
        st.markdown("<div class='section-title'>Signal Reasons</div>", unsafe_allow_html=True)
        for r in signal.reasons:
            icon = "✅" if not r.startswith("Score") else "⛔"
            st.markdown(f"<div style='font-size:12px;color:#cbd5e1;padding:2px 0'>{icon} {r}</div>",
                        unsafe_allow_html=True)

        st.markdown("<div class='section-title' style='margin-top:10px'>Risk Check</div>",
                    unsafe_allow_html=True)
        allow_color = "#22c55e" if decision.allow else "#ef4444"
        allow_icon  = "✅" if decision.allow else "⛔"
        st.markdown(
            f"<div style='font-size:13px;color:{allow_color}'>{allow_icon} {decision.reason}</div>",
            unsafe_allow_html=True,
        )

    # ── Chart ─────────────────────────────────────────────────────────────────
    st.plotly_chart(build_chart(df_1m, signal), use_container_width=True)

    # ── Fundamental + CB filters ──────────────────────────────────────────────
    with st.expander("🌐 Fundamental & Market Filters", expanded=False):
        try:
            fundamentals = FundamentalFilters()
            block = fundamentals.should_block_short(
                symbol,
                use_fear_greed=settings.use_fear_greed_filter,
                use_coingecko=settings.use_coingecko_filter,
            )
            fund_col, cb_col = st.columns(2)
            with fund_col:
                st.markdown("<div class='section-title'>Fundamental Filters</div>",
                            unsafe_allow_html=True)
                if block["block"]:
                    st.warning("⛔ Fundamental block active")
                    for r in block["reasons"]:
                        st.caption(r)
                else:
                    st.success("✅ No fundamental blocks")
            with cb_col:
                st.markdown("<div class='section-title'>Circuit Breaker Status</div>",
                            unsafe_allow_html=True)
                if cb_status["halted"]:
                    st.warning(f"⚡ Halted: {cb_status['reason']}")
                    st.caption(f"Resumes in {cb_status['resume_in']}s")
                else:
                    st.success("✅ Clear — normal market conditions")
        except Exception as exc:
            st.caption(f"Filter error: {exc}")

    # ── Prediction calculator ─────────────────────────────────────────────────
    with st.expander("🧮 Prediction Calculator", expanded=False):
        calc_entry = st.number_input("Short entry price", 0.0001, value=float(latest_price), format="%.6f")
        calc_stop = st.number_input("Stop price", 0.0001,
                                    value=float(max(signal.stop_price or latest_price * 1.002, latest_price * 1.0005)),
                                    format="%.6f")
        calc_notional = st.number_input("Notional USD", 5.0, value=float(max(decision.notional_usd or 100, 100)), step=5.0)
        try:
            plan = calculate_short_trade_plan(
                entry_price=calc_entry,
                stop_price=calc_stop,
                notional_usd=calc_notional,
                target_net_profit_usd=target_profit,
                fee_rate=settings.fee_rate,
            )
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Qty",        f"{plan.quantity:.6f}")
            k2.metric("Take Profit", f"{plan.take_profit_price:.6f}")
            k3.metric("Net Profit",  f"${plan.estimated_net_profit_usd:.4f}")
            k4.metric("Stop Loss",   f"${plan.estimated_stop_loss_usd:.4f}")
        except ValueError as exc:
            st.warning(str(exc))

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — TRADE SIMULATOR
# ════════════════════════════════════════════════════════════════════════════════

with tab_simulator:
    st.subheader("Manual Paper Trade Simulator")
    st.caption("Practice opening and closing short/long positions without real capital.")

    manual_broker = ManualPaperBroker(fee_rate=settings.fee_rate)
    manual_position = manual_broker.load_position()

    if manual_position:
        status = manual_broker.mark_to_market(latest_price)
        pnl_val = status["net_pnl"]
        pnl_color = "#22c55e" if pnl_val >= 0 else "#ef4444"

        st.markdown(
            f"<div style='background:#1e293b;padding:16px;border-radius:10px;"
            f"border:1px solid {'#16a34a' if pnl_val >= 0 else '#dc2626'}'>"
            f"<div style='font-size:13px;color:#94a3b8'>OPEN {status['side']} POSITION</div>"
            f"<div style='font-size:22px;font-weight:800;color:{pnl_color}'>"
            f"Net PnL: ${pnl_val:+.4f}</div></div>",
            unsafe_allow_html=True,
        )
        st.markdown("")

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Entry",    f"{status['entry_price']:.6f}")
        s2.metric("Current",  f"{status['current_price']:.6f}",
                  delta=f"{(status['current_price'] - status['entry_price']):.4f}")
        s3.metric("Quantity", f"{status['quantity']:.6f}")
        s4.metric("Side",     status["side"])

        st.markdown("")
        cl_col, rs_col, _ = st.columns([2, 2, 4])
        with cl_col:
            if st.button("✅ Close Position", use_container_width=True, type="primary"):
                res = manual_broker.close_position(latest_price)
                if res["ok"]:
                    st.success(f"Closed {res['side']} → net PnL ${res['net_pnl']:.4f}")
                else:
                    st.info(res["reason"])
                st.rerun()
        with rs_col:
            if st.button("🗑 Reset Position", use_container_width=True):
                res = manual_broker.reset_position()
                st.warning(res["reason"])
                st.rerun()
    else:
        st.info("No open position. Configure and open a trade below.")

        f1, f2 = st.columns(2)
        with f1:
            manual_notional = st.number_input("Notional USD", 5.0, value=25.0, step=5.0)
            manual_entry = st.number_input("Entry price", 0.0001, value=float(latest_price), format="%.6f")
        with f2:
            manual_stop = st.number_input("Stop price (0 = no stop)", 0.0, value=0.0, format="%.6f")
            manual_tp = st.number_input("Take profit price (0 = none)", 0.0, value=0.0, format="%.6f")

        st.markdown("")
        buy_col, sell_col = st.columns(2)
        with buy_col:
            if st.button("📈 Buy Long", use_container_width=True):
                res = manual_broker.open_position(
                    symbol=symbol, side="LONG",
                    entry_price=manual_entry, notional_usd=manual_notional,
                    stop_price=manual_stop, take_profit_price=manual_tp,
                )
                st.success(res["reason"]) if res["ok"] else st.info(res["reason"])
                st.rerun()
        with sell_col:
            if st.button("📉 Sell Short", use_container_width=True, type="primary"):
                res = manual_broker.open_position(
                    symbol=symbol, side="SHORT",
                    entry_price=manual_entry, notional_usd=manual_notional,
                    stop_price=manual_stop, take_profit_price=manual_tp,
                )
                st.success(res["reason"]) if res["ok"] else st.info(res["reason"])
                st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKTEST
# ════════════════════════════════════════════════════════════════════════════════

with tab_backtest:
    st.subheader("Strategy Backtest")
    st.caption("Replay historical candles through the signal engine to estimate performance.")

    bt_col1, bt_col2 = st.columns([1, 3])
    with bt_col1:
        max_hold = st.slider("Max hold candles", 5, 120, 30, step=5)
        run_bt = st.button("▶ Run Backtest", use_container_width=True, type="primary")

    if run_bt:
        with st.spinner("Running backtest on loaded candles…"):
            try:
                summary = run_short_backtest(
                    df_1m=df_1m,
                    df_5m=df_5m,
                    signal_engine=engine,
                    symbol=symbol,
                    starting_equity=account_equity,
                    max_loss_usd=max_loss,
                    leverage=leverage,
                    max_hold_candles=max_hold,
                    fee_rate=settings.fee_rate,
                )

                b1, b2, b3, b4, b5 = st.columns(5)
                b1.metric("Trades",       summary.total_trades)
                b2.metric("Win Rate",     f"{summary.win_rate:.1f}%")
                b3.metric("Net PnL",      f"${summary.net_pnl:.2f}",
                          delta=f"{'▲' if summary.net_pnl >= 0 else '▼'}")
                b4.metric("Max Drawdown", f"${summary.max_drawdown:.2f}")
                b5.metric("End Equity",   f"${summary.ending_equity:.2f}")

                if not summary.trades.empty:
                    # Equity curve
                    bt_df = summary.trades.copy()
                    bt_df["cum_pnl"] = bt_df.get("net_pnl", 0).cumsum()
                    bt_fig = go.Figure(go.Scatter(
                        x=list(range(len(bt_df))), y=bt_df["cum_pnl"],
                        mode="lines+markers", name="Cumulative PnL",
                        line=dict(color="#22c55e" if summary.net_pnl >= 0 else "#ef4444", width=2),
                    ))
                    bt_fig.update_layout(
                        template="plotly_dark", height=300,
                        margin=dict(l=10, r=10, t=10, b=10),
                        xaxis_title="Trade #", yaxis_title="Cumulative PnL ($)",
                    )
                    st.plotly_chart(bt_fig, use_container_width=True)
                    st.dataframe(summary.trades.tail(50), use_container_width=True, hide_index=True)
                else:
                    st.info("No trades were triggered in the loaded candles. "
                            "Lower the score threshold or load more candles.")
            except Exception as exc:
                st.error(f"Backtest failed: {exc}")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — HISTORY
# ════════════════════════════════════════════════════════════════════════════════

with tab_history:
    signals_path       = Path("logs/signals.csv")
    trades_path        = Path("logs/trades.csv")
    manual_trades_path = Path("logs/manual_trades.csv")

    # ── Bot trades ────────────────────────────────────────────────────────────
    if trades_path.exists():
        trades = pd.read_csv(trades_path)
        trades["closed_at"] = pd.to_datetime(trades["closed_at"], errors="coerce")
        trades["net_pnl"]   = pd.to_numeric(trades["net_pnl"], errors="coerce")
        trades["cum_pnl"]   = trades["net_pnl"].cumsum()

        st.subheader("Bot Trades")
        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("Total Trades",  len(trades))
        t2.metric("Win Rate",      f"{(trades['net_pnl'] > 0).mean() * 100:.1f}%")
        t3.metric("Total Net PnL", f"${trades['net_pnl'].sum():.4f}")
        t4.metric("Avg PnL",       f"${trades['net_pnl'].mean():.4f}")
        t5.metric("Best Trade",    f"${trades['net_pnl'].max():.4f}")

        fig_pnl = go.Figure(go.Scatter(
            x=trades["closed_at"], y=trades["cum_pnl"],
            mode="lines", fill="tozeroy",
            fillcolor="rgba(34,197,94,0.12)" if trades["net_pnl"].sum() >= 0 else "rgba(239,68,68,0.12)",
            line=dict(color="#22c55e" if trades["net_pnl"].sum() >= 0 else "#ef4444", width=2),
        ))
        fig_pnl.update_layout(
            template="plotly_dark", height=260,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Date", yaxis_title="Cumulative PnL ($)",
        )
        st.plotly_chart(fig_pnl, use_container_width=True)
        st.dataframe(trades.tail(50), use_container_width=True, hide_index=True)
    else:
        st.info("No bot trades logged yet. Start the bot and let it run.")

    # ── Signals ───────────────────────────────────────────────────────────────
    if signals_path.exists():
        with st.expander("📡 Recent Signals", expanded=False):
            signals = pd.read_csv(signals_path)
            st.dataframe(signals.tail(100), use_container_width=True, hide_index=True)

    # ── Manual trades ─────────────────────────────────────────────────────────
    if manual_trades_path.exists():
        manual_trades = pd.read_csv(manual_trades_path)
        manual_trades["closed_at"] = pd.to_datetime(manual_trades["closed_at"], errors="coerce")
        manual_trades["net_pnl"]   = pd.to_numeric(manual_trades["net_pnl"], errors="coerce")
        manual_trades["cum_pnl"]   = manual_trades["net_pnl"].cumsum()

        st.subheader("Manual Simulator Trades")
        fig_m = go.Figure(go.Scatter(
            x=manual_trades["closed_at"], y=manual_trades["cum_pnl"],
            mode="lines+markers",
            line=dict(color="#a78bfa", width=2),
        ))
        fig_m.update_layout(
            template="plotly_dark", height=240,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_m, use_container_width=True)
        st.dataframe(manual_trades.tail(50), use_container_width=True, hide_index=True)
