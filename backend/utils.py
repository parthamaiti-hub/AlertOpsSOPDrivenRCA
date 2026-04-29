import re


def strip_rtf(text: str) -> str:
    """Convert RTF to plain text. If input is not RTF, return as-is."""
    if not text.strip().startswith("{\\rtf"):
        return text
    # Remove RTF groups like {\fonttbl ...}, {\colortbl ...}
    result = re.sub(r"\{\\(?:fonttbl|colortbl|stylesheet|info|\\*)[^}]*\}", "", text)
    # Remove RTF control words with optional numeric arg
    result = re.sub(r"\\[a-z]{1,32}-?\d*\s?", " ", result)
    # Remove remaining braces
    result = result.replace("{", "").replace("}", "")
    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()
    return result
