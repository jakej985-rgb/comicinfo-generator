from lxml import etree

def _add(root, name, val):
    e = etree.SubElement(root, name)
    if val not in (None, ""):
        e.text = str(val)

def generate_xml_bytes(c) -> bytes:
    root = etree.Element("ComicInfo")
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
        ("StoryArc", ", ".join(c.story_arcs))
    ]:
        _add(root, k, v)
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="utf-8")

def write_xml(c, path):
    xml_data = generate_xml_bytes(c)
    with open(path, "wb") as f:
        f.write(xml_data)
