"""
tools/base.py
─────────────────────────────────────────────
Return types for all tools. The agent loop routes its next action
based on the ResultType value of each ToolResult.
"""

from dataclasses import dataclass
from typing import Optional


class ResultType:
    OBSERVATION = "observation"  # Normal result — continue the agent loop
    ASK_USER    = "ask_user"     # Return content to the user and pause
    STEP_DONE   = "step_done"    # Current step completed; may advance to next
    GOTO_STEP   = "goto_step"    # Jumped to a different step
    TASK_DONE   = "task_done"    # Entire pipeline complete — exit loop


@dataclass
class ToolResult:
    type:        str            # One of the ResultType constants
    content:     str            # Observation text fed back to the LLM
    target_step: Optional[str] = None  # Target step for GOTO_STEP / STEP_DONE
