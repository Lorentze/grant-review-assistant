from __future__ import annotations

import re
from typing import Any

from .models import AIReview, ApplicationRecord
from .text_utils import clean_value, crop


def _first_sentences(text: str, max_chars: int = 260) -> str:
    text = clean_value(text)
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    parts = re.split(r"(?<=[。！？；])", text)
    selected: list[str] = []
    length = 0
    for part in parts:
        if not part:
            continue
        if length + len(part) > max_chars and selected:
            break
        selected.append(part)
        length += len(part)
        if length >= max_chars:
            break
    return crop("".join(selected), max_chars)


def _section(record: ApplicationRecord, *names: str) -> str:
    for name in names:
        value = record.sections.get(name, "")
        if value:
            return value
    return ""


def generate_rule_initial_review(record: ApplicationRecord, guide: str = "") -> AIReview:
    strengths: list[str] = []
    weaknesses: list[str] = []
    risks: list[str] = []
    gaps: list[str] = []

    research_text = _first_sentences(
        _section(record, "创新点", "研究内容与目标", "研究内容", "拟开展研究工作"), 320
    )
    if research_text:
        strengths.append(
            f"申请书围绕“{record.project_title or '拟申报课题'}”给出了较为完整的研究设想，核心内容可概括为：{research_text}"
        )
    else:
        gaps.append("未能稳定提取研究内容或创新点区块，需人工查看原文。")

    if record.funding:
        strengths.append(f"申请书所列科研项目经历为：{record.funding_summary()}。")
    else:
        gaps.append("未识别到基金主持或参与记录，可能为申请书未列出或版式解析遗漏。")

    if record.publications:
        strengths.append(f"申请书所列论文情况为：{record.publication_summary()}。")
        recent = record.recent_publication_summary()
        if "未列出" in recent:
            weaknesses.append(recent + "，建议结合完整成果清单核验科研工作的持续性。")
    else:
        gaps.append("未识别到代表性论文条目，需人工核对申请人简历。")

    if record.current_institution or record.proposed_institution:
        institution = record.current_institution or record.proposed_institution
        title = record.current_title or record.proposed_title
        strengths.append(
            f"申请人依托单位为{institution}" + (f"，职称为{title}" if title else "") + "，具备开展项目的基本组织依托。"
        )

    condition_text = _section(record, "工作条件", "研究基础")
    if condition_text:
        strengths.append("申请书对研究基础和工作条件作了说明，后续仍应结合关键设备、前期数据及任务分工进行人工核验。")
    else:
        gaps.append("未能提取研究基础或工作条件区块。")

    if record.requested_amount_wan is not None:
        b = record.budget
        components = [b.equipment_wan, b.business_wan, b.labor_wan]
        if all(x is not None for x in components):
            strengths.append(
                f"申请直接费用为{record.requested_amount_wan:g}万元，其中设备费{b.equipment_wan:g}万元、"
                f"业务费{b.business_wan:g}万元、劳务费{b.labor_wan:g}万元，预算结构可据研究任务进一步审查。"
            )
        else:
            gaps.append("已识别申请经费总额，但部分预算科目未能稳定提取。")

    if record.warnings:
        gaps.extend(record.warnings)
    if not weaknesses:
        weaknesses.append("本地规则初评不自动判断创新深度，建议重点核验核心科学问题是否充分凝练、技术路线是否形成不可替代的突破点。")
    risks.append("项目可行性仍需结合关键前期数据、技术指标之间的逻辑关系、研究周期和团队实际投入进行人工判断。")

    overall = (
        f"该申请属于{record.program_type or '科研基金'}，项目名称为“{record.project_title or '未识别'}”。"
        "本地规则初评仅整理申请书中可核验的信息，不替代同行专家对原创性、科学价值和突破潜力的判断。"
    )
    return AIReview(
        preliminary_grade="暂不判级",
        overall_assessment=overall,
        strengths=strengths,
        weaknesses=weaknesses,
        risks=risks,
        funding_history_assessment=record.funding_summary() if record.funding else "申请书中未识别到可结构化的基金记录。",
        publication_assessment=record.publication_summary() if record.publications else "申请书中未识别到可结构化的论文记录。",
        evidence_gaps=list(dict.fromkeys(gaps)),
    )


def _grade_phrase(grade: str) -> str:
    value = grade.strip().upper()
    if value.startswith("A"):
        return "总体创新性较强，科学意义或应用前景较为突出"
    if value.startswith("B"):
        return "立意较为新颖，具有较重要的科学意义或应用前景"
    if value.startswith("C"):
        return "具有一定的科学研究意义或应用前景，但总体方案仍有进一步凝练和完善空间"
    if value.startswith("D"):
        return "项目在若干关键方面尚存在较明显不足"
    return "项目具有一定研究基础，仍需结合人工评议结论作综合判断"


def _funding_sentence(opinion: str) -> str:
    value = opinion.strip()
    if value.startswith("A") or "优先" in value:
        return "建议优先予以资助。"
    if value.startswith("B") or ("可资助" in value and "不予" not in value):
        return "建议予以资助。"
    if value.startswith("C") or "不予" in value:
        return "本轮建议不予资助。"
    return f"资助意见为：{value or '未填写'}。"


def generate_rule_final_review(
    record: ApplicationRecord,
    guide: str = "",
    batch_context: list[dict[str, Any]] | None = None,
) -> str:
    grade = record.manual_review.overall_grade or "未填写"
    opinion = record.manual_review.funding_opinion or "未填写"
    project = record.project_title or "该项目"
    research = _first_sentences(
        _section(record, "创新点", "研究内容与目标", "研究内容", "拟开展研究工作"), 260
    )
    para1 = (
        f"该项目围绕“{project}”开展研究，{_grade_phrase(grade)}。"
        + (f"申请书提出的主要研究内容包括：{research}" if research else "申请书对研究内容和总体技术路线作了说明。")
    )
    fund_text = record.funding_summary() if record.funding else "申请书中未识别到可结构化的基金主持或参与记录"
    pub_text = record.publication_summary() if record.publications else "申请书中未识别到可结构化的代表性论文记录"
    institution = record.current_institution or record.proposed_institution
    title = record.current_title or record.proposed_title
    para2 = (
        (f"申请人现依托{institution}" if institution else "申请人具备相关研究经历")
        + (f"，职称为{title}" if title else "")
        + f"。申请书所列科研项目经历显示：{fund_text}；论文成果情况显示：{pub_text}。"
        "上述基础为项目实施提供了一定支撑，但论文与基金记录仍应结合成果相关性、本人贡献和近期连续性进行综合判断。"
    )
    notes = clean_value(record.manual_review.reviewer_notes)
    caveats: list[str] = []
    if notes:
        caveats.append(notes)
    if record.ai_review.weaknesses:
        caveats.append(record.ai_review.weaknesses[0])
    if record.ai_review.risks:
        caveats.append(record.ai_review.risks[0])
    if not caveats:
        caveats.append("建议进一步核实关键技术指标的实现路径、研究任务之间的衔接以及风险应对措施。")
    para3 = "在研究方案与预期突破方面，" + "；".join(caveats[:2]).rstrip("。；") + "。"
    b = record.budget
    if record.requested_amount_wan is not None:
        if all(x is not None for x in [b.equipment_wan, b.business_wan, b.labor_wan]):
            para4 = (
                f"项目申请直接费用为{record.requested_amount_wan:g}万元，设备费、业务费和劳务费分别为"
                f"{b.equipment_wan:g}万元、{b.business_wan:g}万元和{b.labor_wan:g}万元。预算与研究任务具有一定对应关系，"
                "实施过程中仍应突出关键环节并提高经费使用的针对性。"
            )
        else:
            para4 = f"项目申请直接费用为{record.requested_amount_wan:g}万元，预算总体需结合具体研究任务和关键设备需求进一步核验。"
    else:
        para4 = "预算信息提取不完整，建议人工核对经费科目与研究任务的对应关系。"
    rank_text = f"在当前批次人工评分中排序第{record.manual_review.rank}。" if record.manual_review.rank else ""
    conclusion = f"综合评价为{grade}，{rank_text}{_funding_sentence(opinion)}"
    return "\n\n".join([para1, para2, para3, para4, conclusion])
