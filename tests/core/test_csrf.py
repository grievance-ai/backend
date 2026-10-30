from app.core.csrf import generate_csrf_token, tokens_match


def test_tokens_are_unique_and_long() -> None:
    assert generate_csrf_token() != generate_csrf_token()
    assert len(generate_csrf_token()) >= 32


def test_constant_time_match() -> None:
    token = generate_csrf_token()
    assert tokens_match(token, token)
    assert not tokens_match(token, "other")
    assert not tokens_match(None, token)
    assert not tokens_match(token, None)
    assert not tokens_match("", "")
