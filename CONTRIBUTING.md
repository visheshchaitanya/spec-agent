# Contributing

## Setup

```bash
git clone https://github.com/visheshchaitanya/spec-agent.git
cd spec-agent
pip install -e ".[dev]"
```

No external services required for tests — all tests use temporary directories and do not call the Anthropic API.

## Running Tests

```bash
# All tests
pytest

# Single file
pytest tests/test_agent.py

# With coverage
pytest --cov=spec_agent --cov-report=term-missing
```

Coverage target: 80%+. New behavior must have tests.

## Project Structure

```
spec_agent/        # package source
tests/             # pytest test files
docs/              # documentation
config.yaml        # local dev config (gitignored)
```

Keep files under 500 lines. See `docs/Architecture.md` for a module map.

## Making Changes

- Branch from `main`, name it `feat/...`, `fix/...`, or `chore/...`
- Follow conventional commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`
- Run `pytest` before opening a PR; CI will also run it
- The `ANTHROPIC_API_KEY` env var is only needed for manual end-to-end testing, not for the test suite

## Adding a New Agent Tool

1. Add the tool function in `spec_agent/tools/`
2. Add its schema to `TOOL_DEFINITIONS` in `agent.py`
3. Add a dispatch branch in `_dispatch_tool()` in `agent.py`
4. Add tests in `tests/`

## Pull Requests

- Keep PRs focused — one logical change per PR
- Include a clear description of what changed and why
- Reference any related issues
