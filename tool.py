# tool.py
import json
import re
from llm import LocalQwenLLM
from state import Step, Plan
from pathlib import Path
from context_store import ConversationContext

def planer() -> Plan:
    # 按照按块生成+局部重绘的架构，重新分配工具权限
    step1 = Step(
        title="Requirement Analysis",
        description="Analyze the user's request and extract key structured information.",
        status="pending",
        tools=["requirement_parser", "requirement_check"]
    )
    step2 = Step(
        title="Survey Structure Planning",
        description="Plan the survey's macro structure, overall tone, and content sections.",
        status="pending",
        tools=["macro_structure_planner", "question_distribution_planner"]
    )
    step3 = Step(
        title="Section Generation",
        description="Generate survey questions section by section and fix them if checker finds issues.",
        status="pending",
        tools=["generate_section_questions", "section_checker", "update_specific_question"]
    )
    step4 = Step(
        title="Global Validation",
        description="Check the full draft for overall consistency, logic, and size.",
        status="pending",
        tools=["overall_question_checker", "update_specific_question"]
    )
    step5 = Step(
        title="Survey Output",
        description="CRITICAL: You MUST call the `mcp_survey_executor` tool to save the final survey to a local file before finishing this step.",
        status="pending",
        tools=["mcp_survey_executor"]
    )
    
    plan = Plan(
        goal="Create a complete survey based on the user's requirements.",
        thought="Understand the user's topic, audience, purpose, and other key constraints before building the survey.",
        steps=[step1, step2, step3, step4, step5],
    )
    
    # 动态初始化黑板（ProjectDraft）的一级 Key
    plan.draft.data = {
        "requirement_info": {},
        "survey_outline": {},
        "distribution_map": {},
        "question_list": []
    }
    
    return plan


def generate_question(llm: LocalQwenLLM, err_message: str) -> str:
    """Generate a natural follow-up question for the user."""
    prompt = """
    You are an intelligent clarification assistant for survey creation.
    The current survey requirement parsing step found missing or unclear information.
    Based on the provided `err_message`, generate one concise and polite follow-up question for the user.

    Requirements:
    1. The tone must be natural and polite.
    2. The question must be concise and target the missing information directly.
    3. Output the question only, with no extra explanation.

    Error message: {err_message}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(err_message=err_message)}]).strip()


def requirements_parser_check(llm: LocalQwenLLM, current_requirements: str) -> str:
    """Check whether the parsed requirements are complete and accurate."""
    prompt = """
        You are a VERY STRICT quality inspector for survey-creation requirements.
        Validate whether all required fields are present in the current extracted data.

        Required fields: survey_topic, survey_object, survey_goal.

        CRITICAL EVALUATION RULES:
        1. If ANY of the required fields are `null`, empty strings `""`, or completely missing, you MUST set `next_steps` to "Supplementary information".
        2. You can ONLY set `next_steps` to "Consistent and comprehensive" if ALL THREE required fields have clear and non-null values.

        Output JSON in the following format:
        {{
            "next_steps": "Consistent and comprehensive" | "Supplementary information",
            "error_type": "short error category, or null if no error",
            "error_field": "field name containing the issue, or null if no error",
            "error_description": "detailed explanation of what is missing, or null if no error"
        }}

        Current extracted data:
        {current_requirements}

        Output JSON only.
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(current_requirements=current_requirements)}]).strip()


def requirements_parser(llm: LocalQwenLLM, plan: Plan, user_input: str, current_requirements: str) -> str:
    """Extract structured requirements from natural language and merge."""
    prompt = """
        You are a survey requirement parser.
        Extract structured survey requirement fields from the user's latest input, and MERGE them with the Current Requirements.

        Target JSON format:
        {{
            "survey_topic": "string | null",
            "survey_object": "string | null",
            "survey_goal": "string | null",
            "questionnaire_size": "number of questions |null",
            "need_background_info": "boolean | null",
            "prohibited_content": "string | null",
            "other": "string | null"
        }}

        Extraction rules:
        1. Return valid JSON only.
        2. If a field in the Current Requirements has a valid value, KEEP IT, unless the new User Input explicitly modifies it.
        3. Fill in `null` fields if the new User Input provides the missing information.
        4. Never invent or guess information.

        Current Requirements:
        {current_requirements}

        User input:
        {user_input}
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(current_requirements=current_requirements, user_input=user_input)}]).strip()
    
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        parsed = json.loads(match.group(0) if match else response)
        plan.draft.data["requirement_info"] = parsed
        return "Success: Requirements updated in draft.data['requirement_info']."
    except Exception as e:
        return f"Error parsing JSON: {e}"


def macro_structure_planner(llm: LocalQwenLLM, plan: Plan, requirements: str) -> str:
    """Plan the high-level survey structure."""
    prompt = """
        You are a professional survey structure planner. Based on the following user requirements, design the survey's macro outline and overall style.

        Requirement data:
        {requirements}

        Output JSON with the following fields:
        {{
            "style": "language style adapted to the target respondents",
            "introduction": "design idea and welcome message for the survey opening",
            "sections": [
                {{
                    "section_id": "background",
                    "theme": "respondent background information if applicable",
                    "description": "design idea for this section"
                }},
                {{
                    "section_id": "core_evaluation_1",
                    "theme": "first core evaluation subtopic",
                    "description": "design idea for this section"
                }},
                {{
                    "section_id": "core_evaluation_2",
                    "theme": "second core evaluation subtopic",
                    "description": "design idea for this section"
                }},
                ………………………………{{section_info}}………………………………
                {{
                    "section_id": "open_feedback",
                    "theme": "open-ended suggestions and feedback",
                    "description": "design idea for this section"
                }}
            ]
        }}
        Output JSON only.
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(requirements=requirements)}]).strip()
    
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        parsed = json.loads(match.group(0) if match else response)
        plan.draft.data["survey_outline"] = parsed
        return "Success: Macro structure planned and saved to draft.data['survey_outline']."
    except Exception as e:
        return f"Error parsing JSON: {e}"


def question_distribution_planner(llm: LocalQwenLLM, plan: Plan, requirements: str, macro_structure: str) -> str:
    """Allocate question counts and types across sections."""
    prompt = """
        You are an expert in survey question allocation. Based on the user's requirements and the planned outline, allocate the number of questions and question types for each section.

        Requirement data: {requirements}
        Survey outline: {macro_structure}

        Rules:
        1. Use questionnaire_size to choose a concrete total question count.
        2. Distribute the total question count reasonably across all sections.
        3. Assign a question type for every question in every section. Allowed values: single_choice, multiple_choice, text.

        Output JSON in the following format:
        {{
            "total_questions": 10,
            "distribution": [
                {{
                    "section_id": "background",
                    "question_count": 2,
                    "question_types": ["single_choice", "single_choice"]
                }},
                {{
                    "section_id": "core_evaluation_1",
                    "question_count": 4,
                    "question_types": ["single_choice", "single_choice", "multiple_choice", "text"]
                }}
            ]
        }}
        Output JSON only.
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(requirements=requirements, macro_structure=macro_structure)}]).strip()
    
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        parsed = json.loads(match.group(0) if match else response)
        plan.draft.data["distribution_map"] = parsed
        return "Success: Question distribution planned and saved to draft.data['distribution_map']."
    except Exception as e:
        return f"Error parsing JSON: {e}"


def generate_section_questions(llm: LocalQwenLLM, plan: Plan, section_id: str, requirements: str, macro_structure: str, distribution: str) -> str:
    """Generate detailed survey questions for a single section."""
    prompt = """
        You are a survey question generation expert. Generate the survey questions ONLY for the section `{section_id}` according to the provided outline and distribution.

        Requirement data: {requirements}
        Survey outline: {macro_structure}
        Question distribution: {distribution}

        Output a JSON list in the following format:
        [
            {{
                "id": 1,
                "section_id": "{section_id}",
                "type": "single_choice | multiple_choice | text",
                "question": "question text",
                "options": ["Option A", "Option B"]
            }}
        ]

        Constraints:
        1. The quantity and type must match the distribution exactly for `{section_id}`.
        2. Options must be mutually exclusive and reasonable. If type is text, options must be [].
        3. Output JSON only.
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(
        section_id=section_id, requirements=requirements, macro_structure=macro_structure, distribution=distribution)}]).strip()
    
    try:
        match = re.search(r"\[.*\]", response, re.DOTALL)
        new_questions = json.loads(match.group(0) if match else response)

        if "question_list" not in plan.draft.data:
            plan.draft.data["question_list"] = []

        max_id = max([q.get("id", 0) for q in plan.draft.data["question_list"]]) if plan.draft.data["question_list"] else 0
        for i, q in enumerate(new_questions, 1):
            q["id"] = max_id + i

        plan.draft.data["question_list"].extend(new_questions)
        return f"Success: Generated {len(new_questions)} questions for section '{section_id}' and added to draft."
    except Exception as e:
        return f"Error parsing JSON: {e}"


def section_checker(llm: LocalQwenLLM, section_id: str, section_questions: str, prohibited_content: str) -> str:
    """Check questions within a specific section."""
    prompt = """
        You are a strict survey quality inspector. Check the following questions for section `{section_id}`.

        Questions to inspect:
        {section_questions}

        Prohibited content: {prohibited_content}

        Evaluate:
        1. Leading wording or bias.
        2. Prohibited content.
        3. Option reasonableness (MECE).

        Output JSON in the following format:
        {{
            "is_valid": true | false,
            "issues": [
                {{"question_id": 1, "issue": "specific problem", "suggestion": "specific revision idea"}}
            ],
            "section_issue": "overall section feedback or null"
        }}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(
        section_id=section_id, section_questions=section_questions, prohibited_content=prohibited_content)}]).strip()


def update_specific_question(plan: Plan, question_id: int, new_question_json: str) -> str:
    """Modify a specific question in the draft."""
    try:
        new_data = json.loads(new_question_json)
        new_data["id"] = int(question_id)
        
        found = False
        for i, q in enumerate(plan.draft.data.get("question_list", [])):
            if q.get("id") == int(question_id):
                plan.draft.data["question_list"][i] = new_data
                found = True
                break
                
        if found:
            return f"Success: Question {question_id} has been updated in the draft."
        else:
            return f"Error: Question ID {question_id} not found in current draft."
    except Exception as e:
        return f"Error parsing JSON: {e}"


def overall_question_checker(llm: LocalQwenLLM, all_questions_json: str, expected_size: str) -> str:
    """Check the full survey globally."""
    prompt = """
        You are an expert in full-survey review. Review the generated survey from a global perspective.

        Full survey question list:
        {all_questions_json}

        Expected size: {expected_size}

        Evaluate the following dimensions:
        1. Whether the total number of questions matches the expected size.
        2. Whether there are serious semantic duplicates.
        3. Whether the overall tone is consistent.

        Output JSON in the following format:
        {{
            "is_valid": true | false,
            "rule_issues": ["rule-based issues, or [] if none"],
            "llm_issues": ["semantic or tone issues, or [] if none"],
            "suggestion": "suggestions for revising or optimizing the survey"
        }}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(
        all_questions_json=all_questions_json, expected_size=expected_size)}]).strip()


def mcp_survey_executor(plan: Plan, output_file: str = "./survey_project_draft.json") -> str:
    """Save the final global draft to a local JSON file (No params required from LLM)."""
    output_path = Path(output_file)
    if not plan.draft.data:
         return json.dumps({"status": "error", "message": "Global draft is empty."}, ensure_ascii=False)
         
    with output_path.open("w", encoding="utf-8") as f:
        # dict() 适配 Pydantic, 也可以用 model_dump()
        json.dump(plan.draft.dict() if hasattr(plan.draft, 'dict') else plan.draft.model_dump(), f, ensure_ascii=False, indent=2)

    return json.dumps({
        "status": "success",
        "message": f"Global project draft has been successfully saved to {output_path}.",
        "total_questions": len(plan.draft.data.get("question_list", []))
    }, ensure_ascii=False)


def finish_step(plan: Plan, context: ConversationContext, step_title: str, result_summary: str) -> str:
    """Mark a plan step as completed and trim redundant context."""
    for step in plan.steps:
        if step.title == step_title:
            if step.status == "completed":
                return f"Notice: step '{step_title}' is already completed."

            step.status = "completed"
            step.result = result_summary

            context.clear()
            context.add_user_message(
                f"[System notice] Step '{step_title}' is completed. Core output has been stored in the task plan. Continue with the next pending step."
            )
            return f"Success: step '{step_title}' has been marked as completed."

    return f"Error: no step named '{step_title}' was found in the plan."