"""
prompts/builder.py
─────────────────────────────────────────────
Dynamic system prompt builder.

build_system_prompt(state) is called before every LLM invocation.
The resulting prompt contains:
  1. Agent role description + tool-call format specification
  2. Current task plan (visual step status)
  3. Live core content for the current step
  4. Available tools (global + step-specific)
  5. Workflow guide
"""

from state.models import (
    AgentState,
    STEP_REQUIREMENT, STEP_STRUCTURE, STEP_QUESTION, STEP_OUTPUT,
    STEP_ORDER, STEP_GOALS,
    PENDING, IN_PROGRESS, COMPLETED,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tool metadata definitions
# ─────────────────────────────────────────────────────────────────────────────

GLOBAL_TOOL_META = {
    "ask_user": {
        "purpose": (
            "Send a question or message to the user and pause the agent loop. "
            "Use whenever you need more information, user confirmation, or want to show a draft and get feedback."
        ),
        "params": '{"question": "your question or message to the user"}',
    },
    "confirm_step": {
        "purpose": (
            "Mark the current step as DONE and advance to the next step. "
            "Only call this after you and the user have reviewed the current step's content and agreed it is complete and correct."
        ),
        "params": '{"summary": "one-sentence summary of what was finalized in this step"}',
    },
    "goto_step": {
        "purpose": (
            "Navigate to any step by name — including going backward to revise earlier work. "
            "The existing content of the target step is preserved so you can make targeted edits."
        ),
        "params": (
            '{"step": "requirement_analysis | structure_planning | question_generation | output", '
            '"reason": "why you need to go there"}'
        ),
    },
}

STEP_TOOL_META = {
    STEP_REQUIREMENT: {
        "parse_requirements": {
            "purpose": (
                "Parse the user's natural-language input and MERGE extracted fields into the current requirements. "
                "Existing non-null fields are never overwritten unless the user explicitly changes them. "
                "Use this first whenever the user provides new requirement information."
            ),
            "params": '{"user_input": "the user\'s latest message"}',
        },
        "set_requirement_field": {
            "purpose": "Directly set one specific requirement field to a given value (for precise single-field corrections).",
            "params": (
                '{"field": "survey_topic | survey_object | survey_goal | '
                'questionnaire_size | need_background_info | prohibited_content | other", '
                '"value": "new value"}'
            ),
        },
        "get_requirements": {
            "purpose": "Read and display the current requirements state.",
            "params": "{}",
        },
    },
    STEP_STRUCTURE: {
        "generate_structure": {
            "purpose": (
                "Use the LLM to generate an initial survey structure draft "
                "(sections, style, introduction, question counts) from the confirmed requirements. "
                "Run this first to create a starting point, then refine with the user."
            ),
            "params": "{}",
        },
        "add_section": {
            "purpose": "Add a new section to the survey structure.",
            "params": (
                '{"section_id": "unique_snake_case_id", "theme": "section topic", '
                '"description": "design rationale", '
                '"question_count": 3, "question_types": ["single_choice", "text"]}'
            ),
        },
        "update_section": {
            "purpose": "Modify one field of an existing section (theme, description, question_count, or question_types).",
            "params": (
                '{"section_id": "target_section_id", '
                '"field": "theme | description | question_count | question_types", '
                '"value": "new value"}'
            ),
        },
        "delete_section": {
            "purpose": "Remove a section from the structure.",
            "params": '{"section_id": "target_section_id"}',
        },
        "set_style": {
            "purpose": "Set the language style / tone for the entire survey.",
            "params": '{"style": "e.g., formal academic, friendly casual"}',
        },
        "set_introduction": {
            "purpose": "Set or update the survey's opening introduction and instructions for respondents.",
            "params": '{"introduction": "welcome message text"}',
        },
        "get_structure": {
            "purpose": "Read and display the current structure state.",
            "params": "{}",
        },
    },
    STEP_QUESTION: {
        "generate_all_questions": {
            "purpose": (
                "Use the LLM to generate ALL questions for the entire survey at once, "
                "strictly following the confirmed structure and question distribution. "
                "Run this first to create a complete draft, then refine question by question."
            ),
            "params": "{}",
        },
        "generate_section_questions": {
            "purpose": (
                "Regenerate ALL questions for one specific section "
                "(replaces existing questions in that section). "
                "Use when one section's questions need a complete redo."
            ),
            "params": '{"section_id": "target_section_id", "count": 3}',
        },
        "add_question": {
            "purpose": "Manually add one new question to a section.",
            "params": (
                '{"section_id": "target_section_id", '
                '"question_type": "single_choice | multiple_choice | text", '
                '"question": "question text", '
                '"options": ["Option A", "Option B"]}'
            ),
        },
        "update_question": {
            "purpose": "Modify one field of an existing question (type, question text, options, or section_id).",
            "params": (
                '{"question_id": 1, '
                '"field": "type | question | options | section_id", '
                '"value": "new value (use a list for options)"}'
            ),
        },
        "delete_question": {
            "purpose": "Remove a question by its numeric ID.",
            "params": '{"question_id": 1}',
        },
        "set_survey_meta": {
            "purpose": "Set or update the survey title and/or description.",
            "params": '{"survey_title": "...", "survey_description": "..."}',
        },
        "get_questions": {
            "purpose": "Read and display all current questions grouped by section.",
            "params": "{}",
        },
        "validate_questions": {
            "purpose": (
                "Run a comprehensive LLM-based quality check on all questions "
                "(bias, prohibited content, MECE options, section alignment, duplicates, tone)."
            ),
            "params": "{}",
        },
    },
    STEP_OUTPUT: {
        "execute_output": {
            "purpose": (
                "Create the final survey output: "
                "save the question JSON locally and/or publish to Google Forms."
            ),
            "params": "{}",
        },
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Fixed prompt sections
# ─────────────────────────────────────────────────────────────────────────────

BASE_PROMPT = """\
You are QA Agent, a professional interactive survey creation assistant.
You help users design high-quality surveys through a structured, step-by-step conversation.

[Core interaction model]
- Each step has a CORE CONTENT object (requirements / structure / questions / output).
- Your tools let you CREATE, READ, UPDATE, or DELETE items in that core content.
- You interact with the user FREELY within each step: ask questions, show drafts, discuss changes.
- Only call confirm_step when BOTH you and the user agree the current step is complete.
- You can call goto_step at any time to revisit earlier steps.

[Tool call format]
When calling a tool, output EXACTLY ONE ```json``` block — nothing else:
```json
{
    "name": "tool_name",
    "params": {
        "param_name": "param_value"
    }
}
```
To reply to the user without calling a tool, write plain text WITHOUT a ```json``` block.\
"""

WORKFLOW_GUIDE = """\
[Workflow guide]
1. Start each user turn by reviewing [Current Step Content] to understand the current state.
2. Use step-specific tools to build / modify the core content.
3. Use ask_user to show drafts to the user, request feedback, or ask clarifying questions.
   -> The loop pauses and the user's next reply resumes the SAME step with the SAME state.
4. Iterate with the user until the step's content is fully agreed upon.
5. Call confirm_step only after explicit user approval — this advances to the next step.
6. If user feedback requires revising an earlier step, call goto_step to go back.\
"""

# ─────────────────────────────────────────────────────────────────────────────
# State rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

_STATUS_ICON = {PENDING: "o", IN_PROGRESS: "->", COMPLETED: "v"}


def _render_plan(state: AgentState) -> str:
    lines = ["[Task Plan]"]
    for step in STEP_ORDER:
        raw_status = state.step_statuses.get(step, PENDING)
        icon = ">" if step == state.current_step else _STATUS_ICON.get(raw_status, "o")
        goal = STEP_GOALS.get(step, "")
        lines.append(f"  {icon} [{step}]  ({raw_status})")
        if step == state.current_step:
            lines.append(f"      Goal: {goal}")
    return "\n".join(lines)


def _render_current_state(state: AgentState) -> str:
    step = state.current_step
    lines = [f"[Current Step Content — {step}]"]

    if step == STEP_REQUIREMENT:
        req = state.requirements
        lines.append(req.model_dump_json(indent=2))
        missing = req.missing_fields()
        if missing:
            lines.append(f"Required fields still missing: {missing}")
        else:
            lines.append("All required fields are filled.")

    elif step == STEP_STRUCTURE:
        s = state.structure
        lines.append(f"Style:        {s.style or '(not set)'}")
        lines.append(f"Introduction: {s.introduction or '(not set)'}")
        lines.append(f"Sections ({len(s.sections)}, planned total questions: {s.total_questions()}):")
        for sec in s.sections:
            lines.append(
                f"  [{sec.section_id}]  theme={sec.theme!r}  "
                f"count={sec.question_count}  types={sec.question_types}"
            )
            if sec.description:
                lines.append(f"    -> {sec.description}")

    elif step == STEP_QUESTION:
        qs = state.questions
        lines.append(f"Title:       {qs.survey_title or '(not set)'}")
        lines.append(f"Description: {qs.survey_description or '(not set)'}")
        lines.append(f"Questions ({len(qs.questions)} total):")
        section_map: dict[str, list] = {}
        for q in qs.questions:
            section_map.setdefault(q.section_id, []).append(q)
        for sid, qlist in section_map.items():
            lines.append(f"  [{sid}]")
            for q in qlist:
                opts = f"  options={q.options}" if q.options else ""
                lines.append(f"    Q{q.id} ({q.type}): {q.question}{opts}")

    elif step == STEP_OUTPUT:
        out = state.output
        lines.append(f"Status:    {out.status or '(not started)'}")
        lines.append(f"Form URL:  {out.form_url or '(none)'}")
        lines.append(f"Local path:{out.local_path or '(none)'}")

    return "\n".join(lines)


def _render_tools(state: AgentState) -> str:
    step  = state.current_step
    lines = ["[Available Tools]", "", "# Global tools (always available)"]

    for idx, (name, meta) in enumerate(GLOBAL_TOOL_META.items(), 1):
        lines.append(f"{idx}. {name}")
        lines.append(f"   Purpose: {meta['purpose']}")
        lines.append(f"   Params:  {meta['params']}")

    step_tools = STEP_TOOL_META.get(step, {})
    if step_tools:
        lines.append(f"\n# Step-specific tools for [{step}]")
        offset = len(GLOBAL_TOOL_META) + 1
        for idx, (name, meta) in enumerate(step_tools.items(), offset):
            lines.append(f"{idx}. {name}")
            lines.append(f"   Purpose: {meta['purpose']}")
            lines.append(f"   Params:  {meta['params']}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(state: AgentState) -> str:
    return "\n\n".join([
        BASE_PROMPT,
        _render_plan(state),
        _render_current_state(state),
        _render_tools(state),
        WORKFLOW_GUIDE,
    ])
