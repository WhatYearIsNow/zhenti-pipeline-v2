"""S4 回归：skills/ 标准化（Agent Skills 规范的基本面）。

- 三份 SKILL.md 具备合法 frontmatter（name/description）；
- 相对引用的目标文件存在（自动检查，不凭记忆）；
- 公共 SKILL 文档不含私人事实（私人路径/授权记录/账号周边）。
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
PRIVATE_RE = re.compile(r"C:[/\\]Users|D:[/\\]Documents|/Users/|/home/|/opt/toy")

EXPECTED = {
    "zhenti-pipeline-v2",
    "zhenti-tiku",
    "exam-compilation",
}


def test_skill_files_exist():
    found = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
    assert EXPECTED <= found, found


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_frontmatter_valid(name):
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{name}: 缺 frontmatter"
    fm = m.group(1)
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", fm, re.M), fm
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    assert desc and len(desc.group(1)) >= 20, "description 须可触发"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_relative_references_exist(name):
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#\s]+)\)", text)
    for rel in links:
        target = (SKILLS / name / rel).resolve()
        assert target.is_file(), f"{name}: 引用不存在 {rel}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_no_private_facts_in_public_skill(name):
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    hit = PRIVATE_RE.search(text)
    assert not hit, f"{name}: 公共 skill 文档含私人事实 {hit.group(0)!r}"


def test_external_review_not_public_by_default():
    # 方案 §1：外审网页适配器（含账号/浏览器配置）不进公共 skills；
    # 本地闭环工具在 sources/.../external-review，公开化前须独立审查。
    assert not (SKILLS / "external-review").exists()
