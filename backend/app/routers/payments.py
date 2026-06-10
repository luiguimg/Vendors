"""Estado de cuenta del proveedor: facturas, pagos y Complementos de Pago (REP)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CFDI, CFDIStatus, Vendor
from ..schemas import AccountStatementOut, CFDIOut, VendorOut
from ..security import get_current_vendor

router = APIRouter(prefix="/api/v1/account-statement", tags=["Portal · Estado de Cuenta"])


@router.get("", response_model=AccountStatementOut)
def account_statement(vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    cfdis = (
        db.query(CFDI)
        .filter(CFDI.vendor_id == vendor.id)
        .order_by(CFDI.created_at.desc())
        .all()
    )

    total_pendiente = sum(
        c.total - c.paid_amount for c in cfdis
        if c.status in (CFDIStatus.APROBADA, CFDIStatus.PAGO_PARCIAL)
    )
    total_programado = sum(c.total - c.paid_amount for c in cfdis if c.status == CFDIStatus.PROGRAMADA)
    total_pagado = sum(c.paid_amount for c in cfdis)

    out_cfdis = []
    for c in cfdis:
        item = CFDIOut.model_validate(c)
        item.po_number = c.po.number if c.po else None
        out_cfdis.append(item)

    return AccountStatementOut(
        vendor=VendorOut.model_validate(vendor),
        total_pendiente=round(total_pendiente, 2),
        total_programado=round(total_programado, 2),
        total_pagado=round(total_pagado, 2),
        cfdis=out_cfdis,
    )
