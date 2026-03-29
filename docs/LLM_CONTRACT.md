# LLM Contract

Pipeline:
1. normalize
2. classify + route
3. title
4. next_action

Rules:
- strict JSON
- retry on failure
- fallback heuristics
- short outputs

Title:
- <= 12 words
- actionable
- English

Next action:
- executable
- specific

Low confidence must be explicit.
