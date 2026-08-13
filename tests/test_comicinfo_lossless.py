import unittest
from lxml import etree
from writers.comicinfo import ComicInfoParser, ComicInfoWriter

class TestComicInfoLossless(unittest.TestCase):

    def _canonicalize_xml(self, xml_bytes: bytes) -> str:
        parser = etree.XMLParser(remove_blank_text=True)
        elem = etree.fromstring(xml_bytes, parser=parser)
        return etree.tostring(elem, pretty_print=True, encoding="utf-8").decode("utf-8")

    def test_roundtrip_known_fields(self):
        sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>I Am Gotham Part 1</Title>
  <Series>Batman</Series>
  <Number>1</Number>
  <Volume>1</Volume>
  <Count>1</Count>
  <Summary>No man can save Gotham City alone.</Summary>
  <Year>2016</Year>
  <Month>6</Month>
  <Day>1</Day>
  <Publisher>DC Comics</Publisher>
  <Genre>Superhero</Genre>
  <Writer>Tom King</Writer>
  <Penciller>David Finch</Penciller>
</ComicInfo>
"""
        comic = ComicInfoParser.parse_xml_bytes(sample_xml)
        out_xml = ComicInfoWriter.generate_xml_bytes(comic)

        canon_in = self._canonicalize_xml(sample_xml)
        canon_out = self._canonicalize_xml(out_xml)
        self.assertEqual(canon_in, canon_out)

    def test_roundtrip_unknown_tags_and_attributes(self):
        sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Series>Batman</Series>
  <Number>1</Number>
  <CustomAppRating id="123" score="9.5">Masterpiece</CustomAppRating>
  <MyNamespace:Metadata xmlns:MyNamespace="http://example.com/ns">Value</MyNamespace:Metadata>
</ComicInfo>
"""
        comic = ComicInfoParser.parse_xml_bytes(sample_xml)
        out_xml = ComicInfoWriter.generate_xml_bytes(comic)

        canon_in = self._canonicalize_xml(sample_xml)
        canon_out = self._canonicalize_xml(out_xml)
        self.assertEqual(canon_in, canon_out)

if __name__ == "__main__":
    unittest.main()
