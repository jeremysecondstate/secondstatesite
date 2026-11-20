"""Correct the five November 19 reviews made before recurring Calendar scans began."""

from django.db import migrations


REVIEW_UPDATES = {
    8889: {
        "fingerprint": "bdaf77e560afcb5ca3f972dccd0e08230100a2667ad3c5fb3dacee6291038662",
        "status": "mismatch",
        "sale_market": "West Columbia, South Carolina",
        "stronger_market": "Mexico",
        "reason": (
            "This West Columbia lot is Zúñiga’s Walking Women II, a lithograph printed in Mexico City. "
            "Its women are a recurring subject in his work, shaped by the figures he observed in southeastern Mexico."
        ),
        "sources": [
            ("Fundación Zúñiga Laborde, Walking Women II, no. 303",
             "https://franciscozuniga.org/fundacion-zuniga-laborde/catalogo-razonado/"
             "oleos-estampas-y-reproducciones-oil-paintings-prints-reproductions/litografias-lithographs-1972-1986/"),
            ("The Metropolitan Museum of Art, Zúñiga’s depictions of women",
             "https://www.metmuseum.org/art/collection/search/343365"),
        ],
    },
    8895: {
        "fingerprint": "0bbb4a13f6b874d9d904d44c50cf6003b229a10dbff75bf2b7a5a487588f9f9d",
        "status": "mismatch",
        "sale_market": "Chicago, Illinois",
        "stronger_market": "New Iberia, Louisiana",
        "reason": (
            "The Patchwork Gift, offered in Chicago, shows women gathered around a quilt at church. "
            "Rodrigue drew the scene from Acadian quilting parties in New Iberia, Louisiana."
        ),
        "sources": [
            ("Rodrigue Life & Legacy Foundation, the New Iberia quilting party in The Patchwork Gift",
             "https://legacyarttour.org/2010/11/women-of-vision.html"),
        ],
    },
    8899: {
        "fingerprint": "3191681c066e34e1cb2da1d4f7d15e0ea1c12e599881c403733e7e61da1ea9ee",
        "status": "mismatch",
        "sale_market": "Chicago, Illinois",
        "stronger_market": "New Orleans, Louisiana",
        "reason": (
            "This Chicago lot pairs Rodrigue’s signed levee print with a campaign shirt. After Hurricane "
            "Katrina, he sent the image to members of Congress to call for stronger New Orleans levees."
        ),
        "sources": [
            ("George Rodrigue Foundation of the Arts, New Orleans levee campaign and the print sent to Congress",
             "https://georgerodriguefoundation.org/wp-content/uploads/george_rodrigue_classroom_resource_comprehensive_educator_guide.pdf"),
        ],
    },
    9555: {
        "fingerprint": "db0a5987f4980cad23376f787a3e6b2c23b30abd88e17ce05e521e9d1efa3ce7",
        "status": "clear",
        "sale_market": "Reston, Virginia",
        "stronger_market": "",
        "reason": (
            "Red Finch offered one color screenprint from KAWS’s New York-published URGE series. "
            "Individual sheets have sold in the United States and London, consistent with the Reston placement."
        ),
        "sources": [
            ("Phillips, signed URGE screenprint, lot 494", "https://www.phillips.com/detail/kaws/238997"),
            ("Tate Ward, signed URGE screenprint, lot 307",
             "https://www.tateward.com/auction/lot/307-kaws-american-1974--urge-2020/?lot=12021&sd=1"),
        ],
    },
    10207: {
        "fingerprint": "7f999b81ed42eba79e17cc277874f688d9965b00a23c5acf9a8d67d3f943de7e",
        "status": "mismatch",
        "sale_market": "Stockholm, Sweden",
        "stronger_market": "Lahore, Pakistan",
        "reason": (
            "Chughtai’s Holy Man shows a shackled figure led through a crowd. The image appeared in the "
            "Lahore arts journal Nargis, and this Stockholm impression itself came from Lahore."
        ),
        "sources": [
            ("Grosvenor Gallery, Chughtai’s Etchings, Mujahid (Holy Man), no. 3",
             "https://www.grosvenorgallery.com/usr/library/documents/catalogues/single-pages-catalogue.pdf"),
            ("Tuli Research Centre for India Studies, Holy Man",
             "https://www.tuliresearchcentre.org/m-a-r-chughtai/research-centre/all/"
             "a-r-chughtai-holy-man-etching-on-paper-n-d-graphic-art-0023975"),
        ],
    },
}


def reassess_reviews(apps, schema_editor):
    Review = apps.get_model("secondstateapp", "AuctionLotMarketReview")
    reviews = Review.objects.using(schema_editor.connection.alias)
    for lot_id, update in REVIEW_UPDATES.items():
        review = reviews.select_for_update().filter(
            lot_id=lot_id, fingerprint=update["fingerprint"], revision=1, status="mismatch",
        ).first()
        if review is None:
            continue

        existing_urls = {source["url"] for source in review.sources}
        review.sources.extend(
            {"label": label, "url": url} for label, url in update["sources"] if url not in existing_urls
        )
        review.status = update["status"]
        review.reason = update["reason"]
        review.sale_market = update["sale_market"]
        review.stronger_market = update["stronger_market"]
        review.revision += 1
        review.save(using=schema_editor.connection.alias, update_fields=[
            "status", "reason", "sale_market", "stronger_market", "sources", "revision", "reviewed_at",
        ])


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0053_auction_lot_market_review")]
    operations = [migrations.RunPython(reassess_reviews, migrations.RunPython.noop)]
