from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from .text_utils import normalize_text


class PDFPasswordError(ValueError):
    pass


class PDFProcessingError(ValueError):
    pass


def decrypt_pdf_bytes(pdf_bytes: bytes, password: str = "") -> tuple[bytes, bool]:
    """在内存中解密 PDF。返回 (解密后的字节, 原文件是否加密)。"""
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
    except PdfReadError as exc:
        raise PDFProcessingError(f"PDF 无法读取：{exc}") from exc

    was_encrypted = bool(reader.is_encrypted)
    if was_encrypted:
        result = reader.decrypt(password or "")
        if not result:
            raise PDFPasswordError("密码错误或该加密方式暂不受支持")

    try:
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        output = BytesIO()
        writer.write(output)
        return output.getvalue(), was_encrypted
    except Exception as exc:  # pypdf 对少数异常 PDF 的错误类型不统一
        raise PDFProcessingError(f"PDF 解密后写出失败：{exc}") from exc


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            raise PDFPasswordError("PDF 仍处于加密状态")
        return [normalize_text(page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, PDFPasswordError):
        raise
    except Exception as exc:
        raise PDFProcessingError(f"PDF 文本提取失败：{exc}") from exc


def decrypted_filename(original_name: str) -> str:
    if original_name.lower().endswith(".pdf"):
        stem = original_name[:-4]
        if stem.lower().endswith("_decrypt"):
            return original_name
        return stem + "_decrypt.pdf"
    if original_name.lower().endswith("_decrypt"):
        return original_name + ".pdf"
    return original_name + "_decrypt.pdf"


def build_decrypted_zip(files: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return output.getvalue()
