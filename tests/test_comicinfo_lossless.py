import unittest
from models.comic import Comic
from writers.comicinfo import ComicInfoParser, ComicInfoWriter

class TestComicInfoLossless(unittest.TestCase):

    def test_round_trip_known_fields(self):
        c1 = Comic(
            title="The Long Halloween",
            series="Batman",
            number="1",
            volume="1996",
            year=1996,
            month=10,
            publisher="DC Comics",
            writers=["Jeph Loeb"],
            pencillers=["Tim Sale"],
            story_arcs=["The Long Halloween"]
        )
        xml_bytes = ComicInfoWriter.generate_xml_bytes(c1)
        c2 = ComicInfoParser.parse_xml_bytes(xml_bytes)

        self.assertEqual(c2.title, c1.title)
        self.assertEqual(c2.series, c1.series)
        self.assertEqual(c2.number, c1.number)
        self.assertEqual(c2.publisher, c1.publisher)
        self.assertEqual(c2.writers, c1.writers)
        self.assertEqual(c2.pencillers, c1.pencillers)
        self.assertEqual(c2.story_arcs, c1.story_arcs)

    def test_round_trip_unknown_extra_fields(self):
        c1 = Comic(
            title="Custom Comic",
            series="Custom Series",
            number="10"
        )
        c1.extra_fields["Manga"] = "YesAndRightToLeft"
        c1.extra_fields["CustomRating"] = "18+"

        xml_bytes = ComicInfoWriter.generate_xml_bytes(c1)
        c2 = ComicInfoParser.parse_xml_bytes(xml_bytes)

        self.assertEqual(c2.extra_fields.get("Manga"), "YesAndRightToLeft")
        self.assertEqual(c2.extra_fields.get("CustomRating"), "18+")

        # Re-generate XML and verify extra fields are present in second round-trip
        xml_bytes_2 = ComicInfoWriter.generate_xml_bytes(c2)
        c3 = ComicInfoParser.parse_xml_bytes(xml_bytes_2)
        self.assertEqual(c3.extra_fields.get("Manga"), "YesAndRightToLeft")
        self.assertEqual(c3.extra_fields.get("CustomRating"), "18+")

if __name__ == "__main__":
    unittest.main()
