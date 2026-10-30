"""Tarjoajatestit ilman verkkoa: httpx.MockTransport palauttaa kiinteät vastaukset."""
import httpx
import pytest

from providers import ProviderError, normalize_author, parse_year, pick_isbn
from providers.covers import MAX_COVER_BYTES, fetch_cover
from providers.finna import FinnaProvider
from providers.openlibrary import OpenLibraryProvider
from providers.wikipedia import WikipediaBios
from fakes import Fake, FakeWiki, result
from service import BookService

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2000
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 2000
GIF_PLACEHOLDER = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def json_response(data, status=200):
    return httpx.Response(status, json=data)


def no_requests(request):
    raise AssertionError(f"Odottamaton pyyntö: {request.url}")


# --- apufunktiot ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Linna, Väinö", "Väinö Linna"),
        ("Tolkien, J. R. R. (1892-1973)", "J. R. R. Tolkien"),
        ("Lönnrot, Elias, 1802-1884", "Elias Lönnrot"),
        ("Tove Jansson", "Tove Jansson"),
        ("  Waltari,   Mika ", "Mika Waltari"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_author(raw, expected):
    assert normalize_author(raw) == expected


def test_parse_year_and_pick_isbn():
    assert parse_year("1954") == 1954
    assert parse_year("c1954.") == 1954
    assert parse_year(None) is None and parse_year("n.d.") is None
    assert pick_isbn(["0306406152", "978-0-306-40615-7"]) == "978-0-306-40615-7"
    assert pick_isbn(["0306406152"]) == "0306406152"
    assert pick_isbn([]) is None and pick_isbn(None) is None


# --- Finna -----------------------------------------------------------------

FINNA_RECORD = {
    "id": "fikka.1",
    "title": "Tuntematon sotilas /",
    "nonPresenterAuthors": [
        {"name": "Kuvittaja, Kalle", "role": "kuvittaja"},
        {"name": "Linna, Väinö", "role": "kirjoittaja"},
    ],
    "year": "1954",
    "summary": ["Sotaromaani.", "Toinen kappale."],
    "isbns": ["9510000000", "9789510000001"],
    "images": ["/Cover/Show?id=fikka.1&index=0"],
}


def test_finna_search_parses_records():
    def handler(request):
        assert request.url.host == "api.finna.fi" and request.url.path == "/v1/search"
        params = request.url.params
        assert params["lookfor"] == "linna"
        assert 'format:"0/Book/"' in params.get_list("filter[]")
        assert "nonPresenterAuthors" in params.get_list("field[]")
        return json_response(
            {"resultCount": 3, "records": [FINNA_RECORD, {"id": "x"}, {"title": "Ei id:tä"}], "status": "OK"}
        )

    results = FinnaProvider(client(handler)).search("linna")
    assert len(results) == 1
    r = results[0]
    assert (r.source, r.source_id) == ("finna", "fikka.1")
    assert r.title == "Tuntematon sotilas"
    assert r.author == "Väinö Linna"
    assert r.year == 1954
    assert r.isbn == "9789510000001"
    assert r.summary == "Sotaromaani.\n\nToinen kappale."
    assert r.cover_url == "https://api.finna.fi/Cover/Show?id=fikka.1&index=0&size=large"


def test_finna_missing_author_and_images():
    rec = {"id": "fikka.2", "title": "Antologia", "nonPresenterAuthors": [], "images": []}
    provider = FinnaProvider(client(lambda r: json_response({"records": [rec]})))
    (r,) = provider.search("antologia")
    assert r.author == "Tuntematon kirjailija" and r.cover_url is None and r.year is None


def test_finna_get_found_missing_and_404():
    def handler(request):
        assert request.url.path == "/v1/record"
        assert request.url.params["id"] == "fikka.1"
        return json_response({"resultCount": 1, "records": [FINNA_RECORD]})

    assert FinnaProvider(client(handler)).get("fikka.1").title == "Tuntematon sotilas"
    empty = FinnaProvider(client(lambda r: json_response({"resultCount": 0, "status": "OK"})))
    assert empty.get("fikka.9") is None
    assert FinnaProvider(client(lambda r: httpx.Response(404))).get("fikka.9") is None


def test_finna_errors_become_provider_error():
    with pytest.raises(ProviderError):
        FinnaProvider(client(lambda r: httpx.Response(500))).search("x")
    with pytest.raises(ProviderError):
        FinnaProvider(client(lambda r: httpx.Response(200, text="<html>ei json</html>"))).search("x")

    def boom(request):
        raise httpx.ConnectTimeout("hidas", request=request)

    with pytest.raises(ProviderError):
        FinnaProvider(client(boom)).search("x")


# --- Open Library ----------------------------------------------------------


def test_openlibrary_search_parses_docs():
    def handler(request):
        assert request.url.host == "openlibrary.org" and request.url.path == "/search.json"
        assert request.url.params["q"] == "tolkien"
        return json_response(
            {
                "numFound": 3,
                "docs": [
                    {
                        "key": "/works/OL27448W",
                        "title": "The Lord of the Rings",
                        "author_name": ["J.R.R. Tolkien"],
                        "author_key": ["OL26320A"],
                        "first_publish_year": 1954,
                        "isbn": ["0618260307", "9780618260300"],
                        "cover_i": 8474036,
                    },
                    {"key": "/books/OL1M", "title": "Ei teos"},
                    {"key": "/works/OL2W", "title": "Ilman kirjailijaa ja kantta"},
                ],
            }
        )

    a, b = OpenLibraryProvider(client(handler)).search("tolkien")
    assert (a.source, a.source_id, a.author, a.year) == ("openlibrary", "OL27448W", "J.R.R. Tolkien", 1954)
    assert a.isbn == "9780618260300"
    assert a.cover_url == "https://covers.openlibrary.org/b/id/8474036-L.jpg?default=false"
    assert b.author == "Tuntematon kirjailija" and b.cover_url is None and b.isbn is None


def test_openlibrary_get_combines_work_and_author():
    def handler(request):
        if request.url.path == "/works/OL27448W.json":
            return json_response(
                {
                    "title": "The Lord of the Rings",
                    "description": {"type": "/type/text", "value": "Eepos."},
                    "covers": [-1, 8474036],
                    "first_publish_date": "July 29, 1954",
                    "authors": [{"author": {"key": "/authors/OL26320A"}, "type": {"key": "/type/author_role"}}],
                }
            )
        assert request.url.path == "/authors/OL26320A.json"
        return json_response(
            {"name": "J.R.R. Tolkien", "bio": "Kirjailija ja filologi.\r\n\r\n----------\r\n[Lähde][1]"}
        )

    r = OpenLibraryProvider(client(handler)).get("OL27448W")
    assert r.title == "The Lord of the Rings" and r.author == "J.R.R. Tolkien"
    assert r.year == 1954 and r.summary == "Eepos."
    assert r.author_bio == "Kirjailija ja filologi."  # lähdeosio leikattu pois
    assert r.author_bio_source == "https://openlibrary.org/authors/OL26320A"
    assert r.cover_url.endswith("/b/id/8474036-L.jpg?default=false")


def test_openlibrary_get_survives_author_failure():
    def handler(request):
        if request.url.path.startswith("/works/"):
            return json_response(
                {"title": "Kirja", "description": "Plain", "authors": [{"author": {"key": "/authors/OL1A"}}]}
            )
        return httpx.Response(500)

    r = OpenLibraryProvider(client(handler)).get("OL5W")
    assert r.title == "Kirja" and r.author == "Tuntematon kirjailija" and r.author_bio == ""


def test_openlibrary_get_rejects_bad_ids_without_requests():
    provider = OpenLibraryProvider(client(no_requests))
    for bad in ("../etc/passwd", "OL1M", "ol1w", "OL1W/../x", ""):
        assert provider.get(bad) is None


def test_openlibrary_get_404():
    assert OpenLibraryProvider(client(lambda r: httpx.Response(404))).get("OL1W") is None


# --- Wikipedia ---------------------------------------------------------------


def wiki_page(description="suomalainen kirjailija", extract="Väinö Linna oli kirjailija.", type_="standard"):
    return {
        "type": type_,
        "description": description,
        "extract": extract,
        "content_urls": {"desktop": {"page": "https://fi.wikipedia.org/wiki/V%C3%A4in%C3%B6_Linna"}},
    }


def test_wikipedia_finds_finnish_page():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert request.url.host == "fi.wikipedia.org"
        # raw_path = verkkoon lähtevä (prosenttikoodattu) polku
        assert request.url.raw_path == b"/api/rest_v1/page/summary/V%C3%A4in%C3%B6_Linna"
        return json_response(wiki_page())

    text, url = WikipediaBios(client(handler)).lookup("Väinö Linna")
    assert text == "Väinö Linna oli kirjailija."
    assert url == "https://fi.wikipedia.org/wiki/V%C3%A4in%C3%B6_Linna"
    assert len(seen) == 1  # englantia ei tarvitse kysyä


def test_wikipedia_falls_back_to_english():
    def handler(request):
        if request.url.host == "fi.wikipedia.org":
            return httpx.Response(404)
        return json_response(
            {"type": "standard", "description": "English writer", "extract": "J. R. R. Tolkien was a writer."}
        )

    text, url = WikipediaBios(client(handler)).lookup("J. R. R. Tolkien")
    assert "writer" in text
    assert url.startswith("https://en.wikipedia.org/wiki/")  # content_urls puuttui -> rakennettu


def test_wikipedia_rejects_disambiguation_and_non_writers():
    pages = {
        "fi.wikipedia.org": wiki_page(type_="disambiguation"),
        "en.wikipedia.org": {"type": "standard", "description": "Finnish footballer", "extract": "He plays football."},
    }
    bios = WikipediaBios(client(lambda r: json_response(pages[r.url.host])))
    assert bios.lookup("Matti Meikäläinen") is None


def test_wikipedia_survives_errors_and_skips_unknown_author():
    def handler(request):
        if request.url.host == "fi.wikipedia.org":
            return httpx.Response(500)
        return httpx.Response(404)

    bios = WikipediaBios(client(handler))
    assert bios.lookup("Väinö Linna") is None
    assert WikipediaBios(client(no_requests)).lookup("Tuntematon kirjailija") is None
    assert WikipediaBios(client(no_requests)).lookup("   ") is None


# --- kansikuvat ---------------------------------------------------------------

FINNA_COVER = "https://api.finna.fi/Cover/Show?id=fikka.1&index=0&size=large"


@pytest.mark.parametrize("body, ext", [(JPEG, "jpg"), (PNG, "png"), (WEBP, "webp")])
def test_fetch_cover_accepts_real_images(body, ext):
    http = client(lambda r: httpx.Response(200, content=body, headers={"content-type": "application/octet-stream"}))
    assert fetch_cover(http, FINNA_COVER) == (body, ext)  # tyyppi tunnistetaan sisällöstä


def test_fetch_cover_rejects_bad_content():
    def served(body, status=200):
        return client(lambda r: httpx.Response(status, content=body))

    assert fetch_cover(served(GIF_PLACEHOLDER), FINNA_COVER) is None  # Finnan "ei kantta" -gif
    assert fetch_cover(served(b"\xff\xd8\xff" + b"0" * 10), FINNA_COVER) is None  # liian pieni
    assert fetch_cover(served(b"<html>" + b"0" * 2000), FINNA_COVER) is None  # ei kuva
    assert fetch_cover(served(JPEG, 404), FINNA_COVER) is None
    assert fetch_cover(served(JPEG[:4] + b"0" * (MAX_COVER_BYTES + 1)), FINNA_COVER) is None  # liian suuri


def test_fetch_cover_only_trusted_https_hosts():
    http = client(no_requests)
    assert fetch_cover(http, None) is None
    assert fetch_cover(http, "") is None
    assert fetch_cover(http, "http://api.finna.fi/Cover/Show?id=1") is None  # ei https
    assert fetch_cover(http, "https://evil.example/cover.jpg") is None
    assert fetch_cover(http, "https://api.finna.fi.evil.example/x.jpg") is None
    assert fetch_cover(http, "https://127.0.0.1/x.jpg") is None


def test_fetch_cover_follows_redirects_like_open_library_cdn():
    def handler(request):
        if request.url.host == "covers.openlibrary.org":
            return httpx.Response(302, headers={"location": "https://cdn.example/real.jpg"})
        return httpx.Response(200, content=JPEG)

    url = "https://covers.openlibrary.org/b/id/1-L.jpg?default=false"
    assert fetch_cover(client(handler), url) == (JPEG, "jpg")


def test_fetch_cover_network_error_is_none():
    def boom(request):
        raise httpx.ReadTimeout("hidas", request=request)

    assert fetch_cover(client(boom), FINNA_COVER) is None


# --- BookService ---------------------------------------------------------------


def test_service_merges_and_dedupes_preferring_first_source():
    finna = Fake("finna", [result("finna", "f1", "Tuntematon sotilas", "Väinö Linna")])
    ol = Fake(
        "openlibrary",
        [
            result("openlibrary", "OL1W", "TUNTEMATON SOTILAS", "väinö linna"),  # kaksoiskappale
            result("openlibrary", "OL2W", "The Unknown Soldier", "Väinö Linna"),
        ],
    )
    found = BookService([finna, ol]).search("linna")
    assert [(r.source, r.source_id) for r in found["results"]] == [("finna", "f1"), ("openlibrary", "OL2W")]
    assert found["unavailable"] == []


def test_service_reports_failed_source_but_returns_the_rest_and_does_not_cache_it():
    finna = Fake("finna", fail=True)
    ol = Fake("openlibrary", [result("openlibrary", "OL1W")])
    service = BookService([finna, ol])
    found = service.search("x")
    assert found["unavailable"] == ["finna"] and len(found["results"]) == 1
    service.search("x")
    assert finna.search_calls == 2  # vajaata tulosta ei välimuistiteta


def test_service_all_sources_down():
    found = BookService([Fake("a", fail=True), Fake("b", fail=True)]).search("x")
    assert found == {"results": [], "unavailable": ["a", "b"]}


def test_service_caches_complete_results_case_insensitively():
    finna = Fake("finna", [result("finna", "f1")])
    service = BookService([finna])
    service.search("Linna")
    service.search("  linna ")
    assert finna.search_calls == 1


def test_service_cache_expires_and_is_bounded():
    finna = Fake("finna", [result("finna", "f1")])
    expiring = BookService([finna], cache_ttl=-1)
    expiring.search("a")
    expiring.search("a")
    assert finna.search_calls == 2
    small = BookService([finna], cache_max=2)
    for q in ("a", "b", "c"):
        small.search(q)
    assert len(small._cache) == 2


def test_fetch_uses_wikipedia_only_when_provider_has_no_bio():
    plain = result("finna", "f1", author="Väinö Linna")
    wiki = FakeWiki(("Esittely.", "https://fi.wikipedia.org/wiki/V"))
    r = BookService([Fake("finna", details={"f1": plain})], wiki).fetch("finna", "f1")
    assert (r.author_bio, r.author_bio_source) == ("Esittely.", "https://fi.wikipedia.org/wiki/V")
    assert wiki.calls == ["Väinö Linna"]

    with_bio = result("openlibrary", "OL1W", author="X", author_bio="OL-esittely", author_bio_source="https://ol")
    wiki2 = FakeWiki(("Wiki.", "https://w"))
    r2 = BookService([Fake("openlibrary", details={"OL1W": with_bio})], wiki2).fetch("openlibrary", "OL1W")
    assert r2.author_bio == "OL-esittely" and wiki2.calls == []


def test_fetch_skips_wikipedia_for_unknown_author_and_handles_missing_book():
    unknown = result("finna", "f1", author="Tuntematon kirjailija")
    wiki = FakeWiki(("x", "y"))
    service = BookService([Fake("finna", details={"f1": unknown})], wiki)
    assert service.fetch("finna", "f1").author_bio == "" and wiki.calls == []
    assert service.fetch("finna", "ei-ole") is None


def test_fetch_truncates_long_texts():
    long = result("finna", "f1", summary="a" * 10000, author_bio="b" * 10000, author_bio_source="https://x")
    r = BookService([Fake("finna", details={"f1": long})]).fetch("finna", "f1")
    assert len(r.summary) == 4000 and len(r.author_bio) == 3000


# --- täydennys saman teoksen muista tietueista ------------------------------------

def test_merge_keeps_position_but_prefers_richest_record():
    bare = result("finna", "f1", "Tuntematon sotilas", "Väinö Linna")
    rich = result("finna", "f2", "Tuntematon sotilas", "Väinö Linna", summary="Sota.", cover_url=FINNA_COVER)
    other = result("finna", "f3", "Edvin Laine", "Toinen")
    found = BookService([Fake("finna", [bare, other, rich])]).search("x")["results"]
    assert [r.source_id for r in found] == ["f2", "f3"]


def test_fetch_borrows_summary_and_cover_from_sibling_records():
    bare = result("finna", "f1", "Tuntematon sotilas", "Väinö Linna")
    with_summary = result("finna", "f2", "Tuntematon sotilas /", "Väinö Linna", summary="Jatkosodan romaani.")
    with_cover = result("finna", "f3", "Tuntematon sotilas", "Väinö Linna", cover_url=FINNA_COVER, isbn="978-951-0")
    other_author = result("finna", "f4", "Tuntematon sotilas", "Joku Muu", summary="Väärä kirja.")
    service = BookService([Fake("finna", [with_summary, with_cover, other_author], details={"f1": bare})])
    r = service.fetch("finna", "f1")
    assert r.summary == "Jatkosodan romaani."
    assert r.cover_url == FINNA_COVER
    assert r.extra_cover_urls == ["https://covers.openlibrary.org/b/isbn/9789510-L.jpg?default=false"]
    assert "extra_cover_urls" not in r.to_dict()


def test_fetch_skips_sibling_lookup_when_complete_or_author_unknown():
    full = result("finna", "f1", summary="x", cover_url=FINNA_COVER)
    finna = Fake("finna", details={"f1": full, "f2": result("finna", "f2", author="Tuntematon kirjailija")})
    service = BookService([finna])
    service.fetch("finna", "f1")
    service.fetch("finna", "f2")
    assert finna.search_calls == 0


def test_fetch_survives_failing_sibling_lookup():
    finna = Fake("finna", fail=True, details={"f1": result("finna", "f1")})
    r = BookService([finna]).fetch("finna", "f1")
    assert r.summary == "" and r.cover_url is None


def test_download_cover_tries_candidates_in_order():
    def handler(request):
        if "first" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=JPEG)

    r = result("finna", "f1", cover_url="https://api.finna.fi/first.jpg",
               extra_cover_urls=["https://api.finna.fi/second.jpg"])
    assert BookService([], http=client(handler)).download_cover(r) == (JPEG, "jpg")
    r.extra_cover_urls = []
    assert BookService([], http=client(handler)).download_cover(r) is None
