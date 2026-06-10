"""Datos de demostración: proveedor demo, API key del ERP y OCs de ejemplo."""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import (
    ApiKey, CFDI, CFDIStatus, CFDIType, Payment, POLine, POStatus,
    PurchaseOrder, Vendor,
)
from .security import generate_api_key, hash_api_key, hash_password

logger = logging.getLogger("portal.seed")

DEMO_ERP_KEY = "erp_demo_bc_natureganix_2026"


def seed(db: Session) -> None:
    if db.query(Vendor).first():
        return  # ya inicializado

    vendor = Vendor(
        code="PROV-001",
        name="Insumos Orgánicos del Bajío SA de CV",
        rfc="IOB150612AB1",
        email="proveedor@demo.com",
        password_hash=hash_password("demo123"),
        payment_terms="30 días",
    )
    db.add(vendor)

    # API key fija para pruebas (en producción, generar con generate_api_key())
    db.add(ApiKey(
        name="Business Central DEMO",
        key_hash=hash_api_key(DEMO_ERP_KEY),
        key_prefix=DEMO_ERP_KEY[:12],
    ))
    db.flush()

    today = date.today()

    po1 = PurchaseOrder(
        number="OC-2026-0101",
        vendor_id=vendor.id,
        status=POStatus.ENVIADA,
        requested_date=today + timedelta(days=21),
        notes="Entrega en almacén central. Requiere certificado de calidad.",
        lines=[
            POLine(line_no=1, sku="ORG-CHIA-25", description="Semilla de chía orgánica 25 kg", quantity=40, unit="SAC", unit_price=1850.0, sat_product_key="10331701"),
            POLine(line_no=2, sku="ORG-AMAR-25", description="Amaranto orgánico 25 kg", quantity=20, unit="SAC", unit_price=1420.0, sat_product_key="10331702"),
        ],
    )
    po1.total = 40 * 1850.0 + 20 * 1420.0

    po2 = PurchaseOrder(
        number="OC-2026-0096",
        vendor_id=vendor.id,
        status=POStatus.CONFIRMADA,
        requested_date=today + timedelta(days=10),
        confirmed_date=today + timedelta(days=12),
        lines=[
            POLine(line_no=1, sku="ORG-MIEL-01", description="Miel orgánica multifloral 1 kg", quantity=500, unit="PZA", unit_price=145.0, sat_product_key="50161509"),
        ],
    )
    po2.total = 500 * 145.0

    po3 = PurchaseOrder(
        number="OC-2026-0088",
        vendor_id=vendor.id,
        status=POStatus.RECIBIDA,
        requested_date=today - timedelta(days=20),
        confirmed_date=today - timedelta(days=18),
        lines=[
            POLine(line_no=1, sku="ORG-CACAO-10", description="Cacao orgánico en grano 10 kg", quantity=80, unit="CJA", unit_price=2200.0, sat_product_key="50221301"),
        ],
    )
    po3.total = 80 * 2200.0
    db.add_all([po1, po2, po3])
    db.flush()

    # CFDI aprobado y con pago parcial sobre la OC recibida
    cfdi = CFDI(
        vendor_id=vendor.id,
        po_id=po3.id,
        uuid="A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D",
        cfdi_type=CFDIType.INGRESO,
        serie_folio="A-1042",
        total=po3.total,
        status=CFDIStatus.PAGO_PARCIAL,
        due_date=today + timedelta(days=10),
        paid_amount=100000.0,
        erp_synced=True,
    )
    db.add(cfdi)
    db.flush()
    db.add(Payment(
        cfdi_id=cfdi.id,
        vendor_id=vendor.id,
        amount=100000.0,
        payment_date=today - timedelta(days=3),
        bank_reference="SPEI-7781234",
        rep_uuid="F9E8D7C6-B5A4-4321-9876-543210FEDCBA",
    ))

    db.commit()
    logger.info("Datos demo creados. Proveedor: proveedor@demo.com / demo123 · API Key ERP: %s", DEMO_ERP_KEY)
