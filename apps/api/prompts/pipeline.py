PROMPT_VERSION = "1.0.0"

NORMALIZE = """\
You are a task processor for a personal productivity system.

Your job:
1. Translate everything to English (if not already in English)
2. Rewrite the task title into a clean, actionable English title (5-10 words, start with a verb)
3. Detect language, multi-item, entities

Rules:
- Do NOT invent information not present in the input
- Preserve original meaning exactly
- If the title is already good English, still normalize it (remove noise, fix capitalization)
- Multi-item: true only if the input clearly contains 2+ separate tasks

Return ONLY valid JSON:
{{
  "intent_summary": "short 1-sentence meaning in English",
  "rewritten_title": "Clean actionable English title (5-10 words, starts with verb)",
  "is_multi_item": true|false,
  "entities": ["names", "systems", "objects mentioned"],
  "language": "ru|en|mixed"
}}

Task title: {raw_title}
Task description: {raw_description}"""

CLASSIFY_ROUTE_TITLE = """\
You are an AI Chief of Staff.

Your job is to classify an inbox item, assign it to a project, generate a clean title, \
and define the next action.

Projects:
{project_context}

Task types:
- task: actionable work
- waiting: waiting for someone/something
- commitment: obligation with expectation
- idea: not actionable yet
- reference: informational only

Title rules:
- 5-10 words, max 12 words
- Must be actionable, start with a verb
- In English, no noise or filler

Next action rules:
- Must be executable, start with a verb
- Must be specific, max 12 words

Classification rules:
- Choose EXACTLY ONE project from the list above
- Use meaning, descriptions, and aliases — not just keyword matching
- Prefer specific projects over generic ones
- If unsure, choose best guess and set confidence to "low"

Return ONLY valid JSON:
{{
  "type": "task|waiting|commitment|idea|reference",
  "project": "exact_project_name",
  "confidence": "high|medium|low",
  "reasoning": "1-sentence explanation",
  "title": "Clean actionable title",
  "next_action": "First concrete physical action",
  "due_hint": "ISO date or natural language hint or null"
}}

Raw input: {raw_text}
Normalized intent: {intent_summary}"""

DESCRIPTION = """\
You are restructuring a task description for a busy professional.

Your job:
1. Translate to English if not already in English
2. Restructure into clear, concise bullet points or short sentences
3. Remove noise, filler, and metadata (ignore any lines that look like system tags)
4. Preserve all relevant context, details, and action items from the original

Rules:
- Output must be in English
- 1-5 bullet points or 1-3 sentences — whichever fits better
- Do NOT repeat the title
- If description is empty or has no useful content, output an empty string ""

Return ONLY valid JSON:
{{
  "description": "restructured description in English, or empty string if nothing useful"
}}

Task title: {title}
Original description: {raw_description}"""

STEPS = """\
You are breaking down a task into concrete steps.

Rules:
- Generate 3-5 steps
- Each step must be concrete and actionable
- No vague steps like "think about it" or "plan"
- Steps must be ordered logically

Return ONLY valid JSON:
{{
  "steps": [
    "step 1",
    "step 2",
    "step 3"
  ]
}}

Title: {title}
Next action: {next_action}"""

DISAMBIGUATE = """\
You are handling an ambiguous task that could not be classified with high confidence.

Generate 2-3 possible interpretations of the input.

For each interpretation, provide:
- The most likely task type
- A clean title
- A brief reason why this interpretation fits

Return ONLY valid JSON:
{{
  "options": [
    {{
      "type": "task|waiting|commitment|idea|reference",
      "title": "Interpretation title",
      "reason": "Why this interpretation fits"
    }}
  ]
}}

Raw input: {raw_text}
Normalized intent: {intent_summary}"""
