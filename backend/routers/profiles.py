from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.database import get_db
from models import Profile
from schemas import OkResponse, PinVerify, ProfileCreate, ProfileOut

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut], summary="List active profiles")
def list_profiles(db: Session = Depends(get_db)):
    return db.query(Profile).filter(Profile.is_active.is_(True)).all()


@router.post(
    "", response_model=ProfileOut, status_code=status.HTTP_201_CREATED, summary="Create a profile"
)
def create_profile(data: ProfileCreate, db: Session = Depends(get_db)):
    # PIN format (exactly 4 digits) is enforced by ProfileCreate.pin (→ 422).
    existing = (
        db.query(Profile).filter(Profile.pin == data.pin, Profile.is_active.is_(True)).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A profile with this PIN already exists")
    profile = Profile(name=data.name, pin=data.pin, avatar_color=data.avatar_color)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/verify", response_model=ProfileOut, summary="Verify a profile PIN")
def verify_pin(data: PinVerify, db: Session = Depends(get_db)):
    profile = (
        db.query(Profile).filter(Profile.id == data.profile_id, Profile.is_active.is_(True)).first()
    )
    if not profile or profile.pin != data.pin:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    return profile


@router.delete("/{profile_id}", response_model=OkResponse, summary="Soft-delete a profile")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.is_active = False
    db.commit()
    return {"ok": True}
