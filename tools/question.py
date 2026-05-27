"""
tools/question.py
─────────────────────────────────────────────
Step 3 工具：对 QuestionsState 的增删查改

  generate_all_questions      — LLM 一键生成全部题目草稿
  generate_section_questions  — 对单个 section 重新生成/补充题目
  add_question                — 手动新增一道题
  update_question             — 修改某道题的某字段
  delete_question             — 删除某道题
  set_survey_meta             — 设置问卷标题 / 描述
  get_questions               — 读取当前所有题目
  validate_questions          — LLM 对全套题目做质量检查
"""

import json
from llm import LocalQwenLLM
from state.models import AgentState, QuestionItem
from tools.base import ToolResult, ResultType

# ─────────────────────────────────────────────────────────────────────────────
# Prompt 模板
# ─────────────────────────────────────────────────────────────────────────────

_GEN_ALL_PROMPT = """
You are a survey question generation expert.
Generate ALL questions for the survey based on the requirements and structure below.

Requirements:
{requirements}

Survey structure (sections and question distribution):
{structure}

Output ONLY a JSON list:
[
  {{
    "id": 0,
    "survey_title": "Survey Title",
    "survey_description": "Introduction / instructions for respondents"
  }},
  {{
    "id": 1,
    "section_id": "section_id_from_structure",
    "type": "single_choice | multiple_choice | text",
    "question": "question text",
    "options": ["Option A", "Option B"]
  }}
]

Rules:
1. item id=0 is the meta header (title + description), MUST be first.
2. The question count and types for each section MUST exactly match the structure.
3. For type=text, options MUST be [].
4. Options for single/multiple choice must be MECE and reasonable.
5. Output JSON only — no explanation.
""".strip()


_GEN_SECTION_PROMPT = """
You are a survey question generation expert.
Generate exactly {count} question(s) for the section described below.

Survey requirements context:
{requirements}

Section details:
{section}

Prohibited content: {prohibited}

Return ONLY a JSON list of question objects (no meta header):
[
  {{
    "type": "single_choice | multiple_choice | text",
    "question": "question text",
    "options": ["Option A", "Option B"]
  }}
]
Output JSON only.
""".strip()


_VALIDATE_PROMPT = """
You are a strict survey quality inspector.
Review the complete survey for quality issues.

Requirements:
{requirements}

Questions:
{questions}

Check all of the following:
1. Leading or biased wording.
2. Prohibited content violations (prohibited: {prohibited}).
3. MECE quality of options (single/multiple choice).
4. Alignment between each question and its section topic.
5. Semantic duplicates or redundant questions.
6. Tone consistency throughout the survey.

Return ONLY a JSON object:
{{
    "is_valid": true | false,
    "issues": ["describe each specific issue found, or empty list if none"],
    "suggestions": "overall improvement suggestions, or empty string if none"
}}
Output JSON only.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def generate_all_questions(llm: LocalQwenLLM, state: AgentState) -> ToolResult:
    """
    LLM 根据已确认的结构一次性生成全部题目草稿。
    生成后用户可通过 add/update/delete_question 逐题调整。
    """
    req    = state.requirements.model_dump_json(indent=2)
    struct = state.structure.model_dump_json(indent=2)
    prompt = _GEN_ALL_PROMPT.format(requirements=req, structure=struct)
    raw    = llm.chat([{"role": "user", "content": prompt}]).strip()

    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    try:
        data = json.loads(raw)
    except Exception as e:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Generation failed (JSON parse error): {e}\nRaw:\n{raw}",
        )

    new_questions = []
    for item in data:
        if item.get("id") == 0:
            state.questions.survey_title       = item.get("survey_title")
            state.questions.survey_description = item.get("survey_description")
        else:
            try:
                new_questions.append(QuestionItem(**item))
            except Exception:
                pass  # 跳过格式不合法的条目

    state.questions.questions = new_questions

    # 生成摘要
    section_counts: dict[str, int] = {}
    for q in new_questions:
        section_counts[q.section_id] = section_counts.get(q.section_id, 0) + 1

    lines = [f"Generated {len(new_questions)} questions:"]
    for sid, cnt in section_counts.items():
        lines.append(f"  [{sid}] {cnt} question(s)")
    return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))


def generate_section_questions(
    llm: LocalQwenLLM,
    state: AgentState,
    section_id: str,
    count: int,
) -> ToolResult:
    """
    重新生成（或补充）某个 section 的题目。
    先清空该 section 已有题目，再生成新题目。
    """
    section = state.structure.get_section(section_id)
    if not section:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=(
                f"Section '{section_id}' not found in structure. "
                f"Available: {state.structure.section_ids()}"
            ),
        )

    req      = state.requirements.model_dump_json(indent=2)
    sec_json = section.model_dump_json(indent=2)
    prohibited = state.requirements.prohibited_content or "none"
    prompt = _GEN_SECTION_PROMPT.format(
        requirements=req,
        section=sec_json,
        count=count,
        prohibited=prohibited,
    )
    raw = llm.chat([{"role": "user", "content": prompt}]).strip()

    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    try:
        items = json.loads(raw)
    except Exception as e:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Generation failed: {e}\nRaw:\n{raw}",
        )

    # 清除该 section 旧题目，重新填入
    state.questions.questions = [
        q for q in state.questions.questions if q.section_id != section_id
    ]
    new_qs = []
    for item in items:
        q = QuestionItem(
            id=state.questions.next_id(),
            section_id=section_id,
            type=item.get("type", "text"),
            question=item.get("question", ""),
            options=item.get("options", []),
        )
        state.questions.questions.append(q)
        new_qs.append(q)

    lines = [f"Regenerated {len(new_qs)} question(s) for section '{section_id}':"]
    for q in new_qs:
        lines.append(f"  Q{q.id} ({q.type}): {q.question}")
    return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))


def add_question(
    state: AgentState,
    section_id: str,
    question_type: str,
    question: str,
    options: list = None,
) -> ToolResult:
    """手动新增一道题（CREATE）。"""
    if section_id not in state.structure.section_ids():
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=(
                f"Section '{section_id}' is not in the structure. "
                f"Please add it to the structure first, or use an existing section: "
                f"{state.structure.section_ids()}"
            ),
        )
    qid = state.questions.next_id()
    q = QuestionItem(
        id=qid,
        section_id=section_id,
        type=question_type,
        question=question,
        options=options or [],
    )
    state.questions.questions.append(q)
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Question Q{qid} added to [{section_id}].\n"
            f"  Type: {question_type}\n"
            f"  Text: {question}\n"
            f"  Options: {options or []}\n"
            f"Total questions now: {len(state.questions.questions)}"
        ),
    )


def update_question(
    state: AgentState,
    question_id: int,
    field: str,
    value,
) -> ToolResult:
    """修改某道题的一个字段（UPDATE）。"""
    q = state.questions.get_question(question_id)
    if not q:
        all_ids = [x.id for x in state.questions.questions]
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Question {question_id} not found. Existing IDs: {all_ids}",
        )
    valid_fields = list(QuestionItem.model_fields.keys())
    if field not in valid_fields:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Unknown field '{field}'. Valid fields: {valid_fields}",
        )
    old_val = getattr(q, field)
    setattr(q, field, value)
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=f"Q{question_id}.{field}: {old_val!r} → {value!r}",
    )


def delete_question(state: AgentState, question_id: int) -> ToolResult:
    """删除某道题（DELETE）。"""
    before = len(state.questions.questions)
    state.questions.questions = [
        q for q in state.questions.questions if q.id != question_id
    ]
    if len(state.questions.questions) == before:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Question {question_id} not found.",
        )
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Question Q{question_id} deleted. "
            f"Remaining: {len(state.questions.questions)} question(s)."
        ),
    )


def set_survey_meta(state: AgentState, survey_title: str = None,
                    survey_description: str = None) -> ToolResult:
    """设置问卷标题和介绍文字。"""
    updated = []
    if survey_title is not None:
        state.questions.survey_title = survey_title
        updated.append(f"title = {survey_title!r}")
    if survey_description is not None:
        state.questions.survey_description = survey_description
        updated.append("description updated")
    if not updated:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content="No fields updated. Provide survey_title and/or survey_description.",
        )
    return ToolResult(
        type=ResultType.OBSERVATION,
        content="Survey meta updated: " + ", ".join(updated),
    )


def get_questions(state: AgentState) -> ToolResult:
    """读取当前所有题目（READ 操作）。"""
    qs = state.questions
    lines = [
        f"Title: {qs.survey_title or '(not set)'}",
        f"Description: {qs.survey_description or '(not set)'}",
        f"Total questions: {len(qs.questions)}",
        "",
    ]
    # 按 section 分组展示
    section_map: dict[str, list[QuestionItem]] = {}
    for q in qs.questions:
        section_map.setdefault(q.section_id, []).append(q)

    for sid, qlist in section_map.items():
        lines.append(f"[{sid}]")
        for q in qlist:
            opts = f"  options={q.options}" if q.options else ""
            lines.append(f"  Q{q.id} ({q.type}): {q.question}{opts}")

    return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))


def validate_questions(llm: LocalQwenLLM, state: AgentState) -> ToolResult:
    """LLM 对全部题目做质量检查（领导性措辞、禁止内容、选项质量、整体一致性）。"""
    req        = state.requirements.model_dump_json(indent=2)
    qs_json    = json.dumps([q.model_dump() for q in state.questions.questions],
                            ensure_ascii=False, indent=2)
    prohibited = state.requirements.prohibited_content or "none"
    prompt     = _VALIDATE_PROMPT.format(
        requirements=req, questions=qs_json, prohibited=prohibited
    )
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
        result = json.loads(raw)
        is_valid  = result.get("is_valid", False)
        issues    = result.get("issues", [])
        suggestions = result.get("suggestions", "")
        status    = "✓ PASSED" if is_valid else "✗ FAILED"
        lines = [f"Validation {status}"]
        if issues:
            lines.append("Issues found:")
            for iss in issues:
                lines.append(f"  - {iss}")
        if suggestions:
            lines.append(f"Suggestions: {suggestions}")
        return ToolResult(type=ResultType.OBSERVATION, content="\n".join(lines))
    except Exception:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Validation result (raw):\n{raw}",
        )
