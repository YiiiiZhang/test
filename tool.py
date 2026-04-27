import json
import re
from pathlib import Path
from llm import LocalQwenLLM
from state import Step, Plan
from context_store import ConversationContext

# ----------------- 计划与黑板初始化 -----------------
def planer() -> Plan:
    step1 = Step(
        title="Requirement Analysis",
        description="Analyze the user's request and extract key structured information.",
        status="pending",
        tools=["requirement_parser", "requirement_check"]
    )
    step2 = Step(
        title="Structure Planning",
        description="Plan the survey's macro structure, overall tone, and content sections.",
        status="pending",
        tools=["macro_structure_planner", "question_distribution_planner"]
    )
    step3 = Step(
        title="Section Generation",
        description="Generate detailed survey questions section by section and fix them if checker finds issues.",
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
        description="Produce the final survey result based on the confirmed draft.",
        status="pending",
        tools=["mcp_survey_executor"]
    )
    
    plan = Plan(
        goal="Create a complete survey based on the user's requirements.",
        thought="Understand the user's topic, audience, purpose, and constraints before building the survey.",
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

# ----------------- 全局与通用工具 -----------------
def generate_question(llm: LocalQwenLLM, err_message: str) -> str:
    """Generate a natural follow-up question for the user based on missing info."""
    prompt = """
        You are an intelligent clarification assistant for survey creation.
        Based on the provided `err_message`, generate one concise and polite follow-up question for the user.
        Output the question only, with no extra explanation.

        Error message: {err_message}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(err_message=err_message)}]).strip()

def finish_step(plan: Plan, context: ConversationContext, step_title: str, result_summary: str) -> str:
    """Mark a plan step as completed."""
    for step in plan.steps:
        if step.title == step_title:
            if step.status == "completed":
                return f"Notice: step '{step_title}' is already completed."
            step.status = "completed"
            step.result = result_summary
            context.clear()
            context.add_user_message(f"[System notice] Step '{step_title}' is completed. Core output stored in plan. Proceed to the next pending step.")
            return f"Success: step '{step_title}' marked as completed."
    return f"Error: no step named '{step_title}' found."

# ----------------- 步骤特有工具 -----------------
def requirements_parser(llm: LocalQwenLLM, plan: Plan, user_input: str, current_requirements: str) -> str:
    """Merge user input with current requirements and write back to draft."""
    prompt = """
        You are a survey requirement parser.
        Merge the user's latest input with the current requirements.

        Current Requirements:
        {current_requirements}

        User's Latest Input:
        {user_input}

        Target JSON format:
        {{
            "survey_topic": "string | null",
            "survey_object": "string | null",
            "survey_goal": "string | null",
            "questionnaire_size": "number of questions | null",
            "need_background_info": "boolean | null",
            "prohibited_content": "string | null",
            "other": "string | null"
        }}

        Extraction & Merge Rules:
        1. Return valid JSON only.
        2. If a field in the Current Requirements has a valid value, KEEP IT, unless the new User Input explicitly modifies it.
        3. Fill in `null` fields if the new User Input provides the missing information.
        4. Never invent or guess information.
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(current_requirements=current_requirements, user_input=user_input)}]).strip()
    
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        parsed = json.loads(match.group(0) if match else response)
        plan.draft.data["requirement_info"] = parsed
        return f"Success: Requirements updated in draft.data['requirement_info']."
    except Exception as e:
        return f"Error parsing JSON: {e}. Raw response: {response}"

def requirements_parser_check(llm: LocalQwenLLM, current_requirements: str) -> str:
    """Check if requirements are complete (Pure Function)."""
    prompt = """
        You are a quality inspector for survey requirements.
        Validate whether all required fields are present.
        Required fields: survey_topic, survey_object, survey_goal.

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

def macro_structure_planner(llm: LocalQwenLLM, plan: Plan, requirements: str) -> str:
    """Plan macro structure and write to draft."""
    prompt = """
        You are a professional survey structure planner. Design the macro outline based on requirements.

        Requirement data:
        {requirements}

        Output JSON with the following fields:
        {{
            "style": "language style",
            "introduction": "welcome message",
            "sections": [
                {{
                    "section_id": "background",
                    "theme": "theme description",
                    "description": "design idea"
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
    """Plan distribution and write to draft."""
    prompt = """
        Allocate question counts and types across sections.

        Requirement data: {requirements}
        Survey outline: {macro_structure}

        Output JSON format:
        {{
            "total_questions": 10,
            "distribution": [
                {{
                    "section_id": "background",
                    "question_count": 2,
                    "question_types": ["single_choice", "text"]
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
    """Generate questions for a single section and append to draft."""
    prompt = """
        Generate the survey questions ONLY for the section `{section_id}`.

        Requirement data: {requirements}
        Survey outline: {macro_structure}
        Question distribution: {distribution}

        Output a JSON list containing ONLY the questions for `{section_id}`.
        Format: [{{"id": 0, "section_id": "{section_id}", "type": "single_choice", "question": "...", "options": [...]}}]
        Output JSON only.
    """.strip()
    response = llm.chat([{"role": "user", "content": prompt.format(
        section_id=section_id, requirements=requirements, macro_structure=macro_structure, distribution=distribution)}]).strip()
    
    try:
        match = re.search(r"\[.*\]", response, re.DOTALL)
        new_questions = json.loads(match.group(0) if match else response)

        # 确保 question_list 存在
        if "question_list" not in plan.draft.data:
            plan.draft.data["question_list"] = []

        # 自动递增 ID 以避免重复
        max_id = max([q.get("id", 0) for q in plan.draft.data["question_list"]]) if plan.draft.data["question_list"] else 0
        for i, q in enumerate(new_questions, 1):
            q["id"] = max_id + i

        plan.draft.data["question_list"].extend(new_questions)
        return f"Success: Generated {len(new_questions)} questions for section '{section_id}' and added to draft."
    except Exception as e:
        return f"Error parsing JSON: {e}. Raw response: {response}"

def section_checker(llm: LocalQwenLLM, section_id: str, section_questions: str, prohibited_content: str) -> str:
    """Check a specific section (Pure Function)."""
    prompt = """
        Review the questions generated for section `{section_id}`.
        Questions: {section_questions}
        Prohibited content: {prohibited_content}

        Evaluate: 
        1. Leading wording/bias. 
        2. Prohibited content. 
        3. Option reasonableness (MECE).

        Output JSON in the following format:
        {{
            "is_valid": true | false,
            "issues": [
                {{"question_id": 123, "issue": "specific problem", "suggestion": "specific revision idea"}}
            ],
            "section_issue": "overall section feedback or null"
        }}
        Output JSON only.
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(
        section_id=section_id, section_questions=section_questions, prohibited_content=prohibited_content)}]).strip()

def update_specific_question(plan: Plan, question_id: int, new_question_json: str) -> str:
    """Local Inpainting: Modify a specific question in the draft."""
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
    """Check the full draft globally (Pure Function)."""
    prompt = """
        Review the completely generated survey from a global perspective.
        Full survey draft: {all_questions_json}
        Expected size: {expected_size}

        Evaluate:
        1. Does total count roughly match expected size?
        2. Are there serious semantic duplicates across sections?
        3. Is the overall tone consistent?

        Output JSON:
        {{
            "is_valid": true | false,
            "rule_issues": ["..."],
            "llm_issues": ["..."],
            "suggestion": "..."
        }}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(
        all_questions_json=all_questions_json, expected_size=expected_size)}]).strip()

def mcp_survey_executor(plan: Plan, output_file: str = "./survey_project_draft.json") -> str:
    """Save the final global draft to a local JSON file."""
    output_path = Path(output_file)
    if not plan.draft.data:
         return json.dumps({"status": "error", "message": "Global draft is empty."})
         
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(plan.draft.data, f, ensure_ascii=False, indent=2)

    return json.dumps({
        "status": "success",
        "message": f"Global project draft has been saved to {output_path}.",
        "output_file": str(output_path),
        "total_questions": len(plan.draft.data.get("question_list", []))
    }, ensure_ascii=False)