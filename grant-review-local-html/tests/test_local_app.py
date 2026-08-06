from __future__ import annotations

import json
from pathlib import Path

from grant_review.local_backend import APP_DATA_FILENAME, EXCEL_FILENAME, LocalReviewService
from grant_review.local_review import generate_rule_final_review, generate_rule_initial_review
from grant_review.models import (
    ApplicationRecord,
    FundingEntry,
    PublicationEntry,
)
from grant_review.pdf_utils import decrypted_filename
from grant_review.pipeline import ProcessedDocument
from grant_review.serialization import record_from_dict


def sample_record() -> ApplicationRecord:
    record = ApplicationRecord(
        source_file="申请书.pdf",
        document_format="nsfc_standard",
        document_year=2026,
        project_title="测试项目",
        program_type="面上项目",
        applicant_name="张三",
        current_institution="测试大学",
        current_title="教授",
        requested_amount_wan=58,
        sections={
            "研究内容": "本项目研究一个明确的科学问题，并给出三个相互衔接的研究任务。",
            "研究基础": "申请人已完成相关前期研究。",
        },
    )
    record.funding = [
        FundingEntry(
            source_type="NSFC",
            program_type="青年科学基金项目",
            grant_no="12345678",
            title="前期项目",
            status="结题",
            role="主持",
        )
    ]
    record.publications = [
        PublicationEntry(
            sequence=1,
            title="Representative paper",
            journal="Physical Review A",
            year=2025,
            role_label="唯一第一作者",
            is_first_author=True,
            is_representative=True,
        )
    ]
    return record


def test_decrypted_filename_does_not_repeat_suffix() -> None:
    assert decrypted_filename("a.pdf") == "a_decrypt.pdf"
    assert decrypted_filename("a_decrypt.pdf") == "a_decrypt.pdf"


def test_rule_review_is_local_and_conservative() -> None:
    record = sample_record()
    review = generate_rule_initial_review(record)
    assert review.preliminary_grade == "暂不判级"
    assert "NSFC主持1项" in review.funding_history_assessment
    assert "代表性论著1篇" in review.publication_assessment


def test_rule_final_review_respects_manual_decision() -> None:
    record = sample_record()
    record.manual_review.overall_grade = "C 中"
    record.manual_review.funding_opinion = "C 不予资助"
    record.manual_review.reviewer_notes = "研究基础仍需积累，措辞应客观委婉。"
    text = generate_rule_final_review(record)
    assert "综合评价" in text
    assert "C 中" in text
    assert "不予资助" in text


def test_serialization_roundtrip() -> None:
    record = sample_record()
    recovered = record_from_dict(record.to_dict())
    assert recovered.applicant_name == record.applicant_name
    assert recovered.funding[0].role == "主持"
    assert recovered.publications[0].year == 2025


def test_local_service_writes_batch_without_secrets(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "encrypted.pdf"
    source.write_bytes(b"dummy")
    record = sample_record()

    def fake_process_pdf_bytes(*, source_file: str, pdf_bytes: bytes, password: str, decrypted_name: str):
        assert password == "temporary-password"
        return ProcessedDocument(
            original_name=source_file,
            decrypted_name=decrypted_name,
            decrypted_bytes=b"decrypted-pdf",
            was_encrypted=True,
            record=record,
        )

    monkeypatch.setattr("grant_review.local_backend.process_pdf_bytes", fake_process_pdf_bytes)
    service = LocalReviewService()
    payload = {
        "files": [{"path": str(source), "password": "temporary-password"}],
        "output_dir": str(tmp_path),
        "batch_name": "batch",
        "provider": "rule",
        "guide": "guide",
        "api_key": "sk-test-secret",
    }
    result = service.process_batch(payload)
    assert result["ok"] is True

    batch_dir = Path(result["batch"]["batch_dir"])
    assert (batch_dir / EXCEL_FILENAME).exists()
    assert (batch_dir / APP_DATA_FILENAME).exists()
    assert (batch_dir / "解密PDF" / "encrypted_decrypt.pdf").read_bytes() == b"decrypted-pdf"

    exported = (batch_dir / APP_DATA_FILENAME).read_text(encoding="utf-8")
    assert "temporary-password" not in exported
    assert "sk-test-secret" not in exported
    parsed = json.loads(exported)
    assert parsed["records"][0]["applicant_name"] == "张三"
