"""Módulo del proveedor: bandeja de OC, respuesta y confirmación de fechas."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import POStatus, PurchaseOrder, Vendor
from ..schemas import DateConfirmationIn, POResponseIn, POStatusUpdateIn, PurchaseOrderOut
from ..security import get_current_vendor
from ..webhooks import dispatch_event

router = APIRouter(prefix="/api/v1/purchase-orders", tags=["Portal · Órdenes de Compra"])


def _get_vendor_po(po_id: int, vendor: Vendor, db: Session) -> PurchaseOrder:
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id, PurchaseOrder.vendor_id == vendor.id,
    ).first()
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Orden de compra no encontrada")
    return po


def _po_event_data(po: PurchaseOrder) -> dict:
    return {
        "po_number": po.number,
        "vendor_code": po.vendor.code,
        "status": po.status.value,
        "confirmed_date": po.confirmed_date,
        "proposed_date": po.proposed_date,
        "reason": po.rejection_reason or po.change_request or po.proposed_date_reason,
    }


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    status_filter: POStatus | None = None,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    q = db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id == vendor.id)
    if status_filter:
        q = q.filter(PurchaseOrder.status == status_filter)
    return q.order_by(PurchaseOrder.created_at.desc()).all()


@router.get("/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    po_id: int,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    po = _get_vendor_po(po_id, vendor, db)
    # Al abrir la OC pasa de "enviada" a "en revisión" (trazabilidad de lectura)
    if po.status == POStatus.ENVIADA:
        po.status = POStatus.EN_REVISION
        db.commit()
        db.refresh(po)
    return po


@router.post("/{po_id}/respond", response_model=PurchaseOrderOut)
def respond_purchase_order(
    po_id: int,
    payload: POResponseIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    po = _get_vendor_po(po_id, vendor, db)
    if po.status not in (POStatus.ENVIADA, POStatus.EN_REVISION, POStatus.MODIFICACION_SOLICITADA):
        raise HTTPException(status.HTTP_409_CONFLICT, f"La OC ya fue respondida (estatus: {po.status.value})")

    if payload.action == "aceptar":
        po.status = POStatus.CONFIRMADA
        po.confirmed_date = payload.confirmed_date or po.requested_date
        event = "po.confirmed"
    elif payload.action == "rechazar":
        if not payload.reason:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El rechazo requiere un motivo")
        po.status = POStatus.RECHAZADA
        po.rejection_reason = payload.reason
        event = "po.rejected"
    else:  # solicitar_cambio
        if not payload.reason:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La solicitud de cambio requiere detalle")
        po.status = POStatus.MODIFICACION_SOLICITADA
        po.change_request = payload.reason
        event = "po.change_requested"

    db.commit()
    db.refresh(po)
    background.add_task(dispatch_event, event, _po_event_data(po))
    return po


@router.post("/{po_id}/confirm-date", response_model=PurchaseOrderOut)
def confirm_delivery_date(
    po_id: int,
    payload: DateConfirmationIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    po = _get_vendor_po(po_id, vendor, db)
    if po.status not in (POStatus.CONFIRMADA, POStatus.EN_PRODUCCION):
        raise HTTPException(status.HTTP_409_CONFLICT, "La OC debe estar confirmada para gestionar fechas")

    if payload.action == "confirmar":
        if not payload.confirmed_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica la fecha confirmada")
        po.confirmed_date = payload.confirmed_date
        po.proposed_date = None
        po.proposed_date_reason = None
        event = "po.date_confirmed"
    else:  # proponer
        if not payload.proposed_date or not payload.reason:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "La contrapropuesta requiere fecha y justificación",
            )
        po.proposed_date = payload.proposed_date
        po.proposed_date_reason = payload.reason
        event = "po.date_proposed"

    db.commit()
    db.refresh(po)
    background.add_task(dispatch_event, event, _po_event_data(po))
    return po


@router.post("/{po_id}/status", response_model=PurchaseOrderOut)
def update_production_status(
    po_id: int,
    payload: POStatusUpdateIn,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """El proveedor solo puede avanzar la OC a 'en producción'."""
    po = _get_vendor_po(po_id, vendor, db)
    if payload.status != POStatus.EN_PRODUCCION or po.status != POStatus.CONFIRMADA:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Solo se permite pasar una OC confirmada a 'en_produccion'",
        )
    po.status = POStatus.EN_PRODUCCION
    db.commit()
    db.refresh(po)
    background.add_task(dispatch_event, "po.status_changed", _po_event_data(po))
    return po
