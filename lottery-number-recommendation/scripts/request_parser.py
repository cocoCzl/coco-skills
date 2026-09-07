"""Deterministic Chinese request parsing for the lottery agent entrypoint."""

from __future__ import annotations

import re
from typing import Any


GAME_TERMS = {"dlt": ("大乐透",), "ssq": ("双色球",)}
MODE_TERMS = {
    "random": ("随机", "未出现组合", "随便来"),
    "hot": ("热号", "高频号", "常出号码", "偏热", "强热"),
    "cold": ("冷号", "遗漏久", "很久没开", "偏冷", "强冷"),
}


def matched_games(text: str) -> list[str]:
    return [game for game, terms in GAME_TERMS.items() if any(term in text for term in terms)]


def game_positions(text: str, games: list[str]) -> list[int]:
    return sorted(text.find(term) for game in games for term in GAME_TERMS[game] if text.find(term) >= 0)


def request_segment(text: str, game: str, games: list[str]) -> str:
    positions = [text.find(term) for term in GAME_TERMS[game] if text.find(term) >= 0]
    if not positions:
        return text
    start = min(positions)
    later = [text.find(term, start + 1) for other in games if other != game for term in GAME_TERMS[other] if text.find(term, start + 1) >= 0]
    return text[start:min(later) if later else len(text)]


def is_common_match(match: re.Match[str], text: str, games: list[str]) -> bool:
    positions = game_positions(text, games)
    return bool(positions) and (match.start() < positions[0] or match.start() >= positions[-1])


def common_match(pattern: str, text: str, games: list[str]) -> re.Match[str] | None:
    matches = list(re.finditer(pattern, text))
    if len(matches) == 1 and is_common_match(matches[0], text, games):
        return matches[0]
    return None


def mode_matches(text: str) -> list[tuple[str, int]]:
    matches = []
    for mode, terms in MODE_TERMS.items():
        for term in terms:
            start = text.find(term)
            if start >= 0:
                matches.append((mode, start))
                break
    return matches


def parse_mode(text: str) -> str | None:
    modes = [mode for mode, terms in MODE_TERMS.items() if any(term in text for term in terms)]
    if len(modes) > 1:
        raise ValueError("随机、热号和冷号不能同时使用；请只选择一种模式")
    return modes[0] if modes else None


def parse_request_text(text: str, games_available: list[str]) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("请说明要查询的数据状态、回测，或大乐透/双色球选号请求")
    normalized = text.strip()
    if any(term in normalized for term in ("必中", "保证中奖", "保证盈利", "最大概率发财")):
        return {"action": "refuse", "reason": "无法提供保证中奖、盈利或最大概率的选号；可改为生成号码或运行历史回测"}
    games = matched_games(normalized)
    if any(term in normalized for term in ("数据状态", "检查数据", "同步历史数据")):
        return {"action": "status", "games": games or games_available}
    if any(term in normalized for term in ("回测", "效果", "统计")):
        if len(games) != 1:
            return {"action": "clarify", "reason": "回测请明确指定大乐透或双色球"}
        window_match = re.search(r"(?:最近)?\s*(\d+)\s*期", normalized)
        return {"action": "backtest", "game": games[0], "window": int(window_match.group(1)) if window_match else 100}
    if not games:
        return {"action": "clarify", "reason": "请明确指定大乐透、双色球，或同时说明两者"}
    common_mode = None
    all_mode_matches = mode_matches(normalized)
    if len(all_mode_matches) == 1:
        mode, _ = all_mode_matches[0]
        pseudo_match = re.search(re.escape(next(term for term in MODE_TERMS[mode] if term in normalized)), normalized)
        if pseudo_match and is_common_match(pseudo_match, normalized, games):
            common_mode = mode
    common_count_match = common_match(r"(\d+)\s*(?:注|组|串)", normalized, games)
    common_window_match = common_match(r"(?:最近)?\s*(\d+)\s*期", normalized, games)
    strength_pattern = r"强热|强冷|强烈|稍微|轻微"
    common_strength_match = common_match(strength_pattern, normalized, games)
    common_avoid_match = common_match(r"避开(?:以前|历史推荐|之前)", normalized, games)
    requests = []
    for game in games:
        segment = request_segment(normalized, game, games)
        mode = parse_mode(segment) or common_mode or "random"
        count_match = re.search(r"(\d+)\s*(?:注|组|串)", segment)
        count = int((count_match or common_count_match).group(1)) if count_match or common_count_match else 1
        if not 1 <= count <= 10:
            raise ValueError("每种彩票单次注数必须在 1 到 10 之间")
        window_match = re.search(r"(?:最近)?\s*(\d+)\s*期", segment)
        window = int((window_match or common_window_match).group(1)) if window_match or common_window_match else 100
        strength_text = segment if re.search(strength_pattern, segment) else (common_strength_match.group(0) if common_strength_match else "")
        strength = "strong" if any(term in strength_text for term in ("强热", "强冷", "强烈")) else "mild" if any(term in strength_text for term in ("稍微", "轻微")) else "medium"
        avoid_history = bool(re.search(r"避开" + r".*(?:以前|历史推荐|之前)", segment) or common_avoid_match)
        requests.append({"game": game, "count": count, "mode": mode, "window": window, "strength": strength, "avoid_history": avoid_history})
    return {"action": "recommend", "requests": requests}
