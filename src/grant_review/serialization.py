from __future__ import annotations

from typing import Any

from .models import (
    AIReview,
    ApplicationRecord,
    Budget,
    EducationEntry,
    Evidence,
    FundingEntry,
    ManualReview,
    PublicationEntry,
    WorkEntry,
)


def record_from_dict(data: dict[str, Any]) -> ApplicationRecord:
    """Recreate an ApplicationRecord from a JSON-compatible dictionary.

    Derived summary keys are intentionally ignored. This function is used only
    to reopen batches that were previously exported by the desktop app.
    """

    allowed = {
        "source_file",
        "document_format",
        "document_year",
        "application_code",
        "admission_no",
        "project_title",
        "program_type",
        "subcategory",
        "special_note",
        "applicant_name",
        "brid",
        "birth_date",
        "degree",
        "current_title",
        "proposed_title",
        "current_institution",
        "proposed_institution",
        "department",
        "research_field",
        "research_direction",
        "research_period",
        "requested_amount_wan",
        "research_attribute",
        "keywords",
        "return_date",
        "team_total",
        "team_senior",
        "partner_institutions",
        "self_reported_publication_total",
        "self_reported_first_corr_total",
        "sections",
        "warnings",
    }
    kwargs = {key: data.get(key) for key in allowed if key in data}
    kwargs.setdefault("source_file", "")
    record = ApplicationRecord(**kwargs)

    record.education = [EducationEntry(**item) for item in data.get("education", []) if isinstance(item, dict)]
    record.work_history = [WorkEntry(**item) for item in data.get("work_history", []) if isinstance(item, dict)]
    record.funding = [FundingEntry(**item) for item in data.get("funding", []) if isinstance(item, dict)]
    record.publications = [
        PublicationEntry(**item) for item in data.get("publications", []) if isinstance(item, dict)
    ]
    record.evidence = [Evidence(**item) for item in data.get("evidence", []) if isinstance(item, dict)]

    budget = data.get("budget", {})
    if isinstance(budget, dict):
        record.budget = Budget(**{k: v for k, v in budget.items() if k in Budget.__dataclass_fields__})

    ai = data.get("ai_review", {})
    if isinstance(ai, dict):
        record.ai_review = AIReview(**{k: v for k, v in ai.items() if k in AIReview.__dataclass_fields__})

    manual = data.get("manual_review", {})
    if isinstance(manual, dict):
        record.manual_review = ManualReview(
            **{k: v for k, v in manual.items() if k in ManualReview.__dataclass_fields__}
        )
    return record
