import os
import json
import time
from typing import List, Dict, Any

import requests
import streamlit as st
from dotenv import load_dotenv
from googleapiclient.discovery import build

# ---------- Config ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ---------- Helpers ----------

def google_news_snippets(query: str, num: int = 3) -> List[Dict[str, str]]:
    if not (GOOGLE_CSE_ID and GOOGLE_API_KEY) or not query:
        return []
    try:
        service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
        res = service.cse().list(q=query + " NFL news injury status", cx=GOOGLE_CSE_ID, num=num).execute()
        items = res.get("items", [])
        out = []
        for it in items:
            out.append({
                "title": it.get("title", ""),
                "link": it.get("link", ""),
                "snippet": it.get("snippet", "")
            })
        return out
    except Exception:
        return []

def openai_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    if not OPENAI_API_KEY:
        return "(AI disabled — add OPENAI_API_KEY to enable analysis.)"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"(AI error: {e})"

def parse_pasted_list(txt: str) -> List[str]:
    if not txt:
        return []
    parts = [p.strip() for chunk in txt.splitlines() for p in chunk.replace(";", ",").split(",")]
    return [p for p in parts if p]

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Fantasy Football Assistant", page_icon="🏈")
st.title("🏈 Fantasy Football Assistant — Starts/Sits, Trades & Waivers")
st.caption("Uses AI + Google search snippets to add quick context. Paste your roster, bench, FA pool.")

with st.sidebar:
    st.header("Settings")
    use_ai = st.toggle("Use AI analysis (OpenAI)", value=bool(OPENAI_API_KEY))
    use_google = st.toggle("Pull Google news snippets", value=bool(GOOGLE_CSE_ID and GOOGLE_API_KEY))
    scoring = st.selectbox("Scoring", ["Half-PPR", "PPR", "Standard"], index=0)
    risk_tolerance = st.slider("Risk tolerance (boom vs safe)", 0, 10, 5)
    week = st.number_input("Week (for context only)", min_value=1, max_value=18, value=1)
    st.divider()
    st.subheader("Optional: Sleeper Import")
    sleeper_league_id = st.text_input("Sleeper league_id (optional)")

st.subheader("Your Team")
col1, col2 = st.columns(2)
with col1:
    starters_txt = st.text_area(
        "Starters (one per line or comma-separated)",
        placeholder="QB Player\nRB Player\nRB Player\nWR Player\nWR Player\nTE Player\nFLEX Player\n…",
        height=180,
    )
with col2:
    bench_txt = st.text_area(
        "Bench players",
        placeholder="List bench players here…",
        height=180,
    )

st.subheader("League Pool & Trade Targets")
col3, col4 = st.columns(2)
with col3:
    fa_txt = st.text_area(
        "Free agents / waiver pool (top ~30 names)",
        placeholder="Type or paste: Player A, Player B, Player C…",
        height=140,
    )
with col4:
    trade_targets_txt = st.text_area(
        "Trade targets (players on other teams you’re eyeing)",
        placeholder="Optional list of targets…",
        height=140,
    )

notes = st.text_area("Any league context? (e.g., injuries, opponent matchup, byes, roster rules)", height=100)

if st.button("🔎 Analyze my week"):
    starters = parse_pasted_list(starters_txt)
    bench = parse_pasted_list(bench_txt)
    free_agents = parse_pasted_list(fa_txt)
    trade_targets = parse_pasted_list(trade_targets_txt)

    if not starters:
        st.error("Add at least a few starters to analyze.")
        st.stop()

    snippets = {}
    if use_google:
        names_for_news = starters + bench + trade_targets + free_agents[:10]
        names_for_news = [n for i, n in enumerate(names_for_news) if n and i < 25]
        prog = st.progress(0.0, text="Pulling news…")
        for i, name in enumerate(names_for_news, start=1):
            snippets[name] = google_news_snippets(name, num=2)
            prog.progress(i / len(names_for_news), text=f"News: {name}")
        prog.empty()

    system_prompt = (
        "You are a sharp fantasy football analyst. Give clear, concise bullets. "
        "Weigh recent usage, health, floor/ceiling, matchup, and roster construction. "
        "Tailor advice to the scoring format and risk tolerance."
    )

    user_payload = {
        "scoring": scoring,
        "risk_tolerance": risk_tolerance,
        "week": int(week),
        "starters": starters,
        "bench": bench,
        "free_agents": free_agents,
        "trade_targets": trade_targets,
        "notes": notes,
        "google_snippets": snippets,
    }

    user_prompt = (
        "Analyze my roster for this week.\n"
        "Tasks:\n"
        "1) START/SIT: Suggest swaps to maximize expected points and balance risk.\n"
        "2) WAIVERS: Rank top 5-10 adds from my FA list with quick reasoning and suggested FAAB/priority.\n"
        "3) TRADES: Offer 2-4 realistic trade ideas (give + get) with reasoning.\n"
        "4) WATCHLIST: 5 stash names from FA for upside.\n"
        "Keep it under ~300 words per section.\n\n"
        f"INPUT JSON:\n{json.dumps(user_payload, indent=2)}\n"
    )

    if use_ai:
        with st.status("Thinking (AI)…", expanded=False):
            analysis = openai_complete(system_prompt, user_prompt)
    else:
        analysis = "(AI disabled) Use the sections below as a template for manual notes.\n\n" \
                   "• START/SIT: …\n• WAIVERS: …\n• TRADES: …\n• WATCHLIST: …"

    st.divider()
    st.subheader("Results")
    st.write(analysis)

    export = {
        "timestamp": int(time.time()),
        "settings": {"scoring": scoring, "risk_tolerance": risk_tolerance, "week": int(week)},
        "inputs": user_payload,
        "analysis": analysis,
    }
    st.download_button(
        "📥 Download JSON report",
        data=json.dumps(export, indent=2).encode("utf-8"),
        file_name="fantasy_assistant_report.json",
        mime="application/json",
    )

st.divider()
st.markdown(
    "**Tips**\n\n"
    "• Keep your FA list short and relevant (top ~30).\n\n"
    "• If trade ideas are unrealistic in your league, add context in the notes (e.g., managers’ tendencies).\n\n"
    "• Want auto-import from Sleeper? Paste your league_id in the sidebar and use pulled data as a reference while you build lists.\n\n"
    "• You can duplicate this app and tweak the prompt for your league’s vibes."
)