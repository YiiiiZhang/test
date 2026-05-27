"""
tools/output_tools.py
─────────────────────────────────────────────
Step 4 工具：生成最终问卷输出

  execute_output — 保存本地 JSON 和/或推送到 Google Forms
"""

import json
from state.models import AgentState
from tools.base import ToolResult, ResultType


def _build_payload(state: AgentState) -> list:
    """将 QuestionsState 转换为 google_forms.py 所需格式。"""
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
    执行最终输出：
    - 若 configs["save_survey"]["save_to_local"] 为 True，保存 JSON 到本地。
    - 若 configs["save_survey"]["save_to_google_forms"] 为 True，创建 Google Form。
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

    # 记录输出状态
    state.output.status = "success"
    if isinstance(result, str) and result.startswith("http"):
        state.output.form_url = result

    return ToolResult(
        type=ResultType.TASK_DONE,
        content=(
            f"✓ Survey successfully created!\n"
            f"Result: {result}"
        ),
    )
