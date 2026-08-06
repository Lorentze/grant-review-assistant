from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    field_name: str
    value: str | float | int | None
    page: int | None = None
    snippet: str = ""
    confidence: float = 0.0
    method: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EducationEntry:
    level: str
    institution: str
    major: str = ""
    start: str = ""
    end: str = ""
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkEntry:
    institution: str
    department: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    category: str = "work"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FundingEntry:
    source_type: str = "NSFC"
    agency: str = ""
    program_type: str = ""
    grant_no: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    amount_wan: float | None = None
    status: str = ""
    role: str = ""
    raw: str = ""

    def identity(self) -> str:
        if self.grant_no:
            return f"{self.source_type}|{self.grant_no}"
        return f"{self.source_type}|{self.program_type}|{self.title}|{self.start}|{self.role}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PublicationEntry:
    sequence: int | None = None
    citation: str = ""
    title: str = ""
    journal: str = ""
    year: int | None = None
    role_label: str = ""
    is_first_author: bool = False
    is_corresponding_author: bool = False
    is_representative: bool = True
    applicant_contribution: str = ""
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Budget:
    direct_cost_wan: float | None = None
    equipment_wan: float | None = None
    business_wan: float | None = None
    labor_wan: float | None = None
    transfer_wan: float | None = None
    other_source_wan: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AIReview:
    preliminary_grade: str = ""
    overall_assessment: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    funding_history_assessment: str = ""
    publication_assessment: str = ""
    evidence_gaps: list[str] = field(default_factory=list)
    final_review: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManualReview:
    scientific_question_score: float | None = None
    innovation_score: float | None = None
    applicant_team_score: float | None = None
    breakthrough_score: float | None = None
    budget_score: float | None = None
    total_score: float | None = None
    overall_grade: str = ""
    funding_opinion: str = ""
    reviewer_notes: str = ""
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApplicationRecord:
    source_file: str
    document_format: str = "generic"
    document_year: int | None = None
    application_code: str = ""
    admission_no: str = ""
    project_title: str = ""
    program_type: str = ""
    subcategory: str = ""
    special_note: str = ""
    applicant_name: str = ""
    brid: str = ""
    birth_date: str = ""
    degree: str = ""
    current_title: str = ""
    proposed_title: str = ""
    current_institution: str = ""
    proposed_institution: str = ""
    department: str = ""
    research_field: str = ""
    research_direction: str = ""
    research_period: str = ""
    requested_amount_wan: float | None = None
    research_attribute: str = ""
    keywords: str = ""
    return_date: str = ""
    team_total: int | None = None
    team_senior: int | None = None
    partner_institutions: list[str] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    work_history: list[WorkEntry] = field(default_factory=list)
    funding: list[FundingEntry] = field(default_factory=list)
    publications: list[PublicationEntry] = field(default_factory=list)
    self_reported_publication_total: int | None = None
    self_reported_first_corr_total: int | None = None
    budget: Budget = field(default_factory=Budget)
    sections: dict[str, str] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_review: AIReview = field(default_factory=AIReview)
    manual_review: ManualReview = field(default_factory=ManualReview)

    def funding_summary(self) -> str:
        nsfc_pi = [x for x in self.funding if x.source_type == "NSFC" and x.role == "主持"]
        nsfc_part = [x for x in self.funding if x.source_type == "NSFC" and x.role == "参与"]
        other_pi = [x for x in self.funding if x.source_type != "NSFC" and x.role == "主持"]
        other_part = [x for x in self.funding if x.source_type != "NSFC" and x.role == "参与"]

        def type_counts(entries: list[FundingEntry]) -> str:
            counts: dict[str, int] = {}
            for item in entries:
                key = item.program_type or "未分类"
                counts[key] = counts.get(key, 0) + 1
            return "、".join(f"{k}{v}项" for k, v in counts.items())

        chunks = [
            f"NSFC主持{len(nsfc_pi)}项" + (f"（{type_counts(nsfc_pi)}）" if nsfc_pi else ""),
            f"NSFC参与{len(nsfc_part)}项",
        ]
        if other_pi or other_part:
            chunks.append(f"其他主持{len(other_pi)}项、参与{len(other_part)}项")
        return "；".join(chunks)

    def publication_summary(self) -> str:
        reps = [x for x in self.publications if x.is_representative]
        all_pubs = self.publications
        first_count = sum(x.is_first_author for x in reps)
        corr_count = sum(x.is_corresponding_author for x in reps)
        years: dict[int, int] = {}
        for item in reps:
            if item.year:
                years[item.year] = years.get(item.year, 0) + 1
        year_text = "、".join(f"{year}年{count}篇" for year, count in sorted(years.items(), reverse=True))
        total_text = (
            f"申请书自述论文总数{self.self_reported_publication_total}篇；"
            if self.self_reported_publication_total is not None
            else ""
        )
        corr_text = (
            f"自述第一/通讯作者{self.self_reported_first_corr_total}篇；"
            if self.self_reported_first_corr_total is not None
            else ""
        )
        rep_text = f"代表性论著{len(reps)}篇（一作{first_count}篇、通讯{corr_count}篇）"
        if len(all_pubs) > len(reps):
            rep_text += f"，另列其余论著{len(all_pubs) - len(reps)}篇"
        if year_text:
            rep_text += f"；年份分布：{year_text}"
        return total_text + corr_text + rep_text

    def recent_publication_summary(self) -> str:
        if not self.document_year:
            return "无法确定申请年度，未计算近年代表性论文分布"
        start_year = self.document_year - 1
        recent = [
            x
            for x in self.publications
            if x.is_representative and x.year is not None and start_year <= x.year <= self.document_year
        ]
        if recent:
            years: dict[int, int] = {}
            for item in recent:
                years[item.year or 0] = years.get(item.year or 0, 0) + 1
            detail = "、".join(f"{year}年{count}篇" for year, count in sorted(years.items(), reverse=True))
            return f"代表性论著清单中，{start_year}-{self.document_year}年共{len(recent)}篇（{detail}）"
        return f"代表性论著清单中未列出{start_year}-{self.document_year}年论文；这不等同于申请人没有发表论文"

    def phd_institution(self) -> str:
        for entry in self.education:
            if entry.level == "博士":
                return entry.institution
        return ""

    def undergraduate_institution(self) -> str:
        for entry in self.education:
            if entry.level in {"学士", "本科"}:
                return entry.institution
        return ""

    def postdoc_institutions(self) -> str:
        institutions = []
        for entry in self.work_history:
            if entry.category == "postdoc" and entry.institution not in institutions:
                institutions.append(entry.institution)
        return "；".join(institutions)

    def to_summary_row(self) -> dict[str, Any]:
        return {
            "文件名": self.source_file,
            "文档格式": self.document_format,
            "申请年度": self.document_year,
            "申请代码": self.application_code,
            "接收编号": self.admission_no,
            "项目名称": self.project_title,
            "资助类别": self.program_type,
            "亚类说明": self.subcategory,
            "附注说明": self.special_note,
            "申请人": self.applicant_name,
            "BRID": self.brid,
            "依托单位": self.current_institution or self.proposed_institution,
            "当前职称": self.current_title,
            "拟任职称": self.proposed_title,
            "博士毕业单位": self.phd_institution(),
            "博士后单位": self.postdoc_institutions(),
            "主要研究领域": self.research_field,
            "研究期限": self.research_period,
            "申请直接费用(万元)": self.requested_amount_wan,
            "团队总人数": self.team_total,
            "高级职称人数": self.team_senior,
            "基金主持与参与": self.funding_summary(),
            "论文发表概况": self.publication_summary(),
            "近两年代表性论文": self.recent_publication_summary(),
            "AI初评等级": self.ai_review.preliminary_grade,
            "AI总体评价": self.ai_review.overall_assessment,
            "人工综合等级": self.manual_review.overall_grade,
            "人工资助意见": self.manual_review.funding_opinion,
            "批次排序": self.manual_review.rank,
            "最终评语": self.ai_review.final_review,
            "提取警告": "；".join(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["funding_summary"] = self.funding_summary()
        data["publication_summary"] = self.publication_summary()
        data["recent_publication_summary"] = self.recent_publication_summary()
        return data
