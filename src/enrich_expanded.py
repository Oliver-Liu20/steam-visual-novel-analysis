#!/usr/bin/env python3
"""Build the expanded 2020-2025 Steam visual-novel dataset.

Universe:
  1. The original VNDB x Steam Visual Novel tag intersection.
  2. VNDB-only Steam AppIDs whose VN relation type contains ``complete``.

The job is resumable. VNDB release details and Steam review summaries are
cached per batch/AppID, and existing Gamalytic caches are reused.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from collect import (
    GAMALYTIC_CACHE_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    VNDB_URL,
    chunks,
    fetch_gamalytic,
    request_bytes,
    save_json,
    write_csv,
)


EXPANDED_DIR = PROCESSED_DIR / "expanded"
VNDB_DETAIL_CACHE_DIR = RAW_DIR / "vndb_release_details"
STEAM_REVIEW_CACHE_DIR = RAW_DIR / "steam_reviews"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
AS_OF_DATE = date(2026, 8, 8)


def ensure_dirs() -> None:
    for path in (EXPANDED_DIR, VNDB_DETAIL_CACHE_DIR, STEAM_REVIEW_CACHE_DIR, GAMALYTIC_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def has_token(value: str | None, token: str) -> bool:
    return token in {part.strip() for part in (value or "").split(";") if part.strip()}


def build_universe() -> tuple[list[dict[str, str]], dict[str, int]]:
    original = read_csv(PROCESSED_DIR / "final_visual_novels_2020_2025.csv")
    vndb_only = read_csv(PROCESSED_DIR / "difference_vndb_only.csv")
    incremental = [row for row in vndb_only if has_token(row.get("vndb_rtypes"), "complete")]

    merged: dict[str, dict[str, str]] = {}
    for row in original:
        item = dict(row)
        item["expanded_source"] = "ORIGINAL_INTERSECTION"
        merged[item["steam_appid"]] = item
    for row in incremental:
        item = dict(row)
        item["expanded_source"] = "VNDB_ONLY_COMPLETE_INCREMENT"
        merged[item["steam_appid"]] = item

    rows = sorted(
        merged.values(),
        key=lambda row: (row.get("steam_release_date") or "9999", row.get("name") or "", int(row["steam_appid"])),
    )
    meta = {
        "original_intersection": len(original),
        "vndb_only_total": len(vndb_only),
        "vndb_only_complete_increment": len(incremental),
        "expanded_total": len(rows),
    }
    return rows, meta


def release_ids_for(rows: list[dict[str, str]]) -> list[str]:
    ids: set[str] = set()
    for row in rows:
        for value in (row.get("vndb_release_ids") or "").split(";"):
            value = value.strip()
            if value.startswith("r") and value[1:].isdigit():
                ids.add(value)
    return sorted(ids, key=lambda value: int(value[1:]))


def fetch_vndb_release_details(
    release_ids: list[str], *, refresh: bool = False
) -> dict[str, dict[str, Any]]:
    print(f"[1/4] VNDB age details for {len(release_ids):,} release records", flush=True)
    output: dict[str, dict[str, Any]] = {}
    batches = list(chunks(release_ids, 100))
    for index, batch in enumerate(batches, start=1):
        digest = hashlib.sha1(",".join(batch).encode("ascii")).hexdigest()[:12]
        cache_path = VNDB_DETAIL_CACHE_DIR / f"batch_{index:04d}_{digest}.json"
        if cache_path.exists() and not refresh:
            response = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            filters: list[Any] = ["or"]
            filters.extend([["id", "=", rid] for rid in batch])
            payload = {
                "filters": filters,
                "fields": (
                    "title,released,minage,has_ero,uncensored,freeware,official,patch,"
                    "extlinks{name,id,url},vns{id,title,rtype}"
                ),
                "sort": "id",
                "results": 100,
            }
            result = request_bytes(VNDB_URL, method="POST", payload=payload)
            response = json.loads(result.body.decode("utf-8"))
            save_json(cache_path, response)
            time.sleep(0.6)
        for item in response.get("results") or []:
            output[str(item["id"])] = item
        if index % 10 == 0 or index == len(batches):
            print(f"  VNDB detail batches {index}/{len(batches)}; records={len(output):,}", flush=True)
    return output


def steam_review_params() -> dict[str, Any]:
    return {
        "json": 1,
        "filter": "all",
        "language": "all",
        "review_type": "all",
        "purchase_type": "all",
        "num_per_page": 1,
        "filter_offtopic_activity": 0,
    }


def fetch_one_review(appid: str, refresh: bool) -> tuple[str, dict[str, Any]]:
    cache_path = STEAM_REVIEW_CACHE_DIR / f"{appid}.json"
    if cache_path.exists() and not refresh:
        return appid, json.loads(cache_path.read_text(encoding="utf-8"))
    url = f"{STEAM_REVIEWS_URL.format(appid=appid)}?{urlencode(steam_review_params())}"
    result = request_bytes(url, timeout=35, retries=7)
    response = json.loads(result.body.decode("utf-8"))
    response["_fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    response["_request_parameters"] = steam_review_params()
    save_json(cache_path, response)
    time.sleep(0.10)
    return appid, response


def fetch_steam_reviews(
    appids: list[str], *, refresh: bool = False, workers: int = 6
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    print(f"[2/4] Steam review summaries for {len(appids):,} AppIDs", flush=True)
    output: dict[str, dict[str, Any]] = {}
    cached = [] if refresh else [appid for appid in appids if (STEAM_REVIEW_CACHE_DIR / f"{appid}.json").exists()]
    for appid in cached:
        output[appid] = json.loads((STEAM_REVIEW_CACHE_DIR / f"{appid}.json").read_text(encoding="utf-8"))
    pending = [appid for appid in appids if appid not in output]
    print(f"  Reused {len(output):,} review caches; pending {len(pending):,}", flush=True)
    errors: dict[str, str] = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one_review, appid, refresh): appid for appid in pending}
        for future in as_completed(futures):
            appid = futures[future]
            try:
                result_appid, response = future.result()
                output[result_appid] = response
            except Exception as exc:  # keep the long job resumable even if a few apps fail
                errors[appid] = str(exc)
            completed += 1
            if completed % 100 == 0 or completed == len(pending):
                print(
                    f"  Steam reviews {completed}/{len(pending)} new; "
                    f"total={len(output):,}; errors={len(errors):,}",
                    flush=True,
                )
    return output, {
        "review_cache_reused": len(cached),
        "review_network_attempts": len(pending),
        "review_errors": errors,
        "review_parameters": steam_review_params(),
        "review_fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def parse_release_ids(row: dict[str, Any]) -> list[str]:
    return [value for value in str(row.get("vndb_release_ids") or "").split(";") if value]


def sexual_content_fields(row: dict[str, Any], releases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    details = [releases[rid] for rid in parse_release_ids(row) if rid in releases]
    minages = sorted({int(item["minage"]) for item in details if item.get("minage") is not None})
    has_ero_values = {bool(item["has_ero"]) for item in details if item.get("has_ero") is not None}
    uncensored_values = {bool(item["uncensored"]) for item in details if item.get("uncensored") is not None}
    if True in has_ero_values:
        status = "非全年龄"
        is_all_ages: bool | None = False
    elif False in has_ero_values:
        status = "全年龄"
        is_all_ages = True
    else:
        status = "未知"
        is_all_ages = None

    basis_parts = []
    if minages:
        basis_parts.append("VNDB minage=" + "/".join(map(str, minages)))
    if has_ero_values:
        basis_parts.append("has_ero=" + "/".join(str(value).lower() for value in sorted(has_ero_values)))
    if uncensored_values:
        basis_parts.append("uncensored=" + "/".join(str(value).lower() for value in sorted(uncensored_values)))
    return {
        "vndb_minage_values": ";".join(map(str, minages)),
        "vndb_has_ero_values": ";".join(str(value).lower() for value in sorted(has_ero_values)),
        "vndb_uncensored_values": ";".join(str(value).lower() for value in sorted(uncensored_values)),
        "sexual_content_conflict": len(has_ero_values) > 1,
        "all_ages_status": status,
        "is_all_ages": is_all_ages,
        "has_ero_any": True in has_ero_values,
        "sexual_content_basis": "; ".join(basis_parts) if basis_parts else "VNDB has_ero unavailable",
    }


def review_fields(response: dict[str, Any] | None) -> dict[str, Any]:
    if not response:
        return {
            "steam_review_count": None,
            "steam_review_positive": None,
            "steam_review_negative": None,
            "steam_review_positive_rate": None,
            "steam_review_score_desc": "",
            "steam_review_status": "REQUEST_ERROR",
        }
    summary = response.get("query_summary") or {}
    if response.get("success") != 1 or not summary:
        return {
            "steam_review_count": None,
            "steam_review_positive": None,
            "steam_review_negative": None,
            "steam_review_positive_rate": None,
            "steam_review_score_desc": "",
            "steam_review_status": "UNAVAILABLE",
        }
    total = int(summary.get("total_reviews") or 0)
    positive = int(summary.get("total_positive") or 0)
    negative = int(summary.get("total_negative") or 0)
    return {
        "steam_review_count": total,
        "steam_review_positive": positive,
        "steam_review_negative": negative,
        "steam_review_positive_rate": positive / total if total else None,
        "steam_review_score_desc": summary.get("review_score_desc") or "",
        "steam_review_status": "FOUND",
    }


def choose_review_threshold(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"threshold": 0, "low_share": 1.0, "target_low_share": 0.8}
    counter = Counter(values)
    total = len(values)
    running = 0
    candidates = []
    for threshold in sorted(counter):
        running += counter[threshold]
        share = running / total
        candidates.append((abs(share - 0.8), threshold, share))
    _, threshold, share = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "threshold": threshold,
        "low_share": share,
        "target_low_share": 0.8,
        "known_review_count_games": total,
        "p80_linear": statistics.quantiles(values, n=100, method="inclusive")[79] if len(values) > 1 else values[0],
    }


def months_since_release(value: str) -> float | None:
    try:
        released = datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return round(max(0, (AS_OF_DATE - released).days / 30.4375), 2)


def normalize_number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_final_rows(
    universe: list[dict[str, str]],
    releases: dict[str, dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
    gamalytic: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in universe:
        appid = source["steam_appid"]
        game = gamalytic.get(appid, {})
        copies_sold = normalize_number(game.get("copies_sold"))
        release_date = source.get("steam_release_date") or ""
        name = source.get("steam_title") or game.get("gamalytic_name") or source.get("name") or source.get("vndb_titles") or ""
        row: dict[str, Any] = {
            "steam_appid": appid,
            "name": name,
            "steam_release_date": release_date,
            "release_month": release_date[:7] if release_date else "",
            "release_year": int(release_date[:4]) if release_date else None,
            "months_since_release": months_since_release(release_date),
            "store_url": source.get("store_url") or f"https://store.steampowered.com/app/{appid}/",
            "vndb_url": source.get("vndb_url") or "",
            "copies_sold": copies_sold,
            "gamalytic_status": "FOUND" if copies_sold is not None else "NOT_FOUND",
            "expanded_source": source.get("expanded_source"),
            "in_steam_visual_novel_tag": str(source.get("in_steam_visual_novel_tag")).lower() == "true",
            "vndb_ids": source.get("vndb_ids") or "",
            "vndb_release_ids": source.get("vndb_release_ids") or "",
            "vndb_rtypes": source.get("vndb_rtypes") or "",
            "vndb_official": str(source.get("vndb_official")).lower() == "true",
            "price_text": source.get("price_text") or "",
            "is_free": str(source.get("is_free")).lower() == "true",
            "copies_sold_fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        row.update(review_fields(reviews.get(appid)))
        row.update(sexual_content_fields(source, releases))
        rows.append(row)

    threshold_info = choose_review_threshold(
        [int(row["steam_review_count"]) for row in rows if row["steam_review_count"] is not None]
    )
    threshold = int(threshold_info["threshold"])
    for row in rows:
        count = row["steam_review_count"]
        if count is None:
            row["review_heat_group"] = "评论数未知"
        elif count > threshold:
            row["review_heat_group"] = f"高热度（>{threshold}）"
        else:
            row["review_heat_group"] = f"低热度（≤{threshold}）"

    rows.sort(key=lambda row: (row["steam_release_date"], row["name"], int(row["steam_appid"])))
    return rows, threshold_info


def aggregate_periods(rows: list[dict[str, Any]], period_field: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "game_count": 0,
        "high_heat_count": 0,
        "low_heat_count": 0,
        "unknown_review_count": 0,
        "all_ages_count": 0,
        "not_all_ages_count": 0,
        "unknown_age_count": 0,
        "copies_sold_sum": 0,
        "copies_sold_known": 0,
    })
    for row in rows:
        period = str(row.get(period_field) or "")
        bucket = grouped[period]
        bucket["game_count"] += 1
        heat = row["review_heat_group"]
        if heat.startswith("高热度"):
            bucket["high_heat_count"] += 1
        elif heat.startswith("低热度"):
            bucket["low_heat_count"] += 1
        else:
            bucket["unknown_review_count"] += 1
        age = row["all_ages_status"]
        if age == "全年龄":
            bucket["all_ages_count"] += 1
        elif age == "非全年龄":
            bucket["not_all_ages_count"] += 1
        else:
            bucket["unknown_age_count"] += 1
        if row["copies_sold"] is not None:
            bucket["copies_sold_sum"] += int(row["copies_sold"])
            bucket["copies_sold_known"] += 1
    return [{period_field: key, **grouped[key]} for key in sorted(grouped)]


def emit(
    rows: list[dict[str, Any]],
    universe_meta: dict[str, Any],
    threshold_info: dict[str, Any],
    review_meta: dict[str, Any],
    gamalytic_meta: dict[str, Any],
) -> None:
    fields = [
        "steam_appid", "name", "steam_release_date", "release_month", "release_year",
        "months_since_release", "store_url", "vndb_url", "copies_sold", "gamalytic_status",
        "steam_review_count", "steam_review_positive", "steam_review_negative",
        "steam_review_positive_rate", "steam_review_score_desc", "steam_review_status",
        "review_heat_group", "all_ages_status", "is_all_ages", "has_ero_any",
        "sexual_content_basis", "vndb_minage_values", "vndb_has_ero_values",
        "vndb_uncensored_values", "sexual_content_conflict",
        "expanded_source", "in_steam_visual_novel_tag", "vndb_ids", "vndb_release_ids",
        "vndb_rtypes", "vndb_official", "price_text", "is_free", "copies_sold_fetched_at",
    ]
    write_csv(EXPANDED_DIR / "visual_novels_master_2020_2025.csv", rows, fields)
    write_csv(
        EXPANDED_DIR / "monthly_expanded_summary.csv",
        aggregate_periods(rows, "release_month"),
        ["release_month", "game_count", "high_heat_count", "low_heat_count", "unknown_review_count",
         "all_ages_count", "not_all_ages_count", "unknown_age_count", "copies_sold_sum", "copies_sold_known"],
    )
    write_csv(
        EXPANDED_DIR / "annual_expanded_summary.csv",
        aggregate_periods(rows, "release_year"),
        ["release_year", "game_count", "high_heat_count", "low_heat_count", "unknown_review_count",
         "all_ages_count", "not_all_ages_count", "unknown_age_count", "copies_sold_sum", "copies_sold_known"],
    )

    summary = {
        **universe_meta,
        **threshold_info,
        "copies_sold_found": sum(row["copies_sold"] is not None for row in rows),
        "copies_sold_missing": sum(row["copies_sold"] is None for row in rows),
        "steam_reviews_found": sum(row["steam_review_count"] is not None for row in rows),
        "steam_reviews_missing": sum(row["steam_review_count"] is None for row in rows),
        "all_ages": sum(row["all_ages_status"] == "全年龄" for row in rows),
        "not_all_ages": sum(row["all_ages_status"] == "非全年龄" for row in rows),
        "unknown_age": sum(row["all_ages_status"] == "未知" for row in rows),
        "copies_sold_sum": sum(row["copies_sold"] or 0 for row in rows),
        "as_of_date": AS_OF_DATE.isoformat(),
        "review_metadata": review_meta,
        "gamalytic_metadata": gamalytic_meta,
        "sexual_content_rule": (
            "Across every linked VNDB release for the Steam AppID: any has_ero=true => 非全年龄; "
            "otherwise any known has_ero=false => 全年龄; all null => 未知. "
            "minage and uncensored are descriptive only and never substitute for has_ero."
        ),
    }
    save_json(EXPANDED_DIR / "expanded_metadata.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"Expanded outputs written to {EXPANDED_DIR}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-vndb-details", action="store_true")
    parser.add_argument("--refresh-steam-reviews", action="store_true")
    parser.add_argument("--refresh-gamalytic", action="store_true")
    parser.add_argument("--review-workers", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.review_workers <= 12:
        parser.error("--review-workers must be between 1 and 12")

    ensure_dirs()
    universe, universe_meta = build_universe()
    print(f"Expanded universe: {universe_meta}", flush=True)
    details = fetch_vndb_release_details(
        release_ids_for(universe), refresh=args.refresh_vndb_details
    )
    appids = [row["steam_appid"] for row in universe]
    reviews, review_meta = fetch_steam_reviews(
        appids, refresh=args.refresh_steam_reviews, workers=args.review_workers
    )
    print(f"[3/4] Gamalytic copiesSold for {len(appids):,} expanded games", flush=True)
    gamalytic, gamalytic_meta = fetch_gamalytic(
        appids, refresh=args.refresh_gamalytic, batch_size=250
    )
    print("[4/4] Building master table and grouped summaries", flush=True)
    rows, threshold_info = build_final_rows(universe, details, reviews, gamalytic)
    emit(rows, universe_meta, threshold_info, review_meta, gamalytic_meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
