from util import split_urls


def test_split_urls_empty():
    assert split_urls("") == []
    assert split_urls(None) == []  # type: ignore[arg-type]
    assert split_urls("   \n\t  ") == []


def test_split_urls_single():
    assert split_urls("https://x/1") == ["https://x/1"]
    assert split_urls("  https://x/1  ") == ["https://x/1"]


def test_split_urls_comma_separated():
    raw = "https://x/1, https://x/2,https://x/3"
    assert split_urls(raw) == ["https://x/1", "https://x/2", "https://x/3"]


def test_split_urls_newline_separated():
    raw = "https://x/1\nhttps://x/2\r\nhttps://x/3"
    assert split_urls(raw) == ["https://x/1", "https://x/2", "https://x/3"]


def test_split_urls_mixed_whitespace_and_commas():
    raw = "https://x/1 ,\thttps://x/2\n , https://x/3"
    assert split_urls(raw) == ["https://x/1", "https://x/2", "https://x/3"]


def test_split_urls_dedupes_preserving_order():
    raw = "https://x/2\nhttps://x/1\nhttps://x/2\nhttps://x/3\nhttps://x/1"
    assert split_urls(raw) == ["https://x/2", "https://x/1", "https://x/3"]
