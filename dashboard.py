"""Yale Track & Field — TFRRS results dashboard.

Run with:  streamlit run dashboard.py
"""
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from marks import is_wind_aided, meet_level, WIND_LEGAL_LIMIT

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
YALE_BLUE = "#00356B"
LEVEL_COLOR = {
    "NCAA": "#B08D00", "Ivy Heps": YALE_BLUE, "ECAC/IC4A": "#2A7DE1",
    "Regional": "#5B8C5A", "Championship": "#7A5CA8", "": "#9AA7B2",
}

st.set_page_config(page_title="Yale T&F Dashboard", page_icon="🐶", layout="wide")


@st.cache_data(ttl="30m")
def load():
    res = pd.read_csv(os.path.join(DATA_DIR, "results.csv"), parse_dates=["date"])
    prs = pd.read_csv(os.path.join(DATA_DIR, "prs.csv"))
    for df in (res, prs):
        df["team"] = df["gender"].map({"M": "Men", "F": "Women"}).fillna(df["gender"])

    res["wind_aided"] = [is_wind_aided(e, w) for e, w in zip(res["event"], res["wind"])]
    res["level"] = res["meet"].map(meet_level)
    res["is_champs"] = res["level"] != ""
    res = compute_progression_prs(res)
    return res, prs


def compute_progression_prs(df):
    """Flag rows that set a new wind-legal personal best at the time."""
    df = df.sort_values("date").copy()
    df["is_pr"] = False
    for _, g in df.groupby(["athlete_id", "event"], sort=False):
        higher = bool(g["higher_better"].iloc[0])
        best = None
        for idx in g.index:
            v = df.at[idx, "value"]
            if pd.isna(v) or df.at[idx, "wind_aided"]:
                continue
            if best is None or (v > best if higher else v < best):
                best = v
                df.at[idx, "is_pr"] = True
    return df


def fmt_table(df):
    """Add emoji flags for championship meets and PR-setting marks."""
    out = df.copy()
    if "level" in out:
        out["🏆"] = out["level"].map(lambda l: "🏆" if l else "")
    if "is_pr" in out:
        out["⭐"] = out["is_pr"].map(lambda x: "⭐" if x else "")
    return out


if not os.path.exists(os.path.join(DATA_DIR, "results.csv")):
    st.error("No data found. Run `python scrape.py` first.")
    st.stop()

res, prs = load()

# ---- Header ----
st.markdown(
    f"""
    <div style="background:linear-gradient(90deg,{YALE_BLUE},#1763B0);
                padding:18px 24px;border-radius:12px;margin-bottom:8px;">
      <h1 style="color:white;margin:0;font-size:30px;">🐶 Yale Track &amp; Field</h1>
      <p style="color:#cfe0f5;margin:4px 0 0;font-size:15px;">
        Performance dashboard · {res['athlete'].nunique()} athletes ·
        {len(res):,} results · source: TFRRS</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---- Sidebar ----
_mtime = os.path.getmtime(os.path.join(DATA_DIR, "results.csv"))
st.sidebar.caption(
    f"Data updated: {datetime.fromtimestamp(_mtime):%b %d, %Y %I:%M %p}  ·  "
    "auto-refreshes weekly (Mon 7am)")
if st.sidebar.button("🔄 Reload data now", width="stretch"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.header("Filters")
genders = st.sidebar.multiselect("Team", ["Men", "Women"], default=["Men", "Women"])
seasons = st.sidebar.multiselect(
    "Season", sorted(res["season"].dropna().unique()),
    default=sorted(res["season"].dropna().unique()))
years = sorted(int(y) for y in res["year"].dropna().unique())
yr_range = st.sidebar.select_slider(
    "Year range", options=years,
    value=(years[0], years[-1])) if len(years) > 1 else (years[0], years[0])

st.sidebar.divider()
wind_legal_only = st.sidebar.toggle(
    "Wind-legal marks only", value=False,
    help=f"Hide wind-aided marks (> +{WIND_LEGAL_LIMIT} m/s) in 100/200/hurdles/LJ/TJ.")
champs_only = st.sidebar.toggle(
    "Championship meets only", value=False,
    help="Show only NCAA / Ivy Heps / ECAC-IC4A / Regional results.")

f = res[
    res["team"].isin(genders)
    & res["season"].isin(seasons)
    & res["year"].between(yr_range[0], yr_range[1])
].copy()
if wind_legal_only:
    f = f[~f["wind_aided"]]
if champs_only:
    f = f[f["is_champs"]]

tab_lead, tab_athlete, tab_event, tab_team = st.tabs(
    ["🏆 PR Leaderboards", "📈 Athlete Progression",
     "🎯 Event Explorer", "📊 Team Overview"])

# ---- PR Leaderboards ----
with tab_lead:
    st.subheader("Personal-best leaderboards by event")
    st.caption("Official TFRRS College Bests (wind-legal).")
    p = prs[prs["team"].isin(genders)].dropna(subset=["value"]).copy()
    events = sorted(p["event"].unique())
    if not events:
        st.info("No PR data for this selection.")
    else:
        ev = st.selectbox("Event", events, key="lead_ev")
        sub = p[p["event"] == ev].copy()
        higher = bool(sub["higher_better"].iloc[0])
        sub = sub.sort_values("value", ascending=not higher).reset_index(drop=True)
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        sub["Rank"] = [medals.get(i, str(i + 1)) for i in range(len(sub))]
        st.dataframe(
            sub[["Rank", "athlete", "team", "mark"]].rename(
                columns={"athlete": "Athlete", "team": "Team", "mark": "PR"}),
            width="stretch", hide_index=True)

# ---- Athlete Progression ----
with tab_athlete:
    st.subheader("Track an athlete's progression over time")
    athletes = sorted(f["athlete"].unique())
    if not athletes:
        st.info("No athletes match the current filters.")
    else:
        ath = st.selectbox("Athlete", athletes, key="ath_sel")
        a = f[f["athlete"] == ath].copy()
        a_dated = a.dropna(subset=["value", "date"])

        # summary metrics
        prs_in_window = int(a["is_pr"].sum())
        champ_results = int(a["is_champs"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("PRs set (in window)", prs_in_window)
        c2.metric("Championship results", champ_results)
        c3.metric("Total results", len(a))

        a_events = sorted(a_dated["event"].unique())
        pick = st.multiselect("Events", a_events,
                              default=a_events[:3] if a_events else [])
        plot = a_dated[a_dated["event"].isin(pick)].sort_values("date")
        if plot.empty:
            st.info("Pick at least one event with dated results.")
        else:
            fig = px.line(plot, x="date", y="value", color="event",
                          markers=True, hover_data=["mark", "meet", "place", "wind"])
            # star markers for PR-setting performances
            pr_pts = plot[plot["is_pr"]]
            if not pr_pts.empty:
                fig.add_trace(go.Scatter(
                    x=pr_pts["date"], y=pr_pts["value"], mode="markers",
                    marker=dict(symbol="star", size=15, color="#F2C200",
                                line=dict(color=YALE_BLUE, width=1)),
                    name="PR", hovertext=pr_pts["mark"], hoverinfo="text+x"))
            fig.update_layout(yaxis_title="Mark (sec / meters / pts)",
                              xaxis_title="Date", legend_title="", height=460)
            if (plot["higher_better"] == False).all():  # noqa: E712
                fig.update_yaxes(autorange="reversed")
                st.caption("⭐ = new PR · y-axis reversed so faster (better) is higher.")
            else:
                st.caption("⭐ = new PR.")
            st.plotly_chart(fig, width="stretch")

        # PR cards
        prcard = prs[prs["athlete"] == ath].dropna(subset=["value"])
        if not prcard.empty:
            st.markdown("**Personal Bests**")
            cols = st.columns(min(6, len(prcard)))
            for i, (_, r) in enumerate(prcard.iterrows()):
                cols[i % len(cols)].metric(r["event"], r["mark"])

        st.markdown("**All results**  ·  ⭐ new PR  ·  🏆 championship meet")
        show = fmt_table(a.sort_values("date", ascending=False))
        st.dataframe(
            show[["date", "event", "mark", "wind", "⭐", "🏆", "level",
                  "place", "meet", "season"]].rename(
                columns={"date": "Date", "event": "Event", "mark": "Mark",
                         "wind": "Wind", "level": "Level", "place": "Place",
                         "meet": "Meet", "season": "Season"}),
            width="stretch", hide_index=True)

# ---- Event Explorer ----
with tab_event:
    st.subheader("Season bests across the roster, by event")
    fe = f.dropna(subset=["value"])
    events = sorted(fe["event"].unique())
    if not events:
        st.info("No results match the current filters.")
    else:
        ev = st.selectbox("Event", events, key="exp_ev")
        sub = fe[fe["event"] == ev].copy()
        higher = bool(sub["higher_better"].iloc[0])
        idx = (sub.groupby("athlete")["value"].idxmax() if higher
               else sub.groupby("athlete")["value"].idxmin())
        best = sub.loc[idx].sort_values("value", ascending=not higher)
        best["label"] = best.apply(
            lambda r: r["mark"] + (" 🏆" if r["is_champs"] else "")
            + (" 💨" if r["wind_aided"] else ""), axis=1)
        fig = px.bar(best, x="value", y="athlete", orientation="h",
                     color="team", hover_data=["mark", "meet", "date", "wind", "level"],
                     text="label",
                     color_discrete_map={"Men": YALE_BLUE, "Women": "#C9102F"})
        fig.update_layout(height=max(350, 28 * len(best)),
                          yaxis={"categoryorder": "total ascending" if higher
                                 else "total descending"},
                          xaxis_title="Mark", yaxis_title="", legend_title="")
        st.plotly_chart(fig, width="stretch")
        st.caption("🏆 set at a championship meet · 💨 wind-aided")

# ---- Team Overview ----
with tab_team:
    st.subheader("Team-wide activity")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Athletes", f["athlete"].nunique())
    c2.metric("Results", f"{len(f):,}")
    c3.metric("PRs set", int(f["is_pr"].sum()))
    c4.metric("Champ. results", int(f["is_champs"].sum()))
    c5.metric("Meets", f["meet"].nunique())

    colA, colB = st.columns(2)
    with colA:
        by_year = f.dropna(subset=["year"]).groupby(
            ["year", "season"]).size().reset_index(name="results")
        if not by_year.empty:
            fig = px.bar(by_year, x="year", y="results", color="season",
                         barmode="group", title="Results logged per season")
            st.plotly_chart(fig, width="stretch")
    with colB:
        lvl = f[f["is_champs"]].groupby("level").size().reset_index(name="results")
        if not lvl.empty:
            fig = px.pie(lvl, names="level", values="results",
                         title="Championship results by meet tier",
                         color="level", color_discrete_map=LEVEL_COLOR)
            st.plotly_chart(fig, width="stretch")

    st.markdown("**PR leaders in window** (most personal bests set)")
    pr_leaders = (f[f["is_pr"]].groupby(["athlete", "team"]).size()
                  .reset_index(name="PRs").sort_values("PRs", ascending=False)
                  .head(15))
    st.dataframe(pr_leaders.rename(columns={"athlete": "Athlete", "team": "Team"}),
                 width="stretch", hide_index=True)
