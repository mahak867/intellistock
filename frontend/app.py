"""
IntelliStock — Streamlit Dashboard
────────────────────────────────────
Production-grade investor dashboard:
  • Login gate (JWT via API)
  • Real-time NSE stock search
  • LSTM price forecast chart (Plotly)
  • BUY/SELL/HOLD signal panel
  • Technical indicators overlay
  • Model performance metrics
  • Watchlist + portfolio tracker
  • Backtesting tab
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# ─── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="IntelliStock | NSE Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/yourgithub/intellistock",
        "Report a bug": "https://github.com/yourgithub/intellistock/issues",
        "About": "IntelliStock — LSTM-powered NSE/BSE market intelligence platform",
    },
)

API_BASE = "http://localhost:8000/api/v1"

# ─── Auth helpers ────────────────────────────────────────────────────────────────

def api_login(email: str, password: str) -> dict | None:
    try:
        resp = requests.post(
            f"{API_BASE}/auth/login",
            data={"username": email, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def api_get(endpoint: str, token: str, params: dict | None = None) -> dict | None:
    try:
        resp = requests.get(
            f"{API_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ─── Session state init ──────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "watchlist" not in st.session_state:
    st.session_state.watchlist = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


# ─── Login page ─────────────────────────────────────────────────────────────────

def render_login():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 📈 IntelliStock")
        st.markdown("#### NSE/BSE Market Intelligence Platform")
        st.divider()

        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            with st.spinner("Authenticating…"):
                tokens = api_login(email, password)
            if tokens:
                st.session_state.token = tokens["access_token"]
                st.rerun()
            else:
                st.error("Invalid credentials. Please check your email and password.")

        st.markdown("---")
        st.caption("Don't have an account? Contact your administrator.")


# ─── Sidebar ─────────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("## 📈 IntelliStock")
        st.caption(f"Market: NSE/BSE | {datetime.now().strftime('%d %b %Y')}")
        st.divider()

        page = st.radio(
            "Navigation",
            ["🏠 Dashboard", "🔮 Predictions", "📊 Backtesting", "⚙️ Settings"],
            label_visibility="collapsed",
        )

        st.divider()
        st.markdown("**Watchlist**")
        for t in st.session_state.watchlist:
            if st.button(t, key=f"wl_{t}", use_container_width=True):
                st.session_state.selected_ticker = t

        new_ticker = st.text_input("Add to watchlist", placeholder="e.g. WIPRO")
        if st.button("+ Add", use_container_width=True) and new_ticker:
            ticker = new_ticker.upper().strip()
            if ticker not in st.session_state.watchlist:
                st.session_state.watchlist.append(ticker)
                st.rerun()

        st.divider()
        if st.button("Sign Out", use_container_width=True):
            st.session_state.token = None
            st.rerun()

    return page


# ─── Prediction chart ─────────────────────────────────────────────────────────────

def render_prediction_chart(data: dict):
    predictions = data.get("predictions", [])
    if not predictions:
        st.warning("No prediction data available")
        return

    pred_df = pd.DataFrame(predictions)
    pred_df["date"] = pd.to_datetime(pred_df["date"])

    # Historical OHLCV (from cache or separate API call)
    ticker = data["ticker"]
    hist = api_get(f"/stocks/{ticker}/ohlcv", st.session_state.token, {"days": 90})
    hist_df = pd.DataFrame(hist.get("data", [])) if hist else pd.DataFrame()

    fig = make_subplots(
        rows=3, cols=1,
        row_heights=[0.6, 0.2, 0.2],
        shared_xaxes=True,
        subplot_titles=("Price & Forecast", "Volume", "RSI"),
        vertical_spacing=0.05,
    )

    # ── Historical close ─────────────────────────────────────────────────────
    if not hist_df.empty:
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(hist_df["date"]),
                y=hist_df["Close"],
                name="Historical",
                line=dict(color="#2563EB", width=1.5),
            ),
            row=1, col=1,
        )

    # ── Prediction + confidence band ─────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=pred_df["date"],
            y=pred_df["upper_bound"],
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            name="Upper bound",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=pred_df["date"],
            y=pred_df["lower_bound"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(234, 179, 8, 0.15)",
            line=dict(width=0),
            name="90% CI",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=pred_df["date"],
            y=pred_df["predicted_close"],
            name="LSTM Forecast",
            line=dict(color="#F59E0B", width=2.5, dash="dot"),
            mode="lines+markers",
            marker=dict(size=6),
        ),
        row=1, col=1,
    )

    # ── Volume ───────────────────────────────────────────────────────────────
    if not hist_df.empty and "Volume" in hist_df.columns:
        fig.add_trace(
            go.Bar(
                x=pd.to_datetime(hist_df["date"]),
                y=hist_df["Volume"],
                name="Volume",
                marker_color="#94A3B8",
                opacity=0.7,
            ),
            row=2, col=1,
        )

    # ── RSI ──────────────────────────────────────────────────────────────────
    if not hist_df.empty and "RSI" in hist_df.columns:
        fig.add_trace(
            go.Scatter(x=pd.to_datetime(hist_df["date"]), y=hist_df["RSI"],
                       name="RSI", line=dict(color="#8B5CF6", width=1.5)),
            row=3, col=1,
        )
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        height=620,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(148,163,184,0.2)", gridwidth=0.5),
        margin=dict(l=0, r=0, t=30, b=0),
        font=dict(size=12),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ─── Signal panel ────────────────────────────────────────────────────────────────

def render_signal(signal: dict):
    label = signal.get("signal", "HOLD")
    conf = signal.get("confidence", 0)
    ret = signal.get("predicted_return_pct", 0)
    current = signal.get("current_price", 0)
    predicted = signal.get("predicted_price", 0)

    colors = {"BUY": ("🟢", "#16A34A"), "SELL": ("🔴", "#DC2626"), "HOLD": ("🟡", "#D97706")}
    icon, color = colors.get(label, ("🟡", "#D97706"))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Signal", f"{icon} {label}")
    with col2:
        st.metric("Confidence", f"{conf * 100:.1f}%")
    with col3:
        st.metric("Current Price", f"₹{current:,.2f}")
    with col4:
        delta_color = "normal" if ret >= 0 else "inverse"
        st.metric("Predicted (next day)", f"₹{predicted:,.2f}", f"{ret:+.2f}%")


# ─── Model metrics ───────────────────────────────────────────────────────────────

def render_metrics(metrics: dict):
    with st.expander("📊 Model Performance Metrics", expanded=False):
        cols = st.columns(4)
        cols[0].metric("RMSE (₹)", f"{metrics.get('RMSE', 'N/A'):.2f}")
        cols[1].metric("MAE (₹)", f"{metrics.get('MAE', 'N/A'):.2f}")
        cols[2].metric("MAPE", f"{metrics.get('MAPE', 'N/A'):.2f}%")
        cols[3].metric("Directional Accuracy", f"{metrics.get('Directional_Accuracy', 'N/A'):.1f}%")
        st.caption(f"Model version: {metrics.get('model_version', 'unknown')} | "
                   f"Evaluated on {metrics.get('n_samples', '?')} test samples")


# ─── Predictions page ────────────────────────────────────────────────────────────

def render_predictions_page():
    st.header("🔮 Price Predictions")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        ticker = st.text_input(
            "NSE Ticker",
            value=getattr(st.session_state, "selected_ticker", "RELIANCE"),
            placeholder="e.g. RELIANCE, TCS, INFY",
        ).upper().strip()
    with col2:
        horizon = st.selectbox("Horizon", [1, 3, 5, 7, 14, 30], index=2)
    with col3:
        st.write("")
        predict_btn = st.button("Predict →", type="primary", use_container_width=True)

    if predict_btn or ticker:
        with st.spinner(f"Running LSTM inference for {ticker}…"):
            data = api_get(
                f"/predictions/{ticker}",
                st.session_state.token,
                {"horizon_days": horizon},
            )

        if data:
            render_signal(data.get("signal", {}))
            st.divider()
            render_prediction_chart(data)
            render_metrics(data.get("metrics", {}))

            if data.get("cached"):
                st.caption("⚡ Served from cache")
        else:
            st.error(f"Could not load predictions for {ticker}. Check the ticker and try again.")


# ─── Dashboard page ──────────────────────────────────────────────────────────────

def render_dashboard():
    st.header("🏠 Market Dashboard")
    st.caption(f"NSE/BSE | Last updated: {datetime.now().strftime('%H:%M:%S IST')}")

    # Quick metrics row
    cols = st.columns(len(st.session_state.watchlist[:5]))
    for i, ticker in enumerate(st.session_state.watchlist[:5]):
        signal_data = api_get(f"/predictions/{ticker}/signal", st.session_state.token)
        if signal_data:
            ret = signal_data.get("predicted_return_pct", 0)
            price = signal_data.get("current_price", 0)
            sig = signal_data.get("signal", "HOLD")
            icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(sig, "⚪")
            cols[i].metric(f"{icon} {ticker}", f"₹{price:,.0f}", f"{ret:+.2f}%")

    st.divider()
    st.info("Click any ticker in the sidebar to view detailed predictions.")


# ─── Backtesting page ────────────────────────────────────────────────────────────

def render_backtesting():
    st.header("📊 Backtesting")
    st.caption("Simulate historical IntelliStock signals vs buy-and-hold strategy")

    col1, col2 = st.columns(2)
    with col1:
        bt_ticker = st.text_input("Ticker", value="RELIANCE").upper()
    with col2:
        bt_days = st.slider("Days to backtest", 30, 180, 90)

    if st.button("Run Backtest", type="primary"):
        with st.spinner("Loading historical predictions…"):
            hist = api_get(
                f"/predictions/{bt_ticker}/history",
                st.session_state.token,
                {"days": bt_days},
            )

        if hist and hist.get("history"):
            df = pd.DataFrame(hist["history"])
            st.success(f"Loaded {len(df)} prediction records for {bt_ticker}")
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("No historical prediction data available for backtesting yet.")
            st.info("Backtesting data accumulates as the model runs in production. "
                    "Check back after a few days of live predictions.")


# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not st.session_state.token:
        render_login()
        return

    page = render_sidebar()

    if page == "🏠 Dashboard":
        render_dashboard()
    elif page == "🔮 Predictions":
        render_predictions_page()
    elif page == "📊 Backtesting":
        render_backtesting()
    elif page == "⚙️ Settings":
        st.header("⚙️ Settings")
        st.info("User preferences and API key management coming in v1.1")


if __name__ == "__main__":
    main()
