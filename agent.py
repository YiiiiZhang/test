"""
agent.py
─────────────────────────────────────────────
QAOrchestrator — main agent controller

Design principles:
  - Each step maintains a mutable core state (AgentState)
  - Tools = CRUD operations on core state + navigation
  - ask_user can pause the loop at any step; the next run() call resumes
    at the same step with the same state
  - confirm_step gates step advancement — the step never advances unless
    the LLM explicitly confirms it with the user
  - goto_step supports backward navigation to any step for revision
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
    # Tool registration
    # ─────────────────────────────────────────────────────────────────────────

    def _build_registry(self) -> None:
        self.tools_registry: dict[str, callable] = {
            # ── Global tools (available at every step) ────────────────────────
            "ask_user":     navigation.ask_user,
            "confirm_step": navigation.confirm_step,
            "goto_step":    navigation.goto_step,

            # ── Step 1: requirement analysis ──────────────────────────────────
            "parse_requirements":    requirement.parse_requirements,
            "set_requirement_field": requirement.set_requirement_field,
            "get_requirements":      requirement.get_requirements,

            # ── Step 2: structure planning ────────────────────────────────────
            "generate_structure": structure.generate_structure,
            "add_section":        structure.add_section,
            "update_section":     structure.update_section,
            "delete_section":     structure.delete_section,
            "set_style":          structure.set_style,
            "set_introduction":   structure.set_introduction,
            "get_structure":      structure.get_structure,

            # ── Step 3: question generation ───────────────────────────────────
            "generate_all_questions":     question.generate_all_questions,
            "generate_section_questions": question.generate_section_questions,
            "add_question":               question.add_question,
            "update_question":            question.update_question,
            "delete_question":            question.delete_question,
            "set_survey_meta":            question.set_survey_meta,
            "get_questions":              question.get_questions,
            "validate_questions":         question.validate_questions,

            # ── Step 4: output ────────────────────────────────────────────────
            "execute_output": output_tools.execute_output,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Tool dispatch
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        """Extract a ```json``` block from the LLM response, if present."""
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _inject_and_call(self, tool_name: str, tool_params: dict) -> ToolResult:
        """
        Auto-inject runtime dependencies (llm / state / configs) based on the
        function's parameter names, then call the tool with the LLM-supplied
        params for any remaining parameters.
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

        # Accept LLM-provided params only for keys present in the signature
        for k, v in tool_params.items():
            if k in sig.parameters:
                final_params[k] = v

        return func(**final_params)

    # ─────────────────────────────────────────────────────────────────────────
    # Prompt construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_prompt(self) -> list[dict]:
        system_content = build_system_prompt(self.state)
        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.context.to_message_dicts())
        return messages

    # ─────────────────────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, user_input: str) -> str:
        """
        Process one round of user input, driving the agent loop until:
          - The LLM returns plain text (no tool call) -> reply directly to user
          - A tool returns ASK_USER -> send the question to the user, end this turn
          - A tool returns TASK_DONE -> the entire pipeline is complete
          - The iteration limit is reached -> timeout message

        Step state is persisted in AgentState; the next run() call resumes
        from the exact same position.
        """
        self.context.add_user_message(user_input)
        iteration = 0

        while iteration < self.max_iterations:
            messages = self._build_prompt()
            step_tag = self.state.current_step
            print(f"\n[Agent iter={iteration + 1}/{self.max_iterations} | step={step_tag}]")

            llm_response = self.llm.chat(messages)
            self.context.add_assistant_message(llm_response)

            # ── No tool call -> LLM replies directly to the user ──────────────
            tool_call = self._parse_tool_call(llm_response)
            if tool_call is None:
                return llm_response

            tool_name   = tool_call.get("name", "")
            tool_params = tool_call.get("params", {})

            # ── Unknown tool name ─────────────────────────────────────────────
            if tool_name not in self.tools_registry:
                err = (
                    f"Tool '{tool_name}' does not exist. "
                    "Check the [Available Tools] list in the system prompt."
                )
                print(f"  x {err}")
                self.context.add_user_message(f"[System] {err}")
                iteration += 1
                continue

            print(f"  -> {tool_name}({json.dumps(tool_params, ensure_ascii=False)})")

            # ── Execute the tool ──────────────────────────────────────────────
            try:
                result: ToolResult = self._inject_and_call(tool_name, tool_params)
            except Exception as e:
                err = f"Tool '{tool_name}' raised an exception: {e}"
                print(f"  x {err}")
                self.context.add_user_message(f"[Tool error] {err}")
                iteration += 1
                continue

            content_preview = result.content[:120].replace("\n", " ")
            print(f"  <- [{result.type}] {content_preview}...")

            # ── Route by result type ──────────────────────────────────────────

            if result.type == ResultType.ASK_USER:
                # Return the question to the user and end this turn.
                # The next run() call will continue at the current step.
                return result.content

            if result.type == ResultType.TASK_DONE:
                return result.content

            if result.type in (ResultType.STEP_DONE, ResultType.GOTO_STEP):
                # Step changed: trim short-term context and record the transition.
                # Do not increment iteration — a step transition counts as progress.
                self.context.clear()
                self.context.add_user_message(
                    f"[System] {result.content}\n"
                    f"Current step: [{self.state.current_step}]"
                )
                continue

            # OBSERVATION: feed the tool result back as context and loop again
            self.context.add_user_message(
                f"[Tool: {tool_name}]\n{result.content}\n\n"
                "Review the result above and decide the next action."
            )
            iteration += 1

        return (
            "System: The agent exceeded the maximum number of iterations for this turn. "
            "Please simplify your request or continue with a new message."
        )
