"""Wrong-script guard: Punjabi replies must not slip into other Indian scripts."""

from app.services.assistant_service import foreign_script_count


def test_gurmukhi_and_dandas_are_fine() -> None:
    data = {"reply": "ਤੁਸੀਂ ਇਸ ਸਕੀਮ ਲਈ ਯੋਗ ਹੋ। ਧੰਨਵਾਦ॥", "follow_ups": ["ਹੋਰ ਦੱਸੋ"]}
    assert foreign_script_count(data, "pa") == 0


def test_english_and_digits_are_fine() -> None:
    assert foreign_script_count({"reply": "PM-KISAN pays Rs 6,000 a year."}, "pa") == 0


def test_telugu_inside_punjabi_is_caught() -> None:
    # The slip seen live: "Indira" written in Telugu inside a Punjabi reply.
    data = {"reply": "ਇందిరਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"}
    assert foreign_script_count(data, "pa") == 4


def test_nested_fields_are_checked_but_facts_are_not() -> None:
    data = {
        "schemes": [{"conditions": [{"text": "आयु 60 वर्ष"}]}],
        "facts": [{"key": "village", "value": "रामपुर"}],  # the citizen's own words
    }
    assert foreign_script_count(data, "pa") == 7  # "आयु" (3) + "वर्ष" (4)


def test_other_languages_are_not_checked() -> None:
    assert foreign_script_count({"reply": "आप पात्र हैं"}, "hi") == 0
