"""Modelos de datos del Portal de Proveedores."""
import enum
from datetime import datetime, date

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String,
    Table, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ─── Enumeraciones de estatus (según diseño funcional) ──────────────────────

class POStatus(str, enum.Enum):
    ENVIADA = "enviada"
    EN_REVISION = "en_revision"
    CONFIRMADA = "confirmada"
    RECHAZADA = "rechazada"
    MODIFICACION_SOLICITADA = "modificacion_solicitada"
    EN_PRODUCCION = "en_produccion"
    EMBARCADA = "embarcada"
    RECIBIDA = "recibida"
    CANCELADA = "cancelada"


class ASNStatus(str, enum.Enum):
    BORRADOR = "borrador"
    ENVIADO = "enviado"
    EN_TRANSITO = "en_transito"
    RECIBIDO = "recibido"


class DocumentStatus(str, enum.Enum):
    EN_VALIDACION = "en_validacion"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"


class CFDIType(str, enum.Enum):
    INGRESO = "ingreso"
    EGRESO = "egreso"
    TRASLADO = "traslado"
    PAGO = "pago"


class CFDIStatus(str, enum.Enum):
    EN_VALIDACION = "en_validacion"
    RECHAZADA = "rechazada"
    APROBADA = "aprobada"
    PROGRAMADA = "programada"
    PAGADA = "pagada"
    PAGO_PARCIAL = "pago_parcial"


# ─── Maestros ────────────────────────────────────────────────────────────────

class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # No. proveedor en ERP
    name: Mapped[str] = mapped_column(String(200))
    rfc: Mapped[str] = mapped_column(String(13), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    session_token: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    payment_terms: Mapped[str] = mapped_column(String(50), default="30 días")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")


class ApiKey(Base):
    """Credenciales de sistemas externos (ERP) para la API de integración."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # ej. "Business Central PROD"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12))  # visible para identificar la llave
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─── Órdenes de compra ───────────────────────────────────────────────────────

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # No. OC en ERP
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus), default=POStatus.ENVIADA, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    requested_date: Mapped[date | None] = mapped_column(Date)   # fecha solicitada por compras
    confirmed_date: Mapped[date | None] = mapped_column(Date)   # fecha comprometida por proveedor
    total: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    change_request: Mapped[str | None] = mapped_column(Text)
    proposed_date: Mapped[date | None] = mapped_column(Date)    # contrapropuesta de fecha
    proposed_date_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor: Mapped["Vendor"] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["POLine"]] = relationship(back_populates="po", cascade="all, delete-orphan")
    asns: Mapped[list["ASN"]] = relationship(back_populates="po")
    documents: Mapped[list["Document"]] = relationship(
        secondary="document_purchase_orders", back_populates="pos",
    )
    cfdis: Mapped[list["CFDI"]] = relationship(back_populates="po")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="PZA")
    unit_price: Mapped[float] = mapped_column(Float)
    sat_product_key: Mapped[str | None] = mapped_column(String(10))  # clave producto SAT

    po: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


# ─── Embarques (ASN) y Carta Porte ───────────────────────────────────────────

class ASN(Base):
    """Advanced Shipping Notice — aviso anticipado de embarque."""
    __tablename__ = "asns"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[ASNStatus] = mapped_column(Enum(ASNStatus), default=ASNStatus.ENVIADO)
    shipment_type: Mapped[str] = mapped_column(String(15), default="nacional")  # nacional | internacional
    carrier_name: Mapped[str] = mapped_column(String(200))
    carrier_rfc: Mapped[str | None] = mapped_column(String(13))
    vehicle_plate: Mapped[str | None] = mapped_column(String(15))
    driver_name: Mapped[str | None] = mapped_column(String(150))
    pallets: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    ship_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    eta: Mapped[datetime | None] = mapped_column(DateTime)
    tracking_number: Mapped[str | None] = mapped_column(String(60))  # guía / BL / AWB
    erp_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)  # WMS creó recibo esperado
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="asns")
    lines: Mapped[list["ASNLine"]] = relationship(back_populates="asn", cascade="all, delete-orphan")


class ASNLine(Base):
    __tablename__ = "asn_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    asn_id: Mapped[int] = mapped_column(ForeignKey("asns.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="PZA")

    asn: Mapped["ASN"] = relationship(back_populates="lines")


# ─── Documentación y CFDI ────────────────────────────────────────────────────

document_purchase_orders = Table(
    "document_purchase_orders",
    Base.metadata,
    Column("document_id", ForeignKey("documents.id"), primary_key=True),
    Column("po_id", ForeignKey("purchase_orders.id"), primary_key=True),
)


class Document(Base):
    """Expediente digital: packing list, certificados, pedimentos, Carta Porte, etc.

    Un documento puede amparar un pedido o un grupo de pedidos (p. ej. una
    Carta Porte consolidada que cubre varias OC en un mismo embarque).
    Los CFDI de traslado / Carta Porte se timbran fuera del portal: el
    proveedor carga aquí el XML ya timbrado y el portal valida su estructura
    y extrae el folio fiscal (UUID).
    """
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(50))  # packing_list, carta_porte, pedimento, ...
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(500))
    cfdi_uuid: Mapped[str | None] = mapped_column(String(36), index=True)  # folio fiscal del XML cargado
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.EN_VALIDACION)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    pos: Mapped[list["PurchaseOrder"]] = relationship(
        secondary=document_purchase_orders, back_populates="documents",
    )


class CFDI(Base):
    __tablename__ = "cfdis"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    cfdi_type: Mapped[CFDIType] = mapped_column(Enum(CFDIType), default=CFDIType.INGRESO)
    serie_folio: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    payment_method: Mapped[str] = mapped_column(String(3), default="PPD")  # PUE | PPD
    status: Mapped[CFDIStatus] = mapped_column(Enum(CFDIStatus), default=CFDIStatus.EN_VALIDACION, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    xml_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    due_date: Mapped[date | None] = mapped_column(Date)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    erp_synced: Mapped[bool] = mapped_column(Boolean, default=False)  # registrado en CxP del ERP
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    po: Mapped["PurchaseOrder | None"] = relationship(back_populates="cfdis")
    payments: Mapped[list["Payment"]] = relationship(back_populates="cfdi")


class Payment(Base):
    """Pago realizado por Natureganix; genera el Complemento de Pago (REP)."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    cfdi_id: Mapped[int] = mapped_column(ForeignKey("cfdis.id"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[date] = mapped_column(Date)
    bank_reference: Mapped[str | None] = mapped_column(String(60))
    rep_uuid: Mapped[str | None] = mapped_column(String(36))  # folio fiscal del Complemento de Pago
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cfdi: Mapped["CFDI"] = relationship(back_populates="payments")


# ─── Webhooks de integración ─────────────────────────────────────────────────

class WebhookSubscription(Base):
    """Suscripción del ERP a eventos del portal (po.confirmed, asn.created, ...)."""
    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[str] = mapped_column(String(500))  # CSV de eventos, "*" = todos
    secret: Mapped[str] = mapped_column(String(64))   # firma HMAC-SHA256
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("webhook_subscriptions.id"), index=True)
    event: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
