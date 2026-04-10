from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Action = Literal["include", "exclude"]
RuleType = Literal["glob", "substring", "regex"]
Target = Literal["file", "folder"]


@dataclass
class NameRule:
    id: str
    action: Action
    type: RuleType
    pattern: str
    target: Target
    enabled: bool = True
    _regex: re.Pattern | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.action not in ("include", "exclude"):
            raise ValueError(f"invalid action: {self.action}")
        if self.type not in ("glob", "substring", "regex"):
            raise ValueError(f"invalid type: {self.type}")
        if self.target not in ("file", "folder"):
            raise ValueError(f"invalid target: {self.target}")
        if not self.pattern:
            raise ValueError("pattern must not be empty")
        if self.type == "regex":
            try:
                self._regex = re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc

    def matches(self, value: str) -> bool:
        if not self.enabled:
            return False
        if self.type == "glob":
            return fnmatch.fnmatchcase(value, self.pattern)
        if self.type == "substring":
            return self.pattern.casefold() in value.casefold()
        if self.type == "regex":
            assert self._regex is not None
            return bool(self._regex.search(value))
        return False
