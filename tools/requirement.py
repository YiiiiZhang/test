"""
tools/requirement.py
─────────────────────────────────────────────
Step 1 tools: CRUD operations on RequirementState

  parse_requirements    — LLM parses user input and merges fields into state
  set_requirement_field — directly write a single field
  get_requirements      — read the current state (for LLM decision-making)
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
    Use the LLM to extract requirement fields from user input and merge them
    into the current RequirementState. Supports multi-turn accumulation:
    existing non-null fields are never overwritten.
    """
    existing = state.requirements.model_dump_json(indent=2)
    prompt = _PARSE_PROMPT.format(existing=existing, user_input=user_input)
    raw = llm.chat([{"role": "user", "content": prompt}]).strip()

    # Strip any markdown code fences the LLM may have added
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
        # Only accept known fields; ignore any extra keys the LLM may output
        valid_fields = set(RequirementState.model_fields.keys())
        update = {k: v for k, v in data.items() if k in valid_fields}
        # Merge: only apply non-None new values, preserving existing non-null values
        current = state.requirements.model_dump()
        for k, v in update.items():
            if v is not None:
                current[k] = v
        state.requirements = RequirementState(**current)

        missing = state.requirements.missing_fields()
        status = (
            "Requirements complete. All required fields filled."
            if not missing
            else f"Still missing: {missing}"
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
    Directly set a single requirement field to the given value.
    Use this for precise single-field corrections when the user explicitly
    points out that one field is wrong.
    """
    valid = list(RequirementState.model_fields.keys())
    if field not in valid:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Unknown field '{field}'. Valid fields: {valid}",
        )
    setattr(state.requirements, field, value)
    missing = state.requirements.missing_fields()
    status = "All required fields filled." if not missing else f"Still missing: {missing}"
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
    Read and display the current requirements state (READ operation).
    """
    missing = state.requirements.missing_fields()
    status = "Complete." if not missing else f"Missing required fields: {missing}"
    return ToolResult(
        type=ResultType.OBSERVATION,
        content=(
            f"Current requirements:\n"
            f"{state.requirements.model_dump_json(indent=2)}\n\n"
            f"{status}"
        ),
    )
