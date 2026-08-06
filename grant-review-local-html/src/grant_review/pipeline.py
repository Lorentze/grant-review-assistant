from __future__ import annotations

from dataclasses import dataclass

from .detector import detect_document_format, detect_document_year
from .extractors import extract_generic, extract_nsfc_overseas, extract_nsfc_standard
from .models import ApplicationRecord
from .pdf_utils import decrypt_pdf_bytes, extract_pdf_pages


@dataclass
class ProcessedDocument:
    original_name: str
    decrypted_name: str
    decrypted_bytes: bytes
    was_encrypted: bool
    record: ApplicationRecord


def parse_pages(source_file: str, page_texts: list[str]) -> ApplicationRecord:
    fmt = detect_document_format(page_texts)
    if fmt == "nsfc_overseas_young":
        record = extract_nsfc_overseas(source_file, page_texts)
    elif fmt == "nsfc_standard":
        record = extract_nsfc_standard(source_file, page_texts)
    else:
        record = extract_generic(source_file, page_texts)
    if record.document_year is None:
        record.document_year = detect_document_year(page_texts)
    return record


def process_pdf_bytes(
    source_file: str,
    pdf_bytes: bytes,
    password: str = "",
    decrypted_name: str | None = None,
) -> ProcessedDocument:
    decrypted_bytes, was_encrypted = decrypt_pdf_bytes(pdf_bytes, password)
    pages = extract_pdf_pages(decrypted_bytes)
    record = parse_pages(source_file, pages)
    return ProcessedDocument(
        original_name=source_file,
        decrypted_name=decrypted_name or source_file,
        decrypted_bytes=decrypted_bytes,
        was_encrypted=was_encrypted,
        record=record,
    )
