from __future__ import annotations

from grant_review.extractors.common import parse_funding_entry, split_publication_entries
from grant_review.text_utils import clean_cjk_value


def test_clean_cjk_parentheses() -> None:
    assert clean_cjk_value("粤港澳大湾区(广东)量子科学中心") == "粤港澳大湾区（广东）量子科学中心"


def test_funding_role_and_grant_number() -> None:
    item = parse_funding_entry(
        "国家自然科学基金委员会, 联合基金项目, U20A2074, 基于里德堡原子阵列的量子计算研究, "
        "2021-01-01 至 2024-12-31, 260万元, 结题, 参与",
        "NSFC",
    )
    assert item.grant_no == "U20A2074"
    assert item.role == "参与"
    assert item.title == "基于里德堡原子阵列的量子计算研究"


def test_publication_split_ignores_issue_number() -> None:
    block = """
(1) A; B; Paper one, Physical Review Letters, 2025, 135(11): 110202 (期刊论文) (本人标注: 唯一第一作者)
(2) C; D; Paper two, Physical Review A, 2024, 109(2): 022431 (期刊论文) (本人标注: 共同通讯作者)
"""
    entries = split_publication_entries(block)
    assert len(entries) == 2
    assert entries[0][0] == 1
    assert entries[1][0] == 2
