import re

_VERSION_RE = re.compile(r"^\d+\.\d+$")


def validate_version_format(v: str) -> bool:
    """Return True if v matches x.y format (non-negative integers only)."""
    return bool(_VERSION_RE.match(v))


def version_tuple(v: str) -> tuple[int, int]:
    """Parse 'x.y' into (x, y) for numeric comparison."""
    major, minor = v.split(".")
    return (int(major), int(minor))


def get_next_valid_versions(current: str) -> tuple[str, str]:
    """Return the only two valid next versions from current.

    From '1.2' returns ('1.3', '2.0').
    From '1.0' returns ('1.1', '2.0').
    """
    major, minor = version_tuple(current)
    return (f"{major}.{minor + 1}", f"{major + 1}.0")


def is_valid_progression(current: str, proposed: str) -> bool:
    """Return True only if proposed is exactly one valid step from current.

    Valid steps: minor+1 (same major) or major+1 with minor=0.
    Both values must already be valid x.y format.
    """
    if not validate_version_format(current) or not validate_version_format(proposed):
        return False
    minor_bump, major_bump = get_next_valid_versions(current)
    return proposed == minor_bump or proposed == major_bump
