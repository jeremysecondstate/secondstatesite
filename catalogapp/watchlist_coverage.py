"""Persistent evidence about each watched catalog, separate from its lots."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchCoverage:
    artist: str
    source: str
    watch_url: str
    state: str = "pending"
    lot_count: int = 0
    checked_at: str = ""
    detail: str = ""
    covered_until: str = ""

    @property
    def needs_recovery(self) -> bool:
        return self.state not in {"verified", "empty"}
