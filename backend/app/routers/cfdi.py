"""Gestión de CFDI del proveedor: carga, validación SAT (simulada) y 3-way match."""
import re
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CFDI, CFDIStatus, CFDIType, POStatus, PurchaseOrder, Vendor
from ..schemas import CFDIIn, CFDIOut
from ..security import get_current_vendor
from ..webhooks import dispatch_event

router = APIRouter(prefix="/api/v1/cfdi", tags=["Portal · CFDI"])

UUID_PATTERN = re.compile(r"^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")


def _serialize(cfdi: CFDI) -> CFDIOut:
    out = CFDIOut.model_validate(cfdi)
    out.po_number = cfdi.po.number if cfdi.po else None
    return out


def _three_way_match(cfdi: CFDI, po: PurchaseOrder) -> str | None:
    """Cruce CFDI vs OC vs recibo. Devuelve el motivo de rechazo o None si concilia."""
    if po.status not in (POStatus.EMBARCADA, POStatus.RECIBIDA):
        return "OC sin recibo en almacén: el CFDI se valida tras la recepción (3-way match)"
    if abs(cfdi.total - po.total) > 0.01:
        return f"Monto del CFDI ({cfdi.total:.2f}) no coincide con la OC ({po.total:.2f})"
    return None


@router.get("", response_model=list[CFDIOut])
def list_cfdis(vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    cfdis = (
        db.query(CFDI)
        .filter(CFDI.vendor_id == vendor.id)
        .order_by(CFDI.created_at.desc())
        .all()
    )
    return [_serialize(c) for c in cfdis]


@router.post("", response_model=CFDIOut, status_code=status.HTTP_201_CREATED)
def upload_cfdi(
    payload: CFDIIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    # Validación tipo SAT (simulada): estructura del folio fiscal y duplicidad
    if not UUID_PATTERN.match(payload.uuid):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Folio fiscal (UUID) con formato inválido")
    if db.query(CFDI).filter(CFDI.uuid == payload.uuid.upper()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Este CFDI ya fue cargado (UUID duplicado)")

    po = None
    rejection = None
    if payload.cfdi_type == CFDIType.INGRESO:
        if not payload.po_number:
            rejection = "OC no referenciada: el CFDI de ingreso debe indicar el número de OC"
        else:
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.number == payload.po_number,
                PurchaseOrder.vendor_id == vendor.id,
            ).first()
            if not po:
                rejection = f"La OC {payload.po_number} no existe o no pertenece al proveedor"
        if not rejection and payload.payment_method != "PPD":
            rejection = "Método de pago incorrecto: se requiere PPD para facturas a crédito"

    cfdi = CFDI(
        vendor_id=vendor.id,
        po_id=po.id if po else None,
        uuid=payload.uuid.upper(),
        cfdi_type=payload.cfdi_type,
        serie_folio=payload.serie_folio,
        total=payload.total,
        currency=payload.currency,
        payment_method=payload.payment_method,
    )

    if rejection:
        cfdi.status = CFDIStatus.RECHAZADA
        cfdi.rejection_reason = rejection
    elif po is not None:
        match_error = _three_way_match(cfdi, po)
        if match_error:
            cfdi.status = CFDIStatus.RECHAZADA
            cfdi.rejection_reason = match_error
        else:
            cfdi.status = CFDIStatus.APROBADA
            cfdi.due_date = date.today() + timedelta(days=30)
    # Egreso/traslado/pago quedan en validación manual

    db.add(cfdi)
    db.commit()
    db.refresh(cfdi)

    event = "cfdi.approved" if cfdi.status == CFDIStatus.APROBADA else (
        "cfdi.rejected" if cfdi.status == CFDIStatus.RECHAZADA else "cfdi.uploaded"
    )
    background.add_task(dispatch_event, event, {
        "uuid": cfdi.uuid,
        "vendor_code": vendor.code,
        "po_number": po.number if po else None,
        "cfdi_type": cfdi.cfdi_type.value,
        "total": cfdi.total,
        "status": cfdi.status.value,
        "rejection_reason": cfdi.rejection_reason,
    })
    return _serialize(cfdi)


@router.get("/{cfdi_id}", response_model=CFDIOut)
def get_cfdi(cfdi_id: int, vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    cfdi = db.query(CFDI).filter(CFDI.id == cfdi_id, CFDI.vendor_id == vendor.id).first()
    if not cfdi:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CFDI no encontrado")
    return _serialize(cfdi)
