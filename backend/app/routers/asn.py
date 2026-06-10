"""Módulo de embarques: creación de ASN ligado a la OC."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ASN, ASNLine, POStatus, PurchaseOrder, Vendor
from ..schemas import ASNIn, ASNOut
from ..security import get_current_vendor
from ..webhooks import dispatch_event

router = APIRouter(prefix="/api/v1/asn", tags=["Portal · Embarques (ASN)"])


def _serialize(asn: ASN) -> ASNOut:
    out = ASNOut.model_validate(asn)
    out.po_number = asn.po.number
    return out


@router.get("", response_model=list[ASNOut])
def list_asns(vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    asns = (
        db.query(ASN)
        .filter(ASN.vendor_id == vendor.id)
        .order_by(ASN.created_at.desc())
        .all()
    )
    return [_serialize(a) for a in asns]


@router.post("", response_model=ASNOut, status_code=status.HTTP_201_CREATED)
def create_asn(
    payload: ASNIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.number == payload.po_number,
        PurchaseOrder.vendor_id == vendor.id,
    ).first()
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Orden de compra no encontrada")
    if po.status not in (POStatus.CONFIRMADA, POStatus.EN_PRODUCCION):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Solo se puede crear ASN sobre OC confirmada o en producción",
        )
    if not payload.lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El ASN requiere al menos una línea")

    # Validar que las cantidades embarcadas no excedan lo ordenado
    ordered = {line.sku: line.quantity for line in po.lines}
    for line in payload.lines:
        if line.sku not in ordered:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"El SKU {line.sku} no pertenece a la OC {po.number}",
            )

    seq = db.query(ASN).count() + 1
    asn = ASN(
        number=f"ASN-{seq:05d}",
        po_id=po.id,
        vendor_id=vendor.id,
        shipment_type=payload.shipment_type,
        carrier_name=payload.carrier_name,
        carrier_rfc=payload.carrier_rfc,
        vehicle_plate=payload.vehicle_plate,
        driver_name=payload.driver_name,
        pallets=payload.pallets,
        weight_kg=payload.weight_kg,
        ship_datetime=payload.ship_datetime,
        eta=payload.eta,
        tracking_number=payload.tracking_number,
        lines=[ASNLine(**line.model_dump()) for line in payload.lines],
    )
    po.status = POStatus.EMBARCADA
    db.add(asn)
    db.commit()
    db.refresh(asn)

    background.add_task(dispatch_event, "asn.created", {
        "asn_number": asn.number,
        "po_number": po.number,
        "vendor_code": vendor.code,
        "shipment_type": asn.shipment_type,
        "eta": asn.eta,
        "lines": [line.model_dump() for line in payload.lines],
    })
    return _serialize(asn)


@router.get("/{asn_id}", response_model=ASNOut)
def get_asn(asn_id: int, vendor: Vendor = Depends(get_current_vendor), db: Session = Depends(get_db)):
    asn = db.query(ASN).filter(ASN.id == asn_id, ASN.vendor_id == vendor.id).first()
    if not asn:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ASN no encontrado")
    return _serialize(asn)
