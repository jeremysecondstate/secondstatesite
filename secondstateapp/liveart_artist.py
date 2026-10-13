"""Known artist-name differences between Calendar sources and LiveArt."""

from catalogapp.artprice_artist_links import artist_identity_key


# LiveArt labels this artist Friedrich, while auction records commonly use his
# Friedensreich name. Keep aliases explicit so unrelated artists cannot match.
_LIVEART_NAMES = {
    artist_identity_key("Friedensreich Hundertwasser"): "Friedrich Hundertwasser",
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
