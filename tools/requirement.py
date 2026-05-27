"""
tools/requirement.py
─────────────────────────────────────────────
Step 1 工具：对 RequirementState 的增删查改

  parse_requirements    — LLM 解析用户输入并合并到状态
  set_requirement_field — 直接写入单个字段
  get_requirements      — 读取当前状态（展示给 LLM 决策用）
"""

import json
from llm import LocalQwenLLM
from state.models import AgentState, RequirementState
from tools.base import ToolResult, ResultType

_PARSE_PROMPT = """
You are a survey requirement parser.
Extract structured requirement fields from the NEW user input and MERGE them with the EXISTING data.

Existing data (keep all valid fields; only update what the user explicitly mentioned):
{existing}

New user input:
{user_input}

Output ONLY a valid JSON object with these fields:
{{
    "survey_topic":         "string | null",
    "survey_object":        "string | null",
    "survey_goal":          "string | null",
    "questionnaire_size":   "a number as string, e.g. '10' | null",
    "need_background_info": true | false | null,
    "prohibited_content":   "string | null",
    "other":                "string | null"
}}

Rules:
1. MERGE: never overwrite a non-null existing field with null unless the user explicitly retracts it.
2. Fields not mentioned stay as-is from existing data.
3. Output JSON only — no explanation, no markdown fence.
""".strip()


def parse_requirements(llm: LocalQwenLLM, state: AgentState, user_input: str) -> ToolResult:
    """
    LLM 从用户输入中提取需求字段，并合并进当前 RequirementState。
    支持多轮累积：已有字段不被覆盖。
    """
    existing = state.requirements.model_dump_json(indent=2)
    prompt = _PARSE_PROMPT.format(existing=existing, user_input=user_input)
    raw = llm.chat([{"role": "user", "content": prompt}]).strip()

    # 去除可能存在的 markdown 代码围栏
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
        # 只更新合法字段，忽略 LLM 可能输出的多余 key
        valid_fields = set(RequirementState.model_fields.keys())
        update = {k: v for k, v in data.items() if k in valid_fields}
        # 合并：非 None 的新值才更新，保持已有非空值
        current = state.requirements.model_dump()
        for k, v in update.items():
            if v is not None:
                current[k] = v
        state.requirements = RequirementState(**current)

        missing = state.requirements.missing_fields()
        status = (
            f"✓ Requirements complete. All required fields filled."
            if not missing
            else f"⚠ Still missing: {missing}"
        )
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=(
                f"Requirements updated.\n"
                f"{state.requirements.model_dump_json(indent=2)}\n\n"
                f"{status}"
            ),
        )
    except Exception as e:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Parse failed: {e}\nRaw LLM output:\n{raw}",
        )


def set_requirement_field(state: AgentState, field: str, value) -> ToolResult:
    """
    直接设置需求的某个字段（精确修改，无需 LLM）。
    适合用于用户明确指出某个字段有误时。
    """
    valid = list(RequirementState.model_fields.keys())
    if field not in valid:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Unknown field '{field}'. Valid fields: {valid}",
        )
    setattr(state.requirements, field, value)
    missing = state.requirements.missing_fields()
    status = "✓ All required fields filled." if not missing else f"⚠ Still missing: {missing}"
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Set {field} = {value!r}\n"
            f"Current state:\n{state.requirements.model_dump_json(indent=2)}\n\n"
            f"{status}"
        ),
    )


def get_requirements(state: AgentState) -> ToolResult:
    """
    读取当前需求状态（READ 操作）。
    """
    missing = state.requirements.missing_fields()
    status = "✓ Complete." if not missing else f"⚠ Missing required fields: {missing}"
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Current requirements:\n"
            f"{state.requirements.model_dump_json(indent=2)}\n\n"
            f"{status}"
        ),
    )
