from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .ai_review import generate_final_review_with_provider, generate_initial_review_with_provider
from .excel_export import build_excel
from .models import ApplicationRecord
from .pdf_utils import PDFPasswordError, PDFProcessingError, decrypted_filename
from .pipeline import ProcessedDocument, process_pdf_bytes
from .serialization import record_from_dict
from .text_utils import crop


DEFAULT_GUIDE = """请从以下方面评议申请项目：
一、是否具有明确的科学问题、创新的学术思想、先进的研究目标以及必要的研究条件。
二、项目主持人是否具有较高的学术水平并活跃在科学研究前沿，研究队伍结构是否合理，研究基础是否扎实。
三、如获得资助，预期研究工作能否取得突破性进展。
四、经费预算是否合理。
综合评价等级：A 优、B 良、C 中、D 差。资助意见由评审人最终确定。
对同一领域申请应比较分析、择优排序，并在综合评价中体现差别。
"""

APP_DATA_FILENAME = "批次数据.json"
EXCEL_FILENAME = "基金申请书汇总.xlsx"


def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", (value or "").strip())
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:80] or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return int(number) if number is not None else None


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


@dataclass
class BatchState:
    documents: list[ProcessedDocument] = field(default_factory=list)
    batch_dir: Path | None = None
    guide: str = DEFAULT_GUIDE
    provider: str = "rule"
    model: str = ""
    ollama_url: str = "http://127.0.0.1:11434"

    @property
    def records(self) -> list[ApplicationRecord]:
        return [doc.record for doc in self.documents]


class LocalReviewService:
    """Local-only application service.

    Passwords and API keys are accepted only as method arguments and are never
    assigned to object attributes, written to disk, or included in exports.
    """

    def __init__(self) -> None:
        self.state = BatchState()

    def inspect_pdf_paths(self, paths: list[str]) -> list[dict[str, Any]]:
        from pypdf import PdfReader

        result: list[dict[str, Any]] = []
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            item: dict[str, Any] = {
                "path": str(path),
                "name": path.name,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else None,
                "encrypted": None,
                "error": "",
            }
            if not path.exists() or not path.is_file():
                item["error"] = "文件不存在"
            elif path.suffix.lower() != ".pdf":
                item["error"] = "不是 PDF 文件"
            else:
                try:
                    item["encrypted"] = bool(PdfReader(str(path), strict=False).is_encrypted)
                except Exception as exc:
                    item["error"] = f"无法读取：{exc}"
            result.append(item)
        return result

    def process_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = payload.get("files") or []
        output_value = str(payload.get("output_dir") or "").strip()
        if not files:
            raise ValueError("请先选择至少一个 PDF 文件。")
        if not output_value:
            raise ValueError("请选择本地输出文件夹。")
        output_root = Path(output_value).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)

        batch_name = _safe_name(
            str(payload.get("batch_name") or ""),
            datetime.now().strftime("基金评审_%Y%m%d_%H%M%S"),
        )
        batch_dir = _unique_path(output_root / batch_name)
        decrypted_dir = batch_dir / "解密PDF"
        batch_dir.mkdir(parents=True, exist_ok=False)
        decrypted_dir.mkdir(parents=True, exist_ok=True)

        provider = str(payload.get("provider") or "none").strip().lower()
        guide = str(payload.get("guide") or DEFAULT_GUIDE)
        model = str(payload.get("model") or "").strip()
        ollama_url = str(payload.get("ollama_url") or "http://127.0.0.1:11434").strip()
        api_key = str(payload.get("api_key") or "").strip()
        generate_ai = provider not in {"", "none"}

        processed: list[ProcessedDocument] = []
        errors: list[dict[str, str]] = []
        used_output_names: set[str] = set()

        try:
            for item in files:
                path = Path(str(item.get("path") or "")).expanduser().resolve()
                password = str(item.get("password") or payload.get("common_password") or "")
                if not path.exists() or not path.is_file():
                    errors.append({"file": path.name or str(path), "stage": "读取", "message": "文件不存在"})
                    continue
                try:
                    output_name = decrypted_filename(path.name)
                    if output_name in used_output_names:
                        output_name = _unique_path(decrypted_dir / output_name).name
                    used_output_names.add(output_name)
                    doc = process_pdf_bytes(
                        source_file=path.name,
                        pdf_bytes=path.read_bytes(),
                        password=password,
                        decrypted_name=output_name,
                    )
                    (decrypted_dir / output_name).write_bytes(doc.decrypted_bytes)
                    # Do not retain decrypted PDF bytes in long-lived memory after writing.
                    doc.decrypted_bytes = b""
                    processed.append(doc)
                except PDFPasswordError as exc:
                    errors.append({"file": path.name, "stage": "解密", "message": str(exc)})
                except PDFProcessingError as exc:
                    errors.append({"file": path.name, "stage": "解析", "message": str(exc)})
                except Exception as exc:
                    errors.append({"file": path.name, "stage": "处理", "message": str(exc)})

            if not processed:
                shutil.rmtree(batch_dir, ignore_errors=True)
                return {"ok": False, "errors": errors, "message": "没有文件处理成功。"}

            if generate_ai:
                for doc in processed:
                    try:
                        doc.record.ai_review = generate_initial_review_with_provider(
                            doc.record,
                            provider=provider,
                            model=model,
                            guide=guide,
                            api_key=api_key,
                            base_url=ollama_url,
                        )
                    except Exception as exc:
                        errors.append(
                            {
                                "file": doc.original_name,
                                "stage": "初评",
                                "message": str(exc),
                            }
                        )

            self.state = BatchState(
                documents=processed,
                batch_dir=batch_dir,
                guide=guide,
                provider=provider,
                model=model,
                ollama_url=ollama_url,
            )
            self._save_outputs()
            return {
                "ok": True,
                "message": f"成功处理 {len(processed)} 份申请书。",
                "batch": self.batch_summary(),
                "errors": errors,
            }
        finally:
            # Local variables fall out of scope after the call; passwords/API keys
            # are intentionally never copied into application state.
            api_key = ""
            for item in files:
                if isinstance(item, dict) and "password" in item:
                    item["password"] = ""
            if "common_password" in payload:
                payload["common_password"] = ""
            if "api_key" in payload:
                payload["api_key"] = ""

    def load_batch(self, json_path: str) -> dict[str, Any]:
        path = Path(json_path).expanduser().resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        records = [record_from_dict(item) for item in data.get("records", []) if isinstance(item, dict)]
        if not records:
            raise ValueError("所选文件中没有可恢复的申请书记录。")
        batch_dir = path.parent
        docs = [
            ProcessedDocument(
                original_name=record.source_file,
                decrypted_name=decrypted_filename(record.source_file),
                decrypted_bytes=b"",
                was_encrypted=False,
                record=record,
            )
            for record in records
        ]
        settings = data.get("settings", {}) if isinstance(data.get("settings"), dict) else {}
        self.state = BatchState(
            documents=docs,
            batch_dir=batch_dir,
            guide=str(data.get("guide") or DEFAULT_GUIDE),
            provider=str(settings.get("provider") or "rule"),
            model=str(settings.get("model") or ""),
            ollama_url=str(settings.get("ollama_url") or "http://127.0.0.1:11434"),
        )
        return {"ok": True, "batch": self.batch_summary(), "message": "批次已载入。"}

    def batch_summary(self) -> dict[str, Any]:
        records = self.state.records
        return {
            "count": len(records),
            "batch_dir": str(self.state.batch_dir or ""),
            "excel_path": str((self.state.batch_dir / EXCEL_FILENAME) if self.state.batch_dir else ""),
            "json_path": str((self.state.batch_dir / APP_DATA_FILENAME) if self.state.batch_dir else ""),
            "guide": self.state.guide,
            "provider": self.state.provider,
            "model": self.state.model,
            "records": [self._record_summary(index, record) for index, record in enumerate(records)],
        }

    def _record_summary(self, index: int, record: ApplicationRecord) -> dict[str, Any]:
        return {
            "index": index,
            "source_file": record.source_file,
            "applicant_name": record.applicant_name,
            "project_title": record.project_title,
            "institution": record.current_institution or record.proposed_institution,
            "current_title": record.current_title or record.proposed_title,
            "program_type": record.program_type,
            "requested_amount_wan": record.requested_amount_wan,
            "funding_summary": record.funding_summary(),
            "publication_summary": record.publication_summary(),
            "recent_publication_summary": record.recent_publication_summary(),
            "ai_grade": record.ai_review.preliminary_grade,
            "manual_grade": record.manual_review.overall_grade,
            "funding_opinion": record.manual_review.funding_opinion,
            "total_score": record.manual_review.total_score,
            "rank": record.manual_review.rank,
            "warnings": record.warnings,
        }

    def record_detail(self, index: int) -> dict[str, Any]:
        record = self._record(index)
        return {
            "summary": self._record_summary(index, record),
            "basic": {
                "application_code": record.application_code,
                "admission_no": record.admission_no,
                "project_title": record.project_title,
                "program_type": record.program_type,
                "subcategory": record.subcategory,
                "special_note": record.special_note,
                "applicant_name": record.applicant_name,
                "brid": record.brid,
                "birth_date": record.birth_date,
                "degree": record.degree,
                "current_title": record.current_title,
                "proposed_title": record.proposed_title,
                "current_institution": record.current_institution,
                "proposed_institution": record.proposed_institution,
                "department": record.department,
                "research_field": record.research_field,
                "research_direction": record.research_direction,
                "research_period": record.research_period,
                "requested_amount_wan": record.requested_amount_wan,
                "research_attribute": record.research_attribute,
                "keywords": record.keywords,
                "return_date": record.return_date,
                "team_total": record.team_total,
                "team_senior": record.team_senior,
                "partner_institutions": record.partner_institutions,
            },
            "education": [item.to_dict() for item in record.education],
            "work_history": [item.to_dict() for item in record.work_history],
            "funding": [item.to_dict() for item in record.funding],
            "publications": [item.to_dict() for item in record.publications],
            "budget": record.budget.to_dict(),
            "ai_review": record.ai_review.to_dict(),
            "manual_review": record.manual_review.to_dict(),
            "sections": {name: crop(text, 12000) for name, text in record.sections.items()},
            "evidence": [item.to_dict() for item in record.evidence],
            "warnings": record.warnings,
        }

    def update_record(self, index: int, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._record(index)
        basic = payload.get("basic") or {}
        editable_text = [
            "applicant_name",
            "project_title",
            "current_institution",
            "proposed_institution",
            "current_title",
            "proposed_title",
            "research_field",
            "research_direction",
            "research_period",
        ]
        for key in editable_text:
            if key in basic:
                setattr(record, key, str(basic.get(key) or "").strip())
        if "requested_amount_wan" in basic:
            record.requested_amount_wan = _float_or_none(basic.get("requested_amount_wan"))
        if "team_total" in basic:
            record.team_total = _int_or_none(basic.get("team_total"))
        if "team_senior" in basic:
            record.team_senior = _int_or_none(basic.get("team_senior"))

        manual = payload.get("manual_review") or {}
        m = record.manual_review
        score_fields = [
            "scientific_question_score",
            "innovation_score",
            "applicant_team_score",
            "breakthrough_score",
            "budget_score",
        ]
        for key in score_fields:
            if key in manual:
                setattr(m, key, _float_or_none(manual.get(key)))
        scores = [getattr(m, key) for key in score_fields]
        m.total_score = sum(score for score in scores if score is not None) if any(
            score is not None for score in scores
        ) else None
        if "overall_grade" in manual:
            m.overall_grade = str(manual.get("overall_grade") or "")
        if "funding_opinion" in manual:
            m.funding_opinion = str(manual.get("funding_opinion") or "")
        if "reviewer_notes" in manual:
            m.reviewer_notes = str(manual.get("reviewer_notes") or "")
        if "final_review" in payload:
            record.ai_review.final_review = str(payload.get("final_review") or "")

        self._rank_records()
        self._save_outputs()
        return {"ok": True, "batch": self.batch_summary(), "detail": self.record_detail(index)}

    def generate_initial_reviews(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "rule").strip().lower()
        model = str(payload.get("model") or "").strip()
        guide = str(payload.get("guide") or self.state.guide or DEFAULT_GUIDE)
        api_key = str(payload.get("api_key") or "").strip()
        ollama_url = str(payload.get("ollama_url") or self.state.ollama_url).strip()
        indexes = payload.get("indexes")
        if indexes is None:
            indexes = list(range(len(self.state.records)))

        errors: list[dict[str, str]] = []
        for raw_index in indexes:
            index = int(raw_index)
            record = self._record(index)
            try:
                record.ai_review = generate_initial_review_with_provider(
                    record,
                    provider=provider,
                    model=model,
                    guide=guide,
                    api_key=api_key,
                    base_url=ollama_url,
                )
            except Exception as exc:
                errors.append({"file": record.source_file, "stage": "初评", "message": str(exc)})
        self.state.guide = guide
        self.state.provider = provider
        self.state.model = model
        self.state.ollama_url = ollama_url
        self._save_outputs()
        api_key = ""
        payload["api_key"] = ""
        return {"ok": not errors, "errors": errors, "batch": self.batch_summary()}

    def generate_final_reviews(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "rule").strip().lower()
        model = str(payload.get("model") or "").strip()
        guide = str(payload.get("guide") or self.state.guide or DEFAULT_GUIDE)
        api_key = str(payload.get("api_key") or "").strip()
        ollama_url = str(payload.get("ollama_url") or self.state.ollama_url).strip()
        indexes = payload.get("indexes")
        if indexes is None:
            indexes = list(range(len(self.state.records)))

        self._rank_records()
        context = self._batch_context()
        errors: list[dict[str, str]] = []
        for raw_index in indexes:
            index = int(raw_index)
            record = self._record(index)
            if not record.manual_review.overall_grade or not record.manual_review.funding_opinion:
                errors.append(
                    {
                        "file": record.source_file,
                        "stage": "评语",
                        "message": "请先填写综合评价和资助意见。",
                    }
                )
                continue
            try:
                record.ai_review.final_review = generate_final_review_with_provider(
                    record,
                    provider=provider,
                    model=model,
                    guide=guide,
                    batch_context=context,
                    api_key=api_key,
                    base_url=ollama_url,
                )
            except Exception as exc:
                errors.append({"file": record.source_file, "stage": "评语", "message": str(exc)})

        self.state.guide = guide
        self.state.provider = provider
        self.state.model = model
        self.state.ollama_url = ollama_url
        self._save_outputs()
        api_key = ""
        payload["api_key"] = ""
        return {"ok": not errors, "errors": errors, "batch": self.batch_summary()}

    def export(self) -> dict[str, Any]:
        self._save_outputs()
        return {"ok": True, "batch": self.batch_summary(), "message": "Excel 与 JSON 已更新。"}

    def open_output_folder(self) -> dict[str, Any]:
        if not self.state.batch_dir:
            raise ValueError("当前没有已处理批次。")
        _open_path(self.state.batch_dir)
        return {"ok": True}

    def clear(self) -> dict[str, Any]:
        self.state = BatchState()
        return {"ok": True}

    def _record(self, index: int) -> ApplicationRecord:
        if index < 0 or index >= len(self.state.records):
            raise IndexError("申请书索引超出范围。")
        return self.state.records[index]

    def _rank_records(self) -> None:
        for record in self.state.records:
            record.manual_review.rank = None
        ranked = sorted(
            [record for record in self.state.records if record.manual_review.total_score is not None],
            key=lambda record: record.manual_review.total_score or 0,
            reverse=True,
        )
        for rank, record in enumerate(ranked, start=1):
            record.manual_review.rank = rank

    def _batch_context(self) -> list[dict[str, Any]]:
        return [
            {
                "project_title": record.project_title,
                "applicant": record.applicant_name,
                "total_score": record.manual_review.total_score,
                "grade": record.manual_review.overall_grade,
                "funding_opinion": record.manual_review.funding_opinion,
                "rank": record.manual_review.rank,
                "funding_summary": record.funding_summary(),
                "publication_summary": record.publication_summary(),
            }
            for record in self.state.records
        ]

    def _save_outputs(self) -> None:
        if not self.state.batch_dir:
            return
        self.state.batch_dir.mkdir(parents=True, exist_ok=True)
        (self.state.batch_dir / EXCEL_FILENAME).write_bytes(build_excel(self.state.records))
        _json_dump(
            self.state.batch_dir / APP_DATA_FILENAME,
            {
                "format_version": 1,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "guide": self.state.guide,
                "settings": {
                    "provider": self.state.provider,
                    "model": self.state.model,
                    "ollama_url": self.state.ollama_url,
                },
                "records": [record.to_dict() for record in self.state.records],
            },
        )
