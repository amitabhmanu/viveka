import json

from pdf_fixture import text_pdf

from viveka.census import CatalogueEntry, Reference, catalogue_match, fold, reference_kind
from viveka.corpus.config import Venue
from viveka.corpus.ingest import Author, IngestedWork, arj, eprints, orthomolecular, rows
from viveka.corpus.ingest.text import (
    extract_references,
    html_reference_text,
    parse_reference,
    pdf_text,
    split_lines,
)

CRSQ = Venue("crsq", "Society Quarterly", None, "eprints_json_v1", "https://repo.example", ("SQ", "Society Quarterly"),
             {"article": "article"}, "other")
JOM = Venue("jom", "Journal of Nutrient Medicine", None, "orthomolecular_toc_v2", "https://nm.example/library/jnm",
            ("J Nutr Med",), {"articles": "article", "correspondence": "letter", "editorial": "editorial"}, "other")
ARJ = Venue("arj", "Open Research Journal", None, "arj_volumes_v1", "https://orj.example", ("ORJ",), {}, "article",
            2008)


# ---------------------------------------------------------------- parsing single references


def test_colon_style_reference_reads_journal_volume_page_and_year():
    ref = parse_reference("Cole, J. H. and C. R. Frame, Jr. 1994. The use of trace marks in sediments. SQ 31:117-124.")
    assert (ref.year, ref.journal, ref.volume, ref.first_page) == (1994, "SQ", "31", "117")
    ref = parse_reference("Lamb, Ann. 1994. A pioneer of flight. Creation Monthly 16(2):26-30.")
    assert (ref.journal, ref.volume, ref.first_page) == ("Creation Monthly", "16", "26")


def test_comma_style_reference_extends_over_abbreviations_but_not_a_title():
    ref = parse_reference("FERN, J.D.: Dietary precursors and brain formation. Ann. Rev. Med. 32, 413-425, 1981.")
    assert (ref.year, ref.journal, ref.volume, ref.first_page) == (1981, "Ann. Rev. Med", "32", "413")
    ref = parse_reference("MAW, A.T.: Corn and homicide rates. J. Nutrient Psychiat. 7, 227-230, 1978.")
    assert ref.journal == "J. Nutrient Psychiat"
    ref = parse_reference("Aus, S. A. 1984a. Rapid erosion at Mount St. Helens. Origins 11:90-98.")
    assert ref.journal == "Origins"


def test_dois_books_and_years_alone():
    ref = parse_reference("Doe, J. 2019. A title. Some Journal 3:1-9. https://doi.org/10.1234/ABC.5.")
    assert ref.doi == "10.1234/abc.5"
    book = parse_reference("Arn, E. B. 1946. The shore dimly seen. Lippincott Press. Philadelphia.")
    assert (book.year, book.volume, book.journal) == (1946, None, None) and reference_kind(book) == "excluded"


# ---------------------------------------------------------------- splitting reference sections


def test_pdf_lines_split_at_author_starts_and_lost_ditto_rules_inherit_the_author():
    lines = ["Aus, S. A. 1984a. Rapid erosion at Mount St. Helens. Origins",
             "11:90-98.",
             ". 1984b. Catastrophes in earth history. Institute",
             "Monograph 13.",
             "(editor). 1994a. Grand Canyon. Institute. Santee, CA.",
             "Bish, G. A. and N. A. Bran. 1993. Ecology of shrimp in Farr, K. M., C. W. Hoff and V.",
             "J. Henry, Jr. (editors). Geomorphology of islands. Guidebooks 13(1):19-29.",
             "43",
             "Don A. D. and J. Rein. 1980. Accelerated ero-",
             "sion in sand. Abstracts 12:415."]
    entries = split_lines(lines)
    assert entries == [
        "Aus, S. A. 1984a. Rapid erosion at Mount St. Helens. Origins 11:90-98.",
        "Aus, S. A. 1984b. Catastrophes in earth history. Institute Monograph 13.",
        "Aus, S. A. (editor). 1994a. Grand Canyon. Institute. Santee, CA.",  # "(editor)" marks a book
        "Bish, G. A. and N. A. Bran. 1993. Ecology of shrimp in Farr, K. M., C. W. Hoff and V. J. Henry, Jr. "
        "(editors). Geomorphology of islands. Guidebooks 13(1):19-29.",
        "Don A. D. and J. Rein. 1980. Accelerated erosion in sand. Abstracts 12:415."]


def test_reference_sections_from_pdf_and_web_pages():
    content = text_pdf(["A study", "Body text mentions references in passing.", "References",
                        "Smith, A. B. 1990. A paper on things. SQ 27:10-12.", "Jones, C. 1991. A book. Press. York."])
    refs = extract_references(pdf_text(content), paragraphs=False)
    assert refs.source == "ingested" and [e.year for e in refs.entries] == [1990, 1991]
    assert extract_references(pdf_text(text_pdf(["No list here"])), paragraphs=False) is None
    page = (b"<html><body><h2>Discussion</h2><p>Text.</p><h2>References</h2>"
            b"<p>Adams, Jo. 2022. <cite>A Web Page</cite>. https://example.org/x.</p>"
            b"<p>Hill, Cy. 2006. <cite>A Book</cite>. North Adams: Storey Publishing.</p>"
            b"<h2>You May Also Like</h2><p>Another paper</p><footer>ISSN 2008</footer></body></html>")
    refs = extract_references(html_reference_text(page), paragraphs=True)
    assert [e.year for e in refs.entries] == [2022, 2006]
    assert reference_kind(refs.entries[0]) == "excluded"  # a web page


# ---------------------------------------------------------------- adapters


def test_eprints_records_become_works_with_pdf_documents():
    item = {"eprintid": 804, "title": "  A Review\n of Claims ", "date": "1995-10", "volume": 32, "number": 2,
            "type": "article", "publication": "Society Quarterly", "pagerange": "117-124",
            "creators": [{"name": {"family": "Berg", "given": "Jerry R."}}],
            "documents": [{"format": "application/pdf", "files": [{"uri": "https://repo.example/id/file/1606"}]}]}
    work = eprints.work_of(CRSQ, item)
    assert work == IngestedWork("crsq", "804", "A Review of Claims", 1995, "32", "2", "117",
                                (Author("Berg", "Jerry R."),), "article", "https://repo.example/id/file/1606")
    assert eprints.work_of(CRSQ, {**item, "publication": "Another Journal"}) is None
    assert eprints.work_of(CRSQ, {**item, "type": "book_section"}).work_type == "other"


TOC = b"""<html><body>
<a href="#editorial">Editorials:</a> <a href="#articles">Articles:</a>
<p><a name="editorial"><font size=3><b>Editorials:</a></font></b>
<p><i>A New Name<br>For the Journal</i>
<br>A. Hoff, M.D., Ph. D.<br>
Page 4<!--<a href="articles/1986-v01n01-p004.shtml">(Read Full Text Article)</a> |-->
<a href="pdf/1986-v01n01-p004.pdf" target=new>(Download Full Text PDF)</a>
<p><a name="articles"><font size=3><b>Articles:</a></font></b>
<p><i>Low Levels and Childhood Intelligence</i>
<br>Mike Marl, Ph.D., Charles Moo, M.A. and J.A.M. Hoes M.D. et al.<br>
Page 43 <!--<a href="abstracts/1986-v01n01-p043.shtml">(Read Abstract)</a> | -->
<a href="pdf/1986-v01n01-p043.pdf" target=new>(Download Full Text PDF)</a>
</p>
<!--
<p><a name="memoriam"><font size=3><b>In Memoriam:</a></font></b>
<p><i>Hidden</i><br>Nobody Here<br>Page 50 <a href="pdf/1986-v01n01-p050.pdf">(Download Full Text PDF)</a>
-->
<a name="correspondence"><font size=3><b>Letters</a></font></b> <p>
The Politics of Research; A Second State<br>
A. HOFFR, M.D., Ph.D. and E Chersk DMD, MD<br>
Page 61 <!--<a href="abstracts/1986-v01n01-p061.shtml">(Read Abstract)</a> | -->
<a href="pdf/1986-v01n01-p061.pdf" target=blank>(Download Full Text PDF)</a>
</body></html>"""


def test_contents_pages_give_sections_titles_authors_and_pages():
    works = orthomolecular.parse_toc(JOM, "https://nm.example/library/jnm/1986/toc1.shtml", TOC)
    assert [(w.key, w.work_type, w.first_page, w.volume, w.issue, w.year) for w in works] == [
        ("1986-v01n01-p004", "editorial", "4", "1", "1", 1986), ("1986-v01n01-p043", "article", "43", "1", "1", 1986),
        ("1986-v01n01-p061", "letter", "61", "1", "1", 1986)]  # the commented-out section is not a paper
    assert works[0].title == "A New Name For the Journal"
    assert [(a.given, a.family) for a in works[1].authors] == [("Mike", "Marl"), ("Charles", "Moo"),
                                                              ("J.A.M.", "Hoes")]
    assert works[1].document_url == "https://nm.example/library/jnm/1986/pdf/1986-v01n01-p043.pdf"
    assert works[2].title == "The Politics of Research; A Second State"  # a later layout: no italics, no colon
    assert [(a.given, a.family) for a in works[2].authors] == [("A.", "HOFFR"), ("E", "Chersk")]
    index = b'<a href="toc1.shtml">1</a> <a href="toc2.shtml">2</a> <a href="toc1.shtml">again</a>'
    assert orthomolecular.toc_urls(JOM, 1986, index) == ["https://nm.example/library/jnm/1986/toc1.shtml",
                                                         "https://nm.example/library/jnm/1986/toc2.shtml"]


VOLUME = """<main><article class="paper-card"><a href="/animals/were-horses-made/"><img alt="x"></a>
<h4><a href="/animals/were-horses-made/">Were Horses Made to Be Ridden?</a></h4>
<p class="caption">pp. 61–66 • <span class="contribName">Caleb Harr
</span></p></article>
<article class="paper-card"><h4><a href="/chronology/framework-6/">Framework. 6: Egypt</a></h4>
<p class="caption">pp. 13–60 • <span class="contribName">Kenneth C. Griff , et. al.</span></p>
</article></main>""".encode()


def test_volume_pages_give_papers_with_year_from_volume_number():
    works = arj.parse_volume(ARJ, 18, VOLUME)
    assert [(w.key, w.year, w.volume, w.first_page, [a.family for a in w.authors]) for w in works] == [
        ("animals/were-horses-made", 2025, "18", "61", ["Harr"]),
        ("chronology/framework-6", 2025, "18", "13", ["Griff"])]
    assert works[0].document_url == "https://orj.example/animals/were-horses-made/"


def test_rows_keep_authors_by_name_and_the_catalogue():
    work = IngestedWork("crsq", "804", "T", 1995, "32", "2", None, (Author("Bérg", "Jerry R."), Author("Lutz", None)),
                        "article", "u")
    out = rows([work], CRSQ)
    assert out["works"][0]["work_id"] == "X:crsq:804" and out["works"][0]["venue_id"] == "X:crsq"
    assert [a["author_id"] for a in out["authors"]] == ["name:berg:j", "name:lutz:"]
    assert [a["position"] for a in out["authorships"]] == ["first", "last"]
    assert out["ingested"] == [{"work_id": "X:crsq:804", "venue": "crsq", "volume": "32", "issue": "2",
                                "first_page": None, "first_author": "berg", "document_url": "u"}]


# ---------------------------------------------------------------- catalogue match


def test_catalogue_match_by_page_or_by_first_author():
    by_author = CatalogueEntry(("SQ", "Society Quarterly"), 1994, "31", None, fold("Cole"))
    by_page = CatalogueEntry(("J Nutr Med",), 1986, "1", "43", "marl")
    cited = parse_reference("Cole, J. H. 1994. Trace marks. SQ 31:117-124.")
    assert catalogue_match(cited, [by_author], 1)
    assert not catalogue_match(parse_reference("Frame, C. R. 1994. Wood. SQ 31:117-124."), [by_author], 1)
    assert not catalogue_match(parse_reference("Cole, J. H. 1990. Trace marks. SQ 31:117-124."), [by_author], 1)
    assert not catalogue_match(parse_reference("Cole, J. H. 1994. Trace marks. Other Review 31:117-124."),
                               [by_author], 1)
    assert catalogue_match(parse_reference("MARL, M.: Mercury. J. Nutr. Med. 1, 43-50, 1986."), [by_page], 1)
    assert not catalogue_match(parse_reference("MARL, M.: Mercury. J. Nutr. Med. 1, 44-50, 1986."), [by_page], 1)
    assert not catalogue_match(Reference(None, 1994, text="Cole 1994"), [by_author], 1)


def test_eprints_listing_reads_the_json_export(tmp_path):
    from corpus_fakes import fake_fetcher

    class Fake:
        calls = []

        def transport(self):
            import httpx

            def handle(request):
                self.calls.append(str(request.url))
                if request.url.path.endswith("/1995.js"):
                    return httpx.Response(200, content=json.dumps([{"eprintid": 1, "title": "T", "date": "1995",
                                                                    "type": "article"}]).encode(),
                                          headers={"content-type": "application/json"})
                return httpx.Response(404)

            return httpx.MockTransport(handle)

    fake = Fake()
    with fake_fetcher(tmp_path, fake) as fetcher:
        works = eprints.list_works(fetcher, CRSQ, 1994, 1995)
    assert [w.key for w in works] == ["1"] and len(fake.calls) == 2
