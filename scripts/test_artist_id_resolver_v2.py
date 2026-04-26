from artpricelinkgen_v2.artist_id_resolver import ArtpriceArtistIdResolver


def main():
    artist = input("Artist name to resolve: ").strip()
    if not artist:
        artist = "Rembrandt van Rijn"

    resolver = ArtpriceArtistIdResolver()
    candidate = resolver.resolve(artist)

    if not candidate:
        print(f"No high-confidence Artprice ID found for {artist!r}.")
        return

    print(f"Artist: {artist}")
    print(f"Artprice ID: {candidate.artist_id}")
    print(f"Confidence: {candidate.confidence}")
    print(f"Score: {candidate.score:.2f}")
    print(f"URL: {candidate.url}")


if __name__ == "__main__":
    main()
