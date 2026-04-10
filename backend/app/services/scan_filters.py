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


@dataclass
class ScanFilterConfig:
    include_paths: list[Path]
    exclude_paths: list[Path]
    name_rules: list[NameRule]

    @classmethod
    def from_settings(cls, general: dict, fits_root: Path) -> "ScanFilterConfig":
        raw = (general or {}).get("scan_filters") or {}
        root = fits_root.resolve()

        def _validate(path_str: str) -> Path:
            p = Path(path_str).resolve()
            try:
                p.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    f"path {path_str} is outside configured data path {root}"
                ) from exc
            return p

        include_paths = [_validate(p) for p in raw.get("include_paths", [])]
        exclude_paths = [_validate(p) for p in raw.get("exclude_paths", [])]
        name_rules = [NameRule(**r) for r in raw.get("name_rules", [])]
        return cls(
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            name_rules=name_rules,
        )

    def roots(self, fits_root: Path) -> list[Path]:
        return list(self.include_paths) if self.include_paths else [fits_root]

    def should_walk_dir(self, dir_path: Path, fits_root: Path) -> bool:
        resolved = dir_path.resolve()
        for excluded in self.exclude_paths:
            try:
                resolved.relative_to(excluded)
                return False
            except ValueError:
                pass
        # Folder name-rules apply to the segment name itself
        segment = dir_path.name
        for rule in self.name_rules:
            if rule.target != "folder" or rule.action != "exclude":
                continue
            if rule.matches(segment):
                return False
        return True

    def should_include_file(self, file_path: Path, fits_root: Path) -> bool:
        # Path-based excludes
        resolved = file_path.resolve()
        for excluded in self.exclude_paths:
            try:
                resolved.relative_to(excluded)
                return False
            except ValueError:
                pass

        # Collect ancestor folder segments under fits_root
        root = fits_root.resolve()
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            return False
        segments = list(rel.parts[:-1])  # exclude filename
        filename = rel.parts[-1] if rel.parts else file_path.name

        # Exclude name-rules (file + folder)
        for rule in self.name_rules:
            if rule.action != "exclude":
                continue
            if rule.target == "file" and rule.matches(filename):
                return False
            if rule.target == "folder" and any(rule.matches(s) for s in segments):
                return False

        # Include-narrowing, per target type
        file_includes = [r for r in self.name_rules
                         if r.action == "include" and r.target == "file"]
        folder_includes = [r for r in self.name_rules
                           if r.action == "include" and r.target == "folder"]
        if file_includes and not any(r.matches(filename) for r in file_includes):
            return False
        if folder_includes and not any(
            r.matches(s) for s in segments for r in folder_includes
        ):
            return False
        return True
