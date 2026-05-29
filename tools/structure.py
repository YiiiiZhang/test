"""
tools/structure.py
─────────────────────────────────────────────
Step 2 tools: CRUD operations on StructureState

  generate_structure — LLM generates an initial structure draft in one call
  add_section        — add a new section
  update_section     — modify one field of an existing section
  delete_section     — remove a section
  set_style          — set the language style / tone
  set_introduction   — set the survey opening introduction
  get_structure      — read the current structure state
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
- If questionnaire_size is null, choose a reasonable number (10-15).
- Output JSON only.
""".strip()


def generate_structure(llm: LocalQwenLLM, state: AgentState) -> ToolResult:
    """
    Use the LLM to generate an initial survey structure draft from the
    confirmed requirements. After generation, the user can refine it
    with add/update/delete_section calls.
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
    """Add a new section to the survey structure (CREATE)."""
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
    """Modify one field of an existing section (UPDATE)."""
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
            f"Section '{section_id}'.{field}: {old_val!r} -> {value!r}\n"
            f"Total planned questions: {total}"
        ),
    )


def delete_section(state: AgentState, section_id: str) -> ToolResult:
    """Remove a section from the structure (DELETE)."""
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
    """Set the language style / tone for the entire survey."""
    state.structure.style = style
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=f"Style set to: {style!r}",
    )


def set_introduction(state: AgentState, introduction: str) -> ToolResult:
    """Set or update the survey's opening introduction for respondents."""
    state.structure.introduction = introduction
    return ToolResult(
        type=ResultType.OBSERVATION,
        content="Introduction updated.",
    )


def get_structure(state: AgentState) -> ToolResult:
    """Read and display the current structure state (READ operation)."""
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
