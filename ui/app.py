"""ChurnGuard dashboard. Run (Windows PowerShell, venv on, project root): streamlit run ui/app.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from ui.common import UI_DIR, db, read_alerts, reset, sync_alerts

st.set_page_config(page_title="ChurnGuard", layout="wide")
if not (UI_DIR / "meta.json").exists():
    st.error("No UI data yet. Run: python -m ui.build_ui_data")
    st.stop()


@st.cache_data
def load(name):
    return pd.read_parquet(UI_DIR / f"{name}.parquet")


meta = json.loads((UI_DIR / "meta.json").read_text(encoding="utf-8"))
start, n_hours = pd.Timestamp(meta["sim_start"]), meta["days"] * 24
cu, sh, ou = load("customers"), load("status_history"), load("outages")
towers, mt, ctx = load("towers"), load("tower_metrics"), load("alert_context")
st.session_state.setdefault("t", 0)
conn = db()
COL = {"DOWN": [220, 38, 38], "CRITICAL": [249, 115, 22], "DEGRADED": [234, 179, 8], "HEALTHY": [34, 197, 94]}

with st.sidebar:
    st.title("ChurnGuard")
    t = st.slider("Simulated hour", 0, n_hours, st.session_state.t)
    st.session_state.t = t
    clock = start + pd.Timedelta(hours=t)
    st.caption(f"Simulated now: {clock:%a %d %b %Y %H:%M} PKT")
    st.toggle("Play", key="play")
    speed = st.select_slider("Speed (sim hours per tick)", [1, 3, 6, 12, 24], 6)
    city = st.selectbox("City", ["All"] + sorted(cu["city"].unique()))
    basemap = st.toggle("Online basemap (needs internet)", False)
    if st.button("Reset demo"):
        reset(conn)
        st.session_state.t = 0
        st.rerun()

    @st.fragment(run_every=2)
    def ticker():
        if st.session_state.get("play") and st.session_state.t < n_hours:
            st.session_state.t = min(n_hours, st.session_state.t + speed)
            st.rerun()

    ticker()


def by_city(df):
    return df if city == "All" else df[df["city"] == city]


d = clock.normalize()
asof = sh[(sh.valid_from <= d) & (sh.valid_to.isna() | (sh.valid_to > d))].merge(
    cu[["customer_id", "city", "segment", "arpu_band"]], on="customer_id", how="left")
asof = by_city(asof.fillna({"city": "Unknown"}))
live = ou[ou.start_time <= clock]
sync_alerts(conn, list(zip(live.outage_id, live.tower_id, live.nearest_team_id, live.start_time.astype(str))))
al = read_alerts(conn)

tabs = st.tabs(["Overview", "Churn", "Towers & Alerts", "Offers", "Pipeline"])

with tabs[0]:
    n, ch = len(asof), int((asof.status == "CHURNED").sum())
    c = st.columns(5)
    c[0].metric("Customers signed up", f"{n:,}")
    c[1].metric("Churned", f"{ch:,}")
    c[2].metric("Churn rate", f"{100 * ch / max(n, 1):.1f}%")
    c[3].metric("Outages so far", f"{len(by_city(live)):,}")
    c[4].metric("Open alerts (all cities)", int((al.status == "OPEN").sum()))
    days = pd.date_range(start.normalize(), d)
    cc = by_city(cu)
    su = cc.groupby("signup_date").size().reindex(days, fill_value=0).cumsum()
    cs = cc.dropna(subset=["churn_date"]).groupby("churn_date").size().reindex(days, fill_value=0).cumsum()
    st.plotly_chart(px.line(pd.DataFrame({"Signed up": su, "Churned": cs}), title="Customers (cumulative)",
                            labels={"index": "Date", "value": "Customers"}))
    ud = load("usage_daily")
    ud = ud[ud.event_date <= d]
    a, b = st.columns(2)
    a.plotly_chart(px.bar(ud, x="event_date", y="spend", title="Daily spend (PKR), all cities"))
    b.plotly_chart(px.line(ud, x="event_date", y="data_gb", title="Daily data (GB), all cities"))

with tabs[1]:
    sg = by_city(cu[cu.signup_date <= d]).assign(churned=lambda x: x.churn_date <= d)
    cols = st.columns(3)
    for col, key in zip(cols, ["segment", "arpu_band", "city"]):
        r = sg.groupby(key)["churned"].mean().mul(100).reset_index()
        col.plotly_chart(px.bar(r, x=key, y="churned", title=f"Churn % by {key}"))
    chd = sg[sg.churned].assign(month=lambda x: x.churn_date.dt.to_period("M").astype(str))
    a, b = st.columns(2)
    a.plotly_chart(px.bar(chd.groupby("month").size().reset_index(name="churned"), x="month", y="churned",
                          title="Churned per month"))
    b.plotly_chart(px.bar(chd["churn_reason"].value_counts().reset_index(), x="churn_reason", y="count",
                          title="Churn reasons (simulator ground truth)"))
    st.plotly_chart(px.bar(asof["status"].value_counts().reset_index(), x="status", y="count",
                           title="Customer status now"))
    f = UI_DIR / "churn_scores.parquet"
    if f.exists():
        sc = pd.read_parquet(f)
        st.plotly_chart(px.histogram(sc, x="churn_prob", title="Churn model: risk distribution"))
        st.dataframe(sc.sort_values("churn_prob", ascending=False).head(20), hide_index=True)
    else:
        st.info("Churn model not run yet (data/ui/churn_scores.parquet missing).")

with tabs[2]:
    i = mt["ts"].searchsorted(clock, side="right")
    last = mt.iloc[:i].drop_duplicates("tower_id", keep="last")
    down = set(ou[(ou.start_time <= clock) & (ou.end_time.isna() | (ou.end_time > clock))].tower_id)
    tw = towers.merge(last[["tower_id", "health", "signal_dbm", "load"]], on="tower_id", how="left")
    tw["status"] = tw["health"].fillna("HEALTHY")
    tw.loc[tw.tower_id.isin(down), "status"] = "DOWN"
    tw = by_city(tw)
    tw["color"] = tw["status"].map(COL)
    c = st.columns(4)
    for col, s in zip(c, COL):
        col.metric(s, int((tw.status == s).sum()))
    view = pdk.ViewState(latitude=float(tw.lat.mean()), longitude=float(tw.lon.mean()),
                         zoom=4.6 if city == "All" else 9)
    layer = pdk.Layer("ScatterplotLayer", tw, get_position="[lon, lat]", get_fill_color="color",
                      get_radius=6000, radius_min_pixels=6, pickable=True)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_style="light" if basemap else None,
                             tooltip={"text": "{tower_id} {city}\n{status}"}))
    feed = al.merge(ou[["outage_id", "city", "zone", "start_time", "end_time", "severity", "affected_pct",
                        "team_km", "customers_home", "cause"]], left_on="alert_id", right_on="outage_id")
    feed = by_city(feed)
    feed["restored"] = feed["end_time"].notna() & (feed["end_time"] <= clock)
    feed["root_cause"] = feed["cause"].where(feed["status"] == "RESOLVED", "hidden until resolved")
    st.subheader("Alert feed (Module A: rule-based outage detection)")
    st.dataframe(feed[["alert_id", "status", "tower_id", "city", "zone", "severity", "team_id", "team_km",
                       "customers_home", "restored", "root_cause", "created_sim"]].head(50), hide_index=True)
    if len(feed):
        sel = st.selectbox("Alert detail", feed["alert_id"].head(50))
        row = feed[feed.alert_id == sel].iloc[0]
        a, b = st.columns(2)
        cx = ctx[ctx.outage_id == sel]
        a.plotly_chart(px.line(cx, x="ts", y="signal_dbm", markers=True, title="Last 6 hourly readings before outage"))
        nb = towers.loc[towers.tower_id == row.tower_id, "neighbor_tower_ids"].iloc[0]
        nl = tw[tw.tower_id.isin(list(nb))][["tower_id", "status", "load"]] if nb is not None else None
        b.write(f"Customers with home tower {row.tower_id}: **{row.customers_home:,}**. "
                "If it fails, traffic can shift to these neighbour towers:")
        b.dataframe(nl, hide_index=True)
    f = UI_DIR / "tower_risk.parquet"
    if f.exists():
        st.subheader("Module B: early-warning risk")
        st.dataframe(pd.read_parquet(f).head(20), hide_index=True)
    else:
        st.info("Module B early-warning model not run yet (data/ui/tower_risk.parquet missing).")

with tabs[3]:
    s = load("offers_summary")
    pv = s[s.group == "treatment"].pivot_table(index="offer_type", columns="final_action", values="n",
                                              aggfunc="sum", fill_value=0)
    acc, exp = pv.get("ACCEPTED", 0), pv.get("EXPIRED", 0)
    rate = (100 * acc / (acc + exp).clip(lower=1)).reset_index(name="rate")
    st.plotly_chart(px.bar(rate, x="offer_type", y="rate", title="Acceptance rate % (treatment, closed offers)"))
    st.plotly_chart(px.bar(s, x="offer_type", y="n", color="final_action", facet_col="group",
                           title="Offer outcomes: treatment vs control"))
    g = load("group_churn").assign(churn_pct=lambda x: 100 * x.churned / x.customers.clip(lower=1))
    st.dataframe(g, hide_index=True)
    st.caption("Whole simulation period (not tied to the replay clock).")

with tabs[4]:
    st.graphviz_chart('digraph{rankdir=LR; node[shape=box,style=rounded]; Simulator->Kafka->"S3 Bronze"->Silver->Gold->'
                      '"Models / Dashboard"; Silver [style="rounded,filled",fillcolor="#d4edda"]}')
    st.dataframe(load("pipeline"), hide_index=True)
    st.caption("Complaints model: planned (future work).")