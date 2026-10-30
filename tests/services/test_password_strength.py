from app.services.password_strength import is_strong, password_errors


def test_strong_password_passes() -> None:
    assert is_strong("Tr0ub4dour&3xtra")
    assert password_errors("Tr0ub4dour&3xtra") == []


def test_too_short_is_flagged() -> None:
    assert "password.too_short" in password_errors("Aa1!")


def test_missing_character_classes_flagged() -> None:
    errors = password_errors("alllowercase")
    assert "password.no_uppercase" in errors
    assert "password.no_digit" in errors
    assert "password.no_special" in errors


def test_low_entropy_is_flagged() -> None:
    # Satisfies the composition rules but is trivially guessable.
    assert "password.too_weak" in password_errors("Aaaaaa1!")
