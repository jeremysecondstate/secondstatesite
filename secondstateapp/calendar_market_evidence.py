"""Read cited resale venues from Calendar market-review sources."""

from urllib.parse import urlsplit


def resale_auction_houses(sources):
    houses = []
    for source in sources or ():
        if not isinstance(source, dict):
            continue
        label = source.get("label")
        if not isinstance(label, str) or not label.startswith("Resale auction house · "):
            continue
        fields = label.split(" · ")
        if len(fields) != 3:
            continue
        name, location = (field.strip() for field in fields[1:])
        places = location.split(",")
        if not name or len(places) < 2 or not all(place.strip() for place in places):
            continue
        url = source.get("url")
        if not isinstance(url, str):
            continue
        try:
            link = urlsplit(url)
            if link.scheme not in {"http", "https"} or not link.hostname or link.username is not None or link.password is not None:
                continue
        except ValueError:
            continue
        houses.append({"name": name, "location": location, "url": url})
    return houses
