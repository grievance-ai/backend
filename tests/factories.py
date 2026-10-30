"""Test data factories (factory_boy).

These build *unsaved* model instances via ``factory.Factory`` so they compose
cleanly with our async SQLAlchemy sessions — build here, persist with the
``make_user`` fixture (or ``session.add`` + ``commit``) in tests.

Identifiers are UUID-based rather than plain sequences because the test database
is not reset between runs, so a monotonic counter would collide on re-run.
"""

import uuid

import factory
from app.core.security import hash_password
from app.models.enums import DEFAULT_ROLE, UserState
from app.models.user import User

# Plaintext password whose digest every factory-built user carries; tests log in
# with this value.
PASSWORD = "Tr0ub4dour&3xtra"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class UserFactory(factory.Factory):  # type: ignore[misc]
    class Meta:
        model = User

    email = factory.LazyFunction(lambda: f"{_unique('user')}@example.com")
    username = factory.LazyFunction(lambda: _unique("user"))
    password_digest = factory.LazyFunction(lambda: hash_password(PASSWORD))
    role = DEFAULT_ROLE
    state = UserState.active.value
