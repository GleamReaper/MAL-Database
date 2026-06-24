import csv
import json
import os
import time
from typing import Any, Dict, Optional

import requests


BASE = "https://api.jikan.moe/v4"
OUT_CSV = "anime_catalog.csv"
PROGRESS_JSON = "anime_catalog.update_progress.json"

FIELDS = [
    "mal_id",
    "title_default",
    "title_english",
    "title_japanese",
    "type",
    "source",
    "episodes",
    "season",
    "year",
    "aired_from",
    "score",
    "scored_by",
    "members",
    "studios",
    "genres",
    "themes",
]


def join_names(items, key="name") -> str:
    if not items:
        return ""
    return "; ".join(
        x.get(key, "")
        for x in items
        if isinstance(x, dict) and x.get(key)
    )


def load_existing_rows(path: str) -> dict[int, dict]:
    rows = {}

    if not os.path.exists(path):
        return rows

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                mal_id = int(row["mal_id"])
                rows[mal_id] = row
            except Exception:
                pass

    return rows


def write_all_rows(path: str, rows: dict[int, dict]) -> None:
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for mal_id in sorted(rows):
            row = rows[mal_id]

            clean_row = {field: row.get(field, "") for field in FIELDS}
            writer.writerow(clean_row)

    os.replace(temp_path, path)


def save_progress(next_page: int, last_page: int) -> None:
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "next_page": next_page,
                "last_page": last_page,
            },
            f,
            indent=2,
        )


def load_progress() -> Dict[str, int]:
    if not os.path.exists(PROGRESS_JSON):
        return {"next_page": 1, "last_page": 0}

    try:
        with open(PROGRESS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"next_page": 1, "last_page": 0}


def clear_progress() -> None:
    if os.path.exists(PROGRESS_JSON):
        os.remove(PROGRESS_JSON)


def safe_get(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    
    backoff = 2.0

    while True:
        try:
            r = session.get(url, params=params, timeout=(10, 120))
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}. Retrying in {backoff:.1f}s...")
            time.sleep(backoff)
            backoff = min(backoff * 1.6, 60)
            continue

        if r.status_code == 200:
            return r.json()

        if r.status_code in (429, 500, 502, 503, 504):
            retry_after = r.headers.get("Retry-After")

            if retry_after and retry_after.isdigit():
                wait_time = int(retry_after)
            else:
                wait_time = backoff
                backoff = min(backoff * 1.6, 60)

            print(f"HTTP {r.status_code}. Retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)
            continue

        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")


def anime_to_row(a: dict) -> dict:
    """Convert one Jikan anime object into your CSV row format."""
    aired_from = (a.get("aired") or {}).get("from")

    return {
        "mal_id": a.get("mal_id"),
        "title_default": a.get("title"),
        "title_english": a.get("title_english"),
        "title_japanese": a.get("title_japanese"),
        "type": a.get("type"),
        "source": a.get("source"),
        "episodes": a.get("episodes"),
        "season": a.get("season"),
        "year": a.get("year"),
        "aired_from": aired_from,
        "score": a.get("score"),
        "scored_by": a.get("scored_by"),
        "members": a.get("members"),
        "studios": join_names(a.get("studios", [])),
        "genres": join_names(a.get("genres", [])),
        "themes": join_names(a.get("themes", [])),
    }


def main():
    session = requests.Session()

    sfw = 0

    rows = load_existing_rows(OUT_CSV)
    progress = load_progress()

    first = safe_get(session, f"{BASE}/anime", params={"page": 1, "sfw": sfw})
    last_page = int(first["pagination"]["last_visible_page"])

    start_page = int(progress.get("next_page", 1))

    if start_page < 1 or start_page > last_page:
        start_page = 1

    print(f"Updating anime data from page {start_page}/{last_page}")
    print(f"Existing rows loaded: {len(rows)}")

    for page in range(start_page, last_page + 1):
        data = safe_get(session, f"{BASE}/anime", params={"page": page, "sfw": sfw})

        updated_this_page = 0
        added_this_page = 0

        for a in data.get("data", []):
            mal_id = a.get("mal_id")

            if not mal_id:
                continue

            mal_id = int(mal_id)
            is_new = mal_id not in rows

            #existing logic
            rows[mal_id] = anime_to_row(a)

            if is_new:
                added_this_page += 1
            else:
                updated_this_page += 1

        save_progress(page + 1, last_page)

        if page % 25 == 0:
            write_all_rows(OUT_CSV, rows)
            print(
                f"...page {page}/{last_page} | "
                f"updated: {updated_this_page}, added: {added_this_page}, "
                f"total rows: {len(rows)}"
            )

        time.sleep(1.1)

    write_all_rows(OUT_CSV, rows)
    clear_progress()

    print(f"Done. Updated CSV saved to {OUT_CSV}")
    print(f"Total anime rows: {len(rows)}")


if __name__ == "__main__":
    main()