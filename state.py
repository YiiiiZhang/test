from typing import List, Literal, Dict, Any
from pydantic import BaseModel,Field

class Step(BaseModel):
    title: str = ""
    description: str = ""
    status: Literal["pending", "completed"] = "pending"
    result: str = ""
    tools: list[str] =Field(default_factory=list)


class Plan(BaseModel):
    goal: str = ""
    thought: str = ""
    steps: List[Step] = Field(default_factory=list)
    survey_draft: List[Dict[str, Any]] = Field(default_factory=list)

class ProjectDraft(BaseModel):
    """
    Unified dynamic notepad.
    """
    data: Dict[str, Any] = Field(default_factory=dict)
    
    
