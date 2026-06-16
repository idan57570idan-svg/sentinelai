"""Base classes for all analysis rules."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..parser import ParsedFile


class Severity(Enum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1

    def label(self) -> str:
        return self.name

    def color(self) -> str:
        return {
            "CRITICAL": "bold red",
            "HIGH": "red",
            "MEDIUM": "yellow",
            "LOW": "cyan",
            "INFO": "dim",
        }[self.name]


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: Severity
    lines: List[int]
    description: str
    recommendation: str
    code_snippet: str = ""
    bnb_specific: bool = False
    category: str = "security"

    def line_str(self) -> str:
        if not self.lines:
            return "?"
        if len(self.lines) == 1:
            return str(self.lines[0])
        return f"{min(self.lines)}-{max(self.lines)}"


class RuleBase:
    id: str = ""
    title: str = ""
    severity: Severity = Severity.INFO
    category: str = "security"
    bnb_specific: bool = False

    def check(self, parsed: "ParsedFile") -> List[Finding]:
        raise NotImplementedError
