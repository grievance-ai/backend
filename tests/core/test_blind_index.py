from app.utils.blind_index import blind_index


def test_deterministic() -> None:
    assert blind_index("+61400000000") == blind_index("+61400000000")


def test_normalizes_case_and_whitespace() -> None:
    assert blind_index("  Foo@Bar.com ") == blind_index("foo@bar.com")


def test_distinct_values_differ() -> None:
    assert blind_index("alice") != blind_index("bob")


def test_output_is_sha256_hex() -> None:
    digest = blind_index("value")
    assert len(digest) == 64
    int(digest, 16)  # raises if not valid hex
