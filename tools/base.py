"""
tools/base.py
─────────────────────────────────────────────
所有工具的返回类型。Agent 主循环根据 ResultType 决定下一步行为。
"""

from dataclasses import dataclass
from typing import Optional


class ResultType:
    OBSERVATION = "observation"  # 普通结果，继续 agent 循环
    ASK_USER    = "ask_user"     # 把内容返回给用户，暂停等待回复
    STEP_DONE   = "step_done"    # 当前步骤完成，可能进入下一步
    GOTO_STEP   = "goto_step"    # 已跳转到另一步骤
    TASK_DONE   = "task_done"    # 整个任务完成，退出循环


@dataclass
class ToolResult:
    type:        str            # ResultType 中的常量
    content:     str            # 给 LLM 看的观察内容
    target_step: Optional[str] = None  # GOTO_STEP / STEP_DONE 时的目标步骤
