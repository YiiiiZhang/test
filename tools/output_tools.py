"""
tools/output_tools.py
─────────────────────────────────────────────
Step 4 tools: produce the final survey output

  execute_output — save local JSON and/or publish to Google Forms
"""

import json
from state.models import AgentState
from tools.base import ToolResult, ResultType


def _build_payload(state: AgentState) -> list:
    """Convert QuestionsState into the format expected by google_forms.py."""
    payload = [
        {
            "id": 0,
            "survey_title":       state.questions.survey_title       or "Survey",
            "survey_description": state.questions.survey_description or "",
        }
    ]
    for q in state.questions.questions:
        payload.append(q.model_dump())
    return payload


def execute_output(state: AgentState, configs: dict) -> ToolResult:
    """
    Execute the final output step:
    - If configs["save_survey"]["save_to_local"] is True, save JSON to disk.
    - If configs["save_survey"]["save_to_google_forms"] is True, publish to Google Forms.
    """
    if not state.questions.questions:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content="Error: no questions to output. Complete the question generation step first.",
        )

    from tools.google_forms import survey_executor_google

    payload      = _build_payload(state)
    payload_json = json.dumps(payload, ensure_ascii=False)

    result = survey_executor_google(questions_data=payload_json)

    if isinstance(result, str) and "error" in result.lower():
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Output failed: {result}",
        )

    # Record output status
    state.output.status = "success"
    if isinstance(result, str) and result.startswith("http"):
        state.output.form_url = result

    return ToolResult(
        type=ResultType.TASK_DONE,
        content=(
            f"Survey successfully created!\n"
            f"Result: {result}"
        ),
    )
