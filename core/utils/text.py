import re


def slugify(text: str) -> str:
    """Convert a string to a lowercase slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def truncate(text: str, max_len: int = 100, suffix: str = "…") -> str:
    """Truncate text to max_len characters, appending suffix if truncated."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def sanitize_callback_part(value: str) -> str:
    """Remove characters that could break callback_data parsing."""
    return re.sub(r"[:\s]", "_", value)
