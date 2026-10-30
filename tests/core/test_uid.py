from app.utils.uid import ALPHABET, generate_uid


def test_default_prefix_and_length() -> None:
    uid = generate_uid()
    assert uid.startswith("ID")
    assert len(uid) == 12  # "ID" + 10 chars


def test_custom_prefix_and_length() -> None:
    uid = generate_uid(prefix="SA", length=6)
    assert uid.startswith("SA")
    assert len(uid) == 8
    assert all(char in ALPHABET for char in uid[2:])


def test_uids_are_unique() -> None:
    uids = {generate_uid() for _ in range(2000)}
    assert len(uids) == 2000
