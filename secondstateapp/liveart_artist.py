"""Known artist-name differences between Calendar sources and LiveArt."""

from catalogapp.artprice_artist_links import artist_identity_key


# Keep verified aliases explicit so unrelated artists cannot match.
_LIVEART_NAMES = {
    # LiveArt labels this artist Friedrich; auction records use Friedensreich.
    artist_identity_key("Friedensreich Hundertwasser"): "Friedrich Hundertwasser",
    # Calendar imports use Neimann. Verified against LiveArt artist 25667
    # (c9GBTz/leroy-neiman, 1921-2012) and the imported lot title, 2026-10-15.
    artist_identity_key("Leroy Neimann"): "Leroy Neiman",
    # Calendar/Artprice use his middle name. Verified against LiveArt artist
    # 11328 (8Bwp9T/romare-bearden, 1911-1988) and lot 2086, 2026-10-15.
    artist_identity_key("Romare Howard Bearden"): "Romare Bearden",
}


def liveart_artist_search_name(name: str) -> str:
    """Use LiveArt's documented name for an exact known alias, if available."""

    return _LIVEART_NAMES.get(artist_identity_key(name), name)


def liveart_artist_names_match(left: str, right: str) -> bool:
    """Match normalized names and only explicitly documented aliases."""

    if not left or not right:
        return False
    return artist_identity_key(liveart_artist_search_name(left)) == artist_identity_key(
        liveart_artist_search_name(right)
    )
