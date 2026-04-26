from dataclasses import dataclass


@dataclass
class ExtractedListing:
    artist: str
    title: str
    source_url: str = ""
    raw_heading: str = ""
