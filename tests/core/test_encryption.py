from typing import cast

from app.core import encryption
from app.core.encryption import EncryptedString
from sqlalchemy.engine.interfaces import Dialect

_NO_DIALECT = cast(Dialect, None)


def test_encrypt_decrypt_roundtrip() -> None:
    plaintext = "+61 400 000 000"
    packed = encryption.encrypt(plaintext)
    assert packed != plaintext
    assert encryption.decrypt(packed) == plaintext


def test_ciphertext_is_randomized_but_decryptable() -> None:
    first = encryption.encrypt("same")
    second = encryption.encrypt("same")
    assert first != second  # Fernet uses a random IV per call
    assert encryption.decrypt(first) == encryption.decrypt(second) == "same"


def test_encrypted_string_column_roundtrip() -> None:
    column = EncryptedString()
    bound = column.process_bind_param("hello", _NO_DIALECT)
    assert bound is not None
    assert bound != "hello"
    assert column.process_result_value(bound, _NO_DIALECT) == "hello"
    assert column.process_bind_param(None, _NO_DIALECT) is None
    assert column.process_result_value(None, _NO_DIALECT) is None
