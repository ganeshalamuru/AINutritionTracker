from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Profile
from schemas import ProfileCreate, ProfileOut, PinVerify

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut])
def list_profiles(db: Session = Depends(get_db)):
    return db.query(Profile).filter(Profile.is_active == True).all()


@router.post("", response_model=ProfileOut)
def create_profile(data: ProfileCreate, db: Session = Depends(get_db)):
    if len(data.pin) != 4 or not data.pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")
    existing = db.query(Profile).filter(Profile.pin == data.pin, Profile.is_active == True).first()
    if existing:
        raise HTTPException(status_code=409, detail="A profile with this PIN already exists")
    profile = Profile(name=data.name, pin=data.pin, avatar_color=data.avatar_color)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/verify", response_model=ProfileOut)
def verify_pin(data: PinVerify, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.pin == data.pin, Profile.is_active == True).first()
    if not profile:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    return profile


@router.delete("/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.is_active = False
    db.commit()
    return {"ok": True}
