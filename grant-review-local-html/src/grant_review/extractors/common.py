from __future__ import annotations

import re
from collections import Counter

from ..models import (
    ApplicationRecord,
    Budget,
    EducationEntry,
    Evidence,
    FundingEntry,
    PublicationEntry,
    WorkEntry,
)
from ..text_utils import (
    clean_cjk_value,
    clean_value,
    extract_between,
    find_page_for_value,
    first_match,
    flatten_text,
    normalize_text,
    parse_date_range,
    parse_number,
    split_numbered_entries,
    trim_page_noise,
)


def add_evidence(
    record: ApplicationRecord,
    page_texts: list[str],
    field_name: str,
    value: str | int | float | None,
    snippet: str = "",
    confidence: float = 0.9,
    method: str = "rule",
) -> None:
    if value in (None, ""):
        return
    page = find_page_for_value(page_texts, str(value))
    record.evidence.append(
        Evidence(
            field_name=field_name,
            value=value,
            page=page,
            snippet=trim_page_noise(snippet or str(value))[:500],
            confidence=confidence,
            method=method,
        )
    )


def cover_field(cover: str, label_pattern: str, stop_pattern: str = r"\n") -> tuple[str, str]:
    pattern = rf"{label_pattern}\s*[:：]\s*(.+?)(?={stop_pattern})"
    return first_match([cover], [pattern], cleaner=clean_cjk_value)


def extract_common_cover(record: ApplicationRecord, page_texts: list[str]) -> None:
    cover = page_texts[0] if page_texts else ""
    cover_flat = flatten_text(cover)

    code, raw = first_match(
        [cover],
        [r"申请代码(?:（[^）]*）|\([^)]*\))?\s*[:：]?\s*([A-Z]{1,3}\d{2,8}(?:\.\d+)?)"],
    )
    record.application_code = code
    add_evidence(record, page_texts, "申请代码", code, raw)

    no, raw = first_match(
        [cover],
        [r"接收编号(?:（[^）]*）|\([^)]*\))?\s*[:：]?\s*([A-Z0-9][A-Z0-9_-]{4,})"],
    )
    record.admission_no = no
    add_evidence(record, page_texts, "接收编号", no, raw)

    title, raw = first_match(
        [cover],
        [r"项目名称(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*([^\n]+)"],
        cleaner=clean_cjk_value,
    )
    record.project_title = title
    add_evidence(record, page_texts, "项目名称", title, raw)

    name, raw = first_match(
        [cover],
        [
            r"申\s*请\s*人(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*(.+?)(?=\s+BRID\s*[:：]|\n)",
        ],
        cleaner=clean_cjk_value,
    )
    record.applicant_name = name
    add_evidence(record, page_texts, "申请人", name, raw)

    brid, raw = first_match([cover], [r"BRID\s*[:：]\s*([0-9.]+)"])
    record.brid = brid
    add_evidence(record, page_texts, "BRID", brid, raw)

    institution, raw = first_match(
        [cover],
        [r"依托单位(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*([^\n]+)"],
        cleaner=clean_cjk_value,
    )
    record.current_institution = institution
    add_evidence(record, page_texts, "依托单位", institution, raw)

    program, raw = first_match([cover], [r"资助类别\s*[:：]\s*([^\n]*)"], cleaner=clean_cjk_value)
    record.program_type = program
    add_evidence(record, page_texts, "资助类别", program, raw)

    sub, raw = first_match([cover], [r"亚类说明\s*[:：]\s*([^\n]*)"], cleaner=clean_cjk_value)
    record.subcategory = sub
    add_evidence(record, page_texts, "亚类说明", sub, raw, confidence=0.85)

    note, raw = first_match([cover], [r"附注说明\s*[:：]\s*([^\n]*)"], cleaner=clean_cjk_value)
    record.special_note = note
    add_evidence(record, page_texts, "附注说明", note, raw, confidence=0.85)

    # 年份可能被排成“2 0 2 6 版”。
    year_match = re.search(r"[（(]\s*2\s*0\s*(\d)\s*(\d)\s*版\s*[)）]", cover)
    if year_match:
        record.document_year = int("20" + year_match.group(1) + year_match.group(2))
    else:
        year_match = re.search(r"NSFC\s*(20\d{2})", cover)
        if year_match:
            record.document_year = int(year_match.group(1))

    # 保留封面是否出现空字段的事实，不把空字段误判为缺失。
    if not record.applicant_name:
        record.warnings.append("未能从封面稳定提取申请人姓名，请人工核对")


def extract_standard_basic_page(record: ApplicationRecord, page_texts: list[str]) -> None:
    if len(page_texts) < 2:
        record.warnings.append("PDF 页数不足，无法读取基本信息页")
        return
    page = page_texts[1]
    flat = flatten_text(page)

    def get(patterns: list[str], cleaner=clean_cjk_value) -> tuple[str, str]:
        return first_match([flat], patterns, cleaner=cleaner)

    value, raw = get([r"出生\s*年月\s+([0-9]{4}年[0-9]{1,2}月|[0-9]{4}-[0-9]{2}-[0-9]{2})\s+民族"])
    record.birth_date = value
    add_evidence(record, page_texts, "出生年月", value, raw)

    value, raw = get([r"学\s*位\s+([^\s]+)\s+职称"])
    record.degree = value
    add_evidence(record, page_texts, "学位", value, raw)

    value, raw = get([r"职称\s+(.+?)(?=\s+是否在站博士后)"])
    record.current_title = value
    add_evidence(record, page_texts, "职称", value, raw)

    value, raw = get([r"工\s*作\s*单\s*位\s+(.+?)(?=\s+主\s*要\s*研\s*究\s*领\s*域)"])
    if value:
        pieces = value.split("/", 1)
        record.current_institution = clean_cjk_value(pieces[0]) or record.current_institution
        if len(pieces) > 1:
            record.department = clean_cjk_value(pieces[1])
    add_evidence(record, page_texts, "工作单位", value, raw)

    value, raw = get([r"主\s*要\s*研\s*究\s*领\s*域\s+(.+?)(?=\s+依\s*托\s*单\s*位\s*信\s*息)"])
    record.research_field = value
    add_evidence(record, page_texts, "主要研究领域", value, raw)

    # 项目基本信息区。
    value, raw = get([r"研究期限\s+(.+?)(?=\s+研究方向)"])
    record.research_period = value
    add_evidence(record, page_texts, "研究期限", value, raw)

    value, raw = get([r"研究方向\s*[:：]?\s*(.+?)(?=\s+申请直接费用)"])
    record.research_direction = value
    add_evidence(record, page_texts, "研究方向", value, raw)

    value, raw = get([r"申请直接费用\s+([0-9,.]+)\s*万元"], cleaner=clean_value)
    record.requested_amount_wan = parse_number(value)
    add_evidence(record, page_texts, "申请直接费用", record.requested_amount_wan, raw)

    value, raw = get([r"研究属性\s+(.+?)(?=\s+中文关键词)"])
    record.research_attribute = value
    add_evidence(record, page_texts, "研究属性", value, raw)

    value, raw = get([r"中文关键词\s+(.+?)(?=\s+英文关键词)"])
    record.keywords = value
    add_evidence(record, page_texts, "中文关键词", value, raw)

    # 第二页可对空的封面字段进行补充。
    if not record.program_type:
        value, _ = get([r"资助类别\s+(.+?)(?=\s+亚类说明)"])
        record.program_type = value
    if not record.subcategory:
        value, _ = get([r"亚类说明\s+(.+?)(?=\s+附注说明)"])
        record.subcategory = value
    if not record.special_note:
        value, _ = get([r"附注说明\s+(.+?)(?=\s+申请代码)"])
        record.special_note = value

    # 合作单位：表格中位于“单位名称”和“项目基本信息”之间。
    partners_block = extract_between(
        page,
        [r"合\s*作\s*研\s*究\s*单\s*位\s*信\s*息.*?单\s*位\s*名\s*称"],
        [r"项\s*目\s*基\s*本\s*信\s*息"],
    )
    partners = []
    for line in normalize_text(partners_block).splitlines():
        line = clean_cjk_value(line)
        if line and line not in {"单位名称", "合作研究单位信息"}:
            partners.extend([clean_cjk_value(x) for x in re.split(r"\|\||；|;", line) if clean_cjk_value(x)])
    record.partner_institutions = list(dict.fromkeys(partners))


def extract_cv_block(full_text: str, applicant_name: str) -> str:
    if not applicant_name:
        return ""
    pattern = re.compile(
        rf"(?:20\d{{2}}版\s*)?{re.escape(applicant_name)}\s*\(\s*BRID\s*[:：]\s*[^)]*\)\s*简历",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(full_text)
    if not match:
        return ""
    tail = full_text[match.start() :]

    end_candidates = []
    # 下一位参与者简历。
    next_cv = re.search(
        r"\n\s*20\d{2}版\s*\n\s*[^\n]{2,40}\s*\n\s*\(\s*BRID\s*[:：]",
        tail[match.end() - match.start() :],
        re.IGNORECASE | re.DOTALL,
    )
    if next_cv:
        end_candidates.append(match.end() - match.start() + next_cv.start())
    for marker in [r"\n附件信息", r"\n报告正文", r"\n项目名称：.*?科研诚信承诺书"]:
        m = re.search(marker, tail, re.IGNORECASE | re.DOTALL)
        if m and m.start() > 100:
            end_candidates.append(m.start())
    end = min(end_candidates) if end_candidates else len(tail)
    return tail[:end].strip()


def parse_education_and_work(record: ApplicationRecord, cv_text: str, page_texts: list[str]) -> None:
    if not cv_text:
        record.warnings.append("未找到申请人简历区，教育、工作和成果信息可能不完整")
        return

    education_block = extract_between(
        cv_text,
        [r"教育经历\s*[:：]"],
        [r"博士后工作经历\s*[:：]", r"科研与学术工作经历"],
    )
    for _, entry in split_numbered_entries(education_block):
        flat = flatten_text(entry).replace("，", ",")
        start, end = parse_date_range(flat)
        # 标准格式：日期, 学校, 专业, 学位
        no_dates = re.sub(
            r"(?:19|20)\d{2}-\d{2}\s*至\s*(?:(?:19|20)\d{2}-\d{2}|今)",
            "",
            flat,
        ).strip(" ,")
        parts = [clean_cjk_value(x) for x in no_dates.split(",") if clean_cjk_value(x)]
        institution = parts[0] if parts else ""
        major = parts[1] if len(parts) > 1 else ""
        degree = parts[2] if len(parts) > 2 else ""
        if not degree:
            dm = re.search(r"(博士|硕士|学士|本科|其他)\s*$", flat)
            degree = dm.group(1) if dm else ""
        if institution:
            record.education.append(
                EducationEntry(
                    level=degree,
                    institution=institution,
                    major=major,
                    start=start,
                    end=end,
                    raw=flat,
                )
            )

    postdoc_block = extract_between(
        cv_text,
        [r"博士后工作经历\s*[:：]"],
        [r"科研与学术工作经历"],
    )
    for _, entry in split_numbered_entries(postdoc_block):
        flat = flatten_text(entry).replace("，", ",")
        start, end = parse_date_range(flat)
        no_dates = re.sub(
            r"(?:19|20)\d{2}-\d{2}\s*至\s*(?:(?:19|20)\d{2}-\d{2}|今)",
            "",
            flat,
        ).strip(" ,")
        parts = [clean_cjk_value(x) for x in no_dates.split(",") if clean_cjk_value(x)]
        institution = parts[0] if parts else ""
        if institution and institution != "无":
            record.work_history.append(
                WorkEntry(
                    institution=institution,
                    title="博士后",
                    start=start,
                    end=end,
                    category="postdoc",
                    raw=flat,
                )
            )

    work_block = extract_between(
        cv_text,
        [r"科研与学术工作经历(?:（[^）]*）|\([^)]*\))?\s*[:：]"],
        [r"曾使用其他证件信息", r"近五年主持或参加"],
    )
    for _, entry in split_numbered_entries(work_block):
        flat = flatten_text(entry).replace("，", ",")
        start, end = parse_date_range(flat)
        no_dates = re.sub(
            r"(?:19|20)\d{2}-\d{2}\s*至\s*(?:(?:19|20)\d{2}-\d{2}|今)",
            "",
            flat,
        ).strip(" ,")
        parts = [clean_cjk_value(x) for x in no_dates.split(",") if clean_cjk_value(x)]
        parts = [x for x in parts if x not in {"全职", "兼职", "访问", "实习"}]
        if not parts:
            continue
        institution = parts[0]
        department = parts[1] if len(parts) > 2 else ""
        title = parts[-1] if len(parts) > 1 else ""
        record.work_history.append(
            WorkEntry(
                institution=institution,
                department=department,
                title=title,
                start=start,
                end=end,
                category="work",
                raw=flat,
            )
        )

    # 用简历中“至今”的条目校正当前职称与单位。
    current_entries = [x for x in record.work_history if x.category == "work" and x.end in {"今", "现在", "目前"}]
    if current_entries:
        current = current_entries[0]
        record.current_institution = current.institution or record.current_institution
        record.department = current.department or record.department
        record.current_title = current.title or record.current_title

    add_evidence(record, page_texts, "博士毕业单位", record.phd_institution(), record.phd_institution())
    add_evidence(record, page_texts, "博士后单位", record.postdoc_institutions(), record.postdoc_institutions())


def classify_program_type(text: str) -> str:
    aliases = [
        "国家杰出青年科学基金",
        "杰出青年科学基金",
        "优秀青年科学基金项目（海外）",
        "优秀青年科学基金",
        "青年科学基金项目（C类）",
        "青年科学基金项目",
        "面上项目",
        "重点项目",
        "重大项目",
        "联合基金项目",
        "专项项目",
        "地区科学基金项目",
        "创新研究群体项目",
        "国际（地区）合作与交流项目",
        "中国博士后科学基金",
    ]
    for alias in aliases:
        if alias in text:
            return alias
    # 保留逗号前后常见类型文本。
    parts = [clean_cjk_value(x) for x in text.replace("，", ",").split(",")]
    return parts[1] if len(parts) > 1 else ""


def parse_funding_entry(raw: str, source_type: str) -> FundingEntry:
    flat = flatten_text(raw).replace("，", ",")
    flat = re.sub(r"(?<=\d)-\s+(?=\d)", "-", flat)
    role = "主持" if re.search(r"(?:^|,)\s*(?:主持|负责人|项目负责人)\s*$", flat) else ""
    if not role and re.search(r"(?:^|,)\s*(?:参与|参加|项目骨干)\s*$", flat):
        role = "参与"

    status = ""
    for candidate in ["在研", "结题", "资助期满", "已结题", "完成", "执行中"]:
        if candidate in flat:
            status = candidate
            break

    start, end = parse_date_range(flat)
    amount_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万元", flat)
    amount = float(amount_match.group(1)) if amount_match else None

    # 批准号通常位于项目类型之后、项目名称之前。
    grant_match = re.search(r"(?:^|,)\s*([A-Z0-9-]{6,18})\s*,", flat, re.IGNORECASE)
    grant_no = grant_match.group(1) if grant_match else ""

    agency = ""
    first_piece = clean_cjk_value(flat.split(",", 1)[0])
    if first_piece and not first_piece.startswith(("国家自然科学基金委员会", "中国博士后科学基金会")):
        agency = first_piece
    elif first_piece:
        agency = first_piece

    program_type = classify_program_type(flat)

    title = ""
    if grant_match:
        after = flat[grant_match.end() :]
        # 标题止于日期范围。
        dm = re.search(r"(?=(?:19|20)\d{2}-\d{2}(?:-\d{2})?\s*至)", after)
        title = clean_cjk_value(after[: dm.start()] if dm else after.split(",", 1)[0])
    else:
        # 无批准号的省部级项目：从第二或第三字段取标题。
        pieces = [clean_cjk_value(x) for x in flat.split(",") if clean_cjk_value(x)]
        if len(pieces) >= 3:
            title = pieces[2]
        elif len(pieces) >= 2:
            title = pieces[1]

    return FundingEntry(
        source_type=source_type,
        agency=agency,
        program_type=program_type,
        grant_no=grant_no,
        title=title,
        start=start,
        end=end,
        amount_wan=amount,
        status=status,
        role=role,
        raw=flat,
    )


def parse_funding(record: ApplicationRecord, cv_text: str) -> None:
    if not cv_text:
        return
    nsfc_block = extract_between(
        cv_text,
        [r"近五年主持或参加的国家自然科学基金项目/课题\s*[:：]"],
        [r"近五年主持或参加的其他科研项目/课题", r"代表性研究成果和学术奖励情况"],
    )
    other_block = extract_between(
        cv_text,
        [r"近五年主持或参加的其他科研项目/课题(?:（[^）]*）|\([^)]*\))?\s*[:：]"],
        [r"代表性研究成果和学术奖励情况"],
    )

    items: list[FundingEntry] = []
    for _, raw in split_numbered_entries(nsfc_block):
        items.append(parse_funding_entry(raw, "NSFC"))
    for _, raw in split_numbered_entries(other_block):
        items.append(parse_funding_entry(raw, "其他"))

    deduped: dict[str, FundingEntry] = {}
    for item in items:
        if item.role not in {"主持", "参与"}:
            # 不猜测角色，保留但提示人工核对。
            record.warnings.append(f"基金项目角色未识别：{item.grant_no or item.title or item.raw[:40]}")
        deduped[item.identity()] = item
    record.funding = list(deduped.values())


def split_publication_entries(block: str) -> list[tuple[int | None, str]]:
    """按论文条目切分。条目编号后必须紧跟作者文字，避免把卷(期)号误切为新论文。"""
    block = normalize_text(block)
    pattern = re.compile(
        r"(?:^|\n)\s*[（(]\s*(\d+)\s*[)）]\s*(?=[A-Za-z\u3400-\u9fff])",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(block))
    entries: list[tuple[int | None, str]] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        raw = block[match.end():end].strip()
        if raw:
            entries.append((int(match.group(1)), raw))
    return entries


def parse_publication_entry(sequence: int | None, raw: str, is_representative: bool) -> PublicationEntry:
    flat = flatten_text(trim_page_noise(raw))
    role_match = re.search(
        r"本\s*人\s*标注\s*[:：]\s*(.+?)(?=\s*本\s*人\s*贡献\s*[:：]|$)",
        flat,
        re.IGNORECASE,
    )
    role = clean_value(role_match.group(1)) if role_match else ""
    role = re.sub(r"\s+", "", role).rstrip(")）")
    contribution_match = re.search(r"本\s*人\s*贡献\s*[:：]\s*(.+)$", flat, re.IGNORECASE | re.DOTALL)
    contribution = clean_value(contribution_match.group(1)) if contribution_match else ""

    citation = flat
    citation = re.sub(r"\s*\(期刊论文\).*", "", citation, flags=re.IGNORECASE | re.DOTALL)
    citation = clean_value(citation)

    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", citation)]
    year = years[-1] if years else None

    journal = ""
    title = ""
    if year:
        prefix = citation[: citation.rfind(str(year))].rstrip(" ,，;；")
        # 期刊通常是年份前最后一个逗号分隔项。
        parts = [clean_value(x) for x in re.split(r"[,，]", prefix) if clean_value(x)]
        if parts:
            journal = parts[-1]
            before_journal = prefix[: prefix.rfind(parts[-1])].rstrip(" ,，;；") if parts[-1] in prefix else ""
            # 作者使用分号分隔，标题通常位于最后一个分号之后。
            title = clean_value(before_journal.rsplit(";", 1)[-1].rsplit("；", 1)[-1])
    return PublicationEntry(
        sequence=sequence,
        citation=citation,
        title=title,
        journal=journal,
        year=year,
        role_label=role,
        is_first_author="第一作者" in role,
        is_corresponding_author="通讯作者" in role,
        is_representative=is_representative,
        applicant_contribution=contribution,
        raw=flat,
    )


def parse_publications(record: ApplicationRecord, cv_text: str, full_text: str) -> None:
    if not cv_text:
        return

    representative_block = extract_between(
        cv_text,
        [r"一[、.]\s*(?:近\s*5\s*年内发表的)?代表性论著[^：:]*[:：]"],
        [r"二[、.]\s*已发表的其余论著", r"二[、.]\s*论著之外"],
    )
    remaining_block = extract_between(
        cv_text,
        [r"二[、.]\s*已发表的其余论著\s*[:：]"],
        [r"三[、.]\s*论著之外"],
    )

    publications: list[PublicationEntry] = []
    for sequence, raw in split_publication_entries(representative_block):
        publications.append(parse_publication_entry(sequence, raw, True))
    for sequence, raw in split_publication_entries(remaining_block):
        publications.append(parse_publication_entry(sequence, raw, False))
    record.publications = publications

    # 申请书自述总量。只读取含“发表/论文”的明确句子，不从参考文献数推断。
    flat = flatten_text(trim_page_noise(full_text))
    total_candidates: list[int] = []
    for pattern in [
        r"(?:共|累计)(?:发表|已发表)[^。；;]{0,60}?(?:论文|论著)\s*(?:共计)?\s*(\d+)\s*篇",
        r"(?:相关成果|申请人)[^。；;]{0,40}?(?:发表|已发表)[^。；;]{0,40}?\s*(\d+)\s*篇",
        r"(?:在)?\s*SCI\s*(?:期刊)?(?:上)?发表(?:收录)?论文\s*共计\s*(\d+)\s*篇",
        r"共发表高水平论文\s*(\d+)\s*篇",
        r"共发表[^。；;]{0,25}?论文\s*(\d+)\s*篇",
    ]:
        total_candidates.extend(int(x) for x in re.findall(pattern, flat, re.IGNORECASE))
    if total_candidates:
        # 一份申请书可能同时写“近五年8篇”和“共11篇”；总表采用最大明确值。
        record.self_reported_publication_total = max(total_candidates)

    first_corr_candidates: list[int] = []
    for pattern in [
        r"其中(?:以)?第一(?:或|/)?通讯作者(?:论文)?\s*(?:共计)?\s*(\d+)\s*篇",
        r"第一(?:或|/)?通讯作者论文\s*(?:共计)?\s*(\d+)\s*篇",
    ]:
        first_corr_candidates.extend(int(x) for x in re.findall(pattern, flat, re.IGNORECASE))
    if first_corr_candidates:
        record.self_reported_first_corr_total = max(first_corr_candidates)


def extract_team(record: ApplicationRecord, page_texts: list[str]) -> None:
    for page in page_texts[:8]:
        if "总人数统计" not in page:
            continue
        flat = flatten_text(page)
        # 以表头“其他”后的数字为准；只可靠提取前两列（总人数、高级职称）。
        match = re.search(r"总人数统计.*?总人数.*?其他\s+(\d+)\s+(\d+)", flat, re.DOTALL)
        if match:
            record.team_total = int(match.group(1))
            record.team_senior = int(match.group(2))
            return
        # 备用：页内表头结束后的第一组数字。
        tail_match = re.search(r"总人数\s+高级职称.*?其他\s+([0-9\s]+?)(?=NSFC|第\s*\d+\s*页|$)", flat)
        if tail_match:
            nums = [int(x) for x in re.findall(r"\d+", tail_match.group(1))]
            if nums:
                record.team_total = nums[0]
            if len(nums) > 1:
                record.team_senior = nums[1]
            return


def extract_budget(record: ApplicationRecord, page_texts: list[str]) -> None:
    budget_text = "\n".join(page_texts[:12])
    flat = flatten_text(budget_text)

    def amount(patterns: list[str]) -> float | None:
        value, _ = first_match([flat], patterns, cleaner=clean_value)
        return parse_number(value)

    record.budget = Budget(
        direct_cost_wan=amount(
            [
                r"(?:科学基金资助项目直接费用合计|科学基金资助项目直接费用合计)\s+([0-9,.]+)",
                r"申请直接费用\s+([0-9,.]+)\s*万元",
            ]
        ),
        equipment_wan=amount([r"(?:设备费|1\.1设备费)\s+([0-9,.]+)"]),
        business_wan=amount([r"(?:业务费|1\.2\s*业务费)\s+([0-9,.]+)"]),
        labor_wan=amount([r"(?:劳务费|1\.3\s*劳务费)\s+([0-9,.]+)"]),
        transfer_wan=amount(
            [
                r"(?:合作研究外拨资金|直接费用中合作研究转拨资金)\s+([0-9,.]+)",
                r"直接费用中合作研究转拨资金\s+([0-9,.]+)",
            ]
        ),
        other_source_wan=amount([r"其他来源资金\s+([0-9,.]+)"]),
    )
    if record.requested_amount_wan is None:
        record.requested_amount_wan = record.budget.direct_cost_wan


def extract_sections_standard(record: ApplicationRecord, full_text: str) -> None:
    # 这些区块供 AI 初评使用，不进入总表摘要列。
    aliases: dict[str, tuple[list[str], list[str]]] = {
        "立项依据": (
            [r"(?:（一）|\(一\))\s*立项依据(?:与研究内容)?"],
            [r"(?:（二）|\(二\))\s*(?:研究内容|研究基础)"],
        ),
        "研究内容": (
            [r"(?:（二）|\(二\))\s*研究内容"],
            [r"(?:（三）|\(三\))\s*研究基础"],
        ),
        "研究基础": (
            [r"(?:（三）|\(三\))\s*研究基础"],
            [r"(?:（四）|\(四\))\s*其他需要说明"],
        ),
        "创新点": (
            [r"(?:本项目的)?特色与创新(?:之处|点)\s*[:：;；]?"],
            [r"年度研究计划", r"预期研究结果", r"研究计划及预期"],
        ),
        "工作条件": (
            [r"工作条件(?:（[^）]*）|\([^)]*\))?\s*[:：;；]?"],
            [r"正在承担的与本项目相关", r"完成国家自然科学基金项目情况"],
        ),
    }
    for key, (starts, ends) in aliases.items():
        block = extract_between(full_text, starts, ends)
        if block:
            record.sections[key] = trim_page_noise(block)

    # 2025 版把研究内容、目标、科学问题放在立项依据大节内部，补充精确区块。
    block = extract_between(
        full_text,
        [r"2[.．]\s*项目的研究内容、研究目标，以及拟解决的关键科学问题"],
        [r"3[.．]\s*拟采取的研究方案", r"3[.．]\s*研究方案"],
    )
    if block:
        record.sections["研究内容与目标"] = trim_page_noise(block)
    block = extract_between(
        full_text,
        [r"3[.．]\s*拟采取的研究方案及可行性分析"],
        [r"4[.．]\s*本项目的特色与创新之处"],
    )
    if block:
        record.sections["研究方案与可行性"] = trim_page_noise(block)


def publication_year_distribution(record: ApplicationRecord) -> str:
    counter = Counter(x.year for x in record.publications if x.year)
    return "、".join(f"{year}:{count}" for year, count in sorted(counter.items(), reverse=True))
