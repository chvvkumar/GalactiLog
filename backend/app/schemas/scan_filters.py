from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# Reject control characters and null bytes in user-entered strings.
_FORBIDDEN_CHARS = set("\x00\r\n")


def _no_control_chars(value: str, field_name: str) -> str:
    if any(c in _FORBIDDEN_CHARS for c in value):
        raise ValueError(f"{field_name} contains disallowed control characters")
    return value


class NameRuleIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    action: Literal["include", "exclude"]
    type: Literal["glob", "substring", "regex"]
    pattern: str = Field(min_length=1, max_length=512)
    target: Literal["file", "folder"]
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def _pattern_clean(cls, v: str) -> str:
        return _no_control_chars(v.strip(), "pattern")

    @field_validator("id")
    @classmethod
    def _id_clean(cls, v: str) -> str:
        return _no_control_chars(v, "id")


class ScanFiltersIn(BaseModel):
    include_paths: list[str] = Field(default_factory=list, max_length=256)
    exclude_paths: list[str] = Field(default_factory=list, max_length=256)
    name_rules: list[NameRuleIn] = Field(default_factory=list, max_length=512)

    @field_validator("include_paths", "exclude_paths")
    @classmethod
    def _paths_clean(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for p in v:
            stripped = p.strip()
            if not stripped:
                raise ValueError("path entries must be non-empty")
            cleaned.append(_no_control_chars(stripped, "path"))
        return cleaned

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> "ScanFiltersIn":
        ids = [r.id for r in self.name_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("name_rules contain duplicate ids")
        return self


class ScanFiltersOut(BaseModel):
    configured: bool
    filters: ScanFiltersIn
    fits_root: str


class TestPathIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    target_kind: Literal["auto", "file", "folder"] = "auto"

    @field_validator("path")
    @classmethod
    def _path_clean(cls, v: str) -> str:
        return _no_control_chars(v.strip(), "path")


class TestPathOut(BaseModel):
    verdict: Literal[
        "included", "excluded_by_path", "excluded_by_rule", "excluded_by_missing_include"
    ]
    matched_rule_ids: list[str]


class BrowseEntry(BaseModel):
    name: str
    path: str
    has_children: bool


class ApplyNowOut(BaseModel):
    dry_run: bool
    matched: int
