"""Feikkilähteet testeihin: ei verkkoyhteyksiä."""
from providers import BookResult, ProviderError


class Fake:
    """Feikki BookProvider."""

    def __init__(self, name, results=None, fail=False, details=None, get_fail=False):
        self.name, self.results, self.fail, self.get_fail = name, results or [], fail, get_fail
        self.details = details or {}
        self.search_calls = 0

    def search(self, query, limit=10):
        self.search_calls += 1
        if self.fail:
            raise ProviderError(f"{self.name} alhaalla")
        return self.results

    def get(self, source_id):
        if self.get_fail:
            raise ProviderError(f"{self.name} alhaalla")
        return self.details.get(source_id)


class FakeWiki:
    def __init__(self, found=None):
        self.found, self.calls = found, []

    def lookup(self, name):
        self.calls.append(name)
        return self.found


def result(source, sid, title="Kirja", author="Kirjoittaja", **kw):
    return BookResult(source=source, source_id=sid, title=title, author=author, **kw)
