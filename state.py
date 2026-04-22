from typing import List, Literal
from pydantic import BaseModel

class Step(BaseModel):
    title: str = ""
    description: str = ""
    status: Literal["pending", "completed"] = "pending"
    result: str = ""


class Plan(BaseModel):
    goal: str = ""
    thought: str = ""
    steps: List[Step] = []
    
