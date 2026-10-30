"""The scheme knowledge file loads cleanly and is well-formed."""

from app.db.knowledge import load_file
from app.models.enums import ConditionOperator

PROFILE_FIELDS = {
    "occupation",
    "land_holding_acres",
    "income_band",
    "social_category",
    "gender",
    "age",
}


def test_knowledge_file_is_well_formed() -> None:
    data = load_file()
    departments = {d["code"] for d in data["departments"]}
    slugs = [s["slug"] for s in data["schemes"]]
    operators = {o.value for o in ConditionOperator}

    assert len(slugs) == len(set(slugs)), "duplicate scheme slug"
    for scheme in data["schemes"]:
        for key in ("name", "description", "benefits", "required_documents", "application_steps"):
            assert scheme.get(key), f"{scheme['slug']}: missing {key}"
        assert scheme["official_url"].startswith("https://"), scheme["slug"]
        assert scheme.get("department") in departments, scheme["slug"]
        assert scheme["conditions"], f"{scheme['slug']}: no eligibility conditions"
        for condition in scheme["conditions"]:
            assert condition["operator"] in operators, (scheme["slug"], condition)
            assert condition["description"].strip()


def test_profile_fields_are_spelled_consistently() -> None:
    # A typo like "land_holding" would silently stop matching the profile.
    fields = {c["field"] for s in load_file()["schemes"] for c in s["conditions"]}
    assert {"occupation", "land_holding_acres", "age"} <= fields
    assert not {f for f in fields if f.startswith("land_") and f not in PROFILE_FIELDS}
