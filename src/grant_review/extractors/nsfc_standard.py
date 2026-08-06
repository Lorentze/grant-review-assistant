from __future__ import annotations

from ..models import ApplicationRecord
from .common import (
    extract_budget,
    extract_common_cover,
    extract_cv_block,
    extract_sections_standard,
    extract_standard_basic_page,
    extract_team,
    parse_education_and_work,
    parse_funding,
    parse_publications,
)


def extract_nsfc_standard(source_file: str, page_texts: list[str]) -> ApplicationRecord:
    record = ApplicationRecord(source_file=source_file, document_format="NSFC通用申请书")
    full_text = "\n".join(page_texts)

    extract_common_cover(record, page_texts)
    extract_standard_basic_page(record, page_texts)
    cv_text = extract_cv_block(full_text, record.applicant_name)
    parse_education_and_work(record, cv_text, page_texts)
    parse_funding(record, cv_text)
    parse_publications(record, cv_text, full_text)
    extract_team(record, page_texts)
    extract_budget(record, page_texts)
    extract_sections_standard(record, full_text)

    if not record.publications:
        record.warnings.append("未能识别代表性论著条目，请人工核对简历版式")
    if record.team_total is None:
        record.warnings.append("未识别团队总人数；部分项目类型不提供团队表，此项可留空")
    return record
