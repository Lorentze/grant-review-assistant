from __future__ import annotations

import re

from .text_utils import flatten_text


def detect_document_year(page_texts: list[str]) -> int | None:
    head = "\n".join(page_texts[:3])
    match = re.search(r"(20\d{2})\s*版", head)
    if match:
        return int(match.group(1))
    match = re.search(r"申报日期.*?(20\d{2})", flatten_text(head))
    return int(match.group(1)) if match else None


def detect_document_format(page_texts: list[str]) -> str:
    head = flatten_text("\n".join(page_texts[:8]))
    if "优秀青年科学基金项目(海外)" in head or "Excellent Young Scientists Fund Program(Overseas)" in head:
        return "nsfc_overseas_young"
    if "国家自然科学基金" in head and "申请书" in head:
        return "nsfc_standard"
    return "generic_pdf"
