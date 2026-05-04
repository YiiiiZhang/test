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


def requirements_parser_check(llm: LocalQwenLLM, user_input: str, parse_data) -> str:
    """Check whether the parsed requirements are complete and accurate."""
    prompt = """
        You are a quality inspector for survey-creation requirements.
        Validate whether the extracted requirement data `parse_data` matches the user's latest input `user_input`, and check whether all required fields are present.

        Required fields: survey_topic, survey_object, survey_goal.

        Output JSON in the following format:
        {{
            "next_steps": "Consistent and comprehensive" | "Supplementary information" | "Re-extraction",
            "error_type": "short error category, or null if no error",
            "error_field": "field name containing the issue, or null if no error",
            "error_description": "detailed explanation of what is missing or incorrect, or null if no error"
        }}

        Rules for next_steps:
        1. Consistent and comprehensive: all required fields are correctly covered and there is no error.
        2. Supplementary information: one or more required fields are missing.
        3. Re-extraction: the extracted data conflicts with the user input, or required information was provided but extracted incorrectly.

        Current extracted data:
        {parse_data}

        Original user input:
        {user_input}

        Output JSON only.
    """.strip()
    return llm.chat([
        {"role": "user", "content": prompt.format(user_input=user_input, parse_data=str(parse_data))}
    ]).strip()


def requirements_parser(llm: LocalQwenLLM, user_input: str) -> str:
    """Extract structured requirements from natural language."""
    prompt = """
        You are a survey requirement parser.
        Extract structured survey requirement fields from the user's input.

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
        2. Any field not mentioned by the user must stay null.
        3. Never invent or guess information.
        4. Keep values concise and precise.
        5. If the user is answering a follow-up question from the previous turn, extract the useful content without overwriting the broader intent with casual wording.
        User input:
        {user_input}
    """.strip()
    return llm.chat([{"role": "user", "content": prompt.format(user_input=user_input)}]).strip()


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


def question_distribution_planner(llm: LocalQwenLLM, requirements: str, macro_structure: str) -> str:
    """Allocate question counts and types across sections."""
    prompt = """
        You are an expert in survey question allocation. Based on the user's requirements and the planned outline, allocate the number of questions and question types for each section.

        Requirement data: {requirements}
        Survey outline: {macro_structure}

        Rules:
        1. Use questionnaire_size to choose a concrete total question count within the allowed range.
        2. Distribute the total question count reasonably across all sections.
        3. Assign a question type for every question in every section. Allowed values: single_choice, multiple_choice, text.
        4. Background sections are usually single_choice or text, core evaluation sections are usually single_choice or multiple_choice, and open feedback is usually text.

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
        All section_id values from the outline must appear, and the sum of question_count values must equal total_questions.
        Output JSON only.
    """.strip()
    return llm.chat([
        {"role": "user", "content": prompt.format(requirements=requirements, macro_structure=macro_structure)}
    ]).strip()


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


def mcp_survey_executor(
    questions_data: str,
    output_file: str = "./survey_questions.json"
) -> str:
    """Save generated survey questions JSON string to a local JSON file."""
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
