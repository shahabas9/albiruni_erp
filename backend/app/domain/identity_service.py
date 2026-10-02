from sqlalchemy.orm import Session

from app.models.identity import Role, User
from app.models.tenant import Company


def user_payload(db: Session, user: User) -> dict:
    """The shape returned to the frontend after login/bootstrap/`/auth/me`."""

    role = db.get(Role, user.role_id)
    company = db.get(Company, user.company_id)
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "locale": user.locale,
        "role": role.name if role else None,
        "permissions": role.permissions if role else [],
        "company": company.name if company else None,
        # Decide the tax regime and money formatting on screen.
        "country": (company.country if company else None) or "IN",
        "currency": (company.currency if company else None) or "INR",
    }
