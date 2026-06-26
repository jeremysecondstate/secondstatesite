import tkinter as tk

import requests

try:
    from catalogapp.catalogapp_inv_ui import ArtCatalogApp, BASE_URL, api_headers
except ImportError:
    from catalogapp_inv_ui import ArtCatalogApp, BASE_URL, api_headers


def _read_error(response):
    try:
        data = response.json()
    except ValueError:
        data = {}
    detail = data.get("error") or data.get("message") or response.text.strip()
    if detail:
        return f"{response.status_code} {response.reason} from {response.url}\n\n{detail}"
    return f"{response.status_code} {response.reason} from {response.url}"


def _generate_description(self, payload):
    response = requests.post(
        f"{BASE_URL}/artworks/generate_description/",
        json=payload,
        headers=api_headers({"Content-Type": "application/json"}),
        timeout=70,
    )
    if response.status_code >= 400:
        raise RuntimeError(_read_error(response))
    description = response.json().get("description", "").strip()
    if not description:
        raise ValueError("Website returned an empty generated description.")
    return description


ArtCatalogApp._generate_description = _generate_description


def main():
    root = tk.Tk()
    ArtCatalogApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
