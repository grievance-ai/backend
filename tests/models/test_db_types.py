import uuid
from typing import cast

from app.db.base import GUID
from sqlalchemy.engine.interfaces import Dialect

_NO_DIALECT = cast(Dialect, None)


def test_uuid_roundtrips_through_string() -> None:
    guid = GUID()
    value = uuid.uuid4()
    bound = guid.process_bind_param(value, _NO_DIALECT)
    assert bound == str(value)
    assert guid.process_result_value(bound, _NO_DIALECT) == value


def test_none_passes_through() -> None:
    guid = GUID()
    assert guid.process_bind_param(None, _NO_DIALECT) is None
    assert guid.process_result_value(None, _NO_DIALECT) is None
