import json
from llm import LocalQwenLLM
from state import Step, Plan
from pathlib import Path
from context_store import ConversationContext


def planer() -> Plan:
    step1 = Step(
        title="Requirement Analysis",
        description="Analyze the user's request and extract key structured information.",
        status="pending",
    )
    step2 = Step(
        title="Survey Structure Planning",
        description="Plan the survey's macro structure, overall tone, and content sections.",
        status="pending",
    )
    step3 = Step(
        title="Question Generation",
        description="Generate detailed survey questions based on the approved structure.",
        status="pending",
    )
    step4 = Step(
        title="Question Validation",
        description="Check the generated questions for quality, compliance, and fit with the user requirements.",
        status="pending",
    )
    step5 = Step(
        title="Survey Output",
        description="Produce the final survey result based on the confirmed questions.",
        status="pending",
    )
    return Plan(
        goal="Create a complete survey based on the user's requirements.",
        thought="Understand the user's topic, audience, purpose, and other key constraints before building the survey.",
        steps=[step1, step2, step3, step5],
    )


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


def requirements_parser(llm: LocalQwenLLM, user_input: str, previous_data: str = "{}") -> str:
    """Extract or update structured requirements from natural language."""
    prompt = """
        You are a survey requirement parser.
        Your task is to extract survey requirements from the new user input and MERGE them into the existing data.

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

        Previous extracted data:
        {previous_data}

        New user input:
        {user_input}

        Extraction rules:
        1. Return valid JSON only.
        2. MERGE the new information from 'New user input' into 'Previous extracted data'.
        3. CRITICAL: Do NOT overwrite existing valid fields with null! If a field has a value in 'Previous extracted data' and the user doesn't mention it in 'New user input', KEEP the old value.
        4. Any field not mentioned currently or previously must stay null.
        5. Keep values concise and precise.
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(user_input=user_input, previous_data=previous_data)}]).strip()

def requirements_parser_check(llm: LocalQwenLLM, parse_data: str) -> str:
    """Check whether the parsed requirements are complete."""
    prompt = """
        You are a quality inspector for survey-creation requirements.
        Validate whether the extracted requirement data `parse_data` contains all the mandatory fields.

        Required fields: survey_topic, survey_object, survey_goal.

        Output JSON in the following format:
        {{
            "next_steps": "Consistent and comprehensive" | "Supplementary information",
            "error_type": "short error category, or null if no error",
            "error_field": "field name containing the issue, or null if no error",
            "error_description": "detailed explanation of what is missing, or null if no error"
        }}

        Rules for next_steps:
        1. Consistent and comprehensive: all required fields (survey_topic, survey_object, survey_goal) are present and have valid string values (not null).
        2. Supplementary information: one or more required fields are null or missing.

        Current extracted data:
        {parse_data}

        Output JSON only.
    """.strip()
    return llm.chat([
        {"role": "user", "content": prompt.format(parse_data=str(parse_data))}
    ]).strip()


def macro_structure_planner(llm: LocalQwenLLM, requirements: str) -> str:
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
                {{
                    "section_id": "open_feedback",
                    "theme": "open-ended suggestions and feedback",
                    "description": "design idea for this section"
                }}
            ]
        }}
        Output JSON only.
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(requirements=requirements)}]).strip()


def detailed_question_generator(llm: LocalQwenLLM, requirements: str, macro_structure: str, distribution: str) -> str:
    """Generate detailed survey questions."""
    prompt = """
        You are a survey question generation expert who follows instructions strictly. Generate the survey questions according to the provided outline and question distribution.

        Requirement data: {requirements}
        Survey outline: {macro_structure}
        Question distribution: {distribution}

        Output a JSON list in the following format:
        [
            {{
                "id": 1,
                "section_id": "section_id from the distribution",
                "type": "single_choice | multiple_choice | text",
                "question": "question text",
                "options": ["Option A", "Option B"]
            }}
        ]

        Constraints:
        1. The quantity and type must match the distribution exactly.
        2. Options must be mutually exclusive and reasonable.
        3. If type is text, options must be [].
        4. Output JSON only.
    """.strip()
    return llm.chat([
        {"role": "user", "content": prompt.format(requirements=requirements, macro_structure=macro_structure, distribution=distribution)}
    ]).strip()


def single_question_checker(llm: LocalQwenLLM, question_json: str, prohibited_content: str, section_topic: str) -> str:
    """Check a single survey question."""
    prompt = """
        You are a strict survey quality inspector. Check the following question for compliance and reasonableness.

        Question to inspect:
        {question_json}

        Prohibited content: {prohibited_content}
        Section topic: {section_topic}

        Evaluate the following dimensions:
        1. Leading wording.
        2. Prohibited content.
        3. Option reasonableness and MECE quality.
        4. Match with the section topic.

        Output JSON in the following format:
        {{
            "is_valid": true | false,
            "issues": ["list specific issues here, or [] if valid"],
            "suggestion": "specific revision suggestion, or an empty string if no revision is needed"
        }}
    """.strip()
    return llm.chat([
        {
            "role": "user",
            "content": prompt.format(
                question_json=question_json,
                prohibited_content=prohibited_content,
                section_topic=section_topic,
            ),
        }
    ]).strip()


def overall_question_checker(llm: LocalQwenLLM, all_questions_json: str, expected_size: str) -> str:
    """Check the full survey globally."""
    prompt = """
        You are an expert in full-survey review. Review the generated survey from a global perspective.

        Full survey question list:
        {all_questions_json}

        Expected size: {expected_size}
        Reference ranges: small = 5-10, medium = 11-15, large = 16-20.

        Evaluate the following dimensions:
        1. Whether the total number of questions matches the expected size.
        2. Whether every planned section has corresponding questions.
        3. Whether there are serious semantic duplicates.
        4. Whether the overall tone is consistent.

        Output JSON in the following format:
        {{
            "is_valid": true | false,
            "rule_issues": ["rule-based issues, or [] if none"],
            "llm_issues": ["semantic or tone issues, or [] if none"],
            "suggestion": "suggestions for revising or optimizing the survey"
        }}
    """.strip()
    return llm.chat([
        {"role": "user", "content": prompt.format(all_questions_json=all_questions_json, expected_size=expected_size)}
    ]).strip()

"""
def mcp_survey_executor(
    questions_data: str,
    output_file: str = "./survey_questions.json"
) -> str:
    """#Save generated survey questions JSON string to a local JSON file.
"""
    output_path = Path(output_file)

    try:
        parsed_questions = json.loads(questions_data)
    except json.JSONDecodeError as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"questions_data is not valid JSON: {e}",
                "output_file": str(output_path),
            },
            ensure_ascii=False,
        )

    if not isinstance(parsed_questions, list):
        return json.dumps(
            {
                "status": "error",
                "message": "questions_data must be a JSON list.",
                "output_file": str(output_path),
            },
            ensure_ascii=False,
        )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(parsed_questions, f, ensure_ascii=False, indent=2)

    return json.dumps(
        {
            "status": "success",
            "message": f"Survey questions have been saved to {output_path}.",
            "output_file": str(output_path),
            "question_count": len(parsed_questions),
        },
        ensure_ascii=False,
    )
"""

def finish_step(plan: Plan, context: ConversationContext, step_title: str, result_summary: str) -> str:
    """Mark a plan step as completed and trim redundant context."""
    
    # 1. 规范化输入：转小写，并将下划线替换为空格
    # 例如将 "requirement_analysis" 转换为 "requirement analysis"
    normalized_input = step_title.lower().replace("_", " ")

    for step in plan.steps:
        # 2. 规范化目标标题
        normalized_target = step.title.lower().replace("_", " ")
        
        if normalized_target == normalized_input:
            if step.status == "completed":
                return f"Notice: step '{step.title}' is already completed."
            
            step.status = "completed"
            step.result = result_summary
            context.clear()
            
            # 这里的提示语明确告诉 LLM 进入下一个 pending step
            context.add_user_message(
                f"[System notice] Step '{step.title}' is completed. Core output has been stored in the task plan. Continue with the tools for the next pending step."
            )
            return f"Success: step '{step.title}' has been marked as completed."
            
    # 3. 容错提示：如果找不到，把合法的 step_title 列表抛给 LLM 帮助其纠正
    valid_titles = [s.title for s in plan.steps]
    return f"Error: no step named '{step_title}' was found in the plan. Available valid step titles are: {valid_titles}"

################################################################################
###############    connect to  Google Forms API    #############################
################################################################################
import json
import os
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def mcp_survey_executor(
    questions_data: str,
) -> str:
    """Save generated survey questions JSON string to a local JSON file and publish as a Google Form."""
    configs = json.load(open('./configs.json', 'r'))
    output_file = configs.get("survey_questions_output_file", "./survey_questions.json")
    output_path = Path(output_file)

    # 1. 验证并解析 JSON 数据 (完全保持原样)
    try:
        formatted_data = json.loads(json.dumps(questions_data))
    except json.JSONDecodeError as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"questions_data is not valid JSON: {e}",
                "output_file": str(output_path),
            },
            ensure_ascii=False,
        )

    if not isinstance(parsed_questions, list):
        return json.dumps(
            {
                "status": "error",
                "message": "questions_data must be a JSON list.",
                "output_file": str(output_path),
            },
            ensure_ascii=False,
        )

    # 2. 保存本地 JSON 文件 (完全保持原样)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(parsed_questions, f, ensure_ascii=False, indent=2)

    # 3. Google Forms API 创建表单逻辑
    form_publish_url = ""
    try:
        credentials_path = configs.get("GOOGLE_APPLICATION_CREDENTIALS", "./credentials.json")
        SCOPES = ["https://www.googleapis.com/auth/forms.body"]
        
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        form_service = build("forms", "v1", credentials=creds)

        # 创建初始表单
        initial_form = {
            "info": {
                "title": "食堂就餐体验调查问卷",
                "documentTitle": "Auto-generated Survey Form"
            }
        }
        created_form = form_service.forms().create(body=initial_form).execute()
        form_id = created_form.get("formId")
        form_publish_url = created_form.get("responderUri")

        # 构建批量写入请求
        requests = []
        for index, q_data in enumerate(parsed_questions):
            q_type = q_data.get("type")
            title = q_data.get("question")
            options = q_data.get("options", [])
            
            item = {"title": title}
            
            if q_type in ["single_choice", "multiple_choice"]:
                api_choice_type = "RADIO" if q_type == "single_choice" else "CHECKBOX"
                item["questionItem"] = {
                    "question": {
                        "required": True,
                        "choiceQuestion": {
                            "type": api_choice_type,
                            "options": [{"value": opt} for opt in options]
                        }
                    }
                }
            elif q_type == "text":
                item["questionItem"] = {
                    "question": {
                        "required": False,
                        "textQuestion": {
                            "paragraph": True
                        }
                    }
                }
                
            requests.append({
                "createItem": {
                    "item": item,
                    "location": {"index": index}
                }
            })

        # 写入题目
        if requests:
            form_service.forms().batchUpdate(
                formId=form_id,
                body={"requests": requests}
            ).execute()
            
        final_message = f"Survey questions have been saved to {output_path}. Google Form created: {form_publish_url}"

    except Exception as e:
        # 兼容处理：如果 API 失败，依然返回成功保存本地文件的信息，并在 message 中报告 API 错误
        final_message = f"Survey questions have been saved to {output_path}, but Google Form creation failed: {e}"

    # 4. 返回结果 (严格参照原版输出格式)
    return json.dumps(
        {
            "status": "success",
            "message": final_message,
            "output_file": str(output_path),
            "question_count": len(parsed_questions),
        },
        ensure_ascii=False,
    )