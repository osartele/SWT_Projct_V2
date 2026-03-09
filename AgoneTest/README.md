# AgoneTest Agentic Pipeline

This directory now contains a config-driven pipeline for AST-guided test synchronization with a multi-agent GeminiCLI society.

## Commands

- `python agone_test.py prepare`
- `python agone_test.py map`
- `python agone_test.py evolve`
- `python agone_test.py sync`
- `python agone_test.py summarize`

## Workflow

1. `prepare` reads the flat `../classes2test/*.json` dataset and joins it with local repos in `../repos`.
2. `map` evaluates deterministic focal-method mapping against the labeled `focal_method`.
3. `evolve` creates synthetic focal-method behavior changes.
4. `sync` runs the GeminiCLI Generator/Critic/Analyst loop on isolated workspaces and records telemetry.
5. `summarize` emits RQ-oriented summaries for mapping, synchronization quality, intent preservation, and overhead.

## Notes

- The framework expects Gemini CLI to be installed and available as `gemini` unless overridden in `run_settings.yaml`.
- The old prompt-only execution path is retired; legacy Maven/Gradle helpers are still reused for build metadata, EvoSuite, and coverage collection.


