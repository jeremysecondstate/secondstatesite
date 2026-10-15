"""Open a watched Invaluable lot in the user's regular installed Chrome.

Chrome chooses the window within the selected profile. This launcher cannot
select an exact tab and does not read browser pages or login sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


_INVALUABLE_HOSTS = {"invaluable.com", "www.invaluable.com"}
_CHROME_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
_PROFILE_DIRECTORY = re.compile(r"(?:Default|Profile [0-9]+)\Z")


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    is_last_used: bool = False


def chrome_profiles() -> list[ChromeProfile]:
    """List local Chrome profile labels without reading account/session data.

    Only profile.info_cache directory/name and profile.last_used metadata are
    used. A profile must be a safe existing child directory, so a stale choice
    cannot accidentally create a different browser profile when launched.
    """

    local_directory = os.environ.get("LOCALAPPDATA")
    if not local_directory:
        return []
    user_data = Path(local_directory) / "Google" / "Chrome" / "User Data"
    try:
        metadata = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
        profile_metadata = metadata.get("profile", {})
        information = profile_metadata.get("info_cache", {})
        last_used = profile_metadata.get("last_used")
        if not isinstance(information, dict):
            return []
        root = user_data.resolve()
        profiles = []
        for directory, details in information.items():
            if not isinstance(directory, str) or not _PROFILE_DIRECTORY.fullmatch(directory):
                continue
            candidate = user_data / directory
            # Resolve junctions/symlinks as well as rejecting path separators.
            if not candidate.is_dir() or candidate.resolve().parent != root:
                continue
            name = details.get("name") if isinstance(details, dict) else None
            if not isinstance(name, str) or not name.strip():
                name = directory
            name = " ".join(name.split())[:120]
            name = "".join(character for character in name if ord(character) >= 32 and ord(character) != 127)
            name = name or directory
            profiles.append(ChromeProfile(directory, name, directory == last_used))
        return sorted(profiles, key=lambda profile: (
            not profile.is_last_used, profile.name.casefold(), profile.directory,
        ))
    except (OSError, ValueError, AttributeError, RuntimeError):
        return []


def _validate_lot_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        path = unquote(parts.path)
        valid = (
            isinstance(url, str)
            and not any(character.isspace() or ord(character) < 32 for character in url)
            and "\\" not in url
            and parts.scheme == "https"
            and parts.hostname in _INVALUABLE_HOSTS
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
            and path.startswith("/auction-lot/")
            and bool(path.removeprefix("/auction-lot/").strip("/"))
            and not any(segment in {".", ".."} for segment in path.split("/"))
            and "\\" not in path
        )
    except (AttributeError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Choose an HTTPS Invaluable auction-lot link to open in Chrome.")


def _registry_chrome_paths() -> list[Path]:
    try:
        import winreg
    except ImportError:
        return []

    candidates = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, _CHROME_APP_PATH, 0, winreg.KEY_READ | view) as key:
                    value, _kind = winreg.QueryValueEx(key, "")
                if isinstance(value, str):
                    candidates.append(Path(os.path.expandvars(value.strip().strip('"'))))
            except OSError:
                continue
    return candidates


def _find_chrome() -> Path | None:
    candidates = _registry_chrome_paths()
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        directory = os.environ.get(variable)
        if directory:
            candidates.append(Path(directory) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for candidate in candidates:
        if candidate.is_absolute() and candidate.name.casefold() == "chrome.exe" and candidate.is_file():
            return candidate
    return None


def open_invaluable_in_chrome(url: str, profile_directory: str | None = None) -> bool:
    """Open one lot in regular Chrome; raise ValueError or RuntimeError on failure.

    A successful return means Chrome accepted the launch request, not that the
    page loaded or that the user is signed in. Chrome selects the window within
    the chosen profile; without a profile selection Chrome uses its default.
    """

    _validate_lot_url(url)
    if profile_directory is not None:
        if (
            not isinstance(profile_directory, str)
            or not _PROFILE_DIRECTORY.fullmatch(profile_directory)
            or profile_directory not in {profile.directory for profile in chrome_profiles()}
        ):
            raise ValueError("That Chrome profile is no longer available. Choose an existing profile and try again.")
    executable = _find_chrome()
    if executable is None:
        raise RuntimeError(
            "Chrome could not be found. Install Chrome or open Invaluable in your usual browser."
        )
    arguments = [str(executable)]
    if profile_directory is not None:
        arguments.append(f"--profile-directory={profile_directory}")
    arguments.extend(["--new-tab", url])
    try:
        subprocess.Popen(arguments)
    except OSError as exc:
        raise RuntimeError(
            "Chrome could not be opened. Open Chrome normally, then try again."
        ) from exc
    return True
