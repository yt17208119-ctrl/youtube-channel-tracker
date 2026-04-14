"""
YouTubeチャンネル日次トラッカー
- リサーチシートのA列(URL)からハンドルを抽出
- Socialbladeの埋め込みJSONからデータ取得
- 分析シートの末尾に1行/チャンネル追記
"""
import os
import re
import json
import time
import sys
from datetime import datetime, timezone, timedelta

import requests
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1JmYLo4l1sgNU1IHyD6uFoF4_Vd4p7uyVgW8U4iAKZAI"
RESEARCH_SHEET = "リサーチシート"
ANALYSIS_SHEET = "分析シート"
RESEARCH_RANGE = "A4:C20"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def get_gspread_client():
    info = json.loads(os.environ["GCP_SA_KEY"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def extract_handle(url: str):
    if not url:
        return None
    m = re.search(r"@([\w\-\.]+)", url)
    return m.group(1) if m else None


def fetch_socialblade(handle: str):
    url = f"https://socialblade.com/youtube/handle/{handle}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        r.text,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ not found")
    payload = json.loads(m.group(1))

    queries = payload["props"]["pageProps"]["trpcState"]["json"]["queries"]

    user_data = None
    history = None
    for q in queries:
        key = q.get("queryKey", [[]])[0]
        if isinstance(key, list) and len(key) >= 2:
            if key[0] == "youtube" and key[1] == "user":
                user_data = q["state"]["data"]
            elif key[0] == "youtube" and key[1] == "history":
                history = q["state"]["data"]

    if not user_data or not history:
        raise RuntimeError("user/history data missing")

    today = history[-1]
    prev = history[-2] if len(history) >= 2 else None

    sub_rank = (user_data.get("ranks") or {}).get("subscribers")

    return {
        "name": user_data.get("display_name", handle),
        "subs": int(user_data.get("subscribers") or 0),
        "views": int(user_data.get("views") or 0),
        "videos": int(user_data.get("videos") or 0),
        "d_subs": (today["subscribers"] - prev["subscribers"]) if prev else 0,
        "d_views": (today["views"] - prev["views"]) if prev else 0,
        "d_videos": (today["videos"] - prev["videos"]) if prev else 0,
        "grade": user_data.get("grade") or "TBD",
        "sub_rank": sub_rank if sub_rank is not None else "—",
    }


def main():
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y-%m-%d")

    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)

    research = sh.worksheet(RESEARCH_SHEET)
    analysis = sh.worksheet(ANALYSIS_SHEET)

    rows = research.get_values(RESEARCH_RANGE)
    print(f"Found {len(rows)} candidate rows in リサーチシート")

    new_rows = []
    errors = []
    for i, row in enumerate(rows, start=4):
        if not row or not row[0].strip():
            continue
        url = row[0].strip()
        handle = extract_handle(url)
        if not handle:
            print(f"[skip] row {i}: handle not found in {url}")
            continue
        try:
            print(f"[fetch] {handle}")
            d = fetch_socialblade(handle)
            new_rows.append([
                today_str,
                d["name"],
                d["subs"],
                d["views"],
                d["videos"],
                d["d_subs"],
                d["d_views"],
                d["d_videos"],
                0,
                0,
                d["grade"],
                d["sub_rank"],
            ])
            time.sleep(2)
        except Exception as e:
            msg = f"[error] {handle}: {e}"
            print(msg)
            errors.append(msg)

    if new_rows:
        analysis.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Appended {len(new_rows)} rows to 分析シート ({today_str})")
    else:
        print("No rows to append")

    if errors:
        print("\n--- Errors ---")
        for e in errors:
            print(e)
        if not new_rows:
            sys.exit(1)


if __name__ == "__main__":
    main()
