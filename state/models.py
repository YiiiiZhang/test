"""
state/models.py
───────────────────────────────────────────────
Each pipeline step maintains an independent core-content object (core state).
Agent tools only perform CRUD operations on these objects rather than
regenerating everything from scratch.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field

# ── Step name constants ────────────────────────────────────────────────────────

STEP_REQUIREMENT = "requirement_analysis"
STEP_STRUCTURE   = "structure_planning"
STEP_QUESTION    = "question_generation"
STEP_OUTPUT      = "output"

STEP_ORDER = [STEP_REQUIREMENT, STEP_STRUCTURE, STEP_QUESTION, STEP_OUTPUT]

STEP_GOALS = {
    STEP_REQUIREMENT: "Understand and confirm the user's survey requirements (topic, audience, goal, size, constraints).",
    STEP_STRUCTURE:   "Design the survey's sections, language style, and question distribution.",
    STEP_QUESTION:    "Generate, review, and refine the actual survey questions through discussion with the user.",
    STEP_OUTPUT:      "Produce the final survey (save locally and/or push to Google Forms).",
}

# ── Step status constants ──────────────────────────────────────────────────────

PENDING     = "pending"
IN_PROGRESS = "in_progress"
COMPLETED   = "completed"

# ── Step 1: requirement analysis core content ──────────────────────────────────

_REQUIREMENT_REQUIRED_FIELDS = ["survey_topic", "survey_object", "survey_goal"]


class RequirementState(BaseModel):
    survey_topic:         Optional[str]  = None
    survey_object:        Optional[str]  = None   # target respondents
    survey_goal:          Optional[str]  = None
    questionnaire_size:   Optional[str]  = None   # e.g. "10" or "small"
    need_background_info: Optional[bool] = None
    prohibited_content:   Optional[str]  = None
    other:                Optional[str]  = None

    def is_complete(self) -> bool:
        return all(getattr(self, f) for f in _REQUIREMENT_REQUIRED_FIELDS)

    def missing_fields(self) -> list[str]:
        return [f for f in _REQUIREMENT_REQUIRED_FIELDS if not getattr(self, f)]


# ── Step 2: survey structure core content ─────────────────────────────────────

class SectionItem(BaseModel):
    section_id:     str
    theme:          str
    description:    str  = ""
    question_count: int  = 0
    question_types: list[str] = Field(default_factory=list)  # e.g. ["single_choice", "text"]


class StructureState(BaseModel):
    style:        Optional[str] = None
    introduction: Optional[str] = None
    sections:     list[SectionItem] = Field(default_factory=list)

    def get_section(self, section_id: str) -> Optional[SectionItem]:
        for s in self.sections:
            if s.section_id == section_id:
                return s
        return None

    def section_ids(self) -> list[str]:
        return [s.section_id for s in self.sections]

    def total_questions(self) -> int:
        return sum(s.question_count for s in self.sections)


# ── Step 3: question generation core content ──────────────────────────────────

QuestionType = Literal["single_choice", "multiple_choice", "text"]


class QuestionItem(BaseModel):
    id:         int
    section_id: str
    type:       QuestionType
    question:   str
    options:    list[str] = Field(default_factory=list)


class QuestionsState(BaseModel):
    survey_title:       Optional[str] = None
    survey_description: Optional[str] = None
    questions:          list[QuestionItem] = Field(default_factory=list)

    def get_question(self, question_id: int) -> Optional[QuestionItem]:
        for q in self.questions:
            if q.id == question_id:
                return q
        return None

    def next_id(self) -> int:
        if not self.questions:
            return 1
        return max(q.id for q in self.questions) + 1

    def by_section(self, section_id: str) -> list[QuestionItem]:
        return [q for q in self.questions if q.section_id == section_id]


# ── Step 4: output core content ───────────────────────────────────────────────

class OutputState(BaseModel):
    form_url:   Optional[str] = None
    local_path: Optional[str] = None
    status:     Optional[str] = None


# ── Global agent state ────────────────────────────────────────────────────────

class AgentState(BaseModel):
    current_step:  str  = STEP_REQUIREMENT
    step_statuses: dict = Field(default_factory=lambda: {
        s: PENDING for s in STEP_ORDER
    })

    requirements: RequirementState = Field(default_factory=RequirementState)
    structure:    StructureState   = Field(default_factory=StructureState)
    questions:    QuestionsState   = Field(default_factory=QuestionsState)
    output:       OutputState      = Field(default_factory=OutputState)

    # ── Navigation ────────────────────────────────────────────────────────────

    def goto(self, step: str) -> None:
        """Jump to the specified step. Re-opens the step if it was already completed."""
        if self.step_statuses.get(step) == COMPLETED:
            self.step_statuses[step] = IN_PROGRESS  # Re-open a completed step
        self.current_step = step

    def confirm_current_step(self) -> Optional[str]:
        """Mark the current step as complete and advance to the next one.
        Returns the next step name, or None if all steps are done."""
        self.step_statuses[self.current_step] = COMPLETED
        idx = STEP_ORDER.index(self.current_step)
        if idx + 1 < len(STEP_ORDER):
            next_step = STEP_ORDER[idx + 1]
            self.current_step = next_step
            self.step_statuses[next_step] = IN_PROGRESS
            return next_step
        return None

    def is_all_done(self) -> bool:
        return all(v == COMPLETED for v in self.step_statuses.values())
