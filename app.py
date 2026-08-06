from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_review.ai_review import generate_final_review, generate_initial_review
from grant_review.excel_export import build_excel
from grant_review.models import ApplicationRecord
from grant_review.pdf_utils import (
    PDFPasswordError,
    PDFProcessingError,
    build_decrypted_zip,
    decrypted_filename,
)
from grant_review.pipeline import ProcessedDocument, process_pdf_bytes


st.set_page_config(page_title="基金申请书整理与评审助手", page_icon="📚", layout="wide")


DEFAULT_GUIDE = """请从以下方面评议申请项目：
一、是否具有明确的科学问题、创新的学术思想、先进的研究目标以及必要的研究条件。
二、项目主持人是否具有较高的学术水平并活跃在科学研究前沿，研究队伍结构是否合理，研究基础是否扎实。
三、如获得资助，预期研究工作能否取得突破性进展。
四、经费预算是否合理。
综合评价等级：A 优、B 良、C 中、D 差。资助意见由评审人最终确定。
对同一领域申请应比较分析、择优排序，并在综合评价中体现差别。
"""


if "documents" not in st.session_state:
    st.session_state.documents: list[ProcessedDocument] = []
if "guide" not in st.session_state:
    st.session_state.guide = DEFAULT_GUIDE


def records() -> list[ApplicationRecord]:
    return [doc.record for doc in st.session_state.documents]


def selected_records(selected_files: list[str]) -> list[ApplicationRecord]:
    return [r for r in records() if r.source_file in selected_files]


def batch_context() -> list[dict[str, Any]]:
    result = []
    for record in records():
        result.append(
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
        )
    return result


def apply_basic_edits(df: pd.DataFrame) -> None:
    by_file = {r.source_file: r for r in records()}
    for _, row in df.iterrows():
        record = by_file.get(str(row["文件名"]))
        if not record:
            continue
        record.applicant_name = str(row.get("申请人") or "")
        record.project_title = str(row.get("项目名称") or "")
        record.current_institution = str(row.get("依托单位") or "")
        record.current_title = str(row.get("当前职称") or "")
        record.requested_amount_wan = _float_or_none(row.get("申请直接费用(万元)"))
        record.team_total = _int_or_none(row.get("团队总人数"))
        record.team_senior = _int_or_none(row.get("高级职称人数"))


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return int(number) if number is not None else None


def apply_manual_edits(df: pd.DataFrame) -> None:
    by_file = {r.source_file: r for r in records()}
    for _, row in df.iterrows():
        record = by_file.get(str(row["文件名"]))
        if not record:
            continue
        m = record.manual_review
        m.scientific_question_score = _float_or_none(row.get("科学问题"))
        m.innovation_score = _float_or_none(row.get("创新性"))
        m.applicant_team_score = _float_or_none(row.get("申请人与团队"))
        m.breakthrough_score = _float_or_none(row.get("突破潜力"))
        m.budget_score = _float_or_none(row.get("预算合理性"))
        scores = [
            m.scientific_question_score,
            m.innovation_score,
            m.applicant_team_score,
            m.breakthrough_score,
            m.budget_score,
        ]
        m.total_score = sum(x for x in scores if x is not None) if any(x is not None for x in scores) else None
        m.overall_grade = str(row.get("综合评价") or "")
        m.funding_opinion = str(row.get("资助意见") or "")
        m.reviewer_notes = str(row.get("评审备注") or "")

    ranked = sorted(
        [r for r in records() if r.manual_review.total_score is not None],
        key=lambda x: x.manual_review.total_score or 0,
        reverse=True,
    )
    for idx, record in enumerate(ranked, start=1):
        record.manual_review.rank = idx


def manual_dataframe() -> pd.DataFrame:
    rows = []
    for r in records():
        m = r.manual_review
        rows.append(
            {
                "文件名": r.source_file,
                "申请人": r.applicant_name,
                "项目名称": r.project_title,
                "科学问题": m.scientific_question_score,
                "创新性": m.innovation_score,
                "申请人与团队": m.applicant_team_score,
                "突破潜力": m.breakthrough_score,
                "预算合理性": m.budget_score,
                "综合评价": m.overall_grade,
                "资助意见": m.funding_opinion,
                "评审备注": m.reviewer_notes,
            }
        )
    return pd.DataFrame(rows)


st.title("基金申请书整理与评审助手")
st.caption("批量解密 PDF → 规范化提取 → 人工校正 → AI 初评 → 批次评分与评语 → Excel/解密文档导出")

with st.expander("隐私与部署说明", expanded=True):
    st.markdown(
        """
- 密码不会写入文件、日志或数据库，仅在当前进程内交给 PDF 解密库使用。
- 本工具默认在内存中处理 PDF；下载前不会主动将解密文档落盘。
- 远程部署时，上传文件和密码仍会经过部署服务器的内存。涉密或未公开申请书建议在本机或单位内网通过 Docker 运行。
- AI 功能只发送结构化字段和必要正文区块，不上传解密 PDF 本体；关闭 AI 功能时不会调用外部模型。
        """
    )

upload_tab, initial_tab, batch_tab, export_tab = st.tabs(["1. 解密与整理", "2. AI 初评", "3. 批次评分与评语", "4. 导出"])

with upload_tab:
    uploaded_files = st.file_uploader(
        "上传一个或多个基金申请书 PDF",
        type=["pdf"],
        accept_multiple_files=True,
        help="支持同一批次多文件。当前版本优先支持 NSFC 2025/2026 通用申请书和海外优青申请书。",
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        common_password = st.text_input(
            "统一密码（未加密文件可留空）",
            type="password",
            key="common_pdf_password",
        )
    with col2:
        use_individual = st.checkbox("不同文件使用不同密码")

    per_file_passwords: dict[str, str] = {}
    if use_individual and uploaded_files:
        st.caption("以下密码只用于对应文件的当前解密操作。")
        for idx, uploaded in enumerate(uploaded_files):
            per_file_passwords[uploaded.name] = st.text_input(
                uploaded.name,
                type="password",
                key=f"pdf_password_{idx}_{uploaded.name}",
            )

    if st.button("开始解密并提取", type="primary", disabled=not uploaded_files):
        processed: list[ProcessedDocument] = []
        progress = st.progress(0, text="准备处理")
        errors: list[str] = []
        for idx, uploaded in enumerate(uploaded_files or []):
            progress.progress(idx / max(len(uploaded_files), 1), text=f"正在处理：{uploaded.name}")
            password = per_file_passwords.get(uploaded.name, common_password)
            try:
                doc = process_pdf_bytes(
                    source_file=uploaded.name,
                    pdf_bytes=uploaded.getvalue(),
                    password=password,
                    decrypted_name=decrypted_filename(uploaded.name),
                )
                processed.append(doc)
            except PDFPasswordError as exc:
                errors.append(f"{uploaded.name}：{exc}")
            except PDFProcessingError as exc:
                errors.append(f"{uploaded.name}：{exc}")
            except Exception as exc:
                errors.append(f"{uploaded.name}：未预期错误：{exc}")
        progress.progress(1.0, text="处理完成")
        st.session_state.documents = processed
        if errors:
            st.error("\n".join(errors))
        if processed:
            st.success(f"成功处理 {len(processed)} 个文件。")

    if records():
        st.subheader("规范化总表预览")
        basic_rows = []
        for r in records():
            basic_rows.append(
                {
                    "文件名": r.source_file,
                    "申请人": r.applicant_name,
                    "项目名称": r.project_title,
                    "依托单位": r.current_institution or r.proposed_institution,
                    "当前职称": r.current_title,
                    "申请直接费用(万元)": r.requested_amount_wan,
                    "团队总人数": r.team_total,
                    "高级职称人数": r.team_senior,
                    "基金主持与参与": r.funding_summary(),
                    "论文发表概况": r.publication_summary(),
                    "近两年代表性论文": r.recent_publication_summary(),
                    "提取警告": "；".join(r.warnings),
                }
            )
        basic_df = pd.DataFrame(basic_rows)
        editable_cols = ["申请人", "项目名称", "依托单位", "当前职称", "申请直接费用(万元)", "团队总人数", "高级职称人数"]
        edited_basic = st.data_editor(
            basic_df,
            hide_index=True,
            use_container_width=True,
            disabled=[c for c in basic_df.columns if c not in editable_cols],
            key="basic_editor",
        )
        if st.button("保存人工校正"):
            apply_basic_edits(edited_basic)
            st.success("已保存校正。")

        for record in records():
            with st.expander(f"{record.applicant_name}｜{record.project_title}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**基金经历**")
                    if record.funding:
                        st.dataframe(pd.DataFrame([x.to_dict() for x in record.funding]), hide_index=True, use_container_width=True)
                    else:
                        st.write("申请书简历中未列出近五年基金项目。")
                with c2:
                    st.write("**论文情况**")
                    if record.publications:
                        st.dataframe(pd.DataFrame([x.to_dict() for x in record.publications]), hide_index=True, use_container_width=True)
                    else:
                        st.write("未识别到论文条目。")

with initial_tab:
    if not records():
        st.info("请先在“解密与整理”中处理 PDF。")
    else:
        st.session_state.guide = st.text_area("评审指南/本批次要求", value=st.session_state.guide, height=220)
        ai_col1, ai_col2 = st.columns([2, 1])
        with ai_col1:
            api_key = st.text_input(
                "OpenAI API Key（不写入项目文件）",
                type="password",
                value="",
                help="也可在私有部署中通过 OPENAI_API_KEY 环境变量配置。",
                key="openai_api_key_input",
            )
        with ai_col2:
            model = st.text_input("模型", value="gpt-5.6-luna", key="model_name")
        use_server_key = bool(os.getenv("OPENAI_API_KEY"))
        if use_server_key:
            st.caption("服务器已配置 API Key；输入框留空时将使用服务器密钥。")

        filenames = [r.source_file for r in records()]
        selected = st.multiselect("选择生成初评的申请书", filenames, default=filenames)
        if st.button("生成 AI 初评", type="primary", disabled=not selected):
            key = api_key or os.getenv("OPENAI_API_KEY", "")
            if not key:
                st.error("请提供 API Key，或在部署环境中设置 OPENAI_API_KEY。")
            else:
                targets = selected_records(selected)
                progress = st.progress(0, text="开始生成初评")
                for idx, record in enumerate(targets):
                    progress.progress(idx / max(len(targets), 1), text=f"正在评价：{record.applicant_name}")
                    try:
                        record.ai_review = generate_initial_review(
                            record,
                            api_key=key,
                            model=model,
                            guide=st.session_state.guide,
                        )
                    except Exception as exc:
                        st.error(f"{record.source_file} 初评失败：{exc}")
                progress.progress(1.0, text="初评完成")

        for record in records():
            ai = record.ai_review
            with st.expander(f"{record.applicant_name}｜初评 {ai.preliminary_grade or '未生成'}", expanded=bool(ai.overall_assessment)):
                if not ai.overall_assessment:
                    st.write("尚未生成。")
                    continue
                st.write(ai.overall_assessment)
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.write("**优势**")
                    for item in ai.strengths:
                        st.write("-", item)
                with c2:
                    st.write("**需要完善之处**")
                    for item in ai.weaknesses:
                        st.write("-", item)
                with c3:
                    st.write("**风险与证据缺口**")
                    for item in ai.risks + ai.evidence_gaps:
                        st.write("-", item)
                st.write("**基金经历评价：**", ai.funding_history_assessment)
                st.write("**论文发表评价：**", ai.publication_assessment)

with batch_tab:
    if not records():
        st.info("请先处理 PDF。")
    else:
        st.markdown("各分项分值由评审人自行设定。本表不自动替代专家判断；保存后将按总分降序生成批次排序。")
        manual_df = manual_dataframe()
        edited_manual = st.data_editor(
            manual_df,
            hide_index=True,
            use_container_width=True,
            disabled=["文件名", "申请人", "项目名称"],
            column_config={
                "科学问题": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0),
                "创新性": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0),
                "申请人与团队": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0),
                "突破潜力": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0),
                "预算合理性": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0),
                "综合评价": st.column_config.SelectboxColumn(options=["", "A 优", "B 良", "C 中", "D 差"]),
                "资助意见": st.column_config.SelectboxColumn(options=["", "A 优先资助", "B 可资助", "C 不予资助"]),
                "评审备注": st.column_config.TextColumn(width="large"),
            },
            key="manual_editor",
        )
        if st.button("保存评分并更新排序", type="primary"):
            apply_manual_edits(edited_manual)
            st.success("评分与排序已保存。")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "排序": r.manual_review.rank,
                            "申请人": r.applicant_name,
                            "项目名称": r.project_title,
                            "总分": r.manual_review.total_score,
                            "综合评价": r.manual_review.overall_grade,
                            "资助意见": r.manual_review.funding_opinion,
                        }
                        for r in sorted(records(), key=lambda x: x.manual_review.rank or 9999)
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )

        api_col1, api_col2 = st.columns([2, 1])
        with api_col1:
            final_api_key = st.text_input("生成最终评语所用 API Key", type="password", key="final_api_key")
        with api_col2:
            final_model = st.text_input("最终评语模型", value="gpt-5.6-terra", key="final_model")
        selected_final = st.multiselect("选择生成最终评语的项目", [r.source_file for r in records()], default=[])
        if st.button("按人工结论生成最终评语", disabled=not selected_final):
            key = final_api_key or os.getenv("OPENAI_API_KEY", "")
            if not key:
                st.error("请提供 API Key。")
            else:
                targets = selected_records(selected_final)
                context = batch_context()
                progress = st.progress(0, text="开始生成最终评语")
                for idx, record in enumerate(targets):
                    progress.progress(idx / max(len(targets), 1), text=f"正在生成：{record.applicant_name}")
                    if not record.manual_review.overall_grade or not record.manual_review.funding_opinion:
                        st.warning(f"{record.applicant_name} 尚未填写综合评价或资助意见，已跳过。")
                        continue
                    try:
                        record.ai_review.final_review = generate_final_review(
                            record,
                            api_key=key,
                            model=final_model,
                            guide=st.session_state.guide,
                            batch_context=context,
                        )
                    except Exception as exc:
                        st.error(f"{record.source_file} 评语生成失败：{exc}")
                progress.progress(1.0, text="最终评语生成完成")

        for record in records():
            if record.ai_review.final_review:
                with st.expander(f"{record.applicant_name}｜{record.manual_review.overall_grade}｜{record.manual_review.funding_opinion}"):
                    st.write(record.ai_review.final_review)

with export_tab:
    if not records():
        st.info("请先处理 PDF。")
    else:
        excel_bytes = build_excel(records())
        json_bytes = json.dumps([r.to_dict() for r in records()], ensure_ascii=False, indent=2).encode("utf-8")
        decrypted_files = [(doc.decrypted_name, doc.decrypted_bytes) for doc in st.session_state.documents]
        decrypted_zip = build_decrypted_zip(decrypted_files)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                "下载 Excel 汇总",
                data=excel_bytes,
                file_name="基金申请书汇总与评审.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col2:
            st.download_button(
                "下载解密 PDF 压缩包",
                data=decrypted_zip,
                file_name="decrypted_pdfs.zip",
                mime="application/zip",
                use_container_width=True,
            )
        with col3:
            st.download_button(
                "下载结构化 JSON",
                data=json_bytes,
                file_name="grant_applications.json",
                mime="application/json",
                use_container_width=True,
            )

        st.write("**单个解密文档**")
        for doc in st.session_state.documents:
            st.download_button(
                f"下载 {doc.decrypted_name}",
                data=doc.decrypted_bytes,
                file_name=doc.decrypted_name,
                mime="application/pdf",
                key=f"download_{doc.decrypted_name}",
            )
