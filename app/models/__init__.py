"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate and mapper configuration see the full schema.
"""

from app.models.activity import Activity
from app.models.api_key import APIKey
from app.models.citizen_profile import CitizenProfile
from app.models.comment import Comment
from app.models.consent import ConsentRecord
from app.models.conversation import (
    Conversation,
    ConversationMessage,
    MessageScheme,
    UnansweredQuestion,
)
from app.models.data_storage import DataStorage
from app.models.document import Document
from app.models.geography import Department, District, Tehsil
from app.models.grievance import (
    Grievance,
    GrievanceAttachment,
    GrievanceCategory,
    GrievanceNote,
    GrievanceStatusHistory,
    ReferenceCounter,
)
from app.models.label import Label
from app.models.level import Level
from app.models.permission import Permission
from app.models.phone import Phone
from app.models.profile import Profile
from app.models.restriction import Restriction
from app.models.scheme import (
    Scheme,
    SchemeEligibilityCondition,
    SchemeEmbedding,
    SchemeInterest,
)
from app.models.service_account import ServiceAccount
from app.models.staff_profile import StaffProfile
from app.models.user import User

__all__ = [
    "APIKey",
    "Activity",
    "CitizenProfile",
    "Comment",
    "ConsentRecord",
    "Conversation",
    "ConversationMessage",
    "DataStorage",
    "Department",
    "District",
    "Document",
    "Grievance",
    "GrievanceAttachment",
    "GrievanceCategory",
    "GrievanceNote",
    "GrievanceStatusHistory",
    "Label",
    "Level",
    "MessageScheme",
    "Permission",
    "Phone",
    "Profile",
    "ReferenceCounter",
    "Restriction",
    "Scheme",
    "SchemeEligibilityCondition",
    "SchemeEmbedding",
    "SchemeInterest",
    "ServiceAccount",
    "StaffProfile",
    "Tehsil",
    "UnansweredQuestion",
    "User",
]
