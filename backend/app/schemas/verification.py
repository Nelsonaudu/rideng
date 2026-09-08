from enum import Enum

from pydantic import BaseModel


class VerificationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class VerificationStatusUpdate(BaseModel):
    verification_status: VerificationStatus