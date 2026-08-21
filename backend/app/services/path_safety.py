"""Filesystem path confinement.

Single choke point for turning a user-supplied or database-stored path
into one that is guaranteed to live under an allowed root.  Callers that
build a filesystem path from anything they did not construct themselves
route it through here instead of hand-rolling a ``relative_to`` check.
"""

import os
from pathlib import Path, PurePosixPath


def resolve_under(base: Path | str, candidate: Path | str) -> Path:
    """Resolve candidate and require it to be located under base.

    Returns the fully resolved path. Raises ValueError if the resolved
    path escapes base.
    """
    base_resolved = Path(base).resolve()
    candidate_resolved = Path(candidate).resolve()
    if not candidate_resolved.is_relative_to(base_resolved):
        raise ValueError("path escapes allowed root")
    return candidate_resolved


def resolve_relative_under(base: Path | str, relative: str) -> Path:
    """Join a user-supplied *relative* path onto base and confine it.

    Rejects empty, absolute and ``..``-bearing input before touching the
    filesystem, then defers to :func:`resolve_under` so that a symlink
    inside base cannot smuggle the result back out either.  Raises
    ValueError on any of those.
    """
    if not relative:
        raise ValueError("empty path")
    # os.path.isabs also catches Windows drive-qualified paths ("C:/x"),
    # which PurePosixPath does not consider absolute.
    rel = PurePosixPath(relative)
    if rel.is_absolute() or os.path.isabs(relative) or ".." in rel.parts:
        raise ValueError("path escapes allowed root")
    return resolve_under(base, Path(base) / rel)


if __name__ == "__main__":
    _base = Path(__file__).parent
    assert resolve_under(_base, _base / "path_safety.py").name == "path_safety.py"
    assert resolve_relative_under(_base, "path_safety.py").name == "path_safety.py"
    for _bad in ("../secrets", "/etc/passwd", "a/../../b", "", "C:/Windows"):
        try:
            resolve_relative_under(_base, _bad)
        except ValueError:
            continue
        raise AssertionError(f"not rejected: {_bad!r}")
    try:
        resolve_under(_base, _base.parent)
    except ValueError:
        pass
    else:
        raise AssertionError("parent not rejected")
    print("path_safety self-check ok")
