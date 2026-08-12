#!/usr/bin/env python3
"""Collect and compare VNDB + Steam Visual Novel data, then enrich with Gamalytic.

The script intentionally uses only public, anonymous endpoints and the Python
standard library. Every network page is cached under data/raw so the job can be
resumed without repeating successful requests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html as html_lib
import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
VNDB_CACHE_DIR = RAW_DIR / "vndb"
STEAM_CACHE_DIR = RAW_DIR / "steam_tag_3799"
GAMALYTIC_CACHE_DIR = RAW_DIR / "gamalytic"

VNDB_URL = "https://api.vndb.org/kana/release"
STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/"
GAMALYTIC_LIST_URL = "https://api.gamalytic.com/steam-games/list"

START_DATE = date(2020, 1, 1)
END_DATE = date(2025, 12, 31)
STEAM_VISUAL_NOVEL_TAG_ID = 3799
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 "
    "steam-vn-research/1.0"
)


@dataclass
class HttpResult:
    body: bytes
    headers: dict[str, str]
    status: int


def ensure_dirs() -> None:
    for path in (
        VNDB_CACHE_DIR,
        STEAM_CACHE_DIR,
        GAMALYTIC_CACHE_DIR,
        PROCESSED_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    retries: int = 6,
    timeout: int = 45,
) -> HttpResult:
    data = None
    headers = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as response:
                return HttpResult(
                    body=response.read(),
                    headers={k.lower(): v for k, v in response.headers.items()},
                    status=int(response.status),
                )
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:500]}") from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2**attempt)
            print(f"  HTTP {exc.code}; retrying in {delay:.0f}s ({attempt}/{retries})", flush=True)
            time.sleep(delay)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            delay = min(30, 2**attempt)
            print(f"  Network error; retrying in {delay:.0f}s ({attempt}/{retries}): {exc}", flush=True)
            time.sleep(delay)

    raise RuntimeError(f"Request failed after {retries} attempts: {url}: {last_error}")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    temp.replace(path)


def fetch_vndb(refresh: bool = False) -> list[dict[str, Any]]:
    print("[1/4] Fetching VNDB Steam-linked releases", flush=True)
    all_rows: list[dict[str, Any]] = []
    page = 1
    while True:
        cache_path = VNDB_CACHE_DIR / f"page_{page:04d}.json"
        if cache_path.exists() and not refresh:
            response = load_json(cache_path)
        else:
            payload = {
                "filters": ["extlink", "=", "steam"],
                "fields": (
                    "title,alttitle,released,platforms,patch,freeware,official,"
                    "minage,has_ero,uncensored,"
                    "languages{lang,title},extlinks{url,label,name,id},"
                    "vns{id,title,alttitle,rtype}"
                ),
                "sort": "id",
                "results": 100,
                "page": page,
                "count": page == 1,
            }
            result = request_bytes(VNDB_URL, method="POST", payload=payload)
            response = json.loads(result.body.decode("utf-8"))
            save_json(cache_path, response)
            time.sleep(0.8)

        rows = response.get("results") or []
        all_rows.extend(rows)
        if page == 1:
            count = response.get("count")
            if count is not None:
                print(f"  VNDB reports {count:,} Steam-linked release rows", flush=True)
        if page % 20 == 0 or not response.get("more"):
            print(f"  VNDB page {page}; collected {len(all_rows):,} rows", flush=True)
        if not response.get("more"):
            break
        page += 1

    save_json(RAW_DIR / "vndb_releases_all.json", {"results": all_rows})
    return all_rows


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_steam_date(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    cleaned = strip_tags(text).replace("–", "-").strip()
    lowered = cleaned.casefold()
    if not cleaned or any(token in lowered for token in ("coming soon", "to be announced", "tba")):
        return None, None
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
            return parsed.isoformat(), "day"
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{4})-(\d{2})", cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2)}-01", "month"
    match = re.fullmatch(r"(\d{4})", cleaned)
    if match:
        return f"{match.group(1)}-01-01", "year"
    return None, None


def parse_search_rows(results_html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    anchors = re.findall(
        r'<a\b[^>]*class="[^"]*search_result_row[^"]*"[^>]*>.*?</a>',
        results_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for anchor in anchors:
        app_match = re.search(r'data-ds-appid="(\d+)"', anchor)
        if not app_match:
            continue
        appid = app_match.group(1)
        title_match = re.search(
            r'<span\s+class="title">(.*?)</span>', anchor, flags=re.IGNORECASE | re.DOTALL
        )
        release_match = re.search(
            r'<div\s+class="[^"]*search_released[^"]*">(.*?)</div>',
            anchor,
            flags=re.IGNORECASE | re.DOTALL,
        )
        price_match = re.search(
            r'<div\s+class="[^"]*search_price[^"]*"[^>]*>(.*?)</div>',
            anchor,
            flags=re.IGNORECASE | re.DOTALL,
        )
        tag_match = re.search(r'data-ds-tagids="(\[[^"]*\])"', anchor)
        title = strip_tags(title_match.group(1)) if title_match else ""
        release_text = strip_tags(release_match.group(1)) if release_match else ""
        release_date, precision = parse_steam_date(release_text)
        price_text = strip_tags(price_match.group(1)) if price_match else ""
        tag_ids: list[int] = []
        if tag_match:
            try:
                tag_ids = [int(x) for x in json.loads(html_lib.unescape(tag_match.group(1)))]
            except (ValueError, json.JSONDecodeError):
                pass
        rows.append(
            {
                "steam_appid": appid,
                "steam_title": title,
                "steam_release_text": release_text,
                "steam_release_date": release_date,
                "steam_release_precision": precision,
                "price_text": price_text,
                "is_free": "free" in price_text.casefold(),
                "tag_ids": tag_ids,
                "store_url": f"https://store.steampowered.com/app/{appid}/",
            }
        )
    return rows


def fetch_steam_tag(refresh: bool = False) -> list[dict[str, Any]]:
    print("[2/4] Fetching Steam Visual Novel tag results", flush=True)
    page_size = 100

    def fetch_page(start: int) -> tuple[int, dict[str, Any]]:
        cache_path = STEAM_CACHE_DIR / f"start_{start:06d}.json"
        if cache_path.exists() and not refresh:
            response = load_json(cache_path)
        else:
            params = {
                "query": "",
                "start": start,
                "count": page_size,
                "dynamic_data": "",
                "sort_by": "_ASC",
                "tags": STEAM_VISUAL_NOVEL_TAG_ID,
                "category1": 998,
                "infinite": 1,
                "cc": "us",
                "l": "english",
                "ignore_preferences": 1,
            }
            url = f"{STEAM_SEARCH_URL}?{urlencode(params)}"
            result = request_bytes(url)
            response = json.loads(result.body.decode("utf-8"))
            save_json(cache_path, response)
            time.sleep(0.25)
        return start, response

    first_start, first_response = fetch_page(0)
    total_count = int(first_response.get("total_count") or 0)
    print(f"  Steam reports {total_count:,} tagged game results", flush=True)
    responses: dict[int, dict[str, Any]] = {first_start: first_response}
    pending_starts = list(range(page_size, total_count, page_size))
    completed = 1
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_page, start): start for start in pending_starts}
        for future in as_completed(futures):
            start, response = future.result()
            responses[start] = response
            completed += 1
            if completed % 20 == 0 or completed == len(pending_starts) + 1:
                print(
                    f"  Steam pages {completed}/{len(pending_starts) + 1}",
                    flush=True,
                )

    all_rows: list[dict[str, Any]] = []
    for start in sorted(responses):
        parsed = parse_search_rows(responses[start].get("results_html") or "")
        if not parsed and start < total_count:
            raise RuntimeError(f"Steam page at start={start} returned no parseable rows")
        all_rows.extend(parsed)

    # Later duplicate rows replace earlier ones, which is safe for identical AppIDs.
    deduped = {row["steam_appid"]: row for row in all_rows}
    rows = list(deduped.values())
    save_json(RAW_DIR / "steam_visual_novel_tag_all.json", {"results": rows})
    return rows


def parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def in_scope(value: str | None) -> bool:
    parsed = parse_date_value(value)
    return bool(parsed and START_DATE <= parsed <= END_DATE)


def safe_join(values: Iterable[Any]) -> str:
    return ";".join(sorted({str(v).strip() for v in values if v is not None and str(v).strip()}))


def aggregate_vndb(releases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for release in releases:
        steam_ids = []
        for link in release.get("extlinks") or []:
            if link.get("name") == "steam" and str(link.get("id", "")).isdigit():
                steam_ids.append(str(link["id"]))
        if not steam_ids:
            continue
        vns = release.get("vns") or []
        released, precision = parse_steam_date(release.get("released"))
        for appid in steam_ids:
            row = grouped.setdefault(
                appid,
                {
                    "steam_appid": appid,
                    "vndb_release_ids": set(),
                    "vndb_ids": set(),
                    "vndb_titles": set(),
                    "vndb_release_titles": set(),
                    "vndb_release_dates": set(),
                    "vndb_rtypes": set(),
                    "vndb_patch": False,
                    "vndb_official": False,
                },
            )
            row["vndb_release_ids"].add(release.get("id"))
            row["vndb_release_titles"].add(release.get("title"))
            if released:
                row["vndb_release_dates"].add(released)
            row["vndb_patch"] = row["vndb_patch"] or bool(release.get("patch"))
            row["vndb_official"] = row["vndb_official"] or bool(release.get("official"))
            for vn in vns:
                row["vndb_ids"].add(vn.get("id"))
                row["vndb_titles"].add(vn.get("title") or vn.get("alttitle"))
                if vn.get("rtype"):
                    row["vndb_rtypes"].add(vn["rtype"])

    normalized: dict[str, dict[str, Any]] = {}
    for appid, row in grouped.items():
        release_dates = sorted(row["vndb_release_dates"])
        normalized[appid] = {
            "steam_appid": appid,
            "vndb_release_ids": safe_join(row["vndb_release_ids"]),
            "vndb_ids": safe_join(row["vndb_ids"]),
            "vndb_titles": safe_join(row["vndb_titles"]),
            "vndb_release_titles": safe_join(row["vndb_release_titles"]),
            "vndb_release_dates": safe_join(release_dates),
            "vndb_first_steam_release_date": release_dates[0] if release_dates else None,
            "vndb_rtypes": safe_join(row["vndb_rtypes"]),
            "vndb_patch": row["vndb_patch"],
            "vndb_official": row["vndb_official"],
        }
    return normalized


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def compare_sources(
    vndb: dict[str, dict[str, Any]], steam_rows: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    print("[3/4] Normalizing and comparing source sets", flush=True)
    steam = {row["steam_appid"]: row for row in steam_rows}
    union_ids = sorted(set(vndb) | set(steam), key=int)
    matrix: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for appid in union_ids:
        vrow = vndb.get(appid, {})
        srow = steam.get(appid, {})
        in_vndb = appid in vndb
        in_steam = appid in steam
        canonical_date = srow.get("steam_release_date") or vrow.get("vndb_first_steam_release_date")
        date_source = "steam_store_search" if srow.get("steam_release_date") else "vndb_steam_release"
        title = srow.get("steam_title") or vrow.get("vndb_release_titles") or vrow.get("vndb_titles") or ""
        if in_vndb and in_steam:
            category = "INTERSECTION"
        elif in_vndb:
            category = "VNDB_ONLY"
        else:
            category = "STEAM_ONLY"

        scope = in_scope(canonical_date)
        exclusion_reason = ""
        if not canonical_date:
            exclusion_reason = "MISSING_RELEASE_DATE"
        elif not scope:
            exclusion_reason = "OUTSIDE_2020_2025"
        elif category == "INTERSECTION":
            rtypes = set(filter(None, (vrow.get("vndb_rtypes") or "").split(";")))
            if rtypes and "complete" not in rtypes:
                exclusion_reason = "VNDB_RELEASE_NOT_COMPLETE"
            elif vrow.get("vndb_patch"):
                exclusion_reason = "VNDB_PATCH_RELEASE"

        row = {
            "steam_appid": appid,
            "name": title,
            "steam_release_date": canonical_date,
            "release_month": canonical_date[:7] if canonical_date else "",
            "release_date_source": date_source,
            "in_vndb": in_vndb,
            "in_steam_visual_novel_tag": in_steam,
            "set_category": category,
            "in_target_scope": scope and not exclusion_reason,
            "exclusion_reason": exclusion_reason,
            "vndb_ids": vrow.get("vndb_ids", ""),
            "vndb_release_ids": vrow.get("vndb_release_ids", ""),
            "vndb_titles": vrow.get("vndb_titles", ""),
            "vndb_rtypes": vrow.get("vndb_rtypes", ""),
            "vndb_official": vrow.get("vndb_official", ""),
            "steam_title": srow.get("steam_title", ""),
            "steam_release_text": srow.get("steam_release_text", ""),
            "price_text": srow.get("price_text", ""),
            "is_free": srow.get("is_free", ""),
            "store_url": srow.get("store_url") or f"https://store.steampowered.com/app/{appid}/",
            "vndb_url": f"https://vndb.org/{(vrow.get('vndb_ids') or '').split(';')[0]}" if vrow.get("vndb_ids") else "",
        }
        matrix.append(row)
        if exclusion_reason:
            excluded.append(row)

    target = [row for row in matrix if row["in_target_scope"]]
    intersection = [row for row in target if row["set_category"] == "INTERSECTION"]
    vndb_only = [row for row in target if row["set_category"] == "VNDB_ONLY"]
    steam_only = [row for row in target if row["set_category"] == "STEAM_ONLY"]
    key = lambda row: (row.get("steam_release_date") or "9999", row.get("name") or "", int(row["steam_appid"]))
    for rows in (matrix, excluded, intersection, vndb_only, steam_only):
        rows.sort(key=key)
    print(
        f"  Target scope: intersection={len(intersection):,}, "
        f"VNDB-only={len(vndb_only):,}, Steam-only={len(steam_only):,}",
        flush=True,
    )
    return {
        "matrix": matrix,
        "excluded": excluded,
        "intersection": intersection,
        "vndb_only": vndb_only,
        "steam_only": steam_only,
    }


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_gamalytic(appids: list[str], refresh: bool = False, batch_size: int = 250) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    print(f"[4/4] Fetching Gamalytic copiesSold for {len(appids):,} intersection games", flush=True)
    output: dict[str, dict[str, Any]] = {}
    cache_timestamps: list[int] = []
    request_count = 0
    requested_ids = set(appids)

    # Reuse every previously downloaded result, even when a corrected source
    # comparison changes batch boundaries or ordering.
    if not refresh:
        for cache_path in sorted(GAMALYTIC_CACHE_DIR.glob("batch_*.json")):
            response = load_json(cache_path)
            cache_timestamp = response.get("cacheTimestamp")
            if isinstance(cache_timestamp, int):
                cache_timestamps.append(cache_timestamp)
            for item in response.get("result") or []:
                appid = str(item.get("steamId"))
                if appid in requested_ids:
                    output[appid] = {
                        "gamalytic_name": item.get("name"),
                        "gamalytic_release_date_ms": item.get("releaseDate"),
                        "copies_sold": item.get("copiesSold"),
                        "gamalytic_cache_timestamp": cache_timestamp,
                        "gamalytic_status": "FOUND",
                    }

    missing_ids = [appid for appid in appids if appid not in output]
    if output:
        print(f"  Reused {len(output):,} cached Gamalytic records; {len(missing_ids):,} still missing", flush=True)

    for index, batch in enumerate(chunks(missing_ids, batch_size), start=1):
        digest = hashlib.sha1(",".join(batch).encode("ascii")).hexdigest()[:12]
        cache_path = GAMALYTIC_CACHE_DIR / f"batch_missing_{index:04d}_{digest}.json"
        if cache_path.exists() and not refresh:
            response = load_json(cache_path)
        else:
            params = {
                "limit": 1000,
                "appids": ",".join(batch),
                "fields": "steamId,name,releaseDate,copiesSold",
            }
            url = f"{GAMALYTIC_LIST_URL}?{urlencode(params)}"
            result = request_bytes(url)
            response = json.loads(result.body.decode("utf-8"))
            save_json(cache_path, response)
            request_count += 1
            time.sleep(1.0)
        cache_timestamp = response.get("cacheTimestamp")
        if isinstance(cache_timestamp, int):
            cache_timestamps.append(cache_timestamp)
        for item in response.get("result") or []:
            appid = str(item.get("steamId"))
            if appid and appid != "None":
                output[appid] = {
                    "gamalytic_name": item.get("name"),
                    "gamalytic_release_date_ms": item.get("releaseDate"),
                    "copies_sold": item.get("copiesSold"),
                    "gamalytic_cache_timestamp": cache_timestamp,
                    "gamalytic_status": "FOUND",
                }
        print(
            f"  Gamalytic batch {index}; returned {len(response.get('result') or []):,}; "
            f"cumulative {len(output):,}",
            flush=True,
        )
    metadata = {
        "new_network_requests": request_count,
        "cache_timestamp_min": min(cache_timestamps) if cache_timestamps else None,
        "cache_timestamp_max": max(cache_timestamps) if cache_timestamps else None,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return output, metadata


def emit_outputs(
    source_sets: dict[str, list[dict[str, Any]]],
    gamalytic: dict[str, dict[str, Any]],
    gamalytic_meta: dict[str, Any],
) -> None:
    fetched_at = gamalytic_meta["fetched_at_utc"]
    final_rows: list[dict[str, Any]] = []
    for row in source_sets["intersection"]:
        game = gamalytic.get(row["steam_appid"])
        merged = dict(row)
        if game:
            merged.update(game)
        else:
            merged.update(
                {
                    "gamalytic_name": "",
                    "gamalytic_release_date_ms": "",
                    "copies_sold": None,
                    "gamalytic_cache_timestamp": "",
                    "gamalytic_status": "NOT_FOUND",
                }
            )
        merged["copies_sold_fetched_at"] = fetched_at
        final_rows.append(merged)

    common_fields = [
        "steam_appid",
        "name",
        "steam_release_date",
        "release_month",
        "release_date_source",
        "in_vndb",
        "in_steam_visual_novel_tag",
        "set_category",
        "in_target_scope",
        "exclusion_reason",
        "vndb_ids",
        "vndb_release_ids",
        "vndb_titles",
        "vndb_rtypes",
        "vndb_official",
        "steam_title",
        "price_text",
        "is_free",
        "store_url",
        "vndb_url",
    ]
    final_fields = common_fields + [
        "copies_sold",
        "gamalytic_status",
        "gamalytic_name",
        "gamalytic_release_date_ms",
        "gamalytic_cache_timestamp",
        "copies_sold_fetched_at",
    ]
    write_csv(PROCESSED_DIR / "final_visual_novels_2020_2025.csv", final_rows, final_fields)
    write_csv(PROCESSED_DIR / "intersection_visual_novels.csv", source_sets["intersection"], common_fields)
    write_csv(PROCESSED_DIR / "difference_vndb_only.csv", source_sets["vndb_only"], common_fields)
    write_csv(PROCESSED_DIR / "difference_steam_only.csv", source_sets["steam_only"], common_fields)
    write_csv(PROCESSED_DIR / "source_membership_all.csv", source_sets["matrix"], common_fields)
    write_csv(PROCESSED_DIR / "excluded_candidates.csv", source_sets["excluded"], common_fields)

    summary_rows = [
        {"category": "VNDB_TOTAL_ALL_DATES", "count": sum(1 for r in source_sets["matrix"] if r["in_vndb"]), "description": "VNDB entries with a Steam AppID before date filtering"},
        {"category": "STEAM_TAG_TOTAL_ALL_DATES", "count": sum(1 for r in source_sets["matrix"] if r["in_steam_visual_novel_tag"]), "description": "Steam Visual Novel tag games before date filtering"},
        {"category": "INTERSECTION_2020_2025", "count": len(source_sets["intersection"]), "description": "Present in both sources and in target date scope"},
        {"category": "VNDB_ONLY_2020_2025", "count": len(source_sets["vndb_only"]), "description": "Present in VNDB but missing the Steam Visual Novel tag"},
        {"category": "STEAM_ONLY_2020_2025", "count": len(source_sets["steam_only"]), "description": "Has Steam Visual Novel tag but no VNDB Steam mapping"},
        {"category": "GAMALYTIC_FOUND", "count": sum(1 for r in final_rows if r["gamalytic_status"] == "FOUND"), "description": "Intersection games with copiesSold returned"},
        {"category": "GAMALYTIC_NOT_FOUND", "count": sum(1 for r in final_rows if r["gamalytic_status"] != "FOUND"), "description": "Intersection games missing from the anonymous Gamalytic list"},
    ]
    write_csv(
        PROCESSED_DIR / "source_comparison_summary.csv",
        summary_rows,
        ["category", "count", "description"],
    )

    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"game_count": 0, "games_with_copies_sold": 0, "games_missing_copies_sold": 0, "copies_sold_sum": 0})
    for row in final_rows:
        month = row["release_month"]
        monthly[month]["game_count"] += 1
        if isinstance(row.get("copies_sold"), (int, float)):
            monthly[month]["games_with_copies_sold"] += 1
            monthly[month]["copies_sold_sum"] += int(row["copies_sold"])
        else:
            monthly[month]["games_missing_copies_sold"] += 1
    monthly_rows = [{"month": month, **monthly[month]} for month in sorted(monthly)]
    write_csv(
        PROCESSED_DIR / "monthly_release_counts.csv",
        monthly_rows,
        ["month", "game_count", "games_with_copies_sold", "games_missing_copies_sold", "copies_sold_sum"],
    )
    save_json(PROCESSED_DIR / "run_metadata.json", gamalytic_meta)
    print(f"Outputs written to {PROCESSED_DIR}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-vndb", action="store_true", help="Ignore cached VNDB pages")
    parser.add_argument("--refresh-steam", action="store_true", help="Ignore cached Steam search pages")
    parser.add_argument("--refresh-gamalytic", action="store_true", help="Ignore cached Gamalytic batches")
    parser.add_argument("--gamalytic-batch-size", type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.gamalytic_batch_size <= 500:
        parser.error("--gamalytic-batch-size must be between 1 and 500")

    ensure_dirs()
    vndb_releases = fetch_vndb(refresh=args.refresh_vndb)
    steam_rows = fetch_steam_tag(refresh=args.refresh_steam)
    vndb_apps = aggregate_vndb(vndb_releases)
    source_sets = compare_sources(vndb_apps, steam_rows)
    appids = [row["steam_appid"] for row in source_sets["intersection"]]
    gamalytic, meta = fetch_gamalytic(
        appids,
        refresh=args.refresh_gamalytic,
        batch_size=args.gamalytic_batch_size,
    )
    emit_outputs(source_sets, gamalytic, meta)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; cached pages are safe and the run can be resumed.", file=sys.stderr)
        raise SystemExit(130)
