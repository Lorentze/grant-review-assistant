from __future__ import annotations

import json
import re
from typing import Any

from .models import AIReview, ApplicationRecord
from .text_utils import crop


INITIAL_INSTRUCTIONS = """
你是一名严谨、克制的科研基金评审辅助人员。你的任务是根据用户提供的评审指南和申请书中可核验的信息，给出客观的初步评价。
必须遵守：
1. 只使用输入材料，不补造事实，不进行互联网检索。
2. 将“申请书明确记载的事实”与“基于事实的判断”分开；证据不足时明确说明。
3. 基金经历必须区分主持/参与、国家自然科学基金/其他项目、在研/结题。
4. 论文必须区分申请书自述总数与代表性论著清单；评价近期产出时，只能说“代表性论著清单中未列出”，不得据此断言没有发表。
5. 不以单一期刊标签代替学术评价，应结合作者角色、时间分布、与申请项目的相关性和持续性。
6. 优点要具体，缺点和风险要委婉、可核验、可改进。
7. 输出严格为 JSON，不要输出 Markdown 代码围栏。
JSON 字段：preliminary_grade, overall_assessment, strengths, weaknesses, risks, funding_history_assessment, publication_assessment, evidence_gaps。
其中 preliminary_grade 取 A/B/C/D/暂不判级之一；strengths、weaknesses、risks、evidence_gaps 为字符串数组。
""".strip()


FINAL_INSTRUCTIONS = """
你是一名国家自然科学基金评审辅助人员。请根据申请书事实、评审指南、人工给定的综合评价和资助意见，起草正式评审意见。
要求：
1. 必须与人工给定等级和资助意见一致，不擅自改变结论。
2. 对同批项目体现相对差异，但措辞客观、克制，不贬低申请人。
3. 按科学问题与创新、申请人和团队、突破潜力与可行性、预算合理性等要点展开。
4. 对不资助项目给出具体但委婉的理由；对资助项目突出创新点和研究价值。
5. 不加小标题，写成自然衔接的中文段落；末句明确综合评价和资助意见。
6. 不得编造输入材料之外的事实；对“未列出”与“没有”严格区分。
只输出评审意见正文，不输出说明或 JSON。
""".strip()


def _record_payload(record: ApplicationRecord) -> dict[str, Any]:
    pubs = [
        {
            "year": p.year,
            "journal": p.journal,
            "title": p.title,
            "role": p.role_label,
            "representative": p.is_representative,
        }
        for p in record.publications
    ]
    funds = [
        {
            "source": f.source_type,
            "program_type": f.program_type,
            "grant_no": f.grant_no,
            "title": f.title,
            "period": f"{f.start} 至 {f.end}",
            "amount_wan": f.amount_wan,
            "status": f.status,
            "role": f.role,
        }
        for f in record.funding
    ]
    sections = {
        key: crop(value, 7000)
        for key, value in record.sections.items()
        if key in {
            "立项依据",
            "研究内容",
            "研究内容与目标",
            "研究方案与可行性",
            "研究基础",
            "创新点",
            "工作条件",
            "主要学术成绩",
            "拟开展研究工作",
        }
    }
    return {
        "basic": {
            "source_file": record.source_file,
            "document_format": record.document_format,
            "document_year": record.document_year,
            "project_title": record.project_title,
            "program_type": record.program_type,
            "applicant_name": record.applicant_name,
            "institution": record.current_institution or record.proposed_institution,
            "current_title": record.current_title,
            "proposed_title": record.proposed_title,
            "phd_institution": record.phd_institution(),
            "postdoc_institutions": record.postdoc_institutions(),
            "research_field": record.research_field,
            "requested_amount_wan": record.requested_amount_wan,
            "team_total": record.team_total,
            "team_senior": record.team_senior,
            "partners": record.partner_institutions,
        },
        "funding_summary": record.funding_summary(),
        "funding_records": funds,
        "publication_summary": record.publication_summary(),
        "recent_publication_summary": record.recent_publication_summary(),
        "publication_records": pubs,
        "budget": record.budget.to_dict(),
        "sections": sections,
        "parser_warnings": record.warnings,
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def generate_initial_review(
    record: ApplicationRecord,
    *,
    api_key: str,
    model: str,
    guide: str,
) -> AIReview:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=180.0)
    payload = {
        "review_guide": guide.strip(),
        "application": _record_payload(record),
    }
    response = client.responses.create(
        model=model,
        instructions=INITIAL_INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False),
        store=False,
    )
    data = _extract_json(response.output_text)
    return AIReview(
        preliminary_grade=str(data.get("preliminary_grade", "")),
        overall_assessment=str(data.get("overall_assessment", "")),
        strengths=[str(x) for x in data.get("strengths", [])],
        weaknesses=[str(x) for x in data.get("weaknesses", [])],
        risks=[str(x) for x in data.get("risks", [])],
        funding_history_assessment=str(data.get("funding_history_assessment", "")),
        publication_assessment=str(data.get("publication_assessment", "")),
        evidence_gaps=[str(x) for x in data.get("evidence_gaps", [])],
    )


def generate_final_review(
    record: ApplicationRecord,
    *,
    api_key: str,
    model: str,
    guide: str,
    batch_context: list[dict[str, Any]],
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=180.0)
    payload = {
        "review_guide": guide.strip(),
        "assigned_result": {
            "overall_grade": record.manual_review.overall_grade,
            "funding_opinion": record.manual_review.funding_opinion,
            "scores": record.manual_review.to_dict(),
            "reviewer_notes": record.manual_review.reviewer_notes,
        },
        "application": _record_payload(record),
        "initial_ai_review": record.ai_review.to_dict(),
        "batch_comparison": batch_context,
    }
    response = client.responses.create(
        model=model,
        instructions=FINAL_INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False),
        store=False,
    )
    return response.output_text.strip()
