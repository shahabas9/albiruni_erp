from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.core.security import create_access_token, verify_password
from app.domain.identity_service import user_payload
from app.models.identity import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == form.username)).scalar_one_or_none()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")

    token = create_access_token(subject=str(user.id), extra_claims={"tenant_id": str(user.tenant_id)})

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_payload(db, user),
    }


@router.get("/me")
def me(context: RequestContext = Depends(get_current_context), db: Session = Depends(get_db)):
    """Lets the frontend validate a stored token on page load without re-submitting credentials."""

    return user_payload(db, context.user)
