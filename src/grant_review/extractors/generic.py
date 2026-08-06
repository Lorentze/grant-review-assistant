from __future__ import annotations

from ..models import ApplicationRecord
from .common import extract_common_cover


def extract_generic(source_file: str, page_texts: list[str]) -> ApplicationRecord:
    record = ApplicationRecord(source_file=source_file, document_format="通用PDF（低置信度）")
    extract_common_cover(record, page_texts)
    record.warnings.append("未识别为已支持的基金申请书格式，仅提取了封面通用字段")
    return record
