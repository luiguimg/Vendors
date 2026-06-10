"""Esquemas Pydantic (entrada/salida de la API)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import ASNStatus, CFDIStatus, CFDIType, DocumentStatus, POStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Auth ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    vendor_code: str
    vendor_name: str


# ─── Proveedores ─────────────────────────────────────────────────────────────

class VendorOut(ORMModel):
    id: int
    code: str
    name: str
    rfc: str
    email: str
    payment_terms: str
    active: bool


class VendorUpsert(BaseModel):
    """Sincronización del maestro de proveedores desde el ERP."""
    code: str
    name: str
    rfc: str
    email: str
    payment_terms: str = "30 días"
    active: bool = True
    initial_password: str | None = None  # solo al crear


# ─── Órdenes de compra ───────────────────────────────────────────────────────

class POLineIn(BaseModel):
    line_no: int
    sku: str
    description: str
    quantity: float
    unit: str = "PZA"
    unit_price: float
    sat_product_key: str | None = None


class POLineOut(ORMModel):
    line_no: int
    sku: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    sat_product_key: str | None


class PurchaseOrderIn(BaseModel):
    """OC publicada por el ERP en el portal."""
    number: str
    vendor_code: str
    currency: str = "MXN"
    requested_date: date | None = None
    notes: str | None = None
    lines: list[POLineIn]


class PurchaseOrderOut(ORMModel):
    id: int
    number: str
    status: POStatus
    currency: str
    requested_date: date | None
    confirmed_date: date | None
    proposed_date: date | None
    proposed_date_reason: str | None
    total: float
    notes: str | None
    rejection_reason: str | None
    change_request: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[POLineOut] = []


class PurchaseOrderERPOut(PurchaseOrderOut):
    """Vista para el ERP: incluye al proveedor."""
    vendor: VendorOut


class POResponseIn(BaseModel):
    """Respuesta del proveedor a la OC."""
    action: str = Field(pattern="^(aceptar|rechazar|solicitar_cambio)$")
    reason: str | None = None          # obligatorio en rechazo / cambio
    confirmed_date: date | None = None  # al aceptar


class DateConfirmationIn(BaseModel):
    """Confirmación o contrapropuesta de fecha de entrega."""
    action: str = Field(pattern="^(confirmar|proponer)$")
    confirmed_date: date | None = None
    proposed_date: date | None = None
    reason: str | None = None


class POStatusUpdateIn(BaseModel):
    """Actualización de estatus (proveedor: producción; ERP: recibida/cancelada)."""
    status: POStatus
    reason: str | None = None


# ─── ASN ─────────────────────────────────────────────────────────────────────

class ASNLineIn(BaseModel):
    sku: str
    description: str
    quantity: float
    unit: str = "PZA"


class ASNLineOut(ORMModel):
    sku: str
    description: str
    quantity: float
    unit: str


class ASNIn(BaseModel):
    po_number: str
    shipment_type: str = Field(default="nacional", pattern="^(nacional|internacional)$")
    carrier_name: str
    carrier_rfc: str | None = None
    vehicle_plate: str | None = None
    driver_name: str | None = None
    pallets: int = 0
    weight_kg: float = 0.0
    ship_datetime: datetime | None = None
    eta: datetime | None = None
    tracking_number: str | None = None
    lines: list[ASNLineIn]


class ASNOut(ORMModel):
    id: int
    number: str
    status: ASNStatus
    shipment_type: str
    carrier_name: str
    carrier_rfc: str | None
    vehicle_plate: str | None
    driver_name: str | None
    pallets: int
    weight_kg: float
    ship_datetime: datetime | None
    eta: datetime | None
    tracking_number: str | None
    erp_acknowledged: bool
    created_at: datetime
    lines: list[ASNLineOut] = []
    po_number: str | None = None


# ─── Documentos ──────────────────────────────────────────────────────────────

class DocumentOut(ORMModel):
    id: int
    doc_type: str
    filename: str
    content_type: str
    size_bytes: int
    cfdi_uuid: str | None  # folio fiscal extraído del XML (Carta Porte / CFDI)
    status: DocumentStatus
    rejection_reason: str | None
    uploaded_at: datetime
    po_numbers: list[str] = []  # pedido o grupo de pedidos que ampara


class DocumentReviewIn(BaseModel):
    """Aprobación/rechazo desde el ERP o el equipo de Natureganix."""
    status: DocumentStatus
    rejection_reason: str | None = None


# ─── CFDI ────────────────────────────────────────────────────────────────────

class CFDIIn(BaseModel):
    """Carga de CFDI vía JSON (alternativa al upload de XML)."""
    uuid: str
    po_number: str | None = None
    cfdi_type: CFDIType = CFDIType.INGRESO
    serie_folio: str | None = None
    total: float
    currency: str = "MXN"
    payment_method: str = Field(default="PPD", pattern="^(PUE|PPD)$")


class PaymentOut(ORMModel):
    id: int
    amount: float
    payment_date: date
    bank_reference: str | None
    rep_uuid: str | None


class CFDIOut(ORMModel):
    id: int
    uuid: str
    cfdi_type: CFDIType
    serie_folio: str | None
    total: float
    currency: str
    payment_method: str
    status: CFDIStatus
    rejection_reason: str | None
    due_date: date | None
    paid_amount: float
    erp_synced: bool
    created_at: datetime
    payments: list[PaymentOut] = []
    po_number: str | None = None


class CFDIReviewIn(BaseModel):
    """Resolución del 3-way match desde CxP (ERP o revisor)."""
    status: CFDIStatus
    rejection_reason: str | None = None
    due_date: date | None = None


class PaymentIn(BaseModel):
    """Pago registrado por el ERP; publica el REP en el portal."""
    cfdi_uuid: str
    amount: float
    payment_date: date
    bank_reference: str | None = None
    rep_uuid: str | None = None


# ─── Estado de cuenta ────────────────────────────────────────────────────────

class AccountStatementOut(BaseModel):
    vendor: VendorOut
    total_pendiente: float
    total_programado: float
    total_pagado: float
    cfdis: list[CFDIOut]


# ─── Webhooks ────────────────────────────────────────────────────────────────

class WebhookSubscriptionIn(BaseModel):
    url: str
    events: list[str] = ["*"]
    secret: str


class WebhookSubscriptionOut(ORMModel):
    id: int
    url: str
    events: str
    active: bool
    created_at: datetime
