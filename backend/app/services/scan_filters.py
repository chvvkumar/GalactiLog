from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Action = Literal["include", "exclude"]
RuleType = Literal["glob", "substring", "regex"]
Target = Literal["file", "folder"]
Verdict = Literal[
    "included", "excluded_by_path", "excluded_by_rule", "excluded_by_missing_include",
]


@dataclass
class TestResult:
    verdict: Verdict
    matched_rule_ids: list[str]


# Prevent pytest from collecting TestResult as a test class
TestResult.__test__ = False


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

        # Folder exclude name-rules: check every segment between fits_root
        # and dir_path (inclusive of dir_path itself). This lets the walker
        # prune as early as possible even when starting from an include_path
        # that sits deep in the tree.
        root = fits_root.resolve()
        try:
            rel = resolved.relative_to(root)
            segments = list(rel.parts)
        except ValueError:
            segments = [dir_path.name]

        for rule in self.name_rules:
            if rule.target != "folder" or rule.action != "exclude":
                continue
            if any(rule.matches(s) for s in segments):
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

        # Include-paths narrowing: when set, the file must live under one
        # of them. This matches the scan walker, which uses include_paths
        # as effective roots.
        if self.include_paths:
            under_include = False
            for inc in self.include_paths:
                try:
                    resolved.relative_to(inc)
                    under_include = True
                    break
                except ValueError:
                    pass
            if not under_include:
                return False

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

    def test_path(
        self,
        path: Path,
        fits_root: Path,
        target_kind: str = "auto",
    ) -> TestResult:
        """Explain how the current config would treat `path`.

        `target_kind` is "file", "folder", or "auto". In auto mode the
        on-disk type is used when the path exists; otherwise a trailing
        dot-extension hints at a file, else we treat it as a folder.
        """
        # Resolve to normalize `..`, drive letters, and symlinks so the
        # verdict matches what should_include_file would decide. Resolve
        # does not require the path to exist in modern Python.
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            resolved = path

        root = fits_root.resolve()

        # Decide whether to treat this as a file or a folder.
        if target_kind == "auto":
            if resolved.exists():
                kind = "folder" if resolved.is_dir() else "file"
            else:
                kind = "file" if resolved.suffix else "folder"
        else:
            kind = target_kind

        for excluded in self.exclude_paths:
            try:
                resolved.relative_to(excluded)
                return TestResult("excluded_by_path", [])
            except ValueError:
                pass

        # Include-paths narrowing: when set, the path must live under one
        # of them, otherwise the walker would never reach it.
        if self.include_paths:
            under_include = False
            for inc in self.include_paths:
                try:
                    resolved.relative_to(inc)
                    under_include = True
                    break
                except ValueError:
                    pass
            if not under_include:
                return TestResult("excluded_by_path", [])

        try:
            rel = resolved.relative_to(root)
        except ValueError:
            try:
                rel = resolved.relative_to(fits_root)
            except ValueError:
                return TestResult("excluded_by_path", [])

        parts = rel.parts
        if kind == "folder":
            # For a folder path the trailing component is a folder too,
            # so every segment is a folder to evaluate. No filename.
            segments = list(parts)
            filename = ""
        else:
            segments = list(parts[:-1])
            filename = parts[-1] if parts else ""

        matched: list[str] = []
        for rule in self.name_rules:
            if rule.action != "exclude":
                continue
            if rule.target == "file" and kind == "file" and rule.matches(filename):
                matched.append(rule.id)
                return TestResult("excluded_by_rule", matched)
            if rule.target == "folder" and any(rule.matches(s) for s in segments):
                matched.append(rule.id)
                return TestResult("excluded_by_rule", matched)

        file_includes = [r for r in self.name_rules
                         if r.action == "include" and r.target == "file"]
        folder_includes = [r for r in self.name_rules
                           if r.action == "include" and r.target == "folder"]
        file_hits = [r.id for r in file_includes if kind == "file" and r.matches(filename)]
        folder_hits = [r.id for r in folder_includes
                       if any(r.matches(s) for s in segments)]

        # File-include rules only narrow file tests; folder tests ignore them.
        if kind == "file" and file_includes and not file_hits:
            return TestResult("excluded_by_missing_include", [])
        if folder_includes and segments and not folder_hits:
            return TestResult("excluded_by_missing_include", [])

        return TestResult("included", file_hits + folder_hits)
