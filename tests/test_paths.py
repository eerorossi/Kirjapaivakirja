import pytest

from paths import base_href


@pytest.mark.parametrize(
    "prefix, expected",
    [
        ("/kp", "/kp/"),
        ("/kp/", "/kp/"),
        (" /kp ", "/kp/"),
        ("/a/b", "/a/b/"),
        (None, "/"),
        ("", "/"),
        ("/", "/"),
        # epäilyttävät arvot eivät pääse HTML:ään
        ('/kp"><script>alert(1)</script>', "/"),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("/kp/../x", "/"),
        ("/kp?x=1", "/"),
        ("kp", "/"),
        ("/k p", "/"),
    ],
)
def test_base_href(prefix, expected):
    assert base_href(prefix) == expected
