# prompts.py
from state import Plan

# --- 工具元数据定义 ---
TOOL_META = {
    "requirement_parser": {
        "purpose": "Extract new survey requirements from user input and merge them with previously extracted data.",
        "params": '{"user_input": "the user\'s latest reply", "previous_data": "the JSON string of previously extracted requirements (use {} if this is the first time)"}'
    },
    "requirement_check": {
        "purpose": "check whether the parsed requirements have all the mandatory fields filled.",
        "params": '{"parse_data": "the JSON string returned by requirement_parser"}'
    },
    "generate_question": {
        "purpose": "when the user's requirements are incomplete, generate a follow-up question based on the error information.",
        "params": '{"err_message": "description of the missing field or clarification needed"}'
    },
    "macro_structure_planner": {
        "purpose": "plan the high-level survey outline, including sections, themes, and language style.",
        "params": '{"requirements": "the complete requirement JSON string"}'
    },
    "question_distribution_planner": {
        "purpose": "assign question counts and question types to each section after the outline is ready.",
        "params": '{"requirements": "the complete requirement JSON string", "macro_structure": "the outline returned by macro_structure_planner"}'
    },
    "detailed_question_generator": {
        "purpose": "generate detailed survey questions strictly according to the outline and question distribution.",
        "params": '{"requirements": "requirements JSON", "macro_structure": "outline JSON", "distribution": "the plan returned by question_distribution_planner"}'
    },
    "single_question_checker": {
        "purpose": "check a single question for leading wording, reasonableness, and prohibited content.",
        "params": '{"question_json": "the JSON string of a single question", "prohibited_content": "content that must not appear", "section_topic": "the section topic for this question"}'
    },
    "overall_question_checker": {
        "purpose": "check the full survey for count, repetition, and overall bias.",
        "params": '{"all_questions_json": "the JSON list string of all questions", "expected_size": "expected survey size such as small or medium"}'
    },
    "mcp_survey_executor": {
        "purpose": "Save generated survey questions JSON string to a local JSON file after generate all of questions.",
        "params": '{"questions_data": "the final JSON string of all questions"}'
    },
    "finish_step": {
        "purpose": "when a plan step has been fully completed based on tool results, you must call this tool to solidify the stage result into the Information Base.",
        "params": '{"step_title": "the English step name defined in the plan", "result_summary": "the essential result produced by that step"}'
    }
}

# --- 工具分类配置 ---
GLOBAL_TOOLS = ["finish_step", "generate_question"]

TASK_TOOLS_MAP = {
    "Requirement Analysis": ["requirement_parser", "requirement_check"],
    "Survey Structure Planning": ["macro_structure_planner"],
    "Question Generation": ["question_distribution_planner", "detailed_question_generator"],
    "Question Validation": ["single_question_checker", "overall_question_checker"],
    "Survey Output": ["mcp_survey_executor"]
}

BASE_PROMPT = """You are a professional survey generation assistant (QA Agent). A set of tools is available to help you complete the task. Based on the user's input and the current plan, use these tools step by step in a reasonable way.

[Tool Call Specification]
Whenever you decide to use a tool, you must output one and only one ```json``` code block in the following format, with no extra explanation:
```json
{
    "name": "tool_name",
    "params": {
        "param_name": "param_value"
    }
}
```"""

WORKFLOW_GUIDE = """[Workflow Guide]
- Always check the current plan status and advance step by step.
- Only the tools relevant to the current pending sub-task (and global tools) are shown above.
- Use the [Information Base] to retrieve outputs and context from previously completed steps.
- If a tool result indicates missing information or validation failure, use the feedback to regenerate or adjust the next action.
- When the current sub-task is thoroughly complete, YOU MUST call `finish_step` to solidify the result into the Information Base before moving to the next sub-task."""

def build_system_prompt(plan: Plan) -> str:
    """根据当前的执行计划(Plan)动态生成系统提示词"""
    
    # 1. 获取当前的子任务 (Sub-task)
    current_step_title = None
    for step in plan.steps:
        if step.status == "pending":
            current_step_title = step.title
            break

    # 2. 构建全局信息库 (Information Base) - 只显示已完成任务的成果
    info_base_lines = ["[Information Base - Global Task Memory]"]
    has_results = False
    for step in plan.steps:
        if step.status == "completed" and step.result:
            info_base_lines.append(f" - {step.title}: {step.result}")
            has_results = True
    if not has_results:
        info_base_lines.append(" - (Empty. No subtasks completed yet.)")

    # 3. 构建当前任务计划 (Current Task Plan)
    plan_lines = ["[Current Task Plan]"]
    for idx, step in enumerate(plan.steps, start=1):
        indicator = "-> " if step.title == current_step_title else "   "
        plan_lines.append(
            f"{indicator}Step {idx}. {step.title} | status={step.status} | description={step.description}"
        )

    # 4. 动态聚合可用工具 (Global Tools + Task-specific Tools)
    allowed_tools = list(GLOBAL_TOOLS)
    if current_step_title in TASK_TOOLS_MAP:
        allowed_tools.extend(TASK_TOOLS_MAP[current_step_title])

    tools_lines = ["[Available Tools (Global & Current Sub-task)]"]
    for idx, t_name in enumerate(allowed_tools, start=1):
        if t_name in TOOL_META:
            meta = TOOL_META[t_name]
            tools_lines.append(f"{idx}. {t_name}")
            tools_lines.append(f"   - Purpose: {meta['purpose']}")
            tools_lines.append(f"   - Parameters: {meta['params']}")

    # 5. 组装并返回整体的 System Prompt
    return "\n\n".join([
        BASE_PROMPT,
        "\n".join(info_base_lines),
        "\n".join(plan_lines),
        "\n".join(tools_lines),
        WORKFLOW_GUIDE
    ])