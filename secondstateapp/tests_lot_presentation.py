"""Presentation regressions using observed catalog text and curated artist names."""

from unittest import TestCase

from .lot_presentation import artist_display_name, artist_sort_key, clean_display_text


class LotTextPresentationTests(TestCase):
    def test_observed_title_mojibake_repairs_before_whitespace_normalization(self):
        examples = {
            "Â§ David Hockney OM, CH, RA (1937–2026), FÃ©licitÃ© Sleeping, with Parrot":
                "§ David Hockney OM, CH, RA (1937–2026), Félicité Sleeping, with Parrot",
            "Le Roi David Ã\u00a0 la harpe": "Le Roi David à la harpe",
            "Â¿No hay quien nos desate?": "¿No hay quien nos desate?",
            'ANTONI TÃ\u0080PIES "3 i 4"': 'ANTONI TÀPIES "3 i 4"',
            "AntichitÃ\u00a0 d'Albano": "Antichità d'Albano",
            "Marthaâ\u0080\u0099s Vineyard": "Martha’s Vineyard",
            "Roy Lichtenstein Â© On 1st Inc 1969": "Roy Lichtenstein © On 1st Inc 1969",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_display_text(raw), expected)
                self.assertEqual(clean_display_text(expected), expected)

    def test_cp1252_and_double_encoding_can_coexist_with_correct_unicode(self):
        original = "Félicité — Martha’s ©"
        corrupted = original.encode("utf-8").decode("cp1252")
        twice = corrupted.encode("utf-8").decode("latin1")
        self.assertEqual(clean_display_text("Käthe Kollwitz: " + corrupted), "Käthe Kollwitz: " + original)
        self.assertEqual(clean_display_text(twice), original)

    def test_real_accents_symbols_and_irrecoverable_text_are_not_guessed(self):
        for value in ("L'Âge d'Or", "François — São Paulo", "München © 1969", "£100 × 2 = £200",
                      "Ângulo", "After the Party", "He Enquired After the Quality", "AntichitÃ d'Albano",
                      "👩‍🎨", "中文作品", "¼ inch"):
            with self.subTest(value=value):
                self.assertEqual(clean_display_text(value), value)

    def test_entity_cleanup_removes_artifacts_without_treating_text_as_html(self):
        self.assertEqual(clean_display_text("\ufeff  Martha&amp;#8217;s\u00a0&amp; Co.\nPrint\x00\u200b \ufffd "), "Martha’s & Co. Print")
        self.assertEqual(clean_display_text("Fran&ccedil;ois &amp; Ren&eacute;"), "François & René")
        self.assertEqual(clean_display_text("&lt;em&gt;Title&lt;/em&gt;"), "<em>Title</em>")
        self.assertEqual(clean_display_text("&unknown; and &notit;"), "&unknown; and &notit;")
        self.assertEqual(clean_display_text(None), "")
        self.assertEqual(clean_display_text(0), "0")

    def test_only_opted_in_leading_lot_markers_are_removed(self):
        cases = {
            "§ Victor Vasarely (1906–1997), Sir-Ris Negatif, 1974":
                "Victor Vasarely (1906–1997), Sir-Ris Negatif, 1974",
            "§ David Hockney OM, CH, RA (1937–2026)": "David Hockney OM, CH, RA (1937–2026)",
            "Â§ Christo & Jeanne Claude, Wrapped Reichstag; Berlin and The wall":
                "Christo & Jeanne Claude, Wrapped Reichstag; Berlin and The wall",
            " ** § * After Alexander Calder": "After Alexander Calder",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_display_text(raw, strip_lot_markers=True), expected)
                self.assertIn("§", clean_display_text(raw))
        for text in ("Chapter § 4", "A * B", "© Artist", "¿No hay quien nos desate?", "† Memorial"):
            self.assertEqual(clean_display_text(text, strip_lot_markers=True), text)


class ArtistPresentationTests(TestCase):
    def test_curated_names_preserve_accents_and_compound_surnames(self):
        examples = {
            "Willem De Kooning": "de Kooning, Willem", "Niki de Saint Phalle": "de Saint-Phalle, Niki",
            "Francisco de Goya": "Goya, Francisco de", "Henri de Toulouse-Lautrec": "Toulouse-Lautrec, Henri de",
            "Giovanni Battista Piranesi": "Piranesi, Giovanni Battista", "Thomas Hart Benton": "Benton, Thomas Hart",
            "Wou-Ki Zao": "Zao, Wou-Ki", "Zao Wou-Ki": "Zao, Wou-Ki", "Chu Teh-Chun": "Chu, Teh-Chun",
            "Ai Weiwei": "Ai, Weiwei", "Jean (Hans) Arp": "Arp, Jean (Hans)",
            "Jean-Michel Basquiat": "Basquiat, Jean-Michel", "Georgia O’Keeffe": "O'Keeffe, Georgia",
            "Joan Miro": "Miró, Joan", "Fernand Léger": "Léger, Fernand", "Käthe Kollwitz": "Kollwitz, Käthe",
            "Francisco Zúñiga": "Zúñiga, Francisco", "ANTONI TÃ\u0080PIES": "Tàpies, Antoni",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
                self.assertEqual(artist_display_name(expected), expected)

    def test_verified_provider_aliases_and_year_disambiguators(self):
        examples = {
            "Alexander (1898) Calder": "Calder, Alexander", "Henry (1898) Moore": "Moore, Henry",
            "Albrecht (1471) Dürer": "Dürer, Albrecht", "John (1871) Sloan": "Sloan, John",
            "Leroy Neimann": "Neiman, LeRoy", "Romare Bearden": "Bearden, Romare Howard",
            "John W. Nieto": "Nieto, John", "Will Barnett": "Barnet, Will",
            "Auguste Renoir": "Renoir, Pierre-Auguste",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
        self.assertEqual(artist_display_name("Alexander (1900) Calder"), "Alexander (1900) Calder")

    def test_existing_whole_sale_calendar_artists_have_explicit_surname_labels(self):
        examples = {
            "Alice Neel": "Neel, Alice", "Richard Serra": "Serra, Richard", "Sol LeWitt": "LeWitt, Sol",
            "James Abbott McNeill Whistler": "Whistler, James Abbott McNeill",
            "Maurits Cornelis Escher": "Escher, Maurits Cornelis", "M.C. Escher": "Escher, Maurits Cornelis",
            "Aaron Garber-Maikovska": "Garber-Maikovska, Aaron", "Hank Willis Thomas": "Thomas, Hank Willis",
            "Jeffrey Gibson (Choctaw/Cherokee)": "Gibson, Jeffrey (Choctaw/Cherokee)",
            "T.C. Cannon": "Cannon, T.C.", "William N. Copley": "Copley, William N.",
            "Walasse Ting": "Ting, Walasse", "Alessandra Sanguinetti": "Sanguinetti, Alessandra",
            "Alain Ramié": "Ramié, Alain", "Sarah Sze": "Sze, Sarah",
            "Helen Frankenthaler": "Frankenthaler, Helen", "Essie Bendolph Pettway": "Pettway, Essie Bendolph",
            "Sho Shibuya": "Shibuya, Sho", "Rembrandt van Rijn": "Rijn, Rembrandt van",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
                self.assertEqual(artist_display_name(expected), expected)
                self.assertEqual(artist_sort_key(raw), artist_sort_key(expected))

    def test_attribution_is_retained_and_sorting_uses_the_artist(self):
        examples = {
            "After Pablo Picasso": "After Picasso, Pablo",
            "ATTRIBUTED TO GEORGES BRAQUE": "ATTRIBUTED TO Braque, Georges",
            "Albrecht Dürer (attributed to)": "Dürer, Albrecht (attributed to)",
            "Pablo Picasso, after": "Picasso, Pablo, after",
            "Circle of Jean-Michel Basquiat": "Circle of Basquiat, Jean-Michel",
            "School of Unknown Artist": "School of Unknown Artist",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
                self.assertEqual(artist_display_name(expected), expected)
        self.assertEqual(artist_sort_key("After Pablo Picasso"), artist_sort_key("Pablo Picasso"))
        self.assertEqual(artist_sort_key("Albrecht Dürer (attributed to)"), "durer, albrecht")

    def test_mononyms_stage_names_and_collaborations_are_not_mechanically_inverted(self):
        for raw, expected in (("BANKSY", "Banksy"), ("Arman", "Arman"), ("Christo", "Christo"),
                              ("Rembrandt", "Rembrandt"), ("KAWS", "KAWS"), ("Mr Brainwash", "Mr. Brainwash"),
                              ("CHARLY ROCKS", "CHARLY ROCKS")):
            self.assertEqual(artist_display_name(raw), expected)
        for value in ("Gilbert & George", "Christo and Jeanne-Claude", "Bernd and Hilla Becher",
                      "Katherine Bernhardt and Jonathan Edelhuber", "Unknown Multi Token Artist",
                      "Jane O’Neill", "Doe, Jane", "Jane Doe Jr.", "Estate of Pablo Picasso",
                      "El Anatsui", "Le Corbusier", "Various Artists", "Various Artists (20th/21st Century)"):
            with self.subTest(value=value):
                self.assertEqual(artist_display_name(value), value)

    def test_generational_suffixes_remain_suffixes_and_formatting_is_idempotent(self):
        for raw, expected in (("Alexander Calder Jr.", "Calder, Alexander Jr."),
                              ("Alexander Calder, Jr.", "Calder, Alexander, Jr."),
                              ("Alexander Calder III", "Calder, Alexander III")):
            self.assertEqual(artist_display_name(raw), expected)
            self.assertEqual(artist_display_name(expected), expected)
        self.assertEqual(artist_display_name("Doe, Jane, Jr."), "Doe, Jane, Jr.")

    def test_surname_order_is_scalar_stable_and_does_not_sort_all_name_tokens(self):
        values = ["Andy Warhol", "After Pablo Picasso", "Josef Albers", "Giovanni Battista Piranesi", "Salvador Dalí"]
        self.assertEqual(sorted(values, key=artist_sort_key),
                         ["Josef Albers", "Salvador Dalí", "After Pablo Picasso", "Giovanni Battista Piranesi", "Andy Warhol"])
        self.assertEqual(artist_sort_key("Giovanni Battista Piranesi"), "piranesi, giovanni battista")
        self.assertEqual(artist_sort_key("Salvador Dalí"), "dali, salvador")
        self.assertEqual(artist_display_name("Salvador Dalí"), "Dalí, Salvador")
        for value in values:
            self.assertIsInstance(artist_sort_key(value), str)
            self.assertEqual(artist_sort_key(artist_display_name(value)), artist_sort_key(value))

    def test_helpers_return_new_text_without_mutating_source_data(self):
        source = {"artist": "After Pablo Picasso", "title": "Â§ FÃ©licitÃ©"}
        before = source.copy()
        self.assertEqual(artist_display_name(source["artist"]), "After Picasso, Pablo")
        self.assertEqual(clean_display_text(source["title"], strip_lot_markers=True), "Félicité")
        self.assertEqual(source, before)
