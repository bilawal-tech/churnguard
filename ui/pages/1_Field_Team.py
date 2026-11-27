"""Field team view: acknowledge and resolve alerts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from ui.common import UI_DIR, db, read_alerts, set_status

st.set_page_config(page_title="Field Team", layout="wide")
if not (UI_DIR / "meta.json").exists():
    st.error("No UI data yet. Run: python -m ui.build_ui_data")
    st.stop()
meta = json.loads((UI_DIR / "meta.json").read_text(encoding="utf-8"))
clock = pd.Timestamp(meta["sim_start"]) + pd.Timedelta(hours=st.session_state.get("t", 0))
teams = pd.read_parquet(UI_DIR / "teams.parquet")
ou = pd.read_parquet(UI_DIR / "outages.parquet")
ctx = pd.read_parquet(UI_DIR / "alert_context.parquet")
conn = db()

st.title("Field Team")
team = st.selectbox("Team", teams["team_id"])
st.caption(f"Simulated now: {clock:%a %d %b %H:%M} PKT (clock is controlled from the main dashboard)")
st.button("Refresh")
mine = read_alerts(conn)
mine = mine[mine.team_id == team].merge(
    ou[["outage_id", "city", "zone", "severity", "customers_home", "end_time", "cause"]],
    left_on="alert_id", right_on="outage_id")
done = mine.dropna(subset=["ack_sim"])
avg = (pd.to_datetime(done.ack_sim) - pd.to_datetime(done.created_sim)).dt.total_seconds().mean() / 60
c = st.columns(3)
c[0].metric("Open", int((mine.status == "OPEN").sum()))
c[1].metric("Acknowledged", int((mine.status == "ACKNOWLEDGED").sum()))
c[2].metric("Avg acknowledge time (sim min)", "-" if pd.isna(avg) else f"{avg:.0f}")

mine["rank"] = mine["status"].map({"OPEN": 0, "ACKNOWLEDGED": 1, "RESOLVED": 2})
for r in mine.sort_values(["rank", "created_sim"], ascending=[True, False]).head(20).itertuples():
    with st.container(border=True):
        a, b = st.columns([3, 2])
        a.markdown(f"**{r.tower_id}** ({r.city}, {r.zone}) | severity {r.severity} | status **{r.status}**")
        a.write(f"Started {r.created_sim} | customers on this tower: {r.customers_home:,}")
        if pd.notna(r.end_time) and r.end_time <= clock:
            a.success("Tower restored")
        if r.status == "RESOLVED":
            a.write(f"Root cause (ground truth): {r.cause} | note: {r.note or '-'}")
        b.dataframe(ctx[ctx.outage_id == r.alert_id][["ts", "health", "signal_dbm", "load"]].tail(6),
                    hide_index=True)
        if r.status == "OPEN" and b.button("Acknowledge", key=f"ack_{r.alert_id}"):
            set_status(conn, r.alert_id, "ACKNOWLEDGED", str(clock))
            st.rerun()
        if r.status != "RESOLVED":
            note = b.text_input("Note", key=f"note_{r.alert_id}")
            if b.button("Mark resolved", key=f"res_{r.alert_id}"):
                set_status(conn, r.alert_id, "RESOLVED", str(clock), note)
                st.rerun()