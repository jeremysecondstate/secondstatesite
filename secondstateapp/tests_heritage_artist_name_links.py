"""Verified Heritage artist-page choices must reach Calendar name links offline."""

from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .artist_research_registry import artist_research_urls
from .calendar_views import _lot_json
from .lot_presentation import artist_display_name
from .models import AuctionWatchArtist, AuctionWatchLot


# Original Calendar labels and the artist pages explicitly selected in the
# signed-in Artprice workflow; lot numbers retain the whole-sale source context.
ARTISTS = (('Abdur Rahman Chughtai',
  'Abdur Rahman Chughtai',
  'https://www.artprice.com/artist/130314/abdur-rahman-chughtai/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40095',)),
 ('Al Held',
  'Al Held',
  'https://www.artprice.com/artist/13123/al-held/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40028',)),
 ('Ann Hamilton',
  'Ann Hamilton',
  'https://www.artprice.com/artist/163223/ann-hamilton/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40066',)),
 ('Chris Burden',
  'Chris Burden',
  'https://www.artprice.com/artist/97527/chris-burden/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40069',)),
 ('Christopher Brown',
  'Christopher Brown',
  'https://www.artprice.com/artist/99193/christopher-brown/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40065',)),
 ('David Clyde Driskell',
  'David Clyde Driskell',
  'https://www.artprice.com/artist/228006/david-c-driskell/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40077',)),
 ('David Salle',
  'David Salle',
  'https://www.artprice.com/artist/25522/david-salle/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40064',)),
 ('Donald K. Sultan',
  'Donald K. Sultan',
  'https://www.artprice.com/artist/27757/donald-sultan/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40030', '40031', '40032', '40033')),
 ('Ed Paschke',
  'Ed Paschke',
  'https://www.artprice.com/artist/22168/ed-paschke/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40162',)),
 ('Ernest Tino Trova',
  'Ernest Tino Trova',
  'https://www.artprice.com/artist/32510/ernest-trova/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40029',)),
 ('Gwendolyn Knight',
  'Gwendolyn Knight',
  'https://www.artprice.com/artist/573604/gwen-knight/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40078',)),
 ('Helen Chadwick',
  'Helen Chadwick',
  'https://www.artprice.com/artist/82869/helen-chadwick/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40070',)),
 ('Ida Rittenberg Kohlmeyer',
  'Ida Rittenberg Kohlmeyer',
  'https://www.artprice.com/artist/107919/ida-rittenberg-kohlmeyer/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40011',)),
 ('Indiana, Robert',
  'Robert Indiana',
  'https://www.artprice.com/artist/14269/robert-indiana/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40041', '40042')),
 ('James Ensor',
  'James Ensor',
  'https://www.artprice.com/artist/9143/james-ensor/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40094',)),
 ('James Surls',
  'James Surls',
  'https://www.artprice.com/artist/33198/james-surls/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40166',)),
 ('Joel Shapiro',
  'Joel Shapiro',
  'https://www.artprice.com/artist/26515/joel-shapiro/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40067',)),
 ('John Woodrow Wilson',
  'John Woodrow Wilson',
  'https://www.artprice.com/artist/108549/john-woodrow-wilson/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40086',)),
 ('Jonathan Borofsky',
  'Jonathan Borofsky',
  'https://www.artprice.com/artist/3293/jonathan-borofsky/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40068',)),
 ('Joseph Beuys (German, 1921-1986)',
  'Joseph Beuys',
  'https://www.artprice.com/artist/2485/joseph-beuys/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40071',)),
 ('Jules Olitski',
  'Jules Olitski',
  'https://www.artprice.com/artist/21520/jules-olitski/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40009',)),
 ('Julio Le Parc',
  'Julio Le Parc',
  'https://www.artprice.com/artist/17223/julio-le-parc/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40015',)),
 ('Leon Albert Golub',
  'Leon Albert Golub',
  'https://www.artprice.com/artist/11615/leon-golub/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40169', '40170')),
 ('Longo, Robert',
  'Robert Longo',
  'https://www.artprice.com/artist/17842/robert-longo/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40056', '40057')),
 ('Milton Avery',
  'Milton Avery',
  'https://www.artprice.com/artist/1063/milton-clark-avery/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40098', '40099')),
 ('Mimmo Paladino',
  'Mimmo Paladino',
  'https://www.artprice.com/artist/21921/mimmo-paladino/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40168',)),
 ('Murray, Elizabeth',
  'Elizabeth Murray',
  'https://www.artprice.com/artist/49188/elizabeth-murray/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40160',)),
 ('Opie, Julian',
  'Julian Opie',
  'https://www.artprice.com/artist/21635/julian-opie/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40055',)),
 ('Peter Milton',
  'Peter Milton',
  'https://www.artprice.com/artist/78975/peter-milton/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40096',)),
 ('Piero Dorazio',
  'Piero Dorazio',
  'https://www.artprice.com/artist/7943/piero-dorazio/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40010',)),
 ('Roy Dean De Forest',
  'Roy Dean De Forest',
  'https://www.artprice.com/artist/10073/roy-de-forest/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40161',)),
 ('Russell Young',
  'Russell Young',
  'https://www.artprice.com/artist/342836/russell-young/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40040',)),
 ('Sanford Biggers',
  'Sanford Biggers',
  'https://www.artprice.com/artist/247371/sanford-biggers/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40087',)),
 ('Shara Hughes',
  'Shara Hughes',
  'https://www.artprice.com/artist/534223/shara-hughes/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40167',)),
 ('Stanley Whitney',
  'Stanley Whitney',
  'https://www.artprice.com/artist/214469/stanley-whitney/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40060',)),
 ('Stefan Wewerka',
  'Stefan Wewerka',
  'https://www.artprice.com/artist/30592/stefan-wewerka/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40072',)),
 ('Tony Fitzpatrick',
  'Tony Fitzpatrick',
  'https://www.artprice.com/artist/96621/tony-fitzpatrick/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40163', '40164')),
 ('Trenton Doyle Hancock',
  'Trenton Doyle Hancock',
  'https://www.artprice.com/artist/244350/trenton-doyle-hancock/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40165',)),
 ('Whistler, James Abbott McNeill',
  'James Abbott McNeill Whistler',
  'https://www.artprice.com/artist/30612/james-abbot-mcneill-whistler/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40088',)),
 ('Yozo Hamaguchi',
  'Yozo Hamaguchi',
  'https://www.artprice.com/artist/33135/yozo-hamaguchi/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40097',)),
 ('Yvaral (Jean-Pierre Vasarely)',
  'Yvaral (Jean-Pierre Vasarely)',
  'https://www.artprice.com/artist/31187/yvaral/lots/pasts?idcategory=2&p=1&sort=datesale_desc',
  ('40019',)))


class HeritageArtistNameLinkTests(SimpleTestCase):
    def test_original_and_search_labels_resolve_exact_verified_print_urls(self):
        for original, search_name, expected_url, _ in ARTISTS:
            for label in {original, search_name}:
                with self.subTest(artist=label):
                    self.assertEqual(artist_research_urls(label)[0], expected_url)

    def test_all_49_unsaved_lots_receive_name_links_and_scoped_research_without_mutation(self):
        checked = 0
        saved_work_url = "https://www.artprice.com/lots/7777/user-saved-work"
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=AssertionError("Unexpected database query")):
            for label, _, expected_url, lot_numbers in ARTISTS:
                for number in lot_numbers:
                    with self.subTest(artist=label, lot=number):
                        lot = AuctionWatchLot(
                            pk=int(number), source="Heritage", source_lot_id="heritage-18242-" + number,
                            artist=label, artist_watchlist_name="", watchlist_artist=None,
                            title="Original artwork title", auction_house="Heritage Auctions",
                            sale_title="2026 November 18 Prints & Multiples Showcase Auction",
                            lot_number=number, artprice_url=saved_work_url, won_by_us=True,
                        )
                        lot._state.fields_cache["bid_board_analysis"] = None
                        before = (lot.artist, lot.artist_watchlist_name, lot.title, lot.artprice_url,
                                  lot.won_by_us, lot.watchlist_artist_id, lot._state.adding)
                        payload = _lot_json(lot, ZoneInfo("America/Los_Angeles"), {lot.pk},
                                            {lot.pk: {"status": "pending"}})
                        expected_id = urlsplit(expected_url).path.split("/")[2]
                        self.assertEqual(payload["artist_artprice_url"], expected_url)
                        self.assertEqual(parse_qs(urlsplit(payload["artprice_search_url"]).query)["idartist"], [expected_id])
                        self.assertEqual(payload["artprice_search_scope"], "artist")
                        self.assertEqual(payload["artist_source"], label)
                        self.assertEqual(payload["artist"], artist_display_name(label))
                        self.assertEqual(payload["artprice_url"], saved_work_url)
                        self.assertTrue(payload["won_by_us"])
                        self.assertTrue(payload["email_tray_selected"])
                        self.assertTrue(payload["research_queue_selected"])
                        self.assertEqual(before, (lot.artist, lot.artist_watchlist_name, lot.title,
                                                lot.artprice_url, lot.won_by_us,
                                                lot.watchlist_artist_id, lot._state.adding))
                        checked += 1
        self.assertEqual(checked, 49)

    def test_saved_watchlist_artist_url_still_takes_precedence(self):
        chosen_url = "https://www.artprice.com/artist/163223/ann-hamilton/lots/pasts?idcategory[]=2"
        artist = AuctionWatchArtist(pk=9000, name="Ann Hamilton", artprice_url=chosen_url)
        lot = AuctionWatchLot(pk=40066, source="Heritage", source_lot_id="override",
                              artist="Ann Hamilton", title="Original title", watchlist_artist=artist)
        lot._state.fields_cache["bid_board_analysis"] = None
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=AssertionError("Unexpected database query")):
            payload = _lot_json(lot, ZoneInfo("America/Los_Angeles"))
        self.assertEqual(payload["artist_artprice_url"], chosen_url)
        self.assertEqual(artist.artprice_url, chosen_url)
        self.assertTrue(artist._state.adding)
        self.assertTrue(lot._state.adding)
