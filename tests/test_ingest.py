import json

from pdf_fixture import text_pdf

from viveka.census import CatalogueEntry, Reference, catalogue_match, fold, reference_kind
from viveka.corpus.config import Venue
from viveka.corpus.ingest import Author, IngestedWork, arj, bepress, eprints, ojs, orthomolecular, rows
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


# ---------------------------------------------------------------- OJS and bepress

PATTERNS = (("meeting|abstract", "other"), ("editorial", "editorial"), ("cover|contents", "other"))
OJS = Venue("seemj", "Subtle Journal", None, "ojs_v1", "https://oj.example/index.php/sj", ("Subtle Journal",), {},
            "article", None, PATTERNS)

OJS3_ISSUE = b"""<html><head><title>Vol. 21 No. 3 (2010) | Subtle Journal</title></head><body>
<h1>Vol. 21 No. 3 (2010)</h1>
<div class="section"><h2>Cover</h2><div class="obj_article_summary"><h3 class="title">
<a id="article-9" href="https://oj.example/index.php/sj/article/view/9">Cover</a></h3>
<ul class="galleys_links"><li><a class="obj_galley_link pdf" href="https://oj.example/index.php/sj/article/view/9/5">PDF</a>
</li></ul></div></div>
<div class="section"><h2>Experimental</h2>
<div class="obj_article_summary"><h3 class="title"><a id="article-13" href="https://oj.example/index.php/sj/article/view/13">
Touch and Healing</a></h3><div class="meta"><div class="authors">Daniel P. Wirth, M.S., J.D.</div>
<div class="pages">125-130</div></div>
<ul class="galleys_links"><li><a class="obj_galley_link pdf" href="https://oj.example/index.php/sj/article/view/13/10">
PDF</a></li></ul></div>
<div class="obj_article_summary"><h3 class="title"><a id="article-98" href="https://oj.example/index.php/sj/article/view/98">
No Galley Here</a></h3><div class="meta"><div class="authors">Elizabeth A. Raucher, PhD</div></div>
<ul class="galleys_links"></ul></div>
</div><h2>Information</h2></body></html>"""

OJS2_ISSUE = b"""<html><head><title>Vol 2010</title></head><body><h4 class="tocSectionTitle">Research Articles</h4>
<table class="tocArticle" width="100%"><tr valign="top"><td class="tocTitle">
<a href="https://bc.example/ojs/index.php/main/article/view/BIO-C.2010.3">A Vivisection</a></td>
<td class="tocGalleys">
<a href="https://bc.example/ojs/index.php/main/article/view/BIO-C.2010.3/BIO-C.2010.3" class="file">PDF</a>
</td></tr><tr><td class="tocAuthors">George Monta\xc3\xb1ez, Robert J. Marks II</td>
<td class="tocPages"></td></tr></table>
<div class="separator"></div><h4 class="tocSectionTitle">Editorial</h4>
<table class="tocArticle" width="100%"><tr valign="top"><td class="tocTitle">
<a href="https://bc.example/ojs/index.php/main/article/view/BIO-C.2010.0">Welcome</a></td>
<td class="tocGalleys"></td></tr>
<tr><td class="tocAuthors">Douglas Axe</td><td class="tocPages"></td></tr></table></body></html>"""


def test_ojs3_issue_pages_give_sections_galleys_and_pages():
    works = ojs.parse_issue(OJS, OJS3_ISSUE)
    assert [(w.key, w.year, w.volume, w.issue, w.work_type, w.first_page) for w in works] == [
        ("9", 2010, "21", "3", "other", None), ("13", 2010, "21", "3", "article", "125"),
        ("98", 2010, "21", "3", "article", None)]
    assert works[1].document_url == "https://oj.example/index.php/sj/article/download/13/10"
    assert [(a.given, a.family) for a in works[1].authors] == [("Daniel P.", "Wirth")]
    assert works[2].document_url is None and works[2].title == "No Galley Here"


def test_ojs2_contents_pages_and_generational_suffixes():
    venue = Venue("bioc", "BC", None, "ojs_v1", "https://bc.example/ojs/index.php/main", ("BC",), {}, "article",
                  None, PATTERNS)
    works = ojs.parse_issue(venue, OJS2_ISSUE)
    assert [(w.key, w.year, w.volume, w.work_type) for w in works] == [("BIO-C.2010.3", 2010, "2010", "article"),
                                                                      ("BIO-C.2010.0", 2010, "2010", "editorial")]
    assert [a.family for a in works[0].authors] == ["Montañez", "Marks"]
    assert works[0].document_url.endswith("/article/download/BIO-C.2010.3/BIO-C.2010.3")
    assert works[1].document_url is None
    archive = (b'<a href="https://bc.example/ojs/index.php/main/issue/view/24">Vol 2010</a>'
               b'<a href="https://bc.example/ojs/index.php/main/issue/view/24/showToc">again</a>'
               b'<a href="https://bc.example/ojs/index.php/main/issue/view/25">Vol 2011</a>')
    assert ojs.issue_urls(archive) == ["https://bc.example/ojs/index.php/main/issue/view/24",
                                       "https://bc.example/ojs/index.php/main/issue/view/25"]


def test_section_names_before_patterns_before_default():
    venue = Venue("v", "V", None, "ojs_v1", "https://x.example", ("V",), {"Special Editorial Review": "article"},
                  "article", None, PATTERNS)
    assert venue.work_type("Special  Editorial Review") == "article"
    assert venue.work_type("XXXIX GIRI Meeting - Poland") == "other"
    assert venue.work_type("Editorial") == "editorial" and venue.work_type(None) == "article"


BEPRESS_ISSUE = b"""<html><body><h1>Indian Journal</h1><div id="series-header"><h2>Volume 2, Issue 4 (2008)</h2></div>
<h2>Editorial</h2>
<div class="doc"><p class="pdf"><a href="https://www.jr.example/cgi/viewcontent.cgi?article=1798&amp;context=journal">PDF</a>
</p><p><a href="https://www.jr.example/journal/vol2/iss4/1">Editorial</a><br><span class="auth">C Nayak</span></p></div>
<h2>Original Articles</h2>
<div class="doc"><p class="pdf"><a href="https://www.jr.example/cgi/viewcontent.cgi?article=1799&amp;context=journal">PDF</a>
</p><p><a href="https://www.jr.example/journal/vol2/iss4/2">Modeling High Dilutions</a><br>
<span class="auth">Rajesh Shah, Ph.D. and A K Gupta</span></p></div></body></html>"""


def test_bepress_issue_pages():
    venue = Venue("ijrh", "IJRH", None, "bepress_v1", "https://www.jr.example/journal", ("IJRH",), {}, "article",
                  None, PATTERNS)
    works = bepress.parse_issue(venue, BEPRESS_ISSUE)
    assert [(w.key, w.year, w.volume, w.issue, w.work_type) for w in works] == [
        ("v2-i4-1", 2008, "2", "4", "editorial"), ("v2-i4-2", 2008, "2", "4", "article")]
    assert works[1].document_url == "https://www.jr.example/cgi/viewcontent.cgi?article=1799&context=journal"
    assert [a.family for a in works[1].authors] == ["Shah", "Gupta"]
    index = b'<a href="https://www.jr.example/journal/vol2/iss4/">4</a><a href="https://www.jr.example/journal/vol1/iss1/">1</a>'
    assert bepress.issue_urls(venue, index) == ["https://www.jr.example/journal/vol1/iss1/",
                                                "https://www.jr.example/journal/vol2/iss4/"]


def test_v2_reads_references_and_notes_headings_and_headingless_numbered_lists():
    notes = text_pdf(["Body.", "REFERENCES AND NOTES", "1. A. Brazier, Neurophysiology (Physiological Society, 1959).",
                      "2. R. Descartes, Passions de l'Ame (Amsterdam, 1649)."])
    assert extract_references(pdf_text(notes), paragraphs=False).total == 2
    footer = "doi:10.5048/BIO-C.2016.3"
    lines = ["1. Introduction", "Body text of the paper.", footer, "2. Methods", "More text.", footer,
             "We thank the reviewers.", "1. Hartl D (2000) A Primer of Population Genetics. Sinauer.",
             "2. Haines JL (1998) Gene Mapping. Wiley.", footer,
             "3. Green RE (2008) A Neandertal genome. Cell 134:416-426."]
    refs = extract_references(pdf_text(text_pdf(lines)), paragraphs=False)
    assert [e.year for e in refs.entries] == [2000, 1998, 2008]
    assert all(e.doi is None for e in refs.entries)  # the footer DOI recurs on every page and is dropped
    numbered_headings = ["1. Introduction", "Text.", "2. Methods", "Text.", "3. Results", "Text."]
    assert extract_references(pdf_text(text_pdf(numbered_headings)), paragraphs=False) is None
