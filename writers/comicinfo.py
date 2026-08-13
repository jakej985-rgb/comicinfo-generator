import re
from lxml import etree
from models.comic import Comic

KNOWN_TAGS = {
    "Title", "Series", "Number", "Volume", "Count", "Summary", "Notes",
    "Year", "Month", "Day", "Publisher", "Imprint", "Genre", "Web", "PageCount",
    "LanguageISOCode", "Format", "BlackAndWhite", "Manga", "Characters", "Teams",
    "Locations", "MainCharacterOrTeam", "StoryArc", "Storyarc", "StoryArcNumber",
    "SeriesGroup", "AgeRating", "CommunityRating", "Review", "Writer", "Penciller",
    "Inker", "Colorist", "Letterer", "CoverArtist", "Editor", "Translator"
}

class ComicInfoParser:
    """Parses ComicInfo.xml bytes or ElementTree into a Comic model while preserving unknown nodes & attributes."""

    @staticmethod
    def parse_xml_bytes(xml_bytes: bytes) -> Comic:
        root = etree.fromstring(xml_bytes)
        c = Comic()

        c.title = root.findtext("Title") or ""
        c.series = root.findtext("Series") or ""
        c.number = root.findtext("Number") or ""
        c.volume = root.findtext("Volume") or ""
        c.summary = root.findtext("Summary") or ""
        c.notes = root.findtext("Notes") or ""
        c.publisher = root.findtext("Publisher") or ""
        c.genre = root.findtext("Genre") or ""
        c.web = root.findtext("Web") or ""
        c.language = root.findtext("LanguageISOCode") or ""
        c.format = root.findtext("Format") or ""

        count_text = root.findtext("Count")
        if count_text:
            try:
                c.count = int(count_text)
            except ValueError:
                c.count = 1
        else:
            c.count = None

        try:
            c.year = int(root.findtext("Year") or 0)
            c.month = int(root.findtext("Month") or 0)
            c.day = int(root.findtext("Day") or 0)
        except ValueError:
            pass

        def parse_list(tag, sep=","):
            val = root.findtext(tag)
            if not val:
                return []
            return [x.strip() for x in val.split(sep) if x.strip()]

        c.writers = parse_list("Writer", ";") or parse_list("Writer", ",")
        c.pencillers = parse_list("Penciller", ";") or parse_list("Penciller", ",")
        c.inkers = parse_list("Inker", ";") or parse_list("Inker", ",")
        c.colorists = parse_list("Colorist", ";") or parse_list("Colorist", ",")
        c.letterers = parse_list("Letterer", ";") or parse_list("Letterer", ",")
        c.cover_artists = parse_list("CoverArtist", ";") or parse_list("CoverArtist", ",")
        c.characters = parse_list("Characters", ",")
        c.teams = parse_list("Teams", ",")

        # Story Arc handling
        arc_nodes = root.findall("StoryArc") + root.findall("Storyarc")
        raw_arcs = []
        for node in arc_nodes:
            if node.text:
                raw_arcs.extend([a.strip() for a in node.text.split(",") if a.strip()])
        c.story_arcs = raw_arcs

        arc_num_nodes = root.findall("StoryArcNumber")
        raw_arc_nums = []
        for node in arc_num_nodes:
            if node.text:
                raw_arc_nums.extend([n.strip() for n in node.text.split(",") if n.strip()])
        c.story_arc_numbers = raw_arc_nums

        # Preserve unknown extra XML nodes (tags, attributes, nested elements)
        for child in root:
            tag = child.tag
            if isinstance(tag, str) and tag not in KNOWN_TAGS:
                c.extra_fields[tag] = child.text or ""
                c.extra_nodes.append(etree.fromstring(etree.tostring(child)))

        return c


class ComicInfoWriter:
    """Generates ComicInfo.xml bytes from a Comic model, preserving unknown XML nodes and attributes."""

    @staticmethod
    def _add(root, name, val):
        if val not in (None, ""):
            e = etree.SubElement(root, name)
            e.text = str(val)

    @classmethod
    def generate_xml_bytes(cls, c: Comic) -> bytes:
        root = etree.Element("ComicInfo")
        written_tags = set()

        for k, v in [
            ("Title", c.title), ("Series", c.series), ("Number", c.number),
            ("Volume", c.volume), ("Count", c.count), ("Summary", c.summary),
            ("Notes", c.notes), ("Year", c.year or ""), ("Month", c.month or ""),
            ("Day", c.day or ""), ("Publisher", c.publisher), ("Genre", c.genre),
            ("Web", c.web), ("LanguageISOCode", c.language), ("Format", c.format),
            ("Writer", "; ".join(c.writers)), ("Penciller", "; ".join(c.pencillers)),
            ("Inker", "; ".join(c.inkers)), ("Colorist", "; ".join(c.colorists)),
            ("Letterer", "; ".join(c.letterers)),
            ("CoverArtist", "; ".join(c.cover_artists)),
            ("Characters", ", ".join(c.characters)),
            ("Teams", ", ".join(c.teams)),
            ("StoryArc", ", ".join(c.story_arcs)),
            ("StoryArcNumber", ", ".join(getattr(c, "story_arc_numbers", [])))
        ]:
            if v not in (None, ""):
                cls._add(root, k, v)
                written_tags.add(k)

        # Write preserved extra unknown XML nodes
        for node in getattr(c, "extra_nodes", []):
            if isinstance(node.tag, str) and node.tag not in written_tags:
                root.append(etree.fromstring(etree.tostring(node)))
                written_tags.add(node.tag)

        # Write extra_fields fallback if not already appended
        for k, v in getattr(c, "extra_fields", {}).items():
            if k not in written_tags and v:
                cls._add(root, k, v)

        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="utf-8")


def generate_xml_bytes(c: Comic) -> bytes:
    """Backward-compatible helper."""
    return ComicInfoWriter.generate_xml_bytes(c)

def write_xml(c: Comic, path: str):
    """Backward-compatible helper."""
    xml_data = generate_xml_bytes(c)
    with open(path, "wb") as f:
        f.write(xml_data)
