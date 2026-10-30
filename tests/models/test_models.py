import uuid

from app.db.base import Base
from app.models import APIKey, Profile, User
from sqlalchemy.orm import configure_mappers

EXPECTED_TABLES = {
    "users",
    "profiles",
    "phones",
    "documents",
    "labels",
    "levels",
    "api_keys",
    "service_accounts",
    "activities",
    "permissions",
    "restrictions",
    "data_storages",
    "comments",
}


def test_all_entities_registered() -> None:
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def test_mappers_configure_cleanly() -> None:
    configure_mappers()  # raises if any relationship is misconfigured


def test_user_associations() -> None:
    user = User(email="alice@example.com", password_digest="hashed")
    user.profiles.append(Profile(first_name="enc", last_name="enc"))
    assert len(user.profiles) == 1
    assert user.profiles[0].user is user


def test_polymorphic_api_key_holder() -> None:
    holder_id = uuid.uuid4()
    key = APIKey(
        kid="kid-123",
        secret="enc",
        key_holder_account_id=holder_id,
        key_holder_account_type="User",
    )
    assert key.key_holder_account_id == holder_id
    assert key.key_holder_account_type == "User"
