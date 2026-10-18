"""Build optional Calendar research searches using the desktop link generator."""

import re

from artpricelinkgen.url_builder import ArtpriceURLBuilder
from catalogapp.artprice_artist_links import _valid_artprice_artist_url


def artprice_research_links(artist_name: str, title: str, artist_url: str = "") -> dict[str, str]:
    """Return search suggestions, never a guessed artist ID or saved lot URL.

    A trusted artist bookmark supplies the numeric ID needed to scope a title
    search. Without one, offer both an artist search and the generator's title
    search across artists. Neither is a verified Artprice lot match.
    """

    artist_name = str(artist_name or "").strip()
    title = str(title or "").strip()
    parsed_artist = _valid_artprice_artist_url(artist_url)
    links = {
        "artist_artprice_search_url": ArtpriceURLBuilder.build_artist_search_url(artist_name) if artist_name else "",
        "artprice_search_url": "",
        "artprice_search_scope": "",
    }
    # Imported catalogs may supply only a lot number when no artwork title is
    # available. Such labels do not identify a work in another auction.
    if re.fullmatch(r"lot\s+#?\s*\d+[a-z]?", title, flags=re.IGNORECASE):
        return links
    # Avoid offering an unfiltered search when the title contains only metadata.
    if not ArtpriceURLBuilder.build_keyword(title, exact_match=False, all_terms=True):
        return links
    if parsed_artist:
        links["artprice_search_url"] = ArtpriceURLBuilder.build_url(
            parsed_artist[0], title, exact_match=False, all_terms=True,
        )
        links["artprice_search_scope"] = "artist"
    else:
        links["artprice_search_url"] = ArtpriceURLBuilder.build_url_without_artist(
            title, exact_match=False, all_terms=True,
        )
        links["artprice_search_scope"] = "title"
    return links
