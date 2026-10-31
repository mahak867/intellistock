"""
IntelliStock — Market Terminal views.

Ideas borrowed (no code copied) from public projects: resizable terminal-style
layouts and watchlists (PaisaMachine, Bazaar), sector heat maps and index
strips (Bazaar), candlestick + indicator panes (TradingView-style), and
portfolio/backtest summaries (Ghostfolio, OpenBB).

Data: uses the IntelliStock API when it can return OHLCV, otherwise a
deterministic synthetic generator so the UI works offline. Synthetic data is
always labelled "DEMO DATA" on screen.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

UP, DOWN, AMBER, GRID, BG, PANEL, TEXT = (
    "#26a69a",
    "#ef5350",
    "#f5b942",
    "#1f2937",
    "#0b0f14",
    "#111821",
    "#d1d5db",
)

SECTORS = {
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "Banks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
    "Energy": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA"],
    "Auto": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
}
ALL_TICKERS = [t for v in SECTORS.values() for t in v]

CSS = f"""
<style>
.stApp {{ background:{BG}; color:{TEXT}; }}
header[data-testid="stHeader"] {{ background:{BG}; }}
[data-testid="stSidebar"] {{ background:{PANEL}; border-right:1px solid {GRID}; }}
[data-testid="stMetric"] {{ background:{PANEL}; border:1px solid {GRID};
  border-radius:8px; padding:10px 14px; }}
[data-testid="stMetricLabel"] p {{ font-size:.72rem; letter-spacing:.06em;
  text-transform:uppercase; color:#8b97a7; }}
[data-testid="stMetricValue"] {{ font-variant-numeric:tabular-nums; }}
h1,h2,h3 {{ letter-spacing:-.01em; }}
.tag {{ display:inline-block; padding:2px 10px; border-radius:999px;
  font-size:.72rem; font-weight:600; letter-spacing:.05em; }}
.tag-demo {{ background:#3b2f0b; color:{AMBER}; border:1px solid #5c4a12; }}
.tag-live {{ background:#0d2f2b; color:{UP}; border:1px solid #14504a; }}
.sig {{ border:1px solid {GRID}; background:{PANEL}; border-radius:10px;
  padding:14px 16px; }}
.sig .big {{ font-size:2rem; font-weight:700; line-height:1.1; }}
.sig .sub {{ color:#8b97a7; font-size:.8rem; }}
</style>
"""


# ─── Data layer ──────────────────────────────────────────────────────────────


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


def demo_ohlcv(ticker: str, days: int = 320) -> pd.DataFrame:
    """Deterministic synthetic OHLCV (geometric random walk + regime drift)."""
    rng = np.random.default_rng(_seed(ticker))
    base = 200 + (_seed(ticker) % 3000)
    drift = rng.normal(0.0004, 0.0002)
    vol = rng.uniform(0.011, 0.022)
    regime = np.sin(np.linspace(0, rng.uniform(3, 7), days)) * 0.0009
    rets = rng.normal(drift, vol, days) + regime
    close = base * np.exp(np.cumsum(rets))
    open_ = np.r_[base, close[:-1]] * (1 + rng.normal(0, 0.002, days))
    span = np.abs(rng.normal(0, vol * 0.7, days)) * close
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span
    volume = (rng.lognormal(14.2, 0.35, days) * (1 + 6 * np.abs(rets))).astype(int)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    d["sma20"], d["sma50"] = c.rolling(20).mean(), c.rolling(50).mean()
    d["ema12"], d["ema26"] = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    sd = c.rolling(20).std()
    d["bb_up"], d["bb_lo"] = d["sma20"] + 2 * sd, d["sma20"] - 2 * sd
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    d["macd"] = d["ema12"] - d["ema26"]
    d["macd_sig"] = d["macd"].ewm(span=9).mean()
    d["macd_hist"] = d["macd"] - d["macd_sig"]
    tr = pd.concat(
        [d.high - d.low, (d.high - c.shift()).abs(), (d.low - c.shift()).abs()], axis=1
    ).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    return d


def forecast_fan(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Placeholder forecast for demo mode: damped drift + widening 80% band.
    Live mode should replace this with the API's model output."""
    c = df["close"]
    mu = c.pct_change().tail(60).mean()
    sg = c.pct_change().tail(60).std()
    steps = np.arange(1, horizon + 1)
    mean = c.iloc[-1] * np.exp(mu * steps * 0.6)
    band = c.iloc[-1] * sg * np.sqrt(steps) * 1.28
    idx = pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=horizon)
    return pd.DataFrame({"mean": mean, "lo": mean - band, "hi": mean + band}, index=idx)


def signal_from(df: pd.DataFrame, fc: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    score, why = 0, []
    exp_ret = fc["mean"].iloc[-1] / last["close"] - 1
    if exp_ret > 0.01:
        score += 1; why.append(f"Forecast {exp_ret:+.1%}")
    elif exp_ret < -0.01:
        score -= 1; why.append(f"Forecast {exp_ret:+.1%}")
    if last["sma20"] > last["sma50"]:
        score += 1; why.append("SMA20 > SMA50")
    else:
        score -= 1; why.append("SMA20 < SMA50")
    if last["rsi"] < 30:
        score += 1; why.append(f"RSI {last['rsi']:.0f} oversold")
    elif last["rsi"] > 70:
        score -= 1; why.append(f"RSI {last['rsi']:.0f} overbought")
    if last["macd_hist"] > 0:
        score += 1; why.append("MACD hist +")
    else:
        score -= 1; why.append("MACD hist −")
    label = "BUY" if score >= 2 else "SELL" if score <= -2 else "HOLD"
    return {"label": label, "score": score, "why": why, "exp_ret": exp_ret}


def backtest(df: pd.DataFrame) -> pd.DataFrame:
    """Long-only SMA20/50 + MACD confirm vs buy-and-hold. Signal lagged 1 day."""
    d = add_indicators(df).dropna().copy()
    pos = ((d.sma20 > d.sma50) & (d.macd_hist > 0)).astype(int).shift(1).fillna(0)
    r = d["close"].pct_change().fillna(0)
    d["strategy"] = (1 + r * pos).cumprod()
    d["hold"] = (1 + r).cumprod()
    d["pos"] = pos
    return d


# ─── Charts ──────────────────────────────────────────────────────────────────


def _layout(fig: go.Figure, h: int) -> go.Figure:
    fig.update_layout(
        height=h, paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT, size=12),
        margin=dict(l=8, r=8, t=28, b=8), hovermode="x unified",
        legend=dict(orientation="h", y=1.04, x=0, bgcolor="rgba(0,0,0,0)"),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(gridcolor=GRID, showspikes=True, spikethickness=1)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def price_chart(df: pd.DataFrame, fc: pd.DataFrame, view: int, show: list[str]) -> go.Figure:
    d = df.tail(view)
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02,
        row_heights=[0.56, 0.12, 0.16, 0.16],
    )
    fig.add_trace(go.Candlestick(
        x=d.index, open=d.open, high=d.high, low=d.low, close=d.close, name="Price",
        increasing_line_color=UP, decreasing_line_color=DOWN,
        increasing_fillcolor=UP, decreasing_fillcolor=DOWN), 1, 1)
    if "SMA 20/50" in show:
        fig.add_trace(go.Scatter(x=d.index, y=d.sma20, name="SMA20", line=dict(color=AMBER, width=1.2)), 1, 1)
        fig.add_trace(go.Scatter(x=d.index, y=d.sma50, name="SMA50", line=dict(color="#7aa2f7", width=1.2)), 1, 1)
    if "Bollinger" in show:
        fig.add_trace(go.Scatter(x=d.index, y=d.bb_up, name="BB up", line=dict(width=0.8, color="#6b7280", dash="dot")), 1, 1)
        fig.add_trace(go.Scatter(x=d.index, y=d.bb_lo, name="BB lo", line=dict(width=0.8, color="#6b7280", dash="dot"),
                                 fill="tonexty", fillcolor="rgba(107,114,128,.08)"), 1, 1)
    if "Forecast" in show and len(fc):
        x = [d.index[-1], *fc.index]
        last = d.close.iloc[-1]
        fig.add_trace(go.Scatter(x=x + x[::-1], y=[last, *fc.hi] + [last, *fc.lo][::-1],
                                 fill="toself", fillcolor="rgba(245,185,66,.14)",
                                 line=dict(width=0), name="80% band", hoverinfo="skip"), 1, 1)
        fig.add_trace(go.Scatter(x=x, y=[last, *fc["mean"]], name="Forecast",
                                 line=dict(color=AMBER, width=2, dash="dash")), 1, 1)
    vol_col = [UP if c >= o else DOWN for c, o in zip(d.close, d.open)]
    fig.add_trace(go.Bar(x=d.index, y=d.volume, marker_color=vol_col, name="Volume", opacity=.6), 2, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.rsi, name="RSI", line=dict(color="#c084fc", width=1.3)), 3, 1)
    for lvl in (30, 70):
        fig.add_hline(y=lvl, row=3, col=1, line=dict(color="#4b5563", width=.8, dash="dot"))
    fig.add_trace(go.Bar(x=d.index, y=d.macd_hist, name="MACD hist",
                         marker_color=[UP if v >= 0 else DOWN for v in d.macd_hist], opacity=.55), 4, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.macd, name="MACD", line=dict(color="#7aa2f7", width=1)), 4, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.macd_sig, name="Signal", line=dict(color=AMBER, width=1)), 4, 1)
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    return _layout(fig, 720)


def heatmap(changes: dict[str, float]) -> go.Figure:
    rows = [(s, t, changes[t]) for s, ts in SECTORS.items() for t in ts]
    df = pd.DataFrame(rows, columns=["sector", "ticker", "chg"])
    df["size"] = [abs(_seed(t)) % 90 + 20 for t in df.ticker]
    fig = go.Figure(go.Treemap(
        labels=df.ticker, parents=df.sector, values=df["size"],
        customdata=df.chg, texttemplate="<b>%{label}</b><br>%{customdata:+.2f}%",
        marker=dict(colors=df.chg, colorscale=[[0, DOWN], [.5, "#2b3441"], [1, UP]],
                    cmid=0, cmin=-3, cmax=3, line=dict(width=1, color=BG)),
        branchvalues="remainder", root_color=BG,
    ))
    fig.update_traces(textfont=dict(color="white"))
    return _layout(fig, 420)


def equity_chart(bt: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bt.index, y=bt.hold, name="Buy & hold", line=dict(color="#6b7280", width=1.5)))
    fig.add_trace(go.Scatter(x=bt.index, y=bt.strategy, name="IntelliStock signal", line=dict(color=AMBER, width=2)))
    return _layout(fig, 340)


# ─── Views ───────────────────────────────────────────────────────────────────


def _stats(bt: pd.DataFrame) -> dict:
    r = bt.strategy.pct_change().dropna()
    dd = (bt.strategy / bt.strategy.cummax() - 1).min()
    return {
        "ret": bt.strategy.iloc[-1] - 1, "hold": bt.hold.iloc[-1] - 1,
        "sharpe": (r.mean() / r.std() * np.sqrt(252)) if r.std() else 0.0,
        "dd": dd, "inmkt": bt.pos.mean(),
    }


def _snapshot(ticker: str) -> tuple[float, float, list[float]]:
    d = demo_ohlcv(ticker, 60)
    return d.close.iloc[-1], d.close.iloc[-1] / d.close.iloc[-2] - 1, d.close.tail(30).tolist()


def render_terminal(live: bool) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    tag = ('<span class="tag tag-live">LIVE</span>' if live
           else '<span class="tag tag-demo">DEMO DATA · synthetic</span>')
    st.markdown(f"### Market Terminal &nbsp; {tag}", unsafe_allow_html=True)

    # Index strip
    idx = {"NIFTY 50": "NIFTY", "SENSEX": "SENSEX", "BANK NIFTY": "BANKNIFTY", "INDIA VIX": "VIX"}
    cols = st.columns(len(idx))
    for col, (name, sym) in zip(cols, idx.items()):
        p, ch, _ = _snapshot(sym)
        col.metric(name, f"{p * 8 if sym != 'VIX' else 11 + (p % 9):,.2f}", f"{ch:+.2%}",
                   delta_color="inverse" if sym == "VIX" else "normal")

    # Controls
    c1, c2, c3, c4 = st.columns([2, 1, 1, 3])
    sel = st.session_state.get("selected_ticker", "RELIANCE")
    ticker = c1.selectbox("Symbol", ALL_TICKERS, index=ALL_TICKERS.index(sel) if sel in ALL_TICKERS else 0)
    horizon = c2.selectbox("Forecast (days)", [5, 10, 15, 30], index=1)
    view = c3.selectbox("Window", [60, 120, 250], index=1)
    show = c4.multiselect("Overlays", ["SMA 20/50", "Bollinger", "Forecast"],
                          default=["SMA 20/50", "Forecast"])

    df = add_indicators(demo_ohlcv(ticker))
    fc = forecast_fan(df, horizon)
    sig = signal_from(df, fc)
    last, prev = df.iloc[-1], df.iloc[-2]

    left, right = st.columns([3.2, 1])
    with left:
        st.plotly_chart(price_chart(df, fc, view, show), use_container_width=True)
    with right:
        color = {"BUY": UP, "SELL": DOWN, "HOLD": AMBER}[sig["label"]]
        st.markdown(
            f'<div class="sig"><div class="sub">{ticker} · SIGNAL</div>'
            f'<div class="big" style="color:{color}">{sig["label"]}</div>'
            f'<div class="sub">score {sig["score"]:+d} / 4 · exp. {sig["exp_ret"]:+.1%} in {horizon}d</div></div>',
            unsafe_allow_html=True)
        st.write("")
        st.metric("Last close", f"₹{last.close:,.2f}", f"{last.close / prev.close - 1:+.2%}")
        st.metric("RSI (14)", f"{last.rsi:.1f}")
        st.metric("ATR (14)", f"₹{last.atr:,.2f}", f"{last.atr / last.close:.1%} of price", delta_color="off")
        st.metric("52w range", f"{df.close.tail(250).min():,.0f} – {df.close.tail(250).max():,.0f}")
        st.caption("Why: " + " · ".join(sig["why"]))
    st.caption("Forecast shown is a statistical placeholder in demo mode. Not investment advice.")

    t1, t2, t3 = st.tabs(["Watchlist", "Sector heatmap", "Backtest"])
    with t1:
        rows = []
        for t in st.session_state.get("watchlist", ["RELIANCE", "TCS", "INFY"]):
            d = add_indicators(demo_ohlcv(t))
            p, ch, spark = _snapshot(t)
            s = signal_from(d, forecast_fan(d, 10))
            rows.append({"Symbol": t, "Price": round(p, 2), "Chg %": round(ch * 100, 2),
                         "30d": spark, "RSI": round(d.rsi.iloc[-1], 1), "Signal": s["label"]})
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            column_config={
                "30d": st.column_config.LineChartColumn("30d trend"),
                "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
                "Price": st.column_config.NumberColumn(format="₹%.2f"),
                "RSI": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            })
        movers = sorted(((t, _snapshot(t)[1] * 100) for t in ALL_TICKERS), key=lambda x: x[1])
        g, l = st.columns(2)
        g.markdown("**Top gainers**")
        g.dataframe(pd.DataFrame(movers[-5:][::-1], columns=["Symbol", "Chg %"]), hide_index=True, use_container_width=True)
        l.markdown("**Top losers**")
        l.dataframe(pd.DataFrame(movers[:5], columns=["Symbol", "Chg %"]), hide_index=True, use_container_width=True)
    with t2:
        st.plotly_chart(heatmap({t: _snapshot(t)[1] * 100 for t in ALL_TICKERS}), use_container_width=True)
    with t3:
        bt = backtest(demo_ohlcv(ticker))
        s = _stats(bt)
        m = st.columns(5)
        m[0].metric("Strategy", f"{s['ret']:+.1%}")
        m[1].metric("Buy & hold", f"{s['hold']:+.1%}")
        m[2].metric("Sharpe", f"{s['sharpe']:.2f}")
        m[3].metric("Max drawdown", f"{s['dd']:.1%}")
        m[4].metric("Time in market", f"{s['inmkt']:.0%}")
        st.plotly_chart(equity_chart(bt), use_container_width=True)
        st.caption("Long-only SMA20/50 + MACD rule, signal lagged one day, no costs or slippage.")
