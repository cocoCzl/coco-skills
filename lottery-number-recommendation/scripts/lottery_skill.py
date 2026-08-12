#!/usr/bin/env python3
"""Automatic, auditable official lottery synchronization and recommendations."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import time
import uuid
import platform
import importlib.util
from collections import Counter
from math import ceil
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from request_parser import parse_request_text as _parse_request_text
except ImportError:  # imported directly by repository tests
    _parser_spec = importlib.util.spec_from_file_location("lottery_request_parser", Path(__file__).with_name("request_parser.py"))
    if _parser_spec is None or _parser_spec.loader is None:  # pragma: no cover - corrupt package
        raise
    _parser_module = importlib.util.module_from_spec(_parser_spec)
    _parser_spec.loader.exec_module(_parser_module)
    _parse_request_text = _parser_module.parse_request_text


GAMES = {
    "dlt": {"label": "大乐透", "zones": (("front", 5, 1, 35), ("back", 2, 1, 12))},
    "ssq": {"label": "双色球", "zones": (("red", 6, 1, 33), ("blue", 1, 1, 16))},
}
MODES = {"random", "hot", "cold"}
# ``hot_legacy`` is deliberately not exposed by the recommendation CLI.  It
# remains available to the backtest as a historical control for the previous
# linear-frequency implementation.
GENERATION_MODES = MODES | {"hot_legacy"}
STRENGTHS = {"mild": 0.4, "medium": 1.0, "strong": 2.0}
SMOOTHED_HOT_STRENGTHS = {"mild": 0.5, "medium": 1.0, "strong": 1.5}
SMOOTHED_HOT_BLEND = ((0.25, 0.20), (1.0, 0.50), (2.5, 0.30))
SMOOTHED_HOT_PRIOR_DRAWS = 100
SMOOTHED_HOT_RATIO_RANGE = (0.70, 1.40)
SMOOTHED_HOT_WEIGHT_RANGE = (0.75, 1.50)
PAGE_SIZE = 100
SYNC_DELAY_SECONDS = 0.2

# These are public endpoints used by the corresponding official sites. The
# client does not attempt to solve challenges, inject cookies, or bypass WAF.
OFFICIAL_SOURCES = {
    "ssq": {
        "endpoint": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice",
        "referer": "https://www.cwl.gov.cn/",
        # The public query and announcement archive currently both begin at
        # 2013001.  If the same official source later exposes 2003001, the
        # coverage policy below promotes the data set to full history without
        # a manual migration.
        "first_issue": "2003001",
        "official_available_first_issue": "2013001",
    },
    "dlt": {
        "endpoint": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry",
        "referer": "https://static.sporttery.cn/",
        "first_issue": "07001",
    },
}


class LotteryError(ValueError):
    """A user-actionable validation or readiness error."""


ERROR_CODE_RULES = (
    ("访问限制", "SOURCE_ACCESS_BLOCKED"),
    ("HTTP", "SOURCE_HTTP_ERROR"),
    ("无法连接", "SOURCE_UNAVAILABLE"),
    ("完整", "DATA_INCOMPLETE"),
    ("未准备", "DATA_NOT_READY"),
    ("参数", "INVALID_ARGUMENTS"),
)


def stable_error_code(message: str) -> str:
    for marker, code in ERROR_CODE_RULES:
        if marker in message:
            return code
    return "LOTTERY_OPERATION_FAILED"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LotteryError(f"无法读取 JSON 文件：{exc}") from exc
    if not isinstance(value, dict):
        raise LotteryError("历史数据文件必须是 JSON 对象")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise LotteryError(f"无法原子写入 JSON 文件：{exc}") from exc


def request_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310: fixed official HTTPS URLs
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise LotteryError(f"官方数据源返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise LotteryError(f"无法连接官方数据源：{exc.reason}") from exc
    if "WAF" in body or "访问行为存在异常" in body or "您的请求已中断" in body:
        raise LotteryError("官方数据源触发访问限制；未尝试绕过，暂不能同步")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LotteryError("官方数据源未返回可解析的 JSON") from exc
    if not isinstance(payload, dict):
        raise LotteryError("官方数据源返回了无效数据结构")
    return payload


def source_headers(game: str) -> dict[str, str]:
    return {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": OFFICIAL_SOURCES[game]["referer"],
        # Match the normal desktop browser request made by the official page.
        # No session cookie, challenge token, or privileged credential is used.
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    }


def page_url(game: str, page: int) -> str:
    if game == "ssq":
        return f"{OFFICIAL_SOURCES[game]['endpoint']}?name=ssq&pageNo={page}&pageSize={PAGE_SIZE}&systemType=PC"
    return f"{OFFICIAL_SOURCES[game]['endpoint']}?gameNo=85&provinceId=0&pageSize={PAGE_SIZE}&isVerify=1&pageNo={page}"


def source_rows(game: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("result") if game == "ssq" else (payload.get("value") or {}).get("list")
    if not isinstance(rows, list):
        raise LotteryError("官方数据源缺少开奖列表")
    return rows


def source_total(game: str, payload: dict[str, Any]) -> int:
    total = payload.get("total") if game == "ssq" else (payload.get("value") or {}).get("total")
    try:
        parsed = int(total)
    except (TypeError, ValueError) as exc:
        raise LotteryError("官方数据源缺少历史期数") from exc
    if parsed < 1:
        raise LotteryError("官方数据源返回的历史期数无效")
    return parsed


def official_draw(game: str, row: dict[str, Any]) -> dict[str, Any]:
    if game == "ssq":
        date = str(row.get("date", ""))[:10]
        return normalize_draw(game, {
            "issue": row.get("code"), "sequence": 1, "draw_date": date,
            "red": [int(value) for value in str(row.get("red", "")).split(",") if value],
            "blue": [int(value) for value in str(row.get("blue", "")).split(",") if value],
        })
    values = [int(value) for value in str(row.get("lotteryDrawResult", "")).split() if value]
    return normalize_draw(game, {
        "issue": row.get("lotteryDrawNum"), "sequence": 1, "draw_date": str(row.get("lotteryDrawTime", ""))[:10],
        "front": values[:5], "back": values[5:],
    })


def public_context(game: str, row: dict[str, Any]) -> dict[str, Any]:
    """Keep only official, user-readable context; never feed it into selection."""
    if game == "dlt":
        context = {
            "pool_balance_after_draw": row.get("poolBalanceAfterdraw") or None,
            "draw_notice_url": row.get("drawPdfUrl") or None,
        }
        if str(row.get("lotteryPromotionFlag", "0")) not in {"", "0", "None"}:
            context["promotion_flag"] = row.get("lotteryPromotionFlag")
        return {key: value for key, value in context.items() if value}
    context = {
        "pool_balance": row.get("poolmoney") or None,
        "draw_notice_path": row.get("detailsLink") or None,
    }
    if row.get("addmoney"):
        context["add_money"] = row["addmoney"]
    return {key: value for key, value in context.items() if value}


def sequentialize(draws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(draws, key=lambda draw: (draw["draw_date"], draw["issue"]))
    return [{**draw, "sequence": index} for index, draw in enumerate(ordered, start=1)]


def fetch_with_retry(fetch, url: str, headers: dict[str, str], sleep, retries: int = 3) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            return fetch(url, headers)
        except LotteryError as exc:
            # Retrying a WAF block would be noisy and is not an access-control strategy.
            if "访问限制" in str(exc) or attempt == retries - 1:
                raise
            sleep(2**attempt)
    raise AssertionError("unreachable")


def history_version_path(data_dir: Path, game: str, version: str) -> Path:
    return data_dir / "history" / "versions" / game / f"{version}.json"


def coverage_for_history(game: str, first_issue: str) -> dict[str, str] | None:
    """Describe the verified history scope represented by an official snapshot."""
    source = OFFICIAL_SOURCES[game]
    if first_issue == source["first_issue"]:
        return {
            "kind": "full_history",
            "from_issue": source["first_issue"],
            "label": "从首期至今的完整官方历史",
        }
    available_first = source.get("official_available_first_issue")
    if available_first and first_issue == available_first:
        return {
            "kind": "official_available_history",
            "from_issue": available_first,
            "label": "官网当前可得历史区间",
        }
    return None


def sync_official_history(data_dir: Path, game: str, fetch=None, sleep=None, now: dt.datetime | None = None, force_full: bool = False) -> dict[str, Any]:
    """Fetch a complete official history snapshot, sequentially and fail-closed."""
    require_game(game)
    fetch = fetch or request_json
    sleep = sleep or time.sleep
    now = now or dt.datetime.now(dt.timezone.utc)
    sync_day = now.date().isoformat()
    first_url = page_url(game, 1)
    first = fetch_with_retry(fetch, first_url, source_headers(game), sleep)
    total = source_total(game, first)
    pages = ceil(total / PAGE_SIZE)
    destination = archive_path(data_dir, game)
    previous = read_json(destination) if destination.exists() else None
    full_refresh = bool(force_full or not previous or previous.get("last_full_sync_date") != sync_day)
    payloads = [first]
    fresh_rows = source_rows(game, first)
    previous_draws = previous.get("draws", []) if isinstance(previous, dict) else []
    prior_latest = previous_draws[-1].get("issue") if previous_draws else None

    # First initialization needs every page. On later runs, fetch only until
    # the former latest issue appears; this catches an offline gap without
    # repeatedly downloading the entire archive.
    if previous_draws and not full_refresh:
        page = 1
        while prior_latest not in {str(row.get("code" if game == "ssq" else "lotteryDrawNum", "")) for row in fresh_rows} and page < pages:
            page += 1
            sleep(SYNC_DELAY_SECONDS)
            payload = fetch_with_retry(fetch, page_url(game, page), source_headers(game), sleep)
            payloads.append(payload)
            fresh_rows.extend(source_rows(game, payload))
    else:
        for page in range(2, pages + 1):
            sleep(SYNC_DELAY_SECONDS)
            payload = fetch_with_retry(fetch, page_url(game, page), source_headers(game), sleep)
            payloads.append(payload)
            fresh_rows.extend(source_rows(game, payload))
        if len(fresh_rows) != total:
            raise LotteryError(f"官方数据源返回 {len(fresh_rows)} 期，声明应有 {total} 期；拒绝使用不完整快照")

    normalized_pairs = [(official_draw(game, row), row) for row in fresh_rows]
    merged_by_issue = {} if full_refresh else {draw["issue"]: draw for draw in previous_draws if isinstance(draw, dict)}
    for draw, _row in normalized_pairs:
        merged_by_issue[draw["issue"]] = draw
    draws = sequentialize(list(merged_by_issue.values()))
    issues = [draw["issue"] for draw in draws]
    if len(set(issues)) != len(issues):
        raise LotteryError("官方数据源返回重复期号；拒绝使用")
    source = OFFICIAL_SOURCES[game]
    coverage = coverage_for_history(game, draws[0]["issue"])
    complete = coverage is not None and len(draws) == total
    reason = None
    if coverage is None:
        expected = source.get("official_available_first_issue", source["first_issue"])
        reason = f"官方接口最早为第 {draws[0]['issue']} 期，预期首期应为第 {expected} 期或第 {source['first_issue']} 期"
    elif len(draws) != total:
        reason = f"本地与官方历史期数不一致：本地 {len(draws)} 期，官方 {total} 期"
    latest_pair = max(normalized_pairs, key=lambda pair: (pair[0]["draw_date"], pair[0]["issue"]))
    raw_dir = data_dir / "raw" / game
    raw_dir.mkdir(parents=True, exist_ok=True)
    captured_at = utc_now()
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    raw_name = f"{captured_at.replace(':', '').replace('+00:00', 'Z')}-{digest[:12]}.json"
    write_json(raw_dir / raw_name, {"pages": payloads})
    data_version = hashlib.sha256(json.dumps(draws, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    version_file = history_version_path(data_dir, game, data_version)
    if not version_file.exists():
        write_json(version_file, {
            "schema_version": 1,
            "game": game,
            "data_version": data_version,
            "created_at": captured_at,
            "draws": draws,
            "source_raw_file": str(Path("raw") / game / raw_name),
        })
    archive = {
        "schema_version": 2,
        "game": game,
        "draws": draws,
        "syncs": [*(previous.get("syncs", []) if isinstance(previous, dict) else []), {
            "synced_at": captured_at,
            "source_url": source["endpoint"],
            "sync_kind": "full" if full_refresh else "incremental",
            "page_count": len(payloads),
            "declared_total": total,
            "raw_file": str(Path("raw") / game / raw_name),
            "sha256": digest,
        }],
        "updated_at": captured_at,
        "data_version": data_version,
        "last_full_sync_date": sync_day if full_refresh else previous.get("last_full_sync_date"),
        "complete": complete,
        "synced_to_latest": complete,
        "reason": reason,
        "last_sync_failure": None,
        "history_coverage": coverage,
        "public_context": public_context(game, latest_pair[1]),
        "missing_sequences": [],
    }
    write_json(archive_path(data_dir, game), archive)
    return status_for_game(data_dir, game)


def record_sync_failure(data_dir: Path, game: str, error: str) -> None:
    """Keep the last verified snapshot but prevent it being presented as current."""
    path = archive_path(data_dir, game)
    if not path.exists():
        return
    archive = read_json(path)
    archive["synced_to_latest"] = False
    archive["reason"] = error
    archive["last_sync_failure"] = {"attempted_at": utc_now(), "error": error}
    write_json(path, archive)


def archive_path(data_dir: Path, game: str) -> Path:
    return data_dir / "history" / f"{game}.json"


def audit_path(data_dir: Path) -> Path:
    return data_dir / "audit" / "recommendations.jsonl"


def require_game(game: str) -> dict[str, Any]:
    if game not in GAMES:
        raise LotteryError("彩票种类必须是 dlt（大乐透）或 ssq（双色球）")
    return GAMES[game]


def normalize_zone(numbers: Any, count: int, lower: int, upper: int, zone: str) -> list[int]:
    if not isinstance(numbers, list) or len(numbers) != count:
        raise LotteryError(f"{zone} 必须包含 {count} 个号码")
    if any(not isinstance(number, int) for number in numbers):
        raise LotteryError(f"{zone} 的号码必须是整数")
    if any(number < lower or number > upper for number in numbers):
        raise LotteryError(f"{zone} 号码必须在 {lower:02d}-{upper:02d} 之间")
    if len(set(numbers)) != len(numbers):
        raise LotteryError(f"{zone} 号码不得重复")
    return sorted(numbers)


def normalize_draw(game: str, draw: dict[str, Any]) -> dict[str, Any]:
    config = require_game(game)
    issue = draw.get("issue")
    sequence = draw.get("sequence")
    draw_date = draw.get("draw_date")
    if not isinstance(issue, str) or not issue.strip():
        raise LotteryError("每条开奖记录必须有非空 issue")
    if not isinstance(sequence, int) or sequence < 1:
        raise LotteryError("每条开奖记录必须有大于 0 的整数 sequence")
    if not isinstance(draw_date, str):
        raise LotteryError("每条开奖记录必须有 ISO 日期 draw_date")
    try:
        dt.date.fromisoformat(draw_date)
    except ValueError as exc:
        raise LotteryError("draw_date 必须是 YYYY-MM-DD") from exc
    normalized = {"issue": issue.strip(), "sequence": sequence, "draw_date": draw_date}
    for zone, count, lower, upper in config["zones"]:
        normalized[zone] = normalize_zone(draw.get(zone), count, lower, upper, zone)
    return normalized


def check_continuity(draws: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    if not draws:
        return False, []
    sequences = [draw["sequence"] for draw in draws]
    expected = list(range(1, max(sequences) + 1))
    missing = sorted(set(expected) - set(sequences))
    return sequences[0] == 1 and not missing, missing


def load_ready_archive(data_dir: Path, game: str) -> dict[str, Any]:
    path = archive_path(data_dir, game)
    if not path.exists():
        raise LotteryError(f"{GAMES[game]['label']}尚未同步官方历史数据")
    archive = read_json(path)
    draws = archive.get("draws")
    if not isinstance(draws, list) or not draws:
        raise LotteryError(f"{GAMES[game]['label']}历史数据为空")
    complete, missing = check_continuity(draws)
    if not complete or archive.get("complete") is not True:
        missing_text = "、".join(map(str, missing or archive.get("missing_sequences", []))) or "首期"
        raise LotteryError(f"{GAMES[game]['label']}历史数据不完整（缺少序号：{missing_text}），不能生成号码")
    if archive.get("synced_to_latest") is not True:
        raise LotteryError(archive.get("reason") or f"{GAMES[game]['label']}未能确认完整且最新的官方历史数据，不能生成号码")
    return archive


def status_for_game(data_dir: Path, game: str) -> dict[str, Any]:
    require_game(game)
    path = archive_path(data_dir, game)
    if not path.exists():
        return {"game": game, "label": GAMES[game]["label"], "ready": False, "reason": "尚未同步官方历史数据"}
    archive = read_json(path)
    draws = archive.get("draws", [])
    continuous, missing = check_continuity(draws) if isinstance(draws, list) else (False, [])
    complete = bool(continuous and archive.get("complete"))
    latest = draws[-1] if draws else None
    ready = bool(complete and archive.get("synced_to_latest"))
    return {
        "game": game,
        "label": GAMES[game]["label"],
        "ready": ready,
        "complete": complete,
        "synced_to_latest": bool(archive.get("synced_to_latest")),
        "draw_count": len(draws),
        "first_issue": draws[0]["issue"] if draws else None,
        "latest_issue": latest["issue"] if latest else None,
        "latest_date": latest["draw_date"] if latest else None,
        "updated_at": archive.get("updated_at"),
        "missing_sequences": missing,
        "last_sync": (archive.get("syncs") or [None])[-1],
        "last_sync_failure": archive.get("last_sync_failure"),
        "history_coverage": archive.get("history_coverage"),
        "reason": archive.get("reason"),
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    games = [args.game] if args.game else list(GAMES)
    return {"data_dir": str(Path(args.data_dir)), "games": [status_for_game(Path(args.data_dir), game) for game in games]}


def parse_request_text(text: str) -> dict[str, Any]:
    try:
        return _parse_request_text(text, list(GAMES))
    except ValueError as exc:
        raise LotteryError(str(exc)) from exc


def parse_request(args: argparse.Namespace) -> dict[str, Any]:
    return parse_request_text(args.text)


def sync(args: argparse.Namespace) -> dict[str, Any]:
    games = [args.game] if args.game else list(GAMES)
    data_dir = Path(args.data_dir)
    results = []
    for game in games:
        try:
            results.append({"game": game, "status": sync_official_history(data_dir, game)})
        except LotteryError as exc:
            record_sync_failure(data_dir, game, str(exc))
            results.append({"game": game, "status": status_for_game(data_dir, game), "error": str(exc)})
    return {"data_dir": str(data_dir), "games": results}


def set_current(args: argparse.Namespace) -> dict[str, Any]:
    """Explicit acknowledgement after an approved sync or official latest-check."""
    data_dir = Path(args.data_dir)
    path = archive_path(data_dir, args.game)
    archive = read_json(path)
    complete, missing = check_continuity(archive.get("draws", []))
    if not complete:
        raise LotteryError("历史数据不完整，不能标记为最新")
    archive["complete"] = True
    archive["missing_sequences"] = missing
    archive["synced_to_latest"] = True
    archive["latest_confirmed_at"] = utc_now()
    write_json(path, archive)
    return status_for_game(data_dir, args.game)


def canonical_key(game: str, zones: dict[str, list[int]]) -> tuple[int, ...]:
    return tuple(number for zone, *_ in GAMES[game]["zones"] for number in zones[zone])


def historical_keys(game: str, draws: list[dict[str, Any]]) -> set[tuple[int, ...]]:
    return {canonical_key(game, draw) for draw in draws}


def raw_hot_scores(game: str, draws: list[dict[str, Any]], window: int) -> dict[str, dict[int, float]]:
    config = GAMES[game]
    source = draws[-window:]
    counts = {zone: Counter(number for draw in source for number in draw[zone]) for zone, *_ in config["zones"]}
    return {zone: {number: float(counts[zone][number]) for number in range(lower, upper + 1)} for zone, _, lower, upper in config["zones"]}


def smoothed_hot_scores(game: str, draws: list[dict[str, Any]], window: int) -> dict[str, dict[int, float]]:
    """Return bounded relative-frequency scores for the upgraded hot mode."""
    if not draws:
        return {zone: {number: 1.0 for number in range(lower, upper + 1)} for zone, _, lower, upper in GAMES[game]["zones"]}
    result: dict[str, dict[int, float]] = {}
    for zone, picks_per_draw, lower, upper in GAMES[game]["zones"]:
        population = upper - lower + 1
        expected_per_draw = picks_per_draw / population
        blended = {number: 0.0 for number in range(lower, upper + 1)}
        for factor, blend_weight in SMOOTHED_HOT_BLEND:
            size = max(1, min(len(draws), round(window * factor)))
            counts = Counter(number for draw in draws[-size:] for number in draw[zone])
            expected = size * expected_per_draw
            prior = SMOOTHED_HOT_PRIOR_DRAWS * expected_per_draw
            for number in blended:
                blended[number] += blend_weight * ((counts[number] + prior) / (expected + prior))
        result[zone] = {
            number: max(SMOOTHED_HOT_RATIO_RANGE[0], min(SMOOTHED_HOT_RATIO_RANGE[1], score))
            for number, score in blended.items()
        }
    return result


def zone_scores(game: str, draws: list[dict[str, Any]], mode: str, window: int) -> dict[str, dict[int, float]]:
    config = GAMES[game]
    if mode == "hot":
        return smoothed_hot_scores(game, draws, window)
    if mode == "hot_legacy":
        return raw_hot_scores(game, draws, window)
    if mode == "cold":
        source = draws[-window:] if window else draws
        scores: dict[str, dict[int, float]] = {}
        for zone, _, lower, upper in config["zones"]:
            last_seen = {number: None for number in range(lower, upper + 1)}
            for index, draw in enumerate(source, start=1):
                for number in draw[zone]:
                    last_seen[number] = index
            scores[zone] = {number: float(len(source) - (last_seen[number] or 0)) for number in last_seen}
        return scores
    return {}


def weighted_sample_without_replacement(rng: random.Random, population: list[int], count: int, weights: dict[int, float], strength: float, *, absolute: bool = False) -> list[int]:
    available = list(population)
    picked: list[int] = []
    while len(picked) < count:
        base = [weights[number] if absolute else 1.0 + strength * weights[number] for number in available]
        choice = rng.choices(available, weights=base, k=1)[0]
        picked.append(choice)
        available.remove(choice)
    return sorted(picked)


def candidate(game: str, rng: random.Random, mode: str, scores: dict[str, dict[int, float]], strength: float) -> dict[str, list[int]]:
    value: dict[str, list[int]] = {}
    for zone, count, lower, upper in GAMES[game]["zones"]:
        population = list(range(lower, upper + 1))
        if mode == "random":
            value[zone] = sorted(rng.sample(population, count))
        elif mode == "hot":
            weights = {
                number: max(SMOOTHED_HOT_WEIGHT_RANGE[0], min(SMOOTHED_HOT_WEIGHT_RANGE[1], 1.0 + strength * (scores[zone][number] - 1.0)))
                for number in population
            }
            value[zone] = weighted_sample_without_replacement(rng, population, count, weights, strength, absolute=True)
        else:
            value[zone] = weighted_sample_without_replacement(rng, population, count, scores[zone], strength)
    return value


def format_zone(values: list[int]) -> str:
    return " ".join(f"{value:02d}" for value in values)


def display_number(game: str, value: dict[str, list[int]]) -> str:
    if game == "dlt":
        return f"前区 {format_zone(value['front'])} ｜ 后区 {format_zone(value['back'])}"
    return f"红球 {format_zone(value['red'])} ｜ 蓝球 {format_zone(value['blue'])}"


def generate(game: str, archive: dict[str, Any], count: int, mode: str, window: int, strength_name: str, seed: int | None, exclude: set[tuple[int, ...]], *, precomputed_scores: dict[str, dict[int, float]] | None = None, historical: set[tuple[int, ...]] | None = None) -> tuple[list[dict[str, list[int]]], int]:
    if count < 1 or count > 10:
        raise LotteryError("每种彩票单次注数必须在 1 到 10 之间")
    if mode not in GENERATION_MODES:
        raise LotteryError("模式必须是 random、hot 或 cold")
    if strength_name not in STRENGTHS:
        raise LotteryError("强度必须是 mild、medium 或 strong")
    actual_seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**63)
    rng = random.Random(actual_seed)
    draws = archive["draws"]
    existing = historical if historical is not None else historical_keys(game, draws)
    excluded = set(exclude)
    scores = precomputed_scores if precomputed_scores is not None else zone_scores(game, draws, mode, window)
    strength = SMOOTHED_HOT_STRENGTHS[strength_name] if mode == "hot" else STRENGTHS[strength_name]
    picked: list[dict[str, list[int]]] = []
    attempts = 0
    while len(picked) < count and attempts < 200_000:
        attempts += 1
        value = candidate(game, rng, mode, scores, strength)
        key = canonical_key(game, value)
        if key not in existing and key not in excluded:
            picked.append(value)
            excluded.add(key)
    if len(picked) != count:
        raise LotteryError("在有效候选集中无法生成足够的不重复组合")
    return picked, actual_seed


def stats_for_number(game: str, numbers: dict[str, list[int]], draws: list[dict[str, Any]], mode: str, window: int) -> dict[str, dict[str, int]]:
    if mode == "random":
        return {}
    scores = raw_hot_scores(game, draws, window) if mode == "hot" else zone_scores(game, draws, mode, window)
    return {zone: {f"{number:02d}": int(scores[zone][number]) for number in numbers[zone]} for zone, *_ in GAMES[game]["zones"]}


def past_recommendation_keys(data_dir: Path, game: str) -> set[tuple[int, ...]]:
    path = audit_path(data_dir)
    if not path.exists():
        return set()
    keys: set[tuple[int, ...]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("game") == game:
                keys.add(tuple(row["key"]))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return keys


def recommend(args: argparse.Namespace) -> dict[str, Any]:
    games = [args.game] if args.game else list(GAMES)
    data_dir = Path(args.data_dir)
    response_games = []
    unavailable = []
    audit_rows = []
    for game in games:
        try:
            sync_official_history(data_dir, game)
            archive = load_ready_archive(data_dir, game)
        except LotteryError as exc:
            record_sync_failure(data_dir, game, str(exc))
            unavailable.append({"game": game, "label": GAMES[game]["label"], "reason": str(exc)})
            continue
        exclude = past_recommendation_keys(data_dir, game) if args.avoid_history else set()
        numbers, seed = generate(game, archive, args.count, args.mode, args.window, args.strength, args.seed, exclude)
        latest = archive["draws"][-1]
        results = []
        for index, value in enumerate(numbers, start=1):
            result = {
                "index": index,
                "numbers": value,
                "display": display_number(game, value),
                "historically_unseen": True,
                "stats": stats_for_number(game, value, archive["draws"], args.mode, args.window),
            }
            results.append(result)
            audit_rows.append({
                "id": str(uuid.uuid4()), "generated_at": utc_now(), "game": game,
                "key": list(canonical_key(game, value)), "data_updated_at": archive.get("updated_at"),
                "data_version": archive.get("data_version"), "seed": seed,
                "history_coverage": archive.get("history_coverage"),
            })
        response_games.append({
            "game": game,
            "label": GAMES[game]["label"],
            "data_status": {
                "latest_issue": latest["issue"],
                "latest_date": latest["draw_date"],
                "updated_at": archive.get("updated_at"),
                "data_version": archive.get("data_version"),
                "history_coverage": archive.get("history_coverage"),
                "public_context": archive.get("public_context") or None,
            },
            "mode": args.mode,
            "window": args.window if args.mode in {"hot", "cold"} else None,
            "strength": args.strength if args.mode in {"hot", "cold"} else None,
            "hot_model": "多窗口平滑热度（0.25×/1×/2.5×窗口、有限偏向）" if args.mode == "hot" else None,
            "recommendations": results,
        })
    if audit_rows:
        audit = audit_path(data_dir)
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8") as handle:
            for row in audit_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if not response_games:
        reasons = "；".join(item["label"] + "：" + item["reason"] for item in unavailable)
        raise LotteryError(reasons or "没有可生成号码的彩票")
    return {"games": response_games, "unavailable_games": unavailable, "disclaimer": "仅供娱乐与参考，不保证中奖。"}


MODE_LABELS = {"random": "随机未出现组合", "hot": "热号倾向", "hot_legacy": "旧线性热号（仅回测）", "cold": "冷号倾向"}
STRENGTH_LABELS = {"mild": "轻度", "medium": "中等", "strong": "强"}


def coverage_text(coverage: dict[str, Any] | None, latest_issue: str | None, latest_date: str | None) -> str:
    if not coverage:
        return "历史范围未确认"
    prefix = "官网历史" if coverage.get("kind") == "official_available_history" else "官方历史"
    return f"{prefix} {coverage.get('from_issue')} 至 {latest_issue}（已校验，{latest_date}）"


def context_lines(context: dict[str, Any] | None) -> list[str]:
    if not context:
        return []
    lines = []
    pool = context.get("pool_balance_after_draw") or context.get("pool_balance")
    if pool:
        lines.append(f"官方奖池：{pool}")
    if context.get("add_money"):
        lines.append(f"官方加奖信息：{context['add_money']}")
    if context.get("promotion_flag"):
        lines.append(f"官方加奖标记：{context['promotion_flag']}")
    notice = context.get("draw_notice_url") or context.get("draw_notice_path")
    if notice:
        lines.append(f"官方开奖公告：{notice}")
    return lines


def stats_text(stats: dict[str, dict[str, int]], mode: str) -> str | None:
    if not stats:
        return None
    label = "热度" if mode == "hot" else "遗漏"
    zone_labels = {"front": "前区", "back": "后区", "red": "红球", "blue": "蓝球"}
    zones = "；".join(f"{zone_labels.get(zone, zone)} " + " ".join(f"{number}({value})" for number, value in values.items()) for zone, values in stats.items())
    return f"   {label}：{zones}"


def render_recommendation(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for game in result.get("games", []):
        status = game["data_status"]
        lines.append(f"{game['label']}｜{coverage_text(status.get('history_coverage'), status.get('latest_issue'), status.get('latest_date'))}")
        scope_note = "每注均未出现在上述官网可得历史区间" if (status.get("history_coverage") or {}).get("kind") == "official_available_history" else "每注均为历史未出现组合"
        mode = game["mode"]
        detail = MODE_LABELS[mode]
        if mode in {"hot", "cold"}:
            detail += f"（最近 {game['window']} 期，{STRENGTH_LABELS[game['strength']]}）"
        lines.append(f"模式：{detail}｜{scope_note}")
        if game.get("hot_model"):
            lines.append(f"热号模型：{game['hot_model']}")
        lines.extend(context_lines(status.get("public_context")))
        for recommendation in game["recommendations"]:
            lines.append(f"{recommendation['index']}. {recommendation['display']}")
            statistic = stats_text(recommendation.get("stats", {}), mode)
            if statistic:
                lines.append(statistic)
    for unavailable in result.get("unavailable_games", []):
        lines.append(f"{unavailable['label']}｜未生成：{unavailable['reason']}")
    lines.append(result.get("disclaimer", "仅供娱乐与参考，不保证中奖。"))
    return "\n".join(lines)


def render_status(result: dict[str, Any]) -> str:
    lines = []
    for game in result.get("games", []):
        if "status" in game:
            status = game["status"]
            error = game.get("error")
        else:
            status = game
            error = None
        state = "可用" if status.get("ready") else "不可用"
        range_text = coverage_text(status.get("history_coverage"), status.get("latest_issue"), status.get("latest_date"))
        lines.append(f"{status['label']}｜{state}｜{range_text}")
        if error or status.get("reason"):
            lines.append(f"原因：{error or status['reason']}")
    return "\n".join(lines)


def render_backtest(result: dict[str, Any]) -> str:
    lines = [f"{GAMES[result['game']]['label']}回测｜第 {result['from_issue']} 至 {result['to_issue']}｜{result['periods']} 期"]
    zone_labels = {"front": "前区", "back": "后区", "red": "红球", "blue": "蓝球"}
    for item in result["results"]:
        hits = "，".join(f"{zone_labels.get(zone, zone)} 平均命中 {value}" for zone, value in item["average_hits"].items())
        prizes = "，".join(f"{level} 等奖 {count} 次" for level, count in item["prize_hits"].items()) or "无奖级命中"
        comparison = item.get("relative_to_random")
        interval = ""
        if comparison:
            interval = "；相对随机 " + "，".join(
                f"{zone_labels.get(zone, zone)} {value['difference']:+.4f}（95% CI {value['ci95'][0]:+.4f} 至 {value['ci95'][1]:+.4f}）"
                for zone, value in comparison.items()
            )
        lines.append(f"{MODE_LABELS[item['mode']]}：{hits}；{prizes}{interval}")
    if result.get("trials_per_period"):
        lines.append(f"每期每策略 {result['trials_per_period']} 次抽样；置信区间使用 {result['bootstrap_samples']} 次区块自助法。")
    lines.append(result["note"])
    return "\n".join(lines)


def prize_level(game: str, predicted: dict[str, list[int]], actual: dict[str, Any]) -> int | None:
    if game == "ssq":
        red_hits = len(set(predicted["red"]) & set(actual["red"]))
        blue_hit = predicted["blue"][0] == actual["blue"][0]
        if red_hits == 6 and blue_hit: return 1
        if red_hits == 6: return 2
        if red_hits == 5 and blue_hit: return 3
        if red_hits == 5 or (red_hits == 4 and blue_hit): return 4
        if red_hits == 4 or (red_hits == 3 and blue_hit): return 5
        if blue_hit and red_hits <= 2: return 6
        return None
    front_hits = len(set(predicted["front"]) & set(actual["front"]))
    back_hits = len(set(predicted["back"]) & set(actual["back"]))
    mapping = {
        (5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 3, (4, 1): 4, (3, 2): 4,
        (4, 0): 5, (3, 1): 5, (2, 2): 5, (3, 0): 6, (2, 1): 6, (1, 2): 6,
        (2, 0): 7, (1, 1): 7, (0, 2): 7,
    }
    return mapping.get((front_hits, back_hits))


def issue_position(draws: list[dict[str, Any]], issue: str | None, default: int) -> int:
    if issue is None:
        return default
    for index, draw in enumerate(draws):
        if draw["issue"] == issue:
            return index
    raise LotteryError(f"历史中不存在第 {issue} 期")


def bootstrap_ci(values: list[float], samples: int, seed: int) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    length = len(values)
    for _ in range(samples):
        means.append(sum(values[rng.randrange(length)] for _ in range(length)) / length)
    means.sort()
    return (round(means[int((samples - 1) * 0.025)], 4), round(means[int((samples - 1) * 0.975)], 4))


def backtest(args: argparse.Namespace) -> dict[str, Any]:
    data_dir = Path(args.data_dir)
    sync_official_history(data_dir, args.game)
    archive = load_ready_archive(data_dir, args.game)
    draws = archive["draws"]
    # The longer DLT windows gracefully truncate to the available prior draws,
    # so one centre-window of history is sufficient for an out-of-sample step.
    warmup = max(args.window, 1)
    if len(draws) <= warmup:
        raise LotteryError("历史期数不足以回测")
    modes = ["random", "hot_legacy", "hot", "cold"]
    start_index = max(warmup, issue_position(draws, getattr(args, "from_issue", None), warmup))
    end_index = issue_position(draws, getattr(args, "to_issue", None), len(draws) - 1)
    if start_index > end_index:
        raise LotteryError("回测起始期不得晚于结束期")
    total_hits: dict[str, dict[str, float]] = {mode: {zone: 0.0 for zone, *_ in GAMES[args.game]["zones"]} for mode in modes}
    prize_hits: dict[str, Counter[int]] = {mode: Counter() for mode in modes}
    period_hits: dict[str, dict[str, list[float]]] = {mode: {zone: [] for zone, *_ in GAMES[args.game]["zones"]} for mode in modes}
    trials_per_period = getattr(args, "trials", 200)
    bootstrap_samples = getattr(args, "bootstrap_samples", 1000)
    if trials_per_period < 1 or bootstrap_samples < 1:
        raise LotteryError("回测 trials 和 bootstrap-samples 必须至少为 1")
    historical = historical_keys(args.game, draws[:start_index])
    trials = 0
    for index in range(start_index, end_index + 1):
        prior = {"draws": draws[:index]}
        actual = draws[index]
        for offset, mode in enumerate(modes):
            scores = zone_scores(args.game, prior["draws"], mode, args.window)
            one_period = {zone: 0.0 for zone, *_ in GAMES[args.game]["zones"]}
            for replicate in range(trials_per_period):
                seed = args.seed + index * 1_000_000 + replicate * 10 + offset
                numbers, _ = generate(args.game, prior, 1, mode, args.window, "medium", seed, set(), precomputed_scores=scores, historical=historical)
                for zone, *_ in GAMES[args.game]["zones"]:
                    one_period[zone] += len(set(numbers[0][zone]) & set(actual[zone]))
                level = prize_level(args.game, numbers[0], actual)
                if level is not None:
                    prize_hits[mode][level] += 1
            for zone, *_ in GAMES[args.game]["zones"]:
                average = one_period[zone] / trials_per_period
                total_hits[mode][zone] += average
                period_hits[mode][zone].append(average)
        historical.add(canonical_key(args.game, actual))
        trials += 1
    comparisons: dict[str, dict[str, dict[str, Any]]] = {}
    for mode in modes:
        if mode == "random":
            continue
        comparisons[mode] = {}
        for zone, *_ in GAMES[args.game]["zones"]:
            differences = [value - baseline for value, baseline in zip(period_hits[mode][zone], period_hits["random"][zone])]
            mode_offset = {"hot_legacy": 11, "hot": 23, "cold": 37}[mode]
            zone_offset = {name: position for position, (name, *_rest) in enumerate(GAMES[args.game]["zones"], start=1)}[zone]
            comparisons[mode][zone] = {
                "difference": round(sum(differences) / trials, 4),
                "ci95": bootstrap_ci(differences, bootstrap_samples, args.seed + mode_offset * 100 + zone_offset),
            }
    return {
        "game": args.game,
        "from_issue": draws[start_index]["issue"],
        "to_issue": draws[end_index]["issue"],
        "periods": trials,
        "seed": args.seed,
        "trials_per_period": trials_per_period,
        "bootstrap_samples": bootstrap_samples,
        "data_version": archive.get("data_version"),
        "results": [{
            "mode": mode,
            "average_hits": {zone: round(value / trials, 4) for zone, value in total_hits[mode].items()},
            "prize_hits": {str(level): round(prize_hits[mode][level] / trials_per_period, 4) for level in sorted(prize_hits[mode])},
            "relative_to_random": comparisons.get(mode),
        } for mode in modes],
        "note": "回测仅描述历史表现，不保证未来表现；只有相对随机的 95% 置信区间下界大于零，才可视为该历史划分下的改善。",
    }


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    """Inspect local capability and cached-history readiness without networking."""

    data_dir = Path(args.data_dir)
    games = {game: status_for_game(data_dir, game) for game in GAMES}
    ready_games = [game for game, item in games.items() if item.get("ready") is True]
    return {
        "schema_version": "1.0",
        "skill": "lottery-number-recommendation",
        "python": platform.python_version(),
        "standard_library_only": True,
        "network_tested": False,
        "data_dir": str(data_dir),
        "games": games,
        "ready_games": ready_games,
        "next_action": None if len(ready_games) == len(GAMES) else "运行 sync；若官方源失败，不生成号码。",
    }


def result_state(command: str, result: Any) -> tuple[str, str, str | None, str | None]:
    """Describe successful handler output without hiding partial failures."""

    if not isinstance(result, dict):
        return "completed", "validated_output", None, None
    if command == "doctor":
        ready = result.get("ready_games", [])
        if len(ready) < len(GAMES):
            return "degraded", "cache_not_ready", result.get("next_action"), "DATA_NOT_READY"
    if command == "status":
        games = result.get("games", [])
        if games and not all(item.get("ready") for item in games if isinstance(item, dict)):
            return "degraded", "data_not_ready", "运行 sync；失败的彩票不要生成号码。", "DATA_NOT_READY"
    if command == "sync":
        games = result.get("games", [])
        failures = [item for item in games if isinstance(item, dict) and item.get("error")]
        if failures:
            status = "blocked" if len(failures) == len(games) else "degraded"
            message = str(failures[0].get("error") or "")
            return status, "sync_failed" if status == "blocked" else "partial_sync", "检查官方源后重试；失败的彩票不要生成号码。", stable_error_code(message)
    if command == "recommend" and result.get("unavailable_games"):
        return "degraded", "partial_recommendation", "检查未就绪彩票的官方同步状态。", "PARTIAL_DATA_UNAVAILABLE"
    if command == "parse-request" and result.get("action") in {"clarify", "refuse"}:
        return "blocked", "request_needs_user_action", result.get("reason"), "REQUEST_CLARIFICATION_REQUIRED" if result.get("action") == "clarify" else "UNSAFE_PROMISE_REFUSED"
    return "completed", "validated_output", result.get("next_action"), None


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--data-dir", default="data/lottery-number-recommendation", help="本地数据目录")
    commands = root.add_subparsers(dest="command", required=True)
    health = commands.add_parser("doctor", help="检查本地能力和缓存状态（不联网）")
    health.set_defaults(handler=doctor)
    current_status = commands.add_parser("status", help="检查本地数据状态")
    current_status.add_argument("--game", choices=GAMES)
    current_status.add_argument("--output", choices=("json", "text"), default="json")
    current_status.set_defaults(handler=status)
    sync_command = commands.add_parser("sync", help="自动同步官方历史数据")
    sync_command.add_argument("--game", choices=GAMES)
    sync_command.add_argument("--output", choices=("json", "text"), default="json")
    sync_command.set_defaults(handler=sync)
    parse_command = commands.add_parser("parse-request", help="解析中文彩票请求")
    parse_command.add_argument("text")
    parse_command.set_defaults(handler=parse_request)
    rec = commands.add_parser("recommend", help="生成号码推荐")
    rec.add_argument("--game", choices=GAMES)
    rec.add_argument("--count", type=int, default=1)
    rec.add_argument("--mode", choices=MODES, default="random")
    rec.add_argument("--window", type=int, default=100)
    rec.add_argument("--strength", choices=STRENGTHS, default="medium")
    rec.add_argument("--seed", type=int)
    rec.add_argument("--avoid-history", action="store_true")
    rec.add_argument("--output", choices=("json", "text"), default="json")
    rec.set_defaults(handler=recommend)
    bt = commands.add_parser("backtest", help="运行可复现回测")
    bt.add_argument("game", choices=GAMES)
    bt.add_argument("--window", type=int, default=100)
    bt.add_argument("--seed", type=int, default=20260716)
    bt.add_argument("--from-issue")
    bt.add_argument("--to-issue")
    bt.add_argument("--trials", type=int, default=200, help="每期每策略的可复现抽样次数")
    bt.add_argument("--bootstrap-samples", type=int, default=1000, help="置信区间的区块自助法次数")
    bt.add_argument("--output", choices=("json", "text"), default="json")
    bt.set_defaults(handler=backtest)
    return root


def main() -> int:
    args = parser().parse_args()
    started = time.perf_counter()
    try:
        result = args.handler(args)
    except LotteryError as exc:
        message = str(exc)
        print(
            json.dumps(
                {
                    "ok": False,
                    "schema_version": "1.0",
                    "skill": "lottery-number-recommendation",
                    "command": args.command,
                    "status": "blocked",
                    "data_status": "operation_failed",
                    "next_action": "检查官方源、缓存完整性或请求参数后重试；不要生成兜底号码。",
                    "artifacts": [],
                    "warnings": [],
                    "error_code": stable_error_code(message),
                    "error": message,
                    "metrics": {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3)},
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if getattr(args, "output", "json") == "text":
        renderer = {"recommend": render_recommendation, "status": render_status, "sync": render_status, "backtest": render_backtest}
        print(renderer[args.command](result))
    else:
        status, data_status, next_action, error_code = result_state(args.command, result)
        print(
            json.dumps(
                {
                    "ok": True,
                    "schema_version": "1.0",
                    "skill": "lottery-number-recommendation",
                    "command": args.command,
                    "status": status,
                    "data_status": data_status,
                    "next_action": next_action,
                    "artifacts": [],
                    "warnings": [],
                    "error_code": error_code,
                    "metrics": {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3)},
                    "data": result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
