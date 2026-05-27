"""
agent.py
─────────────────────────────────────────────
QAOrchestrator — 新版 Agent 主控制器

设计原则：
  - 每个步骤维护一个可变的核心状态（AgentState）
  - 工具 = 对核心状态的 CRUD + 导航
  - ask_user 可在任意步骤暂停循环，用户回复后在同一步骤继续
  - confirm_step 确认步骤完成后才进入下一步
  - goto_step 支持随时回退到任意步骤修改
"""

import json
import re
import inspect
from typing import Optional

from llm import LocalQwenLLM
from context_store import ConversationContext
from state.models import AgentState
from tools.base import ToolResult, ResultType
from tools import navigation, requirement, structure, question, output_tools
from prompts.builder import build_system_prompt


class QAOrchestrator:
    def __init__(self):
        with open("configs.json", "r", encoding="utf-8") as f:
            self.configs = json.load(f)

        llm_config = self.configs.get("LLM", {})
        self.max_iterations = self.configs.get("max_iterations", 15)

        print(f"Loading LLM from: {llm_config['model_path']} ...")
        self.llm     = LocalQwenLLM(**llm_config)
        self.state   = AgentState()
        self.context = ConversationContext(
            log_file=self.configs.get("logs_file", "conversation_logs.json")
        )
        self._build_registry()

    # ─────────────────────────────────────────────────────────────────────────
    # 工具注册
    # ─────────────────────────────────────────────────────────────────────────

    def _build_registry(self) -> None:
        self.tools_registry: dict[str, callable] = {
            # ── 全局工具（任意步骤均可调用） ──────────────────────────────────
            "ask_user":     navigation.ask_user,
            "confirm_step": navigation.confirm_step,
            "goto_step":    navigation.goto_step,

            # ── Step 1: 需求分析 ───────────────────────────────────────────
            "parse_requirements":    requirement.parse_requirements,
            "set_requirement_field": requirement.set_requirement_field,
            "get_requirements":      requirement.get_requirements,

            # ── Step 2: 结构规划 ───────────────────────────────────────────
            "generate_structure": structure.generate_structure,
            "add_section":        structure.add_section,
            "update_section":     structure.update_section,
            "delete_section":     structure.delete_section,
            "set_style":          structure.set_style,
            "set_introduction":   structure.set_introduction,
            "get_structure":      structure.get_structure,

            # ── Step 3: 题目生成 ───────────────────────────────────────────
            "generate_all_questions":     question.generate_all_questions,
            "generate_section_questions": question.generate_section_questions,
            "add_question":               question.add_question,
            "update_question":            question.update_question,
            "delete_question":            question.delete_question,
            "set_survey_meta":            question.set_survey_meta,
            "get_questions":              question.get_questions,
            "validate_questions":         question.validate_questions,

            # ── Step 4: 输出 ────────────────────────────────────────────────
            "execute_output": output_tools.execute_output,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 工具调用
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        """从 LLM 输出中提取 ```json``` 代码块。"""
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _inject_and_call(self, tool_name: str, tool_params: dict) -> ToolResult:
        """
        根据函数签名自动注入运行时依赖（llm / state / configs），
        其余参数由 LLM 通过 tool_params 提供。
        """
        func = self.tools_registry[tool_name]
        sig  = inspect.signature(func)

        final_params: dict = {}
        for param_name in sig.parameters:
            if param_name == "llm":
                final_params["llm"] = self.llm
            elif param_name == "state":
                final_params["state"] = self.state
            elif param_name == "configs":
                final_params["configs"] = self.configs

        # LLM 提供的参数（只接受函数签名中存在的 key）
        for k, v in tool_params.items():
            if k in sig.parameters:
                final_params[k] = v

        return func(**final_params)

    # ─────────────────────────────────────────────────────────────────────────
    # Prompt 构建
    # ─────────────────────────────────────────────────────────────────────────

    def _build_prompt(self) -> list[dict]:
        system_content = build_system_prompt(self.state)
        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.context.to_message_dicts())
        return messages

    # ─────────────────────────────────────────────────────────────────────────
    # 主循环
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, user_input: str) -> str:
        """
        处理一轮用户输入，驱动 Agent 循环直到：
          - LLM 返回纯文本（无工具调用）→ 直接回复用户
          - 工具返回 ASK_USER → 把问题发给用户，本轮结束
          - 工具返回 TASK_DONE → 任务全部完成
          - 达到最大迭代次数 → 超时提示

        步骤状态在 AgentState 中持久保存，下一次 run() 从断点继续。
        """
        self.context.add_user_message(user_input)
        iteration = 0

        while iteration < self.max_iterations:
            messages = self._build_prompt()
            step_tag = self.state.current_step
            print(f"\n[Agent iter={iteration + 1}/{self.max_iterations} | step={step_tag}]")

            llm_response = self.llm.chat(messages)
            self.context.add_assistant_message(llm_response)

            # ── 没有工具调用 → LLM 直接回复用户 ──────────────────────────────
            tool_call = self._parse_tool_call(llm_response)
            if tool_call is None:
                return llm_response

            tool_name   = tool_call.get("name", "")
            tool_params = tool_call.get("params", {})

            # ── 工具名不存在 ────────────────────────────────────────────────
            if tool_name not in self.tools_registry:
                err = (
                    f"Tool '{tool_name}' does not exist. "
                    "Check the [Available Tools] list in the system prompt."
                )
                print(f"  ✗ {err}")
                self.context.add_user_message(f"[System] {err}")
                iteration += 1
                continue

            print(f"  → {tool_name}({json.dumps(tool_params, ensure_ascii=False)})")

            # ── 执行工具 ────────────────────────────────────────────────────
            try:
                result: ToolResult = self._inject_and_call(tool_name, tool_params)
            except Exception as e:
                err = f"Tool '{tool_name}' raised an exception: {e}"
                print(f"  ✗ {err}")
                self.context.add_user_message(f"[Tool error] {err}")
                iteration += 1
                continue

            content_preview = result.content[:120].replace("\n", " ")
            print(f"  ← [{result.type}] {content_preview}...")

            # ── 处理返回类型 ─────────────────────────────────────────────────

            if result.type == ResultType.ASK_USER:
                # 把问题/草稿返回给用户，本轮结束
                # 下一轮 run() 将继续在当前步骤工作
                return result.content

            if result.type == ResultType.TASK_DONE:
                # 全部完成
                return result.content

            if result.type in (ResultType.STEP_DONE, ResultType.GOTO_STEP):
                # 步骤发生变化：裁剪短期上下文，写入步骤切换通知
                self.context.clear()
                self.context.add_user_message(
                    f"[System] {result.content}\n"
                    f"Current step: [{self.state.current_step}]"
                )
                # 不增加 iteration，步骤切换视为有意义的推进
                continue

            # OBSERVATION：把工具结果作为 observation 加入上下文，继续循环
            self.context.add_user_message(
                f"[Tool: {tool_name}]\n{result.content}\n\n"
                "Review the result above and decide the next action."
            )
            iteration += 1

        return (
            "System: The agent exceeded the maximum number of iterations for this turn. "
            "Please simplify your request or continue with a new message."
        )
