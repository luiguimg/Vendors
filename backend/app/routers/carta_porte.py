"""Carta Porte: captura y timbrado del complemento (PAC simulado).

En producción, el timbrado se delega a un PAC real; aquí se simula la
validación de datos y la asignación de folio fiscal (UUID).
"""
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ASN, CartaPorte, CartaPorteStatus, Vendor
from ..schemas import CartaPorteIn, CartaPorteOut
from ..security import get_current_vendor
from ..webhooks import dispatch_event

router = APIRouter(prefix="/api/v1/carta-porte", tags=["Portal · Carta Porte"])

RFC_PATTERN = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


def _validate(payload: CartaPorteIn) -> list[str]:
    errors = []
    if not RFC_PATTERN.match(payload.carrier_rfc.upper()):
        errors.append("RFC del transportista con formato inválido")
    if payload.driver_rfc and not RFC_PATTERN.match(payload.driver_rfc.upper()):
        errors.append("RFC del operador con formato inválido")
    if not payload.vehicle_plate or len(payload.vehicle_plate) < 5:
        errors.append("Placa vehicular requerida (mínimo 5 caracteres)")
    if len(payload.origin_address) < 10 or len(payload.destination_address) < 10:
        errors.append("Las ubicaciones origen/destino deben ser direcciones completas")
    return errors


@router.post("", response_model=CartaPorteOut, status_code=status.HTTP_201_CREATED)
def create_and_stamp(
    payload: CartaPorteIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    asn = db.query(ASN).filter(ASN.id == payload.asn_id, ASN.vendor_id == vendor.id).first()
    if not asn:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ASN no encontrado")
    if asn.shipment_type != "nacional":
        raise HTTPException(status.HTTP_409_CONFLICT, "La Carta Porte aplica solo a embarques nacionales")
    if asn.carta_porte and asn.carta_porte.status == CartaPorteStatus.TIMBRADA:
        raise HTTPException(status.HTTP_409_CONFLICT, "El ASN ya tiene una Carta Porte timbrada")

    errors = _validate(payload)
    cp = asn.carta_porte or CartaPorte(asn_id=asn.id)
    for field, value in payload.model_dump(exclude={"asn_id"}).items():
        setattr(cp, field, value)

    if errors:
        cp.status = CartaPorteStatus.RECHAZADA
        cp.rejection_reason = "; ".join(errors)
    else:
        # Timbrado simulado ante PAC/SAT: asigna folio fiscal
        cp.status = CartaPorteStatus.TIMBRADA
        cp.cfdi_uuid = str(uuid.uuid4()).upper()
        cp.stamped_at = datetime.utcnow()
        cp.rejection_reason = None

    db.add(cp)
    db.commit()
    db.refresh(cp)

    if cp.status == CartaPorteStatus.TIMBRADA:
        background.add_task(dispatch_event, "carta_porte.stamped", {
            "asn_number": asn.number,
            "po_number": asn.po.number,
            "vendor_code": vendor.code,
            "cfdi_uuid": cp.cfdi_uuid,
            "stamped_at": cp.stamped_at,
        })
        return cp

    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, cp.rejection_reason)


@router.get("/{asn_id}", response_model=CartaPorteOut)
def get_carta_porte(
    asn_id: int,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    asn = db.query(ASN).filter(ASN.id == asn_id, ASN.vendor_id == vendor.id).first()
    if not asn or not asn.carta_porte:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carta Porte no encontrada")
    return asn.carta_porte
