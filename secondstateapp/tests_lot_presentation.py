"""Presentation regressions using observed catalog text and curated artist names."""

from unittest import TestCase

from .lot_presentation import artist_attribution_label, artist_display_name, artist_sort_key, clean_display_text


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
    def test_november_calendar_names_use_complete_curated_surnames(self):
        examples = {
            "James Ensor": "Ensor, James", "Joseph Beuys": "Beuys, Joseph",
            "Leonor Fini": "Fini, Leonor", "Gillian Ayres": "Ayres, Gillian",
            "Abdur Rahman Chughtai": "Chughtai, Abdur Rahman",
            "Adriaen Jansz van Ostade": "van Ostade, Adriaen Jansz",
            "Julio Le Parc": "Le Parc, Julio", "José García Ortega": "García Ortega, José",
            "Gaston Bernheim de Villers": "Bernheim de Villers, Gaston",
            "Michael Craig-Martin": "Craig-Martin, Michael", "Roy Dean De Forest": "De Forest, Roy Dean",
            "Léonard Tsuguharu Foujita": "Foujita, Léonard Tsuguharu",
            "Ida Rittenberg Kohlmeyer": "Kohlmeyer, Ida Rittenberg",
            "Ivan Le Lorraine Albright": "Albright, Ivan Le Lorraine",
            "Mary Corita Kent": "Kent, Mary Corita", "Norma Bassett Hall": "Hall, Norma Bassett",
            "Rembrandt Harmensz. van Rijn": "Rijn, Rembrandt Harmensz. van",
            'Robert "Shoofly" Shufelt': 'Shufelt, Robert "Shoofly"',
            "H Steven Oiestad": "Oiestad, H Steven", "Öyvind Fahlström": "Fahlström, Öyvind",
            "Pierre (1867) Bonnard": "Bonnard, Pierre", "Jean Michel Basquiat": "Basquiat, Jean-Michel",
            "John Balderssari": "Balderssari, John",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
                self.assertEqual(artist_display_name(expected), expected)
                self.assertEqual(artist_sort_key(raw), artist_sort_key(expected))
        self.assertEqual(sorted(["James Ensor", "Gillian Ayres", "Joseph Beuys"], key=artist_sort_key),
                         ["Gillian Ayres", "Joseph Beuys", "James Ensor"])

    def test_source_qualifiers_biography_and_printmaker_roles_survive_display_order(self):
        examples = {
            "Joseph Beuys (German, 1921-1986)": "Beuys, Joseph (German, 1921-1986)",
            "(after) Joan MIRO": "(after) Miró, Joan", "(after) MATISSE, Henri": "(after) Matisse, Henri",
            "Joan Miró after.": "Miró, Joan after.",
            "Hubert Robert, Attributed to.": "Robert, Hubert, Attributed to.",
            "After Claude Monet, by Georges William Thornley": "After Monet, Claude, by Thornley, Georges William",
            "After Marc Chagall, by Charles Sorlier": "After Chagall, Marc, by Sorlier, Charles",
            "After Pablo Picasso, by Jacques Villon": "After Picasso, Pablo, by Villon, Jacques",
            "Gaston Bernheim de Villers after. Jacques Villon": "Bernheim de Villers, Gaston after. Villon, Jacques",
            "Marcel Duchamp after. Jacques Villon": "Duchamp, Marcel after. Villon, Jacques",
            "Marcel Gromaire after. Jacques Villon": "Gromaire, Marcel after. Villon, Jacques",
            "Marie Laurencin after. Jacques Villon": "Laurencin, Marie after. Villon, Jacques",
            "Pierre-Auguste Renoir after. Jacques Villon": "Renoir, Pierre-Auguste after. Villon, Jacques",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(artist_display_name(raw), expected)
                self.assertEqual(artist_display_name(expected), expected)
                self.assertEqual(artist_attribution_label(raw), artist_attribution_label(expected))
        self.assertEqual(artist_sort_key("Hubert Robert, Attributed to."), artist_sort_key("Hubert Robert"))
        self.assertEqual(artist_sort_key("(after) Joan MIRO"), artist_sort_key("Joan Miró"))

    def test_new_display_aliases_keep_full_credit_attribution_matching_strict(self):
        for artist, title in (
            ("Joseph Beuys", "Joseph Beuys (1921-1986) d'après"),
            ("James Ensor", "James Ensor (1860-1949) d’après"),
            ("Jean Michel Basquiat", "Jean-Michel Basquiat (1960–1988) d'après"),
            ("José García Ortega", "García Ortega, José, after"),
        ):
            with self.subTest(artist=artist):
                self.assertEqual(artist_attribution_label(artist, title=title), "After")
                self.assertEqual(artist_attribution_label(artist_display_name(artist), title=title), "After")
        for title in ("James Ensor Jr. d'après", "Unknown Ensor d'après", "Joseph Beuys d'après",
                      "After the Party", "James Ensor and Unknown Artist d'après"):
            self.assertEqual(artist_attribution_label("James Ensor", title=title), "")

    def test_unknown_credits_and_stage_names_are_not_split_or_assigned_to_known_artists(self):
        for value in ("After James Ensor, by Unknown Maker", "Unknown Artist after. Jacques Villon",
                      "Unknown Artist (German, 1921-1986)", "James Ensor Jr.",
                      "A. R. Penck", "Man Ray", "Invader", "Panamarenko", "Yvaral (Jean-Pierre Vasarely)"):
            expected = "Ensor, James Jr." if value == "James Ensor Jr." else value
            self.assertEqual(artist_display_name(value), expected)
        self.assertNotEqual(artist_display_name("John Balderssari"), artist_display_name("John Baldessari"))

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
