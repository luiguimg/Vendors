from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Vendor
from ..schemas import LoginRequest, LoginResponse, VendorOut
from ..security import generate_session_token, get_current_vendor, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["Portal · Autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.email == payload.email, Vendor.active).first()
    if not vendor or not verify_password(payload.password, vendor.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    vendor.session_token = generate_session_token()
    db.commit()
    return LoginResponse(token=vendor.session_token, vendor_code=vendor.code, vendor_name=vendor.name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    vendor.session_token = None
    db.commit()


@router.get("/me", response_model=VendorOut)
def me(vendor: Vendor = Depends(get_current_vendor)):
    return vendor
