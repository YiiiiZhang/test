"""
tools/navigation.py
─────────────────────────────────────────────
三个全局导航工具，在任意步骤均可调用：
  ask_user    — 向用户提问，暂停循环
  confirm_step — 确认当前步骤并前进
  goto_step   — 跳转到指定步骤（支持回退）
"""

from state.models import AgentState, STEP_ORDER
from tools.base import ToolResult, ResultType


def ask_user(question: str) -> ToolResult:
    """
    向用户发送一个问题并暂停 Agent 循环。
    下一轮 run() 调用时，Agent 将继续在当前步骤工作。
    """
    return ToolResult(type=ResultType.ASK_USER, content=question)


def confirm_step(state: AgentState, summary: str) -> ToolResult:
    """
    确认当前步骤的核心内容已完整正确，标记为完成并进入下一步。
    仅在与用户充分确认后调用。
    """
    next_step = state.confirm_current_step()
    if next_step:
        msg = (
            f"✓ Step confirmed. {summary}\n"
            f"→ Moving to next step: [{next_step}]"
        )
    else:
        msg = f"✓ All steps completed. {summary}"
    return ToolResult(
        type=ResultType.STEP_DONE,
        content=msg,
        target_step=next_step,
    )


def goto_step(state: AgentState, step: str, reason: str) -> ToolResult:
    """
    跳转到指定步骤（可后退到已完成步骤重新修改）。
    """
    if step not in STEP_ORDER:
        return ToolResult(
            type=ResultType.OBSERVATION,
            content=f"Error: unknown step '{step}'. Valid steps: {STEP_ORDER}",
        )
    state.goto(step)
    return ToolResult(
        type=ResultType.GOTO_STEP,
        content=f"→ Navigated to [{step}]. Reason: {reason}",
        target_step=step,
    )
