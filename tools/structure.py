"""
tools/structure.py
─────────────────────────────────────────────
Step 2 工具：对 StructureState 的增删查改

  generate_structure — LLM 一键生成初始结构草稿
  add_section        — 新增一个 section
  update_section     — 修改某 section 的某字段
  delete_section     — 删除某 section
  set_style          — 设置语言风格
  set_introduction   — 设置问卷介绍语
  get_structure      — 读取当前结构
"""

import json
from llm import LocalQwenLLM
from state.models import AgentState, SectionItem
from tools.base import ToolResult, ResultType

_STRUCTURE_PROMPT = """
You are a professional survey structure planner.
Based on the confirmed requirements below, design a macro-level survey outline.

Requirements:
{requirements}

Return ONLY a valid JSON object:
{{
    "style": "language style adapted to the target respondents",
    "introduction": "welcome message / instructions for respondents",
    "sections": [
        {{
            "section_id": "unique_snake_case_id",
            "theme": "what this section is about",
            "description": "design rationale for this section",
            "question_count": <integer>,
            "question_types": ["single_choice", "multiple_choice", "text"]
        }}
    ]
}}

Constraints:
- The sum of all section question_counts MUST equal the total questionnaire_size in the requirements.
- If questionnaire_size is null, choose a reasonable number (10–15).
- Output JSON only.
""".strip()


def generate_structure(llm: LocalQwenLLM, state: AgentState) -> ToolResult:
    """
    LLM 根据已确认的需求一键生成问卷结构草稿。
    生成后，用户可通过 add/update/delete_section 继续调整。
    """
    req_json = state.requirements.model_dump_json(indent=2)
    prompt = _STRUCTURE_PROMPT.format(requirements=req_json)
    raw = llm.chat([{"role": "user", "content": prompt}]).strip()

    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    try:
        data = json.loads(raw)
        state.structure.style        = data.get("style")
        state.structure.introduction = data.get("introduction")
        state.structure.sections     = [SectionItem(**s) for s in data.get("sections", [])]

        total = state.structure.total_questions()
        lines = [
            f"Structure generated (total questions: {total}):",
            f"  Style: {state.structure.style}",
            f"  Sections ({len(state.structure.sections)}):",
        ]
        for s in state.structure.sections:
            lines.append(
                f"    [{s.section_id}] {s.theme!r}  "
                f"count={s.question_count}  types={s.question_types}"
            )
        return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))

    except Exception as e:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Structure generation failed: {e}\nRaw output:\n{raw}",
        )


def add_section(
    state: AgentState,
    section_id: str,
    theme: str,
    description: str = "",
    question_count: int = 0,
    question_types: list = None,
) -> ToolResult:
    """新增一个 section。"""
    if state.structure.get_section(section_id):
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Section '{section_id}' already exists. Use update_section to modify it.",
        )
    section = SectionItem(
        section_id=section_id,
        theme=theme,
        description=description,
        question_count=question_count,
        question_types=question_types or [],
    )
    state.structure.sections.append(section)
    total = state.structure.total_questions()
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Section '{section_id}' added.\n"
            f"Total sections: {len(state.structure.sections)}  "
            f"Total planned questions: {total}"
        ),
    )


def update_section(state: AgentState, section_id: str, field: str, value) -> ToolResult:
    """修改某 section 的一个字段。"""
    section = state.structure.get_section(section_id)
    if not section:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=(
                f"Section '{section_id}' not found. "
                f"Existing sections: {state.structure.section_ids()}"
            ),
        )
    valid_fields = list(SectionItem.model_fields.keys())
    if field not in valid_fields:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Unknown field '{field}'. Valid fields: {valid_fields}",
        )
    old_val = getattr(section, field)
    setattr(section, field, value)
    total = state.structure.total_questions()
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Section '{section_id}'.{field}: {old_val!r} → {value!r}\n"
            f"Total planned questions: {total}"
        ),
    )


def delete_section(state: AgentState, section_id: str) -> ToolResult:
    """删除某 section。"""
    before = len(state.structure.sections)
    state.structure.sections = [
        s for s in state.structure.sections if s.section_id != section_id
    ]
    if len(state.structure.sections) == before:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Section '{section_id}' not found.",
        )
    total = state.structure.total_questions()
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Section '{section_id}' deleted. "
            f"Remaining sections: {state.structure.section_ids()}  "
            f"Total planned questions: {total}"
        ),
    )


def set_style(state: AgentState, style: str) -> ToolResult:
    """设置问卷语言风格。"""
    state.structure.style = style
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=f"Style set to: {style!r}",
    )


def set_introduction(state: AgentState, introduction: str) -> ToolResult:
    """设置问卷开头介绍语。"""
    state.structure.introduction = introduction
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=f"Introduction updated.",
    )


def get_structure(state: AgentState) -> ToolResult:
    """读取当前结构状态（READ 操作）。"""
    struct = state.structure
    lines = [
        f"Style: {struct.style or '(not set)'}",
        f"Introduction: {struct.introduction or '(not set)'}",
        f"Sections ({len(struct.sections)}, total questions: {struct.total_questions()}):",
    ]
    for s in struct.sections:
        lines.append(
            f"  [{s.section_id}] {s.theme!r}  "
            f"count={s.question_count}  types={s.question_types}\n"
            f"    desc: {s.description}"
        )
    return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))
