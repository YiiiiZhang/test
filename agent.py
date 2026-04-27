import json
import inspect
import re
from llm import LocalQwenLLM
from json import JSONDecoder
from typing import Optional
from context_store import ConversationContext
from tool import (
    planer, requirements_parser, requirements_parser_check, generate_question,
    macro_structure_planner, question_distribution_planner, generate_section_questions,
    section_checker, update_specific_question, overall_question_checker, mcp_survey_executor, finish_step
)
from prompts import SYSTEM_PROMPT_TEMPLATE, TOOL_DESCRIPTIONS

class QAOrchestrator:
    def __init__(self):
        config = {}
        self.max_iterations = 5 # 现在这代表【每个子任务/Step的最大允许循环次数】

        try:
            with open("configs.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        except:
            pass

        llm_config = config.get("LLM", {
            "model_path": "local-model-path-placeholder",
            "temperature": 0.1,
            "max_tokens": 2048,
            "down_sample": False,
            "device_map": "auto"
        })
        self.max_iterations = config.get("max_iterations", self.max_iterations)

        print(f"Loading LLM from: {llm_config.get('model_path')} ...")
        self.llm = LocalQwenLLM(**llm_config)
        self.context = ConversationContext()
        self.plan = planer()

        self.tools_registry = {
            "requirement_parser": requirements_parser,
            "requirement_check": requirements_parser_check,
            "generate_question": generate_question,
            "macro_structure_planner": macro_structure_planner,
            "question_distribution_planner": question_distribution_planner,
            "generate_section_questions": generate_section_questions,
            "section_checker": section_checker,
            "update_specific_question": update_specific_question,
            "overall_question_checker": overall_question_checker,
            "mcp_survey_executor": mcp_survey_executor,
            "finish_step": finish_step,
        }

        # 任何步骤都允许调用的全局工具
        self.global_tools = ["generate_question", "finish_step"]

    def _get_current_step(self):
        for step in self.plan.steps:
            if step.status == "pending":
                return step
        return None

    def _get_allowed_tools_for_current_step(self) -> list[str]:
        current_step = self._get_current_step()
        # 如果任务全部完成，不再提供任何工具，强制进入纯文本闲聊模式
        if not current_step:
            return []
            
        step_tools = current_step.tools if current_step else []
        return list(set(step_tools + self.global_tools))
    def _parse_tool_call(self, text: str) -> Optional[dict]:
        def is_valid_tool_call(obj: object) -> bool:
            """Strict validation of tool-call schema."""
            return (
                isinstance(obj, dict)
                and isinstance(obj.get("name"), str)
                and isinstance(obj.get("params"), dict)
            )

        decoder = JSONDecoder()
        fence_pattern = re.compile(
            r"```(?:json)?\s*(.*?)\s*```",
            re.DOTALL | re.IGNORECASE,
        )

        for match in fence_pattern.finditer(text):
            candidate = match.group(1).strip()

            try:
                obj = json.loads(candidate)
                if is_valid_tool_call(obj):
                    return obj
            except json.JSONDecodeError:
                continue
        idx = 0

        while idx < len(text):
            start = text.find("{", idx)
            if start == -1:
                break
            try:
                obj, end = decoder.raw_decode(text, start)

                if is_valid_tool_call(obj):
                    return obj

                idx = end

            except json.JSONDecodeError:
                idx = start + 1

        return None
    def _build_agent_prompt(self) -> list[dict[str, str]]:
        # 1. 构建计划状态区块
        plan_lines = ["[Current Task Plan]"]
        all_completed = True
        
        for idx, step in enumerate(self.plan.steps, start=1):
            plan_lines.append(f"Step {idx}. {step.title} | status={step.status} | description={step.description}")
            if step.result: 
                plan_lines.append(f"Step {idx} result summary: {step.result}")
            if step.status != "completed":
                all_completed = False

        if all_completed:
            plan_lines.append("\n[Notice]: ALL STEPS COMPLETED. You are now in free-chat mode to answer the user's questions about the survey.")

        # 2. 构建动态工具区块
        allowed_tools = self._get_allowed_tools_for_current_step()
        tools_section = "[Available Tools for Current Step (Including Global Tools)]\n"
        if allowed_tools:
            for t_name in allowed_tools:
                if t_name in TOOL_DESCRIPTIONS:
                    tools_section += TOOL_DESCRIPTIONS[t_name] + "\n"
        else:
            tools_section += "No tools available. Please respond to the user directly in plain text.\n"

        # 3. 构建草稿本区块
        draft_section = "[Current Global Draft Data]\n"
        draft_dict = self.plan.draft.dict() if hasattr(self.plan.draft, 'dict') else self.plan.draft.model_dump()
        draft_section += json.dumps(draft_dict, ensure_ascii=False, indent=2) + "\n"

        system_content = (
            SYSTEM_PROMPT_TEMPLATE + "\n\n" +
            tools_section + "\n\n" +
            "\n".join(plan_lines) + "\n\n" +
            draft_section
        )
        
        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.context.to_message_dicts())
        return messages

    def run(self, user_input: str) -> str:
        self.context.add_user_message(user_input)

        current_step_title = None
        step_iterations = 0
        total_max_failsafe = 50 

        for global_iter in range(total_max_failsafe):
            current_step = self._get_current_step()
            
            # 【核心修改点】：如果当前没有 pending 的任务（即任务全完成）
            # 不要 return 死代码，而是调用一次 LLM 让它进行自然语言回复
            if not current_step:
                messages = self._build_agent_prompt()
                print("\n[Agent thinking in Free Chat Mode] ...")
                llm_response = self.llm.chat(messages)
                self.context.add_assistant_message(llm_response)
                return llm_response # 对话结束后直接返回给用户
                
            if current_step.title != current_step_title:
                current_step_title = current_step.title
                step_iterations = 0

            if step_iterations >= self.max_iterations:
                return f"System busy: exceeded max iterations ({self.max_iterations}) in step '{current_step_title}'."

            step_iterations += 1

            messages = self._build_agent_prompt()
            print(f"\n[Agent thinking in Step: {current_step_title} | Iteration: {step_iterations}/{self.max_iterations}] ...")
            llm_response = self.llm.chat(messages)
            self.context.add_assistant_message(llm_response)

            tool_call = self._parse_tool_call(llm_response)
            
            if not tool_call:
                return llm_response

            tool_name = tool_call.get("name")
            tool_params = tool_call.get("params", {})

            allowed_tools = self._get_allowed_tools_for_current_step()
            if tool_name not in allowed_tools:
                error_msg = f"System error: tool '{tool_name}' is not allowed in step '{current_step_title}'. Allowed: {allowed_tools}"
                print(f"-> {error_msg}")
                self.context.add_user_message(f"Tool validation feedback: {error_msg}")
                continue

            print(f"-> Calling tool: {tool_name}")
            
            try:
                import inspect
                func = self.tools_registry[tool_name]
                if "llm" in func.__code__.co_varnames: tool_params["llm"] = self.llm
                if "plan" in func.__code__.co_varnames: tool_params["plan"] = self.plan
                if "context" in func.__code__.co_varnames: tool_params["context"] = self.context
                
                sig = inspect.signature(func)
                valid_params = {k: v for k, v in tool_params.items() if k in sig.parameters}
                
                tool_result = func(**valid_params)
                print(f"-> Tool result length/status: {str(tool_result)[:100]}...")

                observation_msg = f"Tool {tool_name} finished. Result:\n{tool_result}\nDecide next step."
                self.context.add_user_message(observation_msg)

                # 注：这里移除了之前遇到 mcp_survey_executor 就 return 的逻辑。
                # 让系统自然走到下一个循环，发现所有任务完成，再由 LLM 自己说出“任务已完成”的话。

            except Exception as e:
                error_msg = f"Exception executing tool {tool_name}: {e}"
                print(f"-> {error_msg}")
                self.context.add_user_message(f"Tool execution feedback: {error_msg}")

        return "System halted: reached global failsafe limit."