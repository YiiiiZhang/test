"""
tools/navigation.py
─────────────────────────────────────────────
Three global navigation tools available at every step:
  ask_user     — send a question to the user and pause the loop
  confirm_step — confirm the current step and advance to the next
  goto_step    — jump to any step (supports backward revision)
"""

from state.models import AgentState, STEP_ORDER
from tools.base import ToolResult, ResultType


def ask_user(question: str) -> ToolResult:
    """
    Send a question or message to the user and pause the agent loop.
    The next call to run() resumes at the same step with the same state.
    """
    return ToolResult(type=ResultType.ASK_USER, content=question)


def confirm_step(state: AgentState, summary: str) -> ToolResult:
    """
    Mark the current step as complete and advance to the next step.
    Only call this after you and the user have reviewed and agreed on
    the current step's content.
    """
    next_step = state.confirm_current_step()
    if next_step:
        msg = (
            f"Step confirmed. {summary}\n"
            f"Moving to next step: [{next_step}]"
        )
    else:
        msg = f"All steps completed. {summary}"
    return ToolResult(
        type=ResultType.STEP_DONE,
        content=msg,
        target_step=next_step,
    )


def goto_step(state: AgentState, step: str, reason: str) -> ToolResult:
    """
    Navigate to the specified step. Completed steps are re-opened
    automatically, allowing backward revision at any time.
    """
    if step not in STEP_ORDER:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Error: unknown step '{step}'. Valid steps: {STEP_ORDER}",
        )
    state.goto(step)
    return ToolResult(
        type=ResultType.GOTO_STEP,
        content=f"Navigated to [{step}]. Reason: {reason}",
        target_step=step,
    )
