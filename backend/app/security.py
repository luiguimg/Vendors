"""Autenticación: sesiones de proveedor (Bearer) y API Keys del ERP (X-API-Key)."""
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import ApiKey, Vendor

_PWD_SALT = "portal-proveedores-natureganix"


def hash_password(password: str) -> str:
    return hashlib.sha256(f"{_PWD_SALT}:{password}".encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return "erp_" + secrets.token_hex(24)


def generate_session_token() -> str:
    return secrets.token_hex(32)


def get_current_vendor(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Vendor:
    """Proveedor autenticado vía `Authorization: Bearer <token>`."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de sesión requerido")
    token = authorization.split(" ", 1)[1].strip()
    vendor = db.query(Vendor).filter(Vendor.session_token == token, Vendor.active).first()
    if not vendor:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return vendor


def get_erp_client(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Sistema ERP autenticado vía `X-API-Key`."""
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Encabezado X-API-Key requerido")
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == hash_api_key(x_api_key), ApiKey.active,
    ).first()
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key inválida")
    return api_key
