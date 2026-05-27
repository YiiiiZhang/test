# QA Agent

A local LLM-powered interactive survey-creation assistant.  
QA Agent guides users through a structured, multi-step conversation to produce a finished questionnaire — and can publish it directly to Google Forms.

---

## Architecture

The agent is built around a **CRUD state model**: every pipeline step owns a mutable core-content object. The LLM interacts with that object via fine-grained Create / Read / Update / Delete tools rather than regenerating everything at once. This lets the user and the agent iterate freely within each step before moving on.

```
User input ──► QAOrchestrator.run()
                │
                ├─ Build system prompt (step state + available tools)
                ├─ Call local LLM
                ├─ Parse tool call JSON from response
                │
                ├─ Tool: CRUD on core state  ──► OBSERVATION → loop
                ├─ Tool: ask_user            ──► pause, return question to user
                ├─ Tool: confirm_step        ──► advance to next step, clear context
                ├─ Tool: goto_step           ──► jump to any step (backward revision)
                └─ Tool: execute_output      ──► TASK_DONE → return result
```

Key design decisions:

| Decision | Detail |
|---|---|
| **Per-step core state** | `RequirementState`, `StructureState`, `QuestionsState`, `OutputState` — each is a Pydantic model persisted across turns |
| **ask_user pauses the loop** | Returning `ResultType.ASK_USER` ends the current `run()` call; the next call resumes at the exact same step |
| **confirm_step is the only gate** | The step never advances unless the LLM explicitly calls `confirm_step`, preventing accidental progression |
| **goto_step enables revision** | Any step can be revisited at any time; completed steps are re-opened automatically |
| **Context trimmed at transitions** | `ConversationContext.clear()` fires only on step change (not every tool call), keeping the prompt focused |
| **Runtime injection** | Tools declare `llm`, `state`, `configs` as parameters; the orchestrator injects them automatically via `inspect.signature()` |

---

## Pipeline Steps

### Step 1 — Requirement Analysis (`requirement_analysis`)

Collect and confirm the survey requirements through natural-language conversation.

**Core state:** `RequirementState`

| Field | Required | Description |
|---|---|---|
| `survey_topic` | ✓ | What the survey is about |
| `survey_object` | ✓ | Target respondents |
| `survey_goal` | ✓ | Purpose of the survey |
| `questionnaire_size` | — | Target number of questions |
| `need_background_info` | — | Whether to include a background section |
| `prohibited_content` | — | Topics / wording to avoid |
| `other` | — | Any additional constraints |

**Tools:** `parse_requirements` · `set_requirement_field` · `get_requirements`

---

### Step 2 — Structure Planning (`structure_planning`)

Design the survey's sections, language style, introduction, and question distribution.

**Core state:** `StructureState`

| Field | Description |
|---|---|
| `style` | Language tone (e.g. "formal academic", "friendly casual") |
| `introduction` | Opening message shown to respondents |
| `sections` | List of `SectionItem` objects, each with `section_id`, `theme`, `description`, `question_count`, `question_types` |

**Tools:** `generate_structure` · `add_section` · `update_section` · `delete_section` · `set_style` · `set_introduction` · `get_structure`

---

### Step 3 — Question Generation (`question_generation`)

Generate, review, and iteratively refine all survey questions together with the user.

**Core state:** `QuestionsState`

Each `QuestionItem` contains:
- `id` — auto-assigned integer
- `section_id` — links back to a `StructureState` section
- `type` — `single_choice` | `multiple_choice` | `text`
- `question` — question text
- `options` — list of answer choices (empty for `text` type)

**Tools:** `generate_all_questions` · `generate_section_questions` · `add_question` · `update_question` · `delete_question` · `set_survey_meta` · `get_questions` · `validate_questions`

---

### Step 4 — Output (`output`)

Save the final questionnaire locally and/or publish it to Google Forms.

**Core state:** `OutputState` — records `form_url`, `local_path`, `status`

**Tool:** `execute_output`

---

### Global Navigation Tools (available at every step)

| Tool | Purpose |
|---|---|
| `ask_user` | Send a question or draft to the user and pause the loop |
| `confirm_step` | Mark the current step as done and advance to the next |
| `goto_step` | Jump to any step by name (supports backward revision) |

---

## Project Structure

```
.
├── agent.py              # QAOrchestrator — main controller and agent loop
├── cli.py                # Terminal entry point
├── llm.py                # Local Qwen model wrapper
├── context_store.py      # Conversation memory (add / export / clear)
├── configs.json          # Runtime configuration
│
├── state/
│   ├── __init__.py
│   └── models.py         # AgentState + per-step state models (Pydantic v2)
│
├── tools/
│   ├── __init__.py
│   ├── base.py           # ToolResult dataclass + ResultType constants
│   ├── navigation.py     # ask_user / confirm_step / goto_step
│   ├── requirement.py    # Step 1 CRUD tools
│   ├── structure.py      # Step 2 CRUD tools
│   ├── question.py       # Step 3 CRUD tools
│   ├── output_tools.py   # Step 4 execution
│   └── google_forms.py   # Google Forms API client
│
├── prompts/
│   ├── __init__.py
│   └── builder.py        # Dynamic system-prompt builder
│
├── results/              # Local survey output (JSON)
└── logs/                 # Conversation logs (JSON)
```

---

## Configuration (`configs.json`)

```json
{
    "LLM": {
        "model_path": "/path/to/local/model",
        "temperature": 0.1,
        "max_tokens": 2048,
        "down_sample": false,
        "device_map": "auto"
    },
    "max_iterations": 10,
    "GOOGLE_KEYS": {
        "SCOPES": [
            "https://www.googleapis.com/auth/forms.body",
            "https://www.googleapis.com/auth/drive"
        ],
        "GOOGLE_APPLICATION_CREDENTIALS": "../KEYS/client_qa.googleusercontent.com.json",
        "Token_json": "../KEYS/token.json"
    },
    "save_survey": {
        "save_to_local": true,
        "save_to_google_forms": true,
        "output_path": "./results/final_survey.json"
    },
    "logs_file": "./logs/conversation_logs.json"
}
```

| Key | Description |
|---|---|
| `LLM.model_path` | Absolute path to a local Qwen-compatible model |
| `LLM.temperature` | Sampling temperature (lower = more deterministic) |
| `LLM.max_tokens` | Maximum tokens per LLM response |
| `max_iterations` | Maximum agent-loop iterations per user turn |
| `GOOGLE_KEYS` | OAuth credentials for Google Forms / Drive |
| `save_survey.save_to_local` | Whether to save the final JSON locally |
| `save_survey.save_to_google_forms` | Whether to publish to Google Forms |
| `save_survey.output_path` | Local save path |

---

## Installation

```bash
# 1. Install Python dependencies
pip install torch transformers pydantic google-auth google-auth-oauthlib google-api-python-client

# 2. Set model path in configs.json

# 3. Place Google OAuth credentials under ../KEYS/
#    (GOOGLE_APPLICATION_CREDENTIALS and Token_json paths)
```

---

## Usage

```bash
python cli.py
```

Example opening message:

```
I want to create a 10-question satisfaction survey for university students about an online learning platform.
```

The agent will:
1. Extract requirements and ask follow-up questions until all required fields are confirmed
2. Draft a survey structure and discuss it with you
3. Generate all questions section by section and refine them on request
4. Save the final questionnaire to a local JSON file and/or push it to Google Forms

---

## Tool Call Protocol

The LLM communicates tool calls via a single `json` code block:

```json
{
    "name": "tool_name",
    "params": {
        "param_name": "param_value"
    }
}
```

Any LLM response without a `json` block is treated as a direct reply to the user.

---

## Module Reference

### `agent.py` — `QAOrchestrator`

- Loads config, LLM, `AgentState`, `ConversationContext`
- Registers all tools in a flat `dict[str, callable]`
- Injects `llm` / `state` / `configs` into tool calls via `inspect.signature()`
- Routes `ToolResult` types: `OBSERVATION` → loop, `ASK_USER` → return to user, `STEP_DONE` / `GOTO_STEP` → clear context and continue, `TASK_DONE` → return final result

### `state/models.py`

Core Pydantic models:
- `RequirementState` — required fields + `is_complete()` / `missing_fields()`
- `StructureState` + `SectionItem`
- `QuestionsState` + `QuestionItem`
- `OutputState`
- `AgentState` — global container with `goto()`, `confirm_current_step()`, `is_all_done()`

### `tools/base.py`

```python
class ResultType:
    OBSERVATION = "observation"   # tool result fed back into the loop
    ASK_USER    = "ask_user"      # pause loop, return message to user
    STEP_DONE   = "step_done"     # step advanced to next
    GOTO_STEP   = "goto_step"     # jumped to a specific step
    TASK_DONE   = "task_done"     # entire pipeline complete

@dataclass
class ToolResult:
    type: str
    content: str
    target_step: Optional[str] = None
```

### `prompts/builder.py`

Builds the system prompt dynamically on every LLM call:
1. Base role + tool-call format spec
2. Visual task plan (○ pending / → in-progress / ► current / ✓ done)
3. Current step's live state content
4. Available tools (global + step-specific), with purpose and parameter schema
5. Workflow guide

### `context_store.py`

Lightweight conversation memory:
- `add_user_message()` / `add_assistant_message()` — append to history
- `to_message_dicts()` — export as `[{"role": ..., "content": ...}]`
- `clear()` — reset short-term context on step transitions

### `llm.py`

Wraps a local Qwen model loaded via Transformers:
- `LocalQwenLLM(model_path, temperature, max_tokens, ...)`
- `chat(messages: list[dict]) -> str` — applies the chat template and returns decoded output
