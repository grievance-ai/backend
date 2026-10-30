"""Centralized string-valued enums.

The stored value is always the literal string (e.g. ``"pending"``); columns are
plain ``String`` so the database keeps exactly these values.
"""

import enum


class UserState(str, enum.Enum):
    pending = "pending"
    active = "active"
    banned = "banned"
    locked = "locked"
    deleted = "deleted"


class AccountState(str, enum.Enum):
    pending = "pending"
    active = "active"
    disabled = "disabled"


class LabelScope(str, enum.Enum):
    public = "public"
    private = "private"


class ActivityResult(str, enum.Enum):
    succeed = "succeed"
    failed = "failed"
    denied = "denied"


class PermissionAction(str, enum.Enum):
    accept = "ACCEPT"
    drop = "DROP"
    audit = "AUDIT"


class RestrictionScope(str, enum.Enum):
    ip = "ip"
    ip_subnet = "ip_subnet"
    country = "country"
    continent = "continent"
    all = "all"


class RestrictionCategory(str, enum.Enum):
    whitelist = "whitelist"
    blacklist = "blacklist"
    blocklogin = "blocklogin"
    maintenance = "maintenance"


class RestrictionState(str, enum.Enum):
    enabled = "enabled"
    disabled = "disabled"


class APIKeyState(str, enum.Enum):
    active = "active"
    disabled = "disabled"


DEFAULT_ROLE = "member"
DEFAULT_SERVICE_ACCOUNT_ROLE = "service_account"
DEFAULT_API_KEY_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Grievance & scheme assistant
# ---------------------------------------------------------------------------


class Role(str, enum.Enum):
    """Product roles. ``superadmin`` doubles as the spec's system administrator."""

    citizen = "citizen"
    officer = "officer"
    admin = "admin"
    superadmin = "superadmin"


class Language(str, enum.Enum):
    pa = "pa"  # Punjabi (launch language)
    en = "en"
    hi = "hi"


class StaffScope(str, enum.Enum):
    """How wide an officer's/administrator's jurisdiction is."""

    tehsil = "tehsil"
    district = "district"
    state = "state"
    system = "system"


class Gender(str, enum.Enum):
    male = "male"
    female = "female"
    other = "other"
    undisclosed = "undisclosed"


class MaritalStatus(str, enum.Enum):
    single = "single"
    married = "married"
    widowed = "widowed"
    divorced = "divorced"
    separated = "separated"


class AreaType(str, enum.Enum):
    """Matches the ``area`` eligibility field (e.g. PMAY-G requires rural)."""

    rural = "rural"
    urban = "urban"


class SocialCategory(str, enum.Enum):
    general = "general"
    sc = "sc"
    st = "st"
    obc = "obc"


class IncomeBand(str, enum.Enum):
    below_1l = "below_1l"
    l1_to_2_5 = "1l_to_2.5l"
    l2_5_to_5 = "2.5l_to_5l"
    l5_to_10 = "5l_to_10l"
    above_10l = "above_10l"


class ConversationMode(str, enum.Enum):
    unclear = "unclear"
    scheme_enquiry = "scheme_enquiry"
    grievance_intake = "grievance_intake"


class ConversationStatus(str, enum.Enum):
    active = "active"
    ended = "ended"
    grievance_submitted = "grievance_submitted"


class MessageRole(str, enum.Enum):
    citizen = "citizen"
    assistant = "assistant"
    system = "system"


class MessageSource(str, enum.Enum):
    typed = "typed"
    voice = "voice"


class AnswerStatus(str, enum.Enum):
    """How well an assistant reply was grounded — drives the 'could not answer' list."""

    answered = "answered"
    partial = "partial"
    not_in_data = "not_in_data"
    needs_info = "needs_info"
    off_topic = "off_topic"
    official_web = "official_web"  # found on official government websites, not verified by us


class SchemeLevel(str, enum.Enum):
    central = "central"
    state = "state"


class ConditionOperator(str, enum.Enum):
    eq = "eq"
    neq = "neq"
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    in_ = "in"
    not_in = "not_in"
    contains = "contains"
    exists = "exists"


class SchemeReviewStatus(str, enum.Enum):
    verified = "verified"  # checked by a person against the official source
    needs_review = "needs_review"  # imported or changed upstream, not checked yet


class SchemeInterestType(str, enum.Enum):
    viewed = "viewed"
    saved = "saved"
    applied = "applied"


class GrievanceStatus(str, enum.Enum):
    new = "new"
    assigned = "assigned"
    under_verification = "under_verification"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"
    reopened = "reopened"


class GrievancePriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class GrievanceEventType(str, enum.Enum):
    status_change = "status_change"
    assignment = "assignment"


class NoteVisibility(str, enum.Enum):
    internal = "internal"
    citizen = "citizen"


class ResolutionOutcome(str, enum.Enum):
    resolved_fully = "resolved_fully"
    resolved_partially = "resolved_partially"
    not_actionable = "not_actionable"
    referred_elsewhere = "referred_elsewhere"
    duplicate = "duplicate"
    rejected = "rejected"


class UnansweredStatus(str, enum.Enum):
    open = "open"
    added_to_kb = "added_to_kb"
    dismissed = "dismissed"
