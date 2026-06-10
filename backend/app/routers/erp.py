"""API de integración con ERP (Business Central, SAP, Odoo, etc.).

Autenticación: header `X-API-Key` (llaves administradas en la tabla api_keys).

Flujo típico de integración:
  1. El ERP sincroniza el maestro de proveedores  → PUT  /vendors
  2. El ERP publica órdenes de compra             → POST /purchase-orders
  3. El portal notifica respuestas vía webhooks; el ERP también puede
     consultar por polling                        → GET  /purchase-orders?updated_since=...
  4. El ERP consume ASNs para crear recibos
     esperados en el WMS                          → GET  /asn?pending=true  +  POST /asn/{id}/ack
  5. El ERP consume CFDIs aprobados hacia CxP     → GET  /cfdi?status=aprobada&synced=false
  6. El ERP registra pagos y publica el REP       → POST /payments
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ASN, ApiKey, CFDI, CFDIStatus, Document, POLine, POStatus, PurchaseOrder,
    Vendor, WebhookSubscription,
)
from ..schemas import (
    ASNOut, CFDIOut, CFDIReviewIn, DocumentOut, DocumentReviewIn, PaymentIn,
    PaymentOut, POStatusUpdateIn, PurchaseOrderERPOut, PurchaseOrderIn,
    VendorOut, VendorUpsert, WebhookSubscriptionIn, WebhookSubscriptionOut,
)
from ..security import get_erp_client, hash_password
from ..webhooks import dispatch_event
from ..models import Payment

router = APIRouter(
    prefix="/api/erp/v1",
    tags=["Integración ERP"],
    dependencies=[Depends(get_erp_client)],
)


# ─── Maestro de proveedores ──────────────────────────────────────────────────

@router.put("/vendors", response_model=VendorOut)
def upsert_vendor(payload: VendorUpsert, db: Session = Depends(get_db)):
    """Crea o actualiza un proveedor desde el maestro del ERP (idempotente por código)."""
    vendor = db.query(Vendor).filter(Vendor.code == payload.code).first()
    if vendor:
        vendor.name = payload.name
        vendor.rfc = payload.rfc
        vendor.email = payload.email
        vendor.payment_terms = payload.payment_terms
        vendor.active = payload.active
    else:
        vendor = Vendor(
            code=payload.code,
            name=payload.name,
            rfc=payload.rfc,
            email=payload.email,
            payment_terms=payload.payment_terms,
            active=payload.active,
            password_hash=hash_password(payload.initial_password or "cambiar123"),
        )
        db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(db: Session = Depends(get_db)):
    return db.query(Vendor).order_by(Vendor.code).all()


# ─── Órdenes de compra ───────────────────────────────────────────────────────

@router.post("/purchase-orders", response_model=PurchaseOrderERPOut, status_code=status.HTTP_201_CREATED)
def publish_purchase_order(payload: PurchaseOrderIn, db: Session = Depends(get_db)):
    """El ERP publica una OC en el portal; queda en estatus 'enviada'."""
    vendor = db.query(Vendor).filter(Vendor.code == payload.vendor_code, Vendor.active).first()
    if not vendor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Proveedor {payload.vendor_code} no existe en el portal")
    if db.query(PurchaseOrder).filter(PurchaseOrder.number == payload.number).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"La OC {payload.number} ya está publicada")
    if not payload.lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La OC requiere al menos una línea")

    po = PurchaseOrder(
        number=payload.number,
        vendor_id=vendor.id,
        currency=payload.currency,
        requested_date=payload.requested_date,
        notes=payload.notes,
        total=round(sum(l.quantity * l.unit_price for l in payload.lines), 2),
        lines=[POLine(**l.model_dump()) for l in payload.lines],
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    return po


@router.get("/purchase-orders", response_model=list[PurchaseOrderERPOut])
def pull_purchase_orders(
    status_filter: POStatus | None = Query(default=None, alias="status"),
    updated_since: datetime | None = None,
    db: Session = Depends(get_db),
):
    """Polling de OCs: el ERP recupera cambios (respuestas y fechas del proveedor)."""
    q = db.query(PurchaseOrder)
    if status_filter:
        q = q.filter(PurchaseOrder.status == status_filter)
    if updated_since:
        q = q.filter(PurchaseOrder.updated_at >= updated_since)
    return q.order_by(PurchaseOrder.updated_at.desc()).all()


@router.patch("/purchase-orders/{number}/status", response_model=PurchaseOrderERPOut)
def erp_update_po_status(
    number: str,
    payload: POStatusUpdateIn,
    db: Session = Depends(get_db),
):
    """El ERP marca la OC como recibida (recepción en WMS) o cancelada, o la reemite."""
    po = db.query(PurchaseOrder).filter(PurchaseOrder.number == number).first()
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Orden de compra no encontrada")
    allowed = {POStatus.RECIBIDA, POStatus.CANCELADA, POStatus.ENVIADA}
    if payload.status not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El ERP solo puede establecer: recibida, cancelada o enviada (reemisión)",
        )
    po.status = payload.status
    if payload.status == POStatus.ENVIADA:  # reemisión tras modificación
        po.rejection_reason = None
        po.change_request = None
    db.commit()
    db.refresh(po)
    return po


# ─── ASN → recibos esperados en WMS ─────────────────────────────────────────

@router.get("/asn", response_model=list[ASNOut])
def pull_asns(
    pending: bool = Query(default=False, description="Solo ASN aún no confirmados por el WMS"),
    db: Session = Depends(get_db),
):
    q = db.query(ASN)
    if pending:
        q = q.filter(ASN.erp_acknowledged.is_(False))
    asns = q.order_by(ASN.created_at.desc()).all()
    out = []
    for a in asns:
        item = ASNOut.model_validate(a)
        item.po_number = a.po.number
        out.append(item)
    return out


@router.post("/asn/{asn_id}/ack", response_model=ASNOut)
def acknowledge_asn(asn_id: int, db: Session = Depends(get_db)):
    """El ERP confirma que creó el recibo esperado en el WMS a partir del ASN."""
    asn = db.query(ASN).filter(ASN.id == asn_id).first()
    if not asn:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ASN no encontrado")
    asn.erp_acknowledged = True
    db.commit()
    db.refresh(asn)
    out = ASNOut.model_validate(asn)
    out.po_number = asn.po.number
    return out


# ─── Documentos ──────────────────────────────────────────────────────────────

@router.get("/documents", response_model=list[DocumentOut])
def pull_documents(
    po_number: str | None = None,
    pending: bool = Query(default=False, description="Solo documentos en validación"),
    db: Session = Depends(get_db),
):
    q = db.query(Document)
    if po_number:
        q = q.join(PurchaseOrder).filter(PurchaseOrder.number == po_number)
    if pending:
        q = q.filter(Document.status == "en_validacion")
    docs = q.order_by(Document.uploaded_at.desc()).all()
    out = []
    for d in docs:
        item = DocumentOut.model_validate(d)
        item.po_number = d.po.number
        out.append(item)
    return out


@router.patch("/documents/{doc_id}/review", response_model=DocumentOut)
def review_document(doc_id: int, payload: DocumentReviewIn, db: Session = Depends(get_db)):
    """Aprobación o rechazo del documento desde el ERP/equipo de revisión."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
    doc.status = payload.status
    doc.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(doc)
    item = DocumentOut.model_validate(doc)
    item.po_number = doc.po.number
    return item


# ─── CFDI → Cuentas por Pagar ────────────────────────────────────────────────

@router.get("/cfdi", response_model=list[CFDIOut])
def pull_cfdis(
    status_filter: CFDIStatus | None = Query(default=None, alias="status"),
    synced: bool | None = None,
    db: Session = Depends(get_db),
):
    """El ERP recupera CFDIs (p. ej. aprobados y no sincronizados) hacia CxP."""
    q = db.query(CFDI)
    if status_filter:
        q = q.filter(CFDI.status == status_filter)
    if synced is not None:
        q = q.filter(CFDI.erp_synced.is_(synced))
    cfdis = q.order_by(CFDI.created_at.desc()).all()
    out = []
    for c in cfdis:
        item = CFDIOut.model_validate(c)
        item.po_number = c.po.number if c.po else None
        out.append(item)
    return out


@router.post("/cfdi/{uuid}/synced", response_model=CFDIOut)
def mark_cfdi_synced(uuid: str, db: Session = Depends(get_db)):
    """El ERP confirma el registro del CFDI en Cuentas por Pagar."""
    cfdi = db.query(CFDI).filter(CFDI.uuid == uuid.upper()).first()
    if not cfdi:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CFDI no encontrado")
    cfdi.erp_synced = True
    db.commit()
    db.refresh(cfdi)
    return CFDIOut.model_validate(cfdi)


@router.patch("/cfdi/{uuid}/review", response_model=CFDIOut)
def review_cfdi(
    uuid: str,
    payload: CFDIReviewIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Resolución manual del 3-way match (aprobación, rechazo o programación de pago)."""
    cfdi = db.query(CFDI).filter(CFDI.uuid == uuid.upper()).first()
    if not cfdi:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CFDI no encontrado")
    cfdi.status = payload.status
    cfdi.rejection_reason = payload.rejection_reason
    if payload.due_date:
        cfdi.due_date = payload.due_date
    db.commit()
    db.refresh(cfdi)
    event = "cfdi.approved" if payload.status == CFDIStatus.APROBADA else "cfdi.rejected"
    if payload.status in (CFDIStatus.APROBADA, CFDIStatus.RECHAZADA):
        background.add_task(dispatch_event, event, {
            "uuid": cfdi.uuid,
            "status": cfdi.status.value,
            "rejection_reason": cfdi.rejection_reason,
        })
    return CFDIOut.model_validate(cfdi)


# ─── Pagos y Complemento de Pago (REP) ──────────────────────────────────────

@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def register_payment(payload: PaymentIn, db: Session = Depends(get_db)):
    """El ERP registra el pago realizado; el REP queda visible en el portal."""
    cfdi = db.query(CFDI).filter(CFDI.uuid == payload.cfdi_uuid.upper()).first()
    if not cfdi:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CFDI no encontrado")
    if payload.amount <= 0 or cfdi.paid_amount + payload.amount > cfdi.total + 0.01:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto de pago inválido o excede el saldo")

    payment = Payment(
        cfdi_id=cfdi.id,
        vendor_id=cfdi.vendor_id,
        amount=payload.amount,
        payment_date=payload.payment_date,
        bank_reference=payload.bank_reference,
        rep_uuid=payload.rep_uuid,
    )
    cfdi.paid_amount = round(cfdi.paid_amount + payload.amount, 2)
    cfdi.status = CFDIStatus.PAGADA if cfdi.paid_amount >= cfdi.total - 0.01 else CFDIStatus.PAGO_PARCIAL
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ─── Webhooks ────────────────────────────────────────────────────────────────

@router.post("/webhooks", response_model=WebhookSubscriptionOut, status_code=status.HTTP_201_CREATED)
def subscribe_webhook(payload: WebhookSubscriptionIn, db: Session = Depends(get_db)):
    """Suscribe al ERP a eventos del portal (notificación push en lugar de polling)."""
    sub = WebhookSubscription(url=payload.url, events=",".join(payload.events), secret=payload.secret)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/webhooks", response_model=list[WebhookSubscriptionOut])
def list_webhooks(db: Session = Depends(get_db)):
    return db.query(WebhookSubscription).all()


@router.delete("/webhooks/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(sub_id: int, db: Session = Depends(get_db)):
    sub = db.query(WebhookSubscription).filter(WebhookSubscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suscripción no encontrada")
    db.delete(sub)
    db.commit()
