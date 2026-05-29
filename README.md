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

# 2. Set model path in configs.json (see Configuration section)

# 3. Complete Google Forms API setup (see section below)
```

---

## Google Forms API Setup

This section only applies when `save_survey.save_to_google_forms` is `true` in `configs.json`.  
If you only need local JSON output, skip this entire section.

### Step 1 — Create a Google Cloud Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/) and sign in.
2. Click the project dropdown (top bar) → **New Project**.
3. Give it any name (e.g. `qa-agent`) and click **Create**.

### Step 2 — Enable the required APIs

With your new project selected:

1. Go to **APIs & Services → Library**.
2. Search for **Google Forms API** → click it → **Enable**.
3. Search for **Google Drive API** → click it → **Enable**.

### Step 3 — Create OAuth 2.0 credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. If prompted to configure the consent screen first:
   - Choose **External** (or Internal if using a Workspace account).
   - Fill in the required fields (App name, support email). No logo needed.
   - On the **Scopes** page you can skip adding scopes manually — the code requests them at runtime.
   - On the **Test users** page, add the Google account you will authenticate with.
   - Save and return to **Credentials**.
4. Back in **Create OAuth client ID**:
   - Application type: **Desktop app**.
   - Name: anything (e.g. `qa-agent-desktop`).
   - Click **Create**.
5. Click **Download JSON** on the confirmation dialog (or click the download icon next to the credential later).

### Step 4 — Place the credential file

The default paths in `configs.json` expect a `KEYS/` directory **one level above the project root**:

```
parent_directory/
├── KEYS/
│   └── client_qa.googleusercontent.com.json   ← rename your downloaded file to this
└── test/                                        ← project root (where cli.py lives)
```

Create the `KEYS/` folder and rename the downloaded JSON to match the filename in `GOOGLE_APPLICATION_CREDENTIALS`, or update `configs.json` to point to wherever you placed it:

```json
"GOOGLE_KEYS": {
    "SCOPES": [
        "https://www.googleapis.com/auth/forms.body",
        "https://www.googleapis.com/auth/drive"
    ],
    "GOOGLE_APPLICATION_CREDENTIALS": "../KEYS/client_qa.googleusercontent.com.json",
    "Token_json": "../KEYS/token.json"
}
```

| Key | What to change |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the OAuth client secret JSON you downloaded |
| `Token_json` | Path where the access token will be **auto-created** on first login — the directory must exist |

Both paths are relative to the project root (`test/`).

### Step 5 — Authorize on first run

The first time `execute_output` is called (Step 4 of the agent), the program will:

1. Open a browser window asking you to sign in with Google.
2. Show an OAuth consent screen — click **Continue** (you may see a "This app isn't verified" warning because the consent screen is in test mode; click **Advanced → Go to \<app name\>**).
3. Grant the requested permissions (Forms + Drive).
4. Return to the terminal automatically.

The resulting token is saved to `Token_json`. **Subsequent runs reuse this token without opening a browser**, and it is refreshed automatically when it expires.

> **Never commit the `KEYS/` directory or `token.json` to version control.**  
> Add them to `.gitignore`:
> ```
> KEYS/
> ../KEYS/
> ```

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

---

## End-to-End Flow

This section traces exactly what happens from the moment the user types a message to the moment a response is returned.

```
cli.py
  └─ orchestrator.run(user_input)
       │
       │  1. Add user_input to ConversationContext
       │
       └─ Agent loop (up to max_iterations per turn)
            │
            │  2. Build system prompt
            │       build_system_prompt(state)
            │         ├─ BASE_PROMPT       (role + tool-call format)
            │         ├─ _render_plan()    (visual step status)
            │         ├─ _render_current_state()  (live state data)
            │         ├─ _render_tools()   (global + step-specific tools)
            │         └─ WORKFLOW_GUIDE
            │
            │  3. Call local LLM
            │       llm.chat([system_prompt] + conversation_history)
            │
            │  4. Parse LLM response
            │       ┌─ Contains ```json``` block?
            │       │     YES → extract tool_name + tool_params
            │       └─     NO  → return plain text directly to user
            │
            │  5. Dispatch tool call
            │       _inject_and_call(tool_name, tool_params)
            │         ├─ inspect.signature() detects llm/state/configs params
            │         └─ calls the tool function with injected + LLM params
            │
            │  6. Route by ToolResult.type
            │       OBSERVATION  → add result to context, increment iteration, loop
            │       ASK_USER     → return result.content to user (end this turn)
            │       STEP_DONE /
            │       GOTO_STEP   → context.clear(), add step-change notice, loop
            │       TASK_DONE   → return result.content to user (pipeline done)
            │
            └─ (repeat from step 2)
```

### State flow across turns

```
Turn 1:  run("I want a survey on...")
          -> parse_requirements   [OBSERVATION]  loop
          -> ask_user("What is the goal?")  [ASK_USER]  return to user

Turn 2:  run("The goal is to measure satisfaction")
          -> parse_requirements   [OBSERVATION]  loop
          -> ask_user("How many questions?")  [ASK_USER]  return to user

Turn 3:  run("About 12 questions please")
          -> parse_requirements   [OBSERVATION]  loop
          -> confirm_step(...)    [STEP_DONE]    context.clear(), advance step
          -> generate_structure() [OBSERVATION]  loop
          -> ask_user("Here is the draft structure...")  [ASK_USER]  return
```

The `AgentState` object lives in `QAOrchestrator` and is never reset between turns. Every `run()` call picks up exactly where the last one left off.

---

## Adding a New Tool

This section explains how to extend the agent with a new tool, end to end.

### Step 1 — Write the tool function

Add a function to the appropriate `tools/` module (or create a new one).

**Function signature rules:**
- Declare `state: AgentState` as a parameter if you need to read or write step state.
- Declare `llm: LocalQwenLLM` as a parameter if you need LLM inference.
- Declare `configs: dict` as a parameter if you need runtime config values.
- All other parameters are supplied by the LLM via `tool_params`.
- Always return a `ToolResult`.

```python
# tools/requirement.py  (example of adding a new tool to an existing module)

from tools.base import ToolResult, ResultType
from state.models import AgentState

def summarize_requirements(state: AgentState) -> ToolResult:
    """Return a single-sentence plain-English summary of the confirmed requirements."""
    req = state.requirements
    summary = (
        f"A {req.questionnaire_size or 'medium'}-length survey "
        f"about '{req.survey_topic}' targeting {req.survey_object}, "
        f"aimed at {req.survey_goal}."
    )
    return ToolResult(type=ResultType.OBSERVATION, content=summary)
```

Choose the correct `ResultType`:

| Type | When to use |
|---|---|
| `OBSERVATION` | Normal result — the agent loop reads it and continues |
| `ASK_USER` | You want to pause and show something to the user |
| `STEP_DONE` | The current step is finished (only for `confirm_step`) |
| `GOTO_STEP` | You jumped to a different step (only for `goto_step`) |
| `TASK_DONE` | The entire pipeline is complete |

### Step 2 — Register the tool in `agent.py`

Open [agent.py](agent.py) and add the function to `_build_registry()`:

```python
# agent.py — inside _build_registry()

from tools import requirement   # already imported

self.tools_registry: dict[str, callable] = {
    ...
    # ── Step 1: requirement analysis ──
    "parse_requirements":    requirement.parse_requirements,
    "set_requirement_field": requirement.set_requirement_field,
    "get_requirements":      requirement.get_requirements,
    "summarize_requirements": requirement.summarize_requirements,   # <-- add this
    ...
}
```

The key is the exact name the LLM will use to call the tool. The orchestrator's
`_inject_and_call()` handles dependency injection automatically — no other
changes to `agent.py` are needed.

### Step 3 — Expose the tool in the system prompt

Open [prompts/builder.py](prompts/builder.py) and add an entry to `STEP_TOOL_META`
under the appropriate step:

```python
# prompts/builder.py — inside STEP_TOOL_META[STEP_REQUIREMENT]

STEP_TOOL_META = {
    STEP_REQUIREMENT: {
        ...
        "summarize_requirements": {
            "purpose": "Generate a one-sentence plain-English summary of the confirmed requirements.",
            "params": "{}",
        },
    },
    ...
}
```

The `purpose` field is shown to the LLM so it knows when to call the tool.
The `params` field shows the expected JSON parameter schema.

### Step 4 — Test the tool

```python
# Quick smoke test (mocks torch/transformers)
import sys, types
from unittest.mock import MagicMock
sys.modules["torch"] = MagicMock()
sys.modules["torch"].dtype = type("dtype", (), {})
sys.modules["transformers"] = MagicMock()

from state.models import AgentState, RequirementState
from tools.requirement import summarize_requirements

state = AgentState()
state.requirements = RequirementState(
    survey_topic="online learning",
    survey_object="university students",
    survey_goal="measure satisfaction",
    questionnaire_size="12",
)
result = summarize_requirements(state)
print(result.type)     # observation
print(result.content)  # A 12-length survey about 'online learning' ...
```

### Checklist

- [ ] Tool function written and returns `ToolResult`
- [ ] Tool registered in `_build_registry()` with a unique name
- [ ] Tool metadata added to `STEP_TOOL_META` (or `GLOBAL_TOOL_META` if step-agnostic)
- [ ] Tool tested in isolation
