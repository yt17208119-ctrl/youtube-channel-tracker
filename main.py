"""
YouTubeチャンネル日次トラッカー
- リサーチシートのA列(URL)からハンドルを抽出
- YouTube Data API v3 でチャンネル統計を取得
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


def fetch_youtube_api(handle: str, api_key: str):
    """YouTube Data API v3 でチャンネル情報を取得する"""
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "snippet,statistics",
        "forHandle": handle,
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel not found for handle: @{handle}")
    item = items[0]
    stats = item["statistics"]
    return {
        "name": item["snippet"]["title"],
        "subs": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
    }


def get_last_row(analysis, handle_name: str):
    """分析シートから前回のデータを取得してデルタ計算に使う"""
    try:
        all_rows = analysis.get_all_values()
        for row in reversed(all_rows[1:]):
            if len(row) >= 5 and row[1] == handle_name:
                return {
                    "subs": int(str(row[2]).replace(",", "") or 0),
                    "views": int(str(row[3]).replace(",", "") or 0),
                    "videos": int(str(row[4]).replace(",", "") or 0),
                }
    except Exception:
        pass
    return None


def main():
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y-%m-%d")

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        print("[fatal] YOUTUBE_API_KEY is not set")
        sys.exit(1)

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
            print(f"[fetch] @{handle}")
            d = fetch_youtube_api(handle, api_key)

            prev = get_last_row(analysis, d["name"])
            d_subs = d["subs"] - prev["subs"] if prev else 0
            d_views = d["views"] - prev["views"] if prev else 0
            d_videos = d["videos"] - prev["videos"] if prev else 0

            new_rows.append([
                today_str,
                d["name"],
                d["subs"],
                d["views"],
                d["videos"],
                d_subs,
                d_views,
                d_videos,
                0,
                0,
                "—",
                "—",
            ])
            time.sleep(1)
        except Exception as e:
            msg = f"[error] @{handle}: {e}"
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
