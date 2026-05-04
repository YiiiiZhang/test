import json
import os
import re
import inspect
from llm import LocalQwenLLM
from context_store import ConversationContext
from tool import (
    planer,
    requirements_parser,
    requirements_parser_check,
    generate_question,
    macro_structure_planner,
    question_distribution_planner,
    detailed_question_generator,
    single_question_checker,
    overall_question_checker,
    mcp_survey_executor,
    finish_step,
)
from prompts import SYSTEM_PROMPT


class QAOrchestrator:
    def __init__(self):
        config = {}
        self.max_iterations = 5

        with open("configs.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        llm_config = config.get("LLM", {})

        self.max_iterations = config.get("max_iterations", self.max_iterations)

        print(f"Loading LLM from: {llm_config['model_path']} ...")
        self.llm = LocalQwenLLM(**llm_config)
        self.context = ConversationContext()
        self.plan = planer()

        self.tools_registry = {
            "requirement_parser": requirements_parser,
            "requirement_check": requirements_parser_check,
            "generate_question": generate_question,
            "macro_structure_planner": macro_structure_planner,
            "structure_planner": macro_structure_planner,
            "question_distribution_planner": question_distribution_planner,
            "detailed_question_generator": detailed_question_generator,
            "single_question_checker": single_question_checker,
            "overall_question_checker": overall_question_checker,
            "mcp_survey_executor": mcp_survey_executor,
            "finish_step": finish_step,
        }

    def _parse_tool_call(self, text: str) -> dict | None:
        """Parse a JSON tool-call block from the LLM output."""
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            return None

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _build_agent_prompt(self) -> list[dict[str, str]]:
        """Build the message list passed to the LLM."""
        plan_lines = ["[Current Task Plan]"]
        for idx, step in enumerate(self.plan.steps, start=1):
            plan_lines.append(
                f"Step {idx}. {step.title} | status={step.status} | description={step.description}"
            )
            if step.result:
                plan_lines.append(f"Step {idx} result summary: {step.result}")

        system_content = SYSTEM_PROMPT + "\n\n" + "\n".join(plan_lines)
        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.context.to_message_dicts())
        return messages

    def run(self, user_input: str) -> str:
        """Process user input and execute the agent loop."""
        self.context.add_user_message(user_input)

        for iteration in range(self.max_iterations):
            messages = self._build_agent_prompt()
            print(f"\n[Agent thinking: {iteration + 1}/{self.max_iterations}] ...")
            llm_response = self.llm.chat(messages)
            self.context.add_assistant_message(llm_response)

            tool_call = self._parse_tool_call(llm_response)
            if not tool_call:
                return llm_response

            tool_name = tool_call.get("name")
            tool_params = tool_call.get("params", {})

            if tool_name not in self.tools_registry:
                error_msg = (
                    f"System error: tool '{tool_name}' was not found. "
                    "Please check the available tool list and call again."
                )
                print(f"-> {error_msg}")
                self.context.add_user_message(f"Tool feedback: {error_msg}")
                continue

            print(f"-> Calling tool: {tool_name}")
            print(f"-> Parameters: {json.dumps(tool_params, ensure_ascii=False)}")

            try:
                func = self.tools_registry[tool_name]
                if "llm" in func.__code__.co_varnames:
                    tool_params["llm"] = self.llm
                if "plan" in func.__code__.co_varnames:
                    tool_params["plan"] = self.plan
                if "context" in func.__code__.co_varnames:
                    tool_params["context"] = self.context
                sig = inspect.signature(func)
                valid_params = {k: v for k, v in tool_params.items() if k in sig.parameters}
                
                tool_result = func(**valid_params)
                print(f"-> Tool result: {tool_result}")

                observation_msg = (
                    f"Tool {tool_name} finished. Returned result:\n{tool_result}\n"
                    "Decide the next step based on this result, or reply to the user directly."
                )
                self.context.add_user_message(observation_msg)

                if tool_name == "generate_question":
                    return str(tool_result)

                if (
                    tool_name == "mcp_survey_executor"
                    and isinstance(tool_result, str)
                    and "success" in tool_result.lower()
                ):
                    return f"Task completed. Execution result:\n{tool_result}"

            except Exception as e:
                error_msg = (
                    f"An exception occurred while executing tool {tool_name}: {e}. "
                    "Please verify whether the provided parameters satisfy the tool requirements."
                )
                print(f"-> {error_msg}")
                self.context.add_user_message(f"Tool execution feedback: {error_msg}")

        return (
            "System busy: the agent exceeded the maximum number of thinking iterations. "
            "Please simplify the request or restate it."
        )
