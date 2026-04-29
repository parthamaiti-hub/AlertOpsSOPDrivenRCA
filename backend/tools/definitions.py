from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ToolParam:
    name: str
    description: str
    required: bool = True
    default: Optional[str] = None


@dataclass
class ToolDefinition:
    tool: str
    tool_version: str
    tool_tech: str  # "python_script" | "shell_script" | "mcp_client"
    description: str
    tool_params: list[ToolParam] = field(default_factory=list)
    source_code: str = ""
    source_file: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "tool_version": self.tool_version,
            "tool_tech": self.tool_tech,
            "description": self.description,
            "tool_params": [asdict(p) for p in self.tool_params],
            "source_code": self.source_code,
            "source_file": self.source_file,
        }
