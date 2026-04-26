import re
import unicodedata

import pandas as pd


class ArtistIdLookup:
    def __init__(self):
        self.df = None
        self.path = None
        self.normalized_map = {}

    @staticmethod
    def strip_parenthetical(value: str) -> str:
        return re.sub(r"\([^)]*\)", "", str(value or "")).strip()

    @staticmethod
    def reorder_name(value: str) -> str:
        value = str(value or "").strip()
        if "," in value and value.count(",") == 1:
            last, first = [part.strip() for part in value.split(",", 1)]
            if first and last:
                value = f"{first} {last}"
        return value

    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = cls.reorder_name(cls.strip_parenthetical(value))
        value = re.sub(
            r"\b(?:after|attributed to|attr\.?|school of|manner of|circle of|follower of)\b",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(r"[^A-Za-z0-9' .,\-]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" ,;:-")
        return value

    @staticmethod
    def normalize_name(value: str) -> str:
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.lower().replace("&", " and ")
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def load_file(self, path: str):
        if not path:
            raise ValueError("No artist ID file was provided.")
        if path.lower().endswith(".csv"):
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)

        df.columns = [str(c).strip() for c in df.columns]
        if not {"Artist", "ID"}.issubset(df.columns):
            raise ValueError("Artist ID file must contain 'Artist' and 'ID' columns.")

        df = df[["Artist", "ID"]].dropna(subset=["Artist", "ID"]).copy()
        df["Artist"] = df["Artist"].map(self.clean_display_name)
        df["ID"] = df["ID"].astype(str).str.extract(r"(\d+)", expand=False).fillna("")
        df = df[(df["Artist"] != "") & (df["ID"] != "")].drop_duplicates(subset=["Artist"], keep="first")

        self.df = df
        self.path = path
        self.normalized_map = {}
        for _, row in df.iterrows():
            norm = self.normalize_name(row["Artist"])
            if norm and norm not in self.normalized_map:
                self.normalized_map[norm] = row["ID"]

    def lookup(self, artist_name: str):
        cleaned = self.clean_display_name(artist_name)
        norm = self.normalize_name(cleaned)
        if not norm:
            return None
        if norm in self.normalized_map:
            return self.normalized_map[norm]
        norm_words = set(norm.split())
        for known_norm, artist_id in self.normalized_map.items():
            known_words = set(known_norm.split())
            if norm_words and norm_words == known_words:
                return artist_id
        for known_norm, artist_id in self.normalized_map.items():
            if norm in known_norm or known_norm in norm:
                return artist_id
        return None
