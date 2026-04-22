# QA Agent

A local LLM-based questionnaire generation agent that turns a user's natural-language requirements into a structured survey through a staged tool-driven workflow.

## Overview

QA Agent is designed as an orchestration layer around a local Qwen model. Instead of generating a survey in one step, the system breaks the task into multiple stages:

1. Requirement analysis
2. Questionnaire structure planning
3. Question generation
4. Question validation
5. Survey creation/output

The core runtime is an agent loop that lets the LLM decide which tool to call next, executes that tool in Python, and feeds the result back into the LLM until the task is finished or the iteration limit is reached.


## Current Status

This project currently works as a **local prototype**.

- The agent loop is implemented.
- The tool-based planning flow is implemented.
- The final survey executor is currently a **temporary placeholder**.
- Instead of creating a real survey through an API, `mcp_survey_executor` currently prints the final questionnaire payload and returns a success-style result.

## Main Workflow

The end-to-end workflow is:

```text
User input
  -> CLI entry (`cli.py`)
  -> QAOrchestrator initialization (`agent.py`)
  -> Load config and local LLM
  -> Build system prompt + plan state + conversation history
  -> LLM decides whether to call a tool
  -> Parse tool call JSON
  -> Execute Python tool
  -> Feed tool result back into conversation context
  -> Continue until:
       - the agent asks the user a follow-up question, or
       - the final survey result is produced, or
       - max iterations are exceeded
```

### Detailed Stage Flow

#### 1. Requirement Analysis

The system first extracts structured survey requirements from the user's natural-language input.

Typical fields include:

- survey topic
- survey object
- survey goal
- questionnaire size
- whether background information is needed
- prohibited content
- other custom requirements

Then the extracted result is checked for completeness and consistency.

If required information is missing, the agent generates a follow-up question for the user.

#### 2. Questionnaire Structure Planning

Once the requirements are complete, the agent creates a macro-level survey structure, including:

- language style
- introduction wording
- section breakdown
- section themes
- section descriptions

#### 3. Question Distribution Planning

The system assigns:

- total question count
- question count per section
- question type per question

Supported question types are:

- `single_choice`
- `multiple_choice`
- `text`

#### 4. Detailed Question Generation

Based on the approved structure and distribution, the agent generates the full questionnaire in JSON format.

Each question contains:

- question id
- section id
- question type
- question text
- options

#### 5. Validation

Validation happens at two levels:

- **Single-question validation**
  - leading or biased wording
  - prohibited content
  - option quality and mutual exclusiveness
  - section-topic alignment

- **Overall questionnaire validation**
  - total question count
  - section coverage
  - repetition
  - tone consistency

#### 6. Final Output

After validation succeeds, the final questionnaire data is passed to `mcp_survey_executor`.

At the moment, this function only:

- prints the final questionnaire JSON
- returns a mock success-style result

## Project Structure

```text
.
├── agent.py           # Core orchestrator and agent loop
├── cli.py             # Command-line entry point
├── configs.json       # Runtime configuration
├── context_store.py   # Conversation memory container
├── llm.py             # Local Qwen model wrapper
├── prompts.py         # System prompt for agent tool use
├── state.py           # Plan / step data structures
├── tool.py            # All business tools used by the agent
└── README.md          # Project documentation
```

## Module Description

### `cli.py`

Provides a simple terminal interface.

Responsibilities:

- initialize the agent
- accept user input
- exit on `exit` or `quit`
- print the final agent response

### `agent.py`

Contains `QAOrchestrator`, which is the core controller.

Responsibilities:

- load configuration
- initialize the local LLM
- initialize conversation context
- initialize the plan
- register available tools
- build prompt messages
- parse tool call JSON
- run the tool-calling loop

### `context_store.py`

Defines the conversation-memory abstraction used by the orchestrator.

Responsibilities:

- store user messages
- store assistant messages
- export messages into chat format
- clear temporary context when needed

### `llm.py`

Wraps the local Qwen model.

Responsibilities:

- load tokenizer
- load model
- apply chat template
- run generation
- decode the final response

### `state.py`

Defines the planning data structure.

Core objects:

- `Step`
- `Plan`

Each step stores:

- title
- description
- status
- result

### `prompts.py`

Stores the global system prompt.

The prompt defines:

- the agent role
- tool call format
- tool descriptions
- workflow rules
- step completion behavior

### `tool.py`

Contains all business tools used by the agent.

Main tools:

- `planer`
- `requirements_parser`
- `requirements_parser_check`
- `generate_question`
- `macro_structure_planner`
- `question_distribution_planner`
- `detailed_question_generator`
- `single_question_checker`
- `overall_question_checker`
- `mcp_survey_executor`
- `finish_step`

## Requirements

Recommended environment:

- Python 3.10+
- PyTorch
- Transformers
- A local Qwen-compatible model path

## Installation

### 1. Clone or copy the project

Place all project files in the same working directory.

### 2. Install dependencies

Example:

```bash
pip install torch transformers pydantic
```

Install any additional dependencies required by your local environment.

### 3. Configure the model path

Edit `configs.json`:

```json
{
  "LLM": {
    "model_path": "/path/to/your/local/model",
    "temperature": 0.1,
    "max_tokens": 2048,
    "down_sample": false,
    "device_map": "auto"
  },
  "max_iterations": 5
}
```

Make sure `model_path` points to a valid local model directory.

## Usage

Run:

```bash
python cli.py
```

Example input:

```text
I want to create a questionnaire for university students about satisfaction with an online learning platform, with around 10 questions.
```

The system will then:

- analyze the requirement
- ask follow-up questions if needed
- plan the structure
- generate and validate questions
- print the final survey payload

## Tool Call Protocol

The agent uses a strict JSON tool call format.

Example:

```json
{
  "name": "requirements_parser",
  "params": {
    "user_input": "I want a survey for university students about online learning satisfaction."
  }
}
```

The orchestrator parses this JSON block and dispatches execution to the corresponding Python function.

## Step Persistence and Context Trimming

The project includes a step finalization mechanism through `finish_step`.

Purpose:

- mark a plan step as completed
- save the step result into the plan
- clear redundant short-term context
- keep later reasoning focused

This is useful for long multi-turn tasks where prompt length could otherwise keep growing.

## Known Limitations

### 1. Final survey creation is still mocked

`mcp_survey_executor` is currently a temporary placeholder.

It does not:

- create a real survey link
- call an external API
- persist the survey remotely

### 2. Output quality depends heavily on the local model

Because parsing, planning, validation, and question generation all rely on the LLM, output quality depends on:

- model capability
- prompt alignment
- generation settings
- local hardware/runtime stability

### 3. Validation is still model-driven

Even though the project separates validation into single-question and overall validation, the checks are still primarily LLM-based rather than rule-engine based.

### 4. No web/API integration yet

The current version is fully local and does not include:

- real survey platforms
- database storage
- user authentication
- frontend UI

## Next Steps

1. Replace `mcp_survey_executor` with a real survey platform API integration.
2. Add unit tests for tool functions and orchestration paths.

