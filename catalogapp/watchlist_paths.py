"""Remember portable HTML sources without copying machine-local browser paths."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping, MutableMapping


_HTML_SUFFIXES = {".html", ".htm"}


def resolve_saved_bookmark_path(
    saved: Mapping[str, object], path_key: str, project_root: str | Path,
) -> Path | None:
    """Prefer the saved local path, then an existing HTML file in this clone.

    The original path is retained when unavailable so callers can explain a
    disconnected source. Browser JSON/profile files never use the portable
    fallback, even if settings contain an old relative HTML value.
    """

    original = saved.get(path_key)
    path = Path(original) if isinstance(original, str) and original.strip() else None
    try:
        if path is not None and path.is_file():
            return path
        if path is not None and path.suffix.casefold() not in _HTML_SUFFIXES:
            return path
        relative = saved.get(f"{path_key}_relative")
        if not isinstance(relative, str) or not relative.strip():
            return path
        windows = PureWindowsPath(relative)
        posix = PurePosixPath(relative)
        if (windows.drive or windows.root or posix.is_absolute()
                or ".." in windows.parts or ".." in posix.parts):
            return path
        root = Path(project_root).resolve()
        candidate = (root / relative).resolve()
        if (candidate.is_relative_to(root) and candidate.suffix.casefold() in _HTML_SUFFIXES
                and candidate.is_file()):
            return candidate
    except (OSError, ValueError, RuntimeError):
        # Missing drives and invalid old paths do not prevent local startup.
        pass
    return path


def remember_bookmark_path(
    payload: MutableMapping[str, object], path_key: str, path: str | Path,
    project_root: str | Path,
) -> None:
    """Keep the legacy absolute setting and add only a repository HTML hint."""

    payload.pop(f"{path_key}_relative", None)
    if not str(path).strip():
        payload[path_key] = ""
        return
    current = Path(path).resolve()
    payload[path_key] = str(current)
    root = Path(project_root).resolve()
    if current.suffix.casefold() in _HTML_SUFFIXES and current.is_relative_to(root):
        payload[f"{path_key}_relative"] = current.relative_to(root).as_posix()
