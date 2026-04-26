import re
import unicodedata
from urllib.parse import quote, urlencode

from artpricelinkgen_v2.config import DEFAULT_CATEGORY_ID, DEFAULT_DATE_FROM, DEFAULT_SORT


class ArtpriceURLBuilder:
    @staticmethod
    def resolve_mode(exact_match: bool, all_terms: bool) -> str:
        if exact_match:
            return "exact"
        if all_terms:
            return "all_terms"
        return "plain"

    @staticmethod
    def clean_title_for_keyword(title: str) -> str:
        value = str(title or "").strip()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"\([^)]*\)", "", value)
        value = re.sub(r"\[[^\]]*\]", "", value)
        value = re.sub(r",?\s*(?:from|from the|from an?)\s+[^,;]+(?:series|suite|set|portfolio|album)?", "", value, flags=re.I)
        value = re.sub(r",?\s*(?:series|suite|set|portfolio|album)\s+[^,;]+$", "", value, flags=re.I)
        value = re.sub(r",?\s*(19|20)\d{2}$", "", value)
        value = re.sub(r"\s+", " ", value).strip(" ,;:-")
        return value

    @classmethod
    def build_keyword(cls, title: str, exact_match: bool, all_terms: bool) -> str:
        title = cls.clean_title_for_keyword(title)
        parts = re.findall(r"[A-Za-z0-9']+", title)
        phrase = " ".join(parts).strip()
        if not phrase:
            return title
        if exact_match:
            return phrase
        if all_terms:
            return "-".join(parts)
        return phrase

    @classmethod
    def build_url(cls, artist_id: str, title: str, exact_match: bool, all_terms: bool) -> str:
        params = {
            "dt_from": DEFAULT_DATE_FROM,
            "exact_match": "1" if exact_match else "0",
            "idartist": str(artist_id),
            "idcategory": DEFAULT_CATEGORY_ID,
            "keyword": cls.build_keyword(title, exact_match, all_terms),
            "p": "1",
            "sort": DEFAULT_SORT,
        }
        return "https://www.artprice.com/lots/search?" + urlencode(params)

    @classmethod
    def build_url_without_artist(cls, title: str, exact_match: bool, all_terms: bool) -> str:
        params = {
            "dt_from": DEFAULT_DATE_FROM,
            "exact_match": "1" if exact_match else "0",
            "idcategory": DEFAULT_CATEGORY_ID,
            "keyword": cls.build_keyword(title, exact_match, all_terms),
            "p": "1",
            "sort": DEFAULT_SORT,
        }
        return "https://www.artprice.com/lots/search?" + urlencode(params)

    @staticmethod
    def build_artist_search_url(artist_name: str) -> str:
        return f"https://www.artprice.com/artists/search?keyword={quote(artist_name)}"
