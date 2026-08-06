from __future__ import annotations

import re

from ..models import ApplicationRecord, WorkEntry
from ..text_utils import clean_cjk_value, clean_value, extract_between, first_match, flatten_text, trim_page_noise
from .common import (
    add_evidence,
    extract_common_cover,
    extract_cv_block,
    parse_education_and_work,
    parse_funding,
    parse_publications,
)


def extract_nsfc_overseas(source_file: str, page_texts: list[str]) -> ApplicationRecord:
    record = ApplicationRecord(source_file=source_file, document_format="优秀青年科学基金项目（海外）")
    full_text = "\n".join(page_texts)
    extract_common_cover(record, page_texts)
    record.program_type = "优秀青年科学基金项目（海外）"

    if len(page_texts) > 1:
        basic = flatten_text(page_texts[1])

        value, raw = first_match(
            [basic],
            [r"Date\s+of\s+Birth\s+([0-9]{4}-[0-9]{2}-[0-9]{2})"],
            cleaner=clean_value,
        )
        record.birth_date = value
        add_evidence(record, page_texts, "出生日期", value, raw)

        value, raw = first_match(
            [basic],
            [r"Degree\s+(.+?)(?=\s+电话|\s+Telephone\s+No)"],
            cleaner=clean_cjk_value,
        )
        record.degree = value
        add_evidence(record, page_texts, "学位", value, raw)

        value, raw = first_match(
            [basic],
            [
                r"Proposed\s+employer\s+(.+?)(?=\s+拟任职单位所在省份|\s+Province\s+of\s+the\s+proposed)",
            ],
            cleaner=clean_cjk_value,
        )
        record.proposed_institution = value
        add_evidence(record, page_texts, "拟任职单位", value, raw)

        value, raw = first_match(
            [basic],
            [
                r"Proposed\s+professional\s+or\s+academic\s+title/rank\s+(.+?)(?=\s+\(拟\)全职回国工作时间|\s+\(Proposed\)Date)",
            ],
            cleaner=clean_cjk_value,
        )
        record.proposed_title = value
        add_evidence(record, page_texts, "拟任专业技术职务", value, raw)

        value, raw = first_match(
            [basic],
            [r"\(Proposed\)Date\s+of\s+full-time\s+return\s+to\s+China\s+([0-9]{4}-[0-9]{2}-[0-9]{2})"],
            cleaner=clean_value,
        )
        record.return_date = value
        add_evidence(record, page_texts, "全职回国时间", value, raw)

        value, raw = first_match(
            [basic],
            [r"Research\s+Fields\s+(.+?)(?=\s+NSFC\s*20\d{2})"],
            cleaner=clean_cjk_value,
        )
        record.research_direction = value
        record.research_field = value
        add_evidence(record, page_texts, "研究方向", value, raw)

    if len(page_texts) > 2:
        page3 = flatten_text(page_texts[2])
        value, raw = first_match(
            [page3],
            [r"专业领域\s+Area\s+of\s+Specialization\s+(.+?)(?=\s+研究类型)"],
            cleaner=clean_cjk_value,
        )
        if value:
            record.research_field = value
            add_evidence(record, page_texts, "专业领域", value, raw)
        value, raw = first_match(
            [page3],
            [r"研究类型\s+Research\s+Type\s+(.+?)(?=\s+中文关键词)"],
            cleaner=clean_cjk_value,
        )
        record.research_attribute = value
        add_evidence(record, page_texts, "研究类型", value, raw)
        value, raw = first_match(
            [page3],
            [r"中文关键词\s+Keywords\s+(.+?)(?=\s+NSFC\s*20\d{2})"],
            cleaner=clean_cjk_value,
        )
        record.keywords = value
        add_evidence(record, page_texts, "中文关键词", value, raw)

    cv_text = extract_cv_block(full_text, record.applicant_name)
    parse_education_and_work(record, cv_text, page_texts)
    parse_funding(record, cv_text)
    parse_publications(record, cv_text, full_text)

    # 海外优青基本信息页给出了回国前博士后单位，即使简历博士后区不完整也保留。
    if not record.postdoc_institutions() and len(page_texts) > 1:
        basic = flatten_text(page_texts[1])
        employer, _ = first_match(
            [basic],
            [
                r"Name\s+of\s+Employer\s+before\s+returning/coming\s+to\s+China\s+(.+?)(?=\s+回国\(来华\)前专业技术职务)",
            ],
            cleaner=clean_cjk_value,
        )
        before_title, _ = first_match(
            [basic],
            [
                r"Professional\s+or\s+academic\s+title/rank\s+before\s+returning/coming\s+to\s+China\s+(.+?)(?=\s+University\s+of|\s+回国\(来华\)前任职单位类型)",
            ],
            cleaner=clean_cjk_value,
        )
        if employer and ("博士后" in before_title or "Postdoc" in before_title):
            record.work_history.append(WorkEntry(institution=employer, title="博士后", category="postdoc", raw=employer))

    # 海外优青正文结构。
    academic = extract_between(
        full_text,
        [r"(?:（一）|\(一\))\s*主要学术成绩"],
        [r"(?:（二）|\(二\))\s*全职回国"],
    )
    future = extract_between(
        full_text,
        [r"(?:（二）|\(二\))\s*全职回国(?:（来华）|\(来华\))?后拟开展的研究工作"],
        [r"(?:（三）|\(三\))\s*其他需要说明"],
    )
    if academic:
        record.sections["主要学术成绩"] = trim_page_noise(academic)
    if future:
        record.sections["拟开展研究工作"] = trim_page_noise(future)

    if record.proposed_institution and not record.current_institution:
        record.current_institution = record.proposed_institution
    if not record.publications:
        record.warnings.append("未能识别代表性论著条目，请人工核对")
    return record
