import os
import re
from typing import Optional, List
from models.archive import ArchiveRecord
from models.identity import ComicIdentity, IdentityEvidence
from writers.comicinfo import ComicInfoParser

def extract_archive_identity(archive: ArchiveRecord) -> Optional[ComicIdentity]:
    """
    Extracts identity signals from embedded ComicInfo.xml and directory structure
    of an ArchiveRecord, returning a candidate ComicIdentity with attached evidence.
    """
    if not archive or not os.path.exists(archive.path):
        return None

    evidence: List[IdentityEvidence] = []
    identity = ComicIdentity(provider="ExistingXML")

    # 1. Inspect embedded ComicInfo.xml if present
    if archive.comicinfo_present and archive.path.lower().endswith(".cbz"):
        try:
            import zipfile
            with zipfile.ZipFile(archive.path, "r") as z:
                xml_names = [n for n in z.namelist() if n.lower() == "comicinfo.xml"]
                if xml_names:
                    xml_bytes = z.read(xml_names[0])
                    comic = ComicInfoParser.parse_xml_bytes(xml_bytes)

                    if comic.series:
                        identity.series_name = comic.series
                        evidence.append(IdentityEvidence(
                            source="ExistingXML", field="series_name",
                            expected="", actual=comic.series, score=10.0,
                            explanation=f"Embedded ComicInfo.xml contains series '{comic.series}'"
                        ))
                    if comic.number:
                        identity.issue_number = comic.number
                        evidence.append(IdentityEvidence(
                            source="ExistingXML", field="issue_number",
                            expected="", actual=comic.number, score=10.0,
                            explanation=f"Embedded ComicInfo.xml contains issue #{comic.number}"
                        ))
                    if comic.year > 0:
                        identity.publication_year = comic.year
                        evidence.append(IdentityEvidence(
                            source="ExistingXML", field="year",
                            expected="", actual=str(comic.year), score=5.0,
                            explanation=f"Embedded ComicInfo.xml contains year {comic.year}"
                        ))
                    if comic.publisher:
                        identity.publisher = comic.publisher
                        evidence.append(IdentityEvidence(
                            source="ExistingXML", field="publisher",
                            expected="", actual=comic.publisher, score=5.0,
                            explanation=f"Embedded ComicInfo.xml contains publisher '{comic.publisher}'"
                        ))

                    # Parse Web URL for provider issue/series ID if present
                    if comic.web:
                        m_cv = re.search(r"comicvine\.gamespot\.com/.*?/4000-(\d+)", comic.web)
                        if m_cv:
                            identity.issue_id = f"4000-{m_cv.group(1)}"
                            identity.issue_provider = "ComicVine"
                            evidence.append(IdentityEvidence(
                                source="ExistingXML", field="issue_id",
                                expected="", actual=identity.issue_id, score=90.0,
                                explanation=f"Embedded Web URL contains Comic Vine Issue ID '{identity.issue_id}'"
                            ))
        except Exception:
            pass

    # 2. Inspect folder structure (e.g. /comics/Batman (2016)/Batman 001.cbz)
    parent_dir = os.path.basename(os.path.dirname(os.path.abspath(archive.path)))
    if parent_dir and parent_dir.lower() not in ("comics", "downloads", "tmp", "temp"):
        m_year = re.search(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", parent_dir)
        clean_folder = re.sub(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", "", parent_dir)
        clean_folder = re.sub(r"[_\-\.\(\)\[\]]+", " ", clean_folder).strip()

        if clean_folder and not identity.series_name:
            identity.series_name = clean_folder
            evidence.append(IdentityEvidence(
                source="DirectoryStructure", field="series_name",
                expected="", actual=clean_folder, score=10.0,
                explanation=f"Folder name contains series '{clean_folder}'"
            ))

        if m_year and identity.publication_year == 0:
            identity.publication_year = int(m_year.group(1))
            evidence.append(IdentityEvidence(
                source="DirectoryStructure", field="year",
                expected="", actual=m_year.group(1), score=5.0,
                explanation=f"Folder name contains year {m_year.group(1)}"
            ))

    identity.evidence = evidence
    return identity if (identity.series_name or identity.issue_number) else None
