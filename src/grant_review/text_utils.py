from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\xad", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def flatten_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def compact_label_text(text: str) -> str:
    """用于标签匹配：去除汉字间空白，但保留正文的英文空格。"""
    text = normalize_text(text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    return text


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    value = flatten_text(value)
    value = value.strip(" \t\n\r:：,，;；。")
    return value


def clean_cjk_value(value: str | None) -> str:
    value = clean_value(value)
    if not value:
        return ""
    value = re.sub(r"(?<=[\u3400-\u9fff)）])\s+(?=[\u3400-\u9fff(（])", "", value)
    value = re.sub(r"(?<=[(（])\s+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[)）])", "", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\((?=[\u3400-\u9fff])", "（", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])\)(?=[\u3400-\u9fff])", "）", value)
    return value


def first_match(
    texts: Iterable[str],
    patterns: Iterable[str],
    *,
    flags: int = re.IGNORECASE | re.DOTALL,
    cleaner=clean_value,
) -> tuple[str, str]:
    for text in texts:
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, flags)
            if match:
                value = cleaner(match.group(1))
                if value:
                    return value, match.group(0)
    return "", ""


def extract_between(
    text: str,
    start_patterns: Iterable[str],
    end_patterns: Iterable[str],
    *,
    flags: int = re.IGNORECASE | re.DOTALL,
) -> str:
    start_match = None
    for pattern in start_patterns:
        match = re.search(pattern, text, flags)
        if match and (start_match is None or match.start() < start_match.start()):
            start_match = match
    if not start_match:
        return ""

    tail = text[start_match.end() :]
    positions: list[int] = []
    for pattern in end_patterns:
        match = re.search(pattern, tail, flags)
        if match:
            positions.append(match.start())
    if positions:
        tail = tail[: min(positions)]
    return tail.strip()


def split_numbered_entries(block: str) -> list[tuple[int | None, str]]:
    """按行首的 (1)/(2) 切分，避免把卷期号 20(10) 误识别为新条目。"""
    block = normalize_text(block)
    pattern = re.compile(r"(?:^|\n)\s*[（(]\s*(\d+)\s*[)）]\s*", re.MULTILINE)
    matches = list(pattern.finditer(block))
    if not matches:
        return []
    entries: list[tuple[int | None, str]] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        raw = block[match.end() : end].strip()
        if raw:
            entries.append((int(match.group(1)), raw))
    return entries


def parse_date_range(text: str) -> tuple[str, str]:
    match = re.search(
        r"((?:19|20)\d{2}[-./年]\d{1,2}(?:[-./月]\d{1,2})?)\s*(?:至|--|—|–|~|～)\s*((?:19|20)\d{2}[-./年]\d{1,2}(?:[-./月]\d{1,2})?|今|现在|目前)",
        text,
    )
    if not match:
        return "", ""
    return clean_value(match.group(1)), clean_value(match.group(2))


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group(0)) if match else None


def find_page_for_value(page_texts: list[str], value: str) -> int | None:
    if not value:
        return None
    needle = flatten_text(value)
    if not needle:
        return None
    for idx, page in enumerate(page_texts, start=1):
        if needle in flatten_text(page):
            return idx
        # 长文本只用前 60 字符定位。
        if len(needle) > 60 and needle[:60] in flatten_text(page):
            return idx
    return None


def trim_page_noise(text: str) -> str:
    text = re.sub(r"NSFC\s*20\d{2}", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"第\s*\d+\s*页", " ", text)
    text = re.sub(r"国家自然科学基金申请书(?:NSFC Grant Proposal)?\s*20\d{2}版", " ", text)
    text = re.sub(r"版本\s*[:：]\s*\d+", " ", text)
    return clean_value(text)


def crop(text: str, max_chars: int = 8000) -> str:
    text = clean_value(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "……"
