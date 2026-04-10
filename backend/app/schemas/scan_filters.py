from typing import Literal

from pydantic import BaseModel, Field


class NameRuleIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    action: Literal["include", "exclude"]
    type: Literal["glob", "substring", "regex"]
    pattern: str = Field(min_length=1, max_length=512)
    target: Literal["file", "folder"]
    enabled: bool = True


class ScanFiltersIn(BaseModel):
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    name_rules: list[NameRuleIn] = Field(default_factory=list)


class ScanFiltersOut(BaseModel):
    configured: bool
    filters: ScanFiltersIn
    fits_root: str


class TestPathIn(BaseModel):
    path: str


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
