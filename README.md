# Self-Correcting Multi-Agent System with DigitalOcean

A small, runnable demonstration of a self-correcting AI workflow. The app uses
LangGraph to coordinate three agents backed by DigitalOcean Serverless
Inference:

```text
Topic -> Writer -> Reviewer -- PASS ------> Final answer
										|
										REVISE
										|
										v
									Reviser -> Reviewer
```

The Writer creates a beginner-friendly explanation. The Reviewer checks it
against explicit quality rules and returns structured `PASS` or `REVISE`
feedback. The Reviser improves rejected drafts until the Reviewer accepts one
or the revision limit is reached. The browser UI displays the complete
execution trace.

## Features

- FastAPI web application with a simple browser interface.
- LangGraph state machine for the Writer, Reviewer, and Reviser loop.
- DigitalOcean Serverless Inference through its OpenAI-compatible endpoint.
- Optional DigitalOcean Inference Router support.
- Separate model configuration for each agent.
- Strict Pydantic validation of reviewer decisions.
- JSON API and command-line demo entry points.
- Lazy model initialization, allowing the web server to start before a key is
	configured.

## Project structure

```text
.
├── app.py                 # FastAPI application and HTTP routes
├── backend.py             # LangGraph workflow and inference configuration
├── requirements.txt       # Python dependencies
├── templates/index.html   # Web UI markup
└── static/
		├── app.js             # UI behavior and API calls
		└── style.css          # UI styling
```

## Requirements

- Python 3.11 or newer
- A DigitalOcean Model Access Key
- Access to DigitalOcean Serverless Inference

## Installation

### Conda

```bash
conda create -n loop-agent python=3.11 -y
conda activate loop-agent
python -m pip install -r requirements.txt
```

### Virtual environment

```bash
python -m venv .venv
```

Activate it with the command for your shell:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS/Linux
source .venv/bin/activate
```

Then install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root. Never commit this file or expose the
access key in source control, browser code, screenshots, or logs.

```dotenv
MODEL_ACCESS_KEY=replace_with_your_digitalocean_model_access_key
DO_INFERENCE_BASE_URL=https://inference.do-ai.run/v1
DO_MODEL=kimi-k3
MAX_REVISIONS=3
```

The application loads `.env` automatically through `python-dotenv`.

### Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MODEL_ACCESS_KEY` | Yes for runs | Empty | DigitalOcean Model Access Key. |
| `DO_INFERENCE_BASE_URL` | No | `https://inference.do-ai.run/v1` | OpenAI-compatible inference endpoint. |
| `DO_MODEL` | No | `kimi-k3` | Fallback model used by all agents. |
| `DO_WRITER_MODEL` | No | `DO_MODEL` | Direct model for the Writer. |
| `DO_REVIEWER_MODEL` | No | `DO_MODEL` | Direct model for the Reviewer. |
| `DO_REVISER_MODEL` | No | `DO_MODEL` | Direct model for the Reviser. |
| `DO_INFERENCE_ROUTER` | No | Empty | Router name. When set, all agents use `router:<name>`. |
| `MAX_REVISIONS` | No | `3` | Maximum number of Reviser passes before returning the latest draft. |

To configure different direct models, for example:

```dotenv
DO_WRITER_MODEL=kimi-k3
DO_REVIEWER_MODEL=kimi-k3
DO_REVISER_MODEL=kimi-k3
```

When `DO_INFERENCE_ROUTER` is set, the direct model names are replaced by the
router model identifier for all three agents. The agents remain distinct
through their system prompts.

## Run the web application

From the project root:

```bash
python app.py
```

Open <http://localhost:8000> in a browser. The server uses the `PORT`
environment variable when it is set, which is useful for managed hosting:

```powershell
$env:PORT = "8080"
python app.py
```

The page lets you submit a topic, then shows every Writer draft, Reviewer
decision, and Reviser pass. Good example topics include:

- `Explain recursion in programming`
- `What is retrieval-augmented generation?`
- `How does a database index work?`

## Run the command-line demo

The workflow can also be run without the browser:

```bash
python backend.py
```

Enter a topic when prompted. If no topic is entered, the demo uses
`What is an AI agent?`.

## API reference

### `GET /`

Returns the HTML application.

### `GET /api/config`

Returns non-secret runtime information, including the provider, endpoint,
selected models or router, and revision limit. The access key is never
returned.

### `POST /api/run`

Runs the workflow for a topic.

Request:

```json
{
	"topic": "What is an AI agent?"
}
```

The topic must contain 2 to 300 characters after trimming. A successful
response contains:

```json
{
	"topic": "What is an AI agent?",
	"events": [
		{
			"agent": "writer",
			"draft": "...",
			"decision": "",
			"feedback": "",
			"revision_count": 0,
			"provider": "DigitalOcean Serverless Inference",
			"model": "kimi-k3"
		}
	],
	"final_answer": "...",
	"final_decision": "PASS",
	"revision_count": 1,
	"provider": "DigitalOcean Serverless Inference",
	"endpoint": "https://inference.do-ai.run/v1",
	"router_enabled": false,
	"router": null,
	"writer_model": "kimi-k3",
	"reviewer_model": "kimi-k3",
	"reviser_model": "kimi-k3",
	"max_revisions": 3
}
```

Validation failures return HTTP `422`. Empty input is rejected with HTTP
`400`; workflow or inference failures return HTTP `500` with a diagnostic
message.

## Deploy to DigitalOcean App Platform

1. Push the project to a Git repository.
2. Create an App Platform app from that repository.
3. Use Python as the service type and set the build command to:

	 ```bash
	 pip install -r requirements.txt
	 ```

4. Set the run command to:

	 ```bash
	 python app.py
	 ```

5. Add `MODEL_ACCESS_KEY` as an encrypted App Platform environment variable.
6. Add any optional model, router, or `MAX_REVISIONS` variables.
7. Deploy and open the generated app URL.

`app.py` binds Uvicorn to `0.0.0.0` and reads the platform-provided `PORT`.
Do not hard-code a production port or place the access key in the repository.

## How the workflow works

`backend.py` maintains this state:

```text
topic
draft
feedback
decision
revision_count
```

The graph starts at `writer`, always moves to `reviewer`, and then branches:

- `PASS`: finish and return the current draft.
- `REVISE`: call `reviser`, increment `revision_count`, and review again.
- Revision limit reached: finish with the latest draft even if the last review
	requested another change.

The Writer is instructed to produce 120 to 160 words, one everyday analogy,
and one tiny example. The Reviewer checks beginner clarity, the analogy, the
example, and topic focus. Reviewer output is parsed and validated as:

```json
{"decision":"PASS|REVISE","feedback":"..."}
```

## Troubleshooting

### `MODEL_ACCESS_KEY is missing`

Check that `.env` is in the same directory as `backend.py`, that the variable
name is spelled exactly as shown, and that the process was restarted after
changing it. On App Platform, add it as an environment variable instead of a
local file.

### Inference requests time out or fail

Confirm the endpoint, model name, and DigitalOcean account permissions. The
client uses a 90-second request timeout and retries failed requests twice.

### The browser cannot connect

Confirm that the process is running, that you opened the correct port, and
that the port is not already in use. For hosted deployments, verify the run
command and that the service listens on `0.0.0.0`.

## Security notes

- Treat `MODEL_ACCESS_KEY` as a password.
- Rotate any key that has been exposed or committed.
- Keep credentials in `.env` locally or encrypted platform environment
	variables in production.
- The `/api/config` and workflow responses intentionally contain model and
	endpoint metadata but never the access key.
- This demo does not provide authentication or per-user rate limiting. Add
	those controls before exposing it to an untrusted public audience.

## License

This project is distributed under the Apache License 2.0. See [LICENSE](LICENSE)
for the complete text.