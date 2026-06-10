"""Datos de demostración: proveedor demo, API key del ERP y ejemplos en todos los módulos.

Se ejecuta al primer arranque (o tras cada reinicio en hosting con disco efímero),
poblando el ciclo completo: OCs en todos los estatus, ASN con Carta Porte timbrada,
expediente documental, CFDIs en cada etapa y pagos con Complemento de Pago (REP).
"""
import logging
import os
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import (
    ASN, ASNLine, ApiKey, CFDI, CFDIStatus, CFDIType, Document,
    DocumentStatus, Payment, POLine, POStatus, PurchaseOrder, Vendor,
)
from .security import hash_api_key, hash_password

logger = logging.getLogger("portal.seed")

DEMO_ERP_KEY = "erp_demo_bc_natureganix_2026"
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")


def _demo_file(name: str, text: str) -> str:
    """Crea un archivo de demostración en UPLOAD_DIR y devuelve su ruta."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def seed(db: Session) -> None:
    if db.query(Vendor).first():
        return  # ya inicializado

    today = date.today()
    now = datetime.utcnow()

    # ─── Maestros ────────────────────────────────────────────────────────
    vendor = Vendor(
        code="PROV-001",
        name="Insumos Orgánicos del Bajío SA de CV",
        rfc="IOB150612AB1",
        email="proveedor@demo.com",
        password_hash=hash_password("demo123"),
        payment_terms="30 días",
    )
    vendor2 = Vendor(
        code="PROV-002",
        name="Empaques Sustentables de Occidente SA de CV",
        rfc="ESO180304CD2",
        email="proveedor2@demo.com",
        password_hash=hash_password("demo123"),
        payment_terms="45 días",
    )
    db.add_all([vendor, vendor2])

    # API key fija para pruebas (en producción, generar con generate_api_key())
    db.add(ApiKey(
        name="Business Central DEMO",
        key_hash=hash_api_key(DEMO_ERP_KEY),
        key_prefix=DEMO_ERP_KEY[:12],
    ))
    db.flush()

    # ─── Órdenes de compra en todos los estatus ──────────────────────────
    def make_po(number, status, lines, *, req_days=None, conf_days=None, **extra):
        po = PurchaseOrder(
            number=number,
            vendor_id=vendor.id,
            status=status,
            requested_date=today + timedelta(days=req_days) if req_days is not None else None,
            confirmed_date=today + timedelta(days=conf_days) if conf_days is not None else None,
            lines=[POLine(**l) for l in lines],
            **extra,
        )
        po.total = round(sum(l["quantity"] * l["unit_price"] for l in lines), 2)
        return po

    po_enviada = make_po("OC-2026-0101", POStatus.ENVIADA, [
        dict(line_no=1, sku="ORG-CHIA-25", description="Semilla de chía orgánica 25 kg", quantity=40, unit="SAC", unit_price=1850.0, sat_product_key="10331701"),
        dict(line_no=2, sku="ORG-AMAR-25", description="Amaranto orgánico 25 kg", quantity=20, unit="SAC", unit_price=1420.0, sat_product_key="10331702"),
    ], req_days=21, notes="Entrega en almacén central. Requiere certificado de calidad.")

    po_revision = make_po("OC-2026-0102", POStatus.EN_REVISION, [
        dict(line_no=1, sku="ORG-QUIN-10", description="Quinoa orgánica tricolor 10 kg", quantity=60, unit="CJA", unit_price=980.0, sat_product_key="10331703"),
    ], req_days=28, notes="Producto de temporada; confirmar disponibilidad.")

    po_confirmada = make_po("OC-2026-0096", POStatus.CONFIRMADA, [
        dict(line_no=1, sku="ORG-MIEL-01", description="Miel orgánica multifloral 1 kg", quantity=500, unit="PZA", unit_price=145.0, sat_product_key="50161509"),
    ], req_days=10, conf_days=12)

    po_produccion = make_po("OC-2026-0095", POStatus.EN_PRODUCCION, [
        dict(line_no=1, sku="ORG-AGAVE-05", description="Jarabe de agave orgánico 5 L", quantity=120, unit="GRF", unit_price=620.0, sat_product_key="50161901"),
        dict(line_no=2, sku="ORG-COCO-01", description="Aceite de coco orgánico 1 L", quantity=200, unit="PZA", unit_price=310.0, sat_product_key="50151513"),
    ], req_days=7, conf_days=7)

    po_embarcada = make_po("OC-2026-0090", POStatus.EMBARCADA, [
        dict(line_no=1, sku="ORG-CAFE-69", description="Café orgánico de altura 69 kg", quantity=30, unit="SAC", unit_price=4850.0, sat_product_key="50201706"),
    ], req_days=2, conf_days=2)

    po_recibida = make_po("OC-2026-0088", POStatus.RECIBIDA, [
        dict(line_no=1, sku="ORG-CACAO-10", description="Cacao orgánico en grano 10 kg", quantity=80, unit="CJA", unit_price=2200.0, sat_product_key="50221301"),
    ], req_days=-20, conf_days=-18)

    po_recibida2 = make_po("OC-2026-0085", POStatus.RECIBIDA, [
        dict(line_no=1, sku="ORG-VAIN-01", description="Extracto de vainilla orgánica 1 L", quantity=90, unit="PZA", unit_price=890.0, sat_product_key="50171550"),
    ], req_days=-35, conf_days=-33)

    po_rechazada = make_po("OC-2026-0099", POStatus.RECHAZADA, [
        dict(line_no=1, sku="ORG-SPIR-05", description="Espirulina orgánica en polvo 5 kg", quantity=50, unit="CJA", unit_price=3400.0, sat_product_key="51191905"),
    ], req_days=5, rejection_reason="Sin capacidad de producción para la fecha solicitada; reabrir con entrega a 30 días.")

    po_modif = make_po("OC-2026-0100", POStatus.MODIFICACION_SOLICITADA, [
        dict(line_no=1, sku="ORG-AJON-25", description="Ajonjolí orgánico natural 25 kg", quantity=100, unit="SAC", unit_price=1150.0, sat_product_key="10331704"),
    ], req_days=14, change_request="Solicito ajustar a 80 sacos: inventario de materia prima limitado este mes.")

    db.add_all([
        po_enviada, po_revision, po_confirmada, po_produccion,
        po_embarcada, po_recibida, po_recibida2, po_rechazada, po_modif,
    ])
    db.flush()

    # ─── ASN: nacional con Carta Porte timbrada + internacional en tránsito ──
    asn_nacional = ASN(
        number="ASN-00001",
        po_id=po_embarcada.id,
        vendor_id=vendor.id,
        shipment_type="nacional",
        carrier_name="Transportes del Bajío SA de CV",
        carrier_rfc="TBA010101AB1",
        vehicle_plate="ABC-123-X",
        driver_name="José Luis Hernández",
        pallets=15,
        weight_kg=2070.0,
        ship_datetime=now - timedelta(hours=6),
        eta=now + timedelta(hours=18),
        tracking_number="GUIA-MX-44521",
        erp_acknowledged=True,
        lines=[ASNLine(sku="ORG-CAFE-69", description="Café orgánico de altura 69 kg", quantity=30, unit="SAC")],
    )
    asn_internacional = ASN(
        number="ASN-00002",
        po_id=po_recibida.id,
        vendor_id=vendor.id,
        shipment_type="internacional",
        carrier_name="Pacific Cargo Lines",
        vehicle_plate=None,
        pallets=8,
        weight_kg=820.0,
        ship_datetime=now - timedelta(days=22),
        eta=now - timedelta(days=19),
        tracking_number="BL-PCL-88273",
        erp_acknowledged=True,
        lines=[ASNLine(sku="ORG-CACAO-10", description="Cacao orgánico en grano 10 kg", quantity=80, unit="CJA")],
    )
    db.add_all([asn_nacional, asn_internacional])
    db.flush()

    # ─── Expediente documental ───────────────────────────────────────────
    # La Carta Porte se timbra fuera del portal: el proveedor carga el XML
    # ya timbrado. Un documento puede amparar un pedido o un grupo de pedidos.
    def carta_porte_xml(uuid_: str, plate: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:cartaporte31="http://www.sat.gob.mx/CartaPorte31"
    Version="4.0" TipoDeComprobante="T" Fecha="{(now - timedelta(hours=7)).isoformat()}"
    LugarExpedicion="38000">
  <cfdi:Emisor Rfc="IOB150612AB1" Nombre="Insumos Organicos del Bajio" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="IOB150612AB1" Nombre="Insumos Organicos del Bajio" UsoCFDI="S01"
      DomicilioFiscalReceptor="38000" RegimenFiscalReceptor="601"/>
  <cfdi:Complemento>
    <cartaporte31:CartaPorte Version="3.1" TranspInternac="No" TotalDistRec="185">
      <cartaporte31:Mercancias PesoBrutoTotal="2070" UnidadPeso="KGM" NumTotalMercancias="1">
        <cartaporte31:Autotransporte PermSCT="TPAF01" NumPermisoSCT="DEMO-001">
          <cartaporte31:IdentificacionVehicular ConfigVehicular="T3S2"
              PlacaVM="{plate}" AnioModeloVM="2022"/>
        </cartaporte31:Autotransporte>
      </cartaporte31:Mercancias>
    </cartaporte31:CartaPorte>
    <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
        Version="1.1" UUID="{uuid_}" FechaTimbrado="{(now - timedelta(hours=7)).isoformat()}"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""

    docs = [
        # (doc_type, filename, status, motivo_rechazo, [pedidos], cfdi_uuid, contenido)
        ("carta_porte", "CartaPorte-OC-2026-0090.xml", DocumentStatus.APROBADO, None,
         [po_embarcada], "C4F3A2B1-9D8E-4C7B-A615-2F3E4D5C6B7A",
         carta_porte_xml("C4F3A2B1-9D8E-4C7B-A615-2F3E4D5C6B7A", "ABC-123-X")),
        # Carta Porte consolidada: un solo traslado ampara dos pedidos
        ("carta_porte", "CartaPorte-Consolidada-0085-0088.xml", DocumentStatus.EN_VALIDACION, None,
         [po_recibida, po_recibida2], "D5E4F3A2-1B0C-4D9E-B726-3A4B5C6D7E8F",
         carta_porte_xml("D5E4F3A2-1B0C-4D9E-B726-3A4B5C6D7E8F", "XYZ-987-A")),
        ("packing_list", "Packing-List-ASN-00001.txt", DocumentStatus.APROBADO, None,
         [po_embarcada], None,
         "PACKING LIST — ASN-00001\nOC-2026-0090 · 30 sacos café orgánico 69 kg · 15 pallets · 2,070 kg"),
        ("certificado_calidad", "Certificado-Calidad-Cafe.txt", DocumentStatus.APROBADO, None,
         [po_embarcada], None,
         "CERTIFICADO DE ANÁLISIS\nLote CAF-2026-118 · Humedad 11.2% · Sin residuos detectados · Cumple NOM"),
        ("cfdi_ingreso", "Factura-A-1042.txt", DocumentStatus.APROBADO, None,
         [po_recibida], None,
         "REPRESENTACIÓN IMPRESA CFDI — Serie A Folio 1042\nTotal: $176,000.00 MXN"),
        ("pedimento", "Pedimento-3801-6004421.txt", DocumentStatus.EN_VALIDACION, None,
         [po_recibida], None,
         "PEDIMENTO DE IMPORTACIÓN 26 48 3801 6004421\nAduana: Manzanillo · Régimen: A1"),
        ("certificado_calidad", "Certificado-Vainilla.txt", DocumentStatus.RECHAZADO,
         "El certificado no incluye el número de lote; reemitir con lote VAI-2026-077.",
         [po_recibida2], None,
         "CERTIFICADO DE ANÁLISIS — Extracto de vainilla (sin número de lote)"),
    ]
    for doc_type, filename, doc_status, reason, pos, cfdi_uuid, content in docs:
        path = _demo_file(filename, content)
        db.add(Document(
            vendor_id=vendor.id,
            doc_type=doc_type,
            filename=filename,
            content_type="text/xml" if filename.endswith(".xml") else "text/plain",
            size_bytes=os.path.getsize(path),
            storage_path=path,
            cfdi_uuid=cfdi_uuid,
            status=doc_status,
            rejection_reason=reason,
            pos=pos,
        ))

    # ─── CFDIs en cada etapa del flujo ───────────────────────────────────
    cfdi_parcial = CFDI(
        vendor_id=vendor.id, po_id=po_recibida.id,
        uuid="A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D",
        cfdi_type=CFDIType.INGRESO, serie_folio="A-1042",
        total=po_recibida.total, status=CFDIStatus.PAGO_PARCIAL,
        due_date=today + timedelta(days=10), paid_amount=100000.0, erp_synced=True,
    )
    cfdi_pagada = CFDI(
        vendor_id=vendor.id, po_id=po_recibida2.id,
        uuid="B2C3D4E5-F6A7-4B8C-9D0E-1F2A3B4C5D6E",
        cfdi_type=CFDIType.INGRESO, serie_folio="A-1029",
        total=po_recibida2.total, status=CFDIStatus.PAGADA,
        due_date=today - timedelta(days=5), paid_amount=po_recibida2.total, erp_synced=True,
    )
    cfdi_aprobada = CFDI(
        vendor_id=vendor.id, po_id=po_recibida.id,
        uuid="C3D4E5F6-A7B8-4C9D-0E1F-2A3B4C5D6E7F",
        cfdi_type=CFDIType.EGRESO, serie_folio="NC-088",
        total=8800.0, status=CFDIStatus.APROBADA,
        due_date=today + timedelta(days=25), erp_synced=True,
    )
    cfdi_programada = CFDI(
        vendor_id=vendor.id, po_id=po_recibida2.id,
        uuid="D4E5F6A7-B8C9-4D0E-1F2A-3B4C5D6E7F80",
        cfdi_type=CFDIType.INGRESO, serie_folio="A-1031",
        total=12500.0, status=CFDIStatus.PROGRAMADA,
        due_date=today + timedelta(days=3), erp_synced=True,
    )
    cfdi_validacion = CFDI(
        vendor_id=vendor.id, po_id=po_embarcada.id,
        uuid="E5F6A7B8-C9D0-4E1F-2A3B-4C5D6E7F8091",
        cfdi_type=CFDIType.INGRESO, serie_folio="A-1050",
        total=po_embarcada.total, status=CFDIStatus.EN_VALIDACION,
    )
    cfdi_rechazada = CFDI(
        vendor_id=vendor.id, po_id=po_recibida.id,
        uuid="F6A7B8C9-D0E1-4F2A-3B4C-5D6E7F809102",
        cfdi_type=CFDIType.INGRESO, serie_folio="A-1043",
        total=180000.0, status=CFDIStatus.RECHAZADA,
        rejection_reason="Monto del CFDI (180,000.00) no coincide con la OC (176,000.00)",
    )
    db.add_all([
        cfdi_parcial, cfdi_pagada, cfdi_aprobada,
        cfdi_programada, cfdi_validacion, cfdi_rechazada,
    ])
    db.flush()

    # ─── Pagos con Complemento de Pago (REP) ─────────────────────────────
    db.add_all([
        Payment(
            cfdi_id=cfdi_parcial.id, vendor_id=vendor.id,
            amount=100000.0, payment_date=today - timedelta(days=3),
            bank_reference="SPEI-7781234",
            rep_uuid="F9E8D7C6-B5A4-4321-9876-543210FEDCBA",
        ),
        Payment(
            cfdi_id=cfdi_pagada.id, vendor_id=vendor.id,
            amount=po_recibida2.total, payment_date=today - timedelta(days=8),
            bank_reference="SPEI-7765410",
            rep_uuid="E8D7C6B5-A493-4210-8765-43210FEDCBA9",
        ),
    ])

    db.commit()
    logger.info(
        "Datos demo creados. Proveedor: proveedor@demo.com / demo123 · API Key ERP: %s",
        DEMO_ERP_KEY,
    )
