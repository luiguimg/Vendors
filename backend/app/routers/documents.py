"""Centro de documentación: expediente digital por pedido o grupo de pedidos.

Incluye la carga de la Carta Porte: el portal NO genera ni timbra CFDIs de
traslado — el proveedor timbra con su PAC y carga aquí el XML resultante.
El portal valida la estructura (CFDI con complemento Carta Porte y timbre),
extrae el folio fiscal (UUID) y rechaza duplicados.
"""
import os
import re
import uuid as uuid_lib
import xml.etree.ElementTree as ET

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, PurchaseOrder, Vendor
from ..schemas import DocumentOut
from ..security import get_current_vendor
from ..webhooks import dispatch_event

router = APIRouter(prefix="/api/v1/documents", tags=["Portal · Documentos"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")

DOC_TYPES = {
    "acuse_confirmacion", "asn", "packing_list", "carta_porte", "bl_awb",
    "certificado_calidad", "cfdi_ingreso", "pedimento", "permiso_sanitario",
    "nota_credito", "otro",
}

# Tipos que admiten XML fiscal; si se carga XML se valida y se extrae el UUID
FISCAL_XML_TYPES = {"carta_porte", "cfdi_ingreso", "nota_credito"}

TFD_TAG = "{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital"


def serialize(doc: Document) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.po_numbers = [po.number for po in doc.pos]
    return out


def _validate_fiscal_xml(content: bytes, doc_type: str) -> str:
    """Valida un XML timbrado y devuelve su folio fiscal (UUID).

    Para `carta_porte` exige CFDI de tipo Traslado (T) o Ingreso (I) con el
    complemento Carta Porte. No sustituye la verificación ante el SAT: valida
    estructura y timbre para rechazar cargas erróneas de inmediato.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El archivo no es un XML válido")

    if not root.tag.endswith("}Comprobante"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El XML no es un CFDI (nodo Comprobante no encontrado)")

    tfd = next((el for el in root.iter(TFD_TAG)), None)
    if tfd is None or not tfd.get("UUID"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El CFDI no está timbrado (sin Timbre Fiscal Digital). Timbra con tu PAC antes de cargarlo.",
        )
    cfdi_uuid = tfd.get("UUID").upper()
    if not re.match(r"^[0-9A-F]{8}-([0-9A-F]{4}-){3}[0-9A-F]{12}$", cfdi_uuid):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Folio fiscal (UUID) con formato inválido")

    if doc_type == "carta_porte":
        tipo = root.get("TipoDeComprobante", "")
        if tipo not in ("T", "I"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"La Carta Porte debe ser CFDI de Traslado (T) o Ingreso (I); se recibió tipo '{tipo}'",
            )
        if not any("CartaPorte" in el.tag for el in root.iter()):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El CFDI no contiene el complemento Carta Porte",
            )
    return cfdi_uuid


@router.get("", response_model=list[DocumentOut])
def list_documents(
    po_number: str | None = None,
    doc_type: str | None = None,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    q = db.query(Document).filter(Document.vendor_id == vendor.id)
    if po_number:
        q = q.join(Document.pos).filter(PurchaseOrder.number == po_number)
    if doc_type:
        q = q.filter(Document.doc_type == doc_type)
    return [serialize(d) for d in q.order_by(Document.uploaded_at.desc()).all()]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    po_numbers: str = Form(..., description="Pedido o grupo de pedidos, separados por coma"),
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    if doc_type not in DOC_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Tipo de documento inválido. Permitidos: {', '.join(sorted(DOC_TYPES))}",
        )

    numbers = [n.strip() for n in po_numbers.split(",") if n.strip()]
    if not numbers:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica al menos un pedido")
    pos = db.query(PurchaseOrder).filter(
        PurchaseOrder.number.in_(numbers), PurchaseOrder.vendor_id == vendor.id,
    ).all()
    missing = set(numbers) - {po.number for po in pos}
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Pedidos no encontrados o no pertenecen al proveedor: {', '.join(sorted(missing))}",
        )

    content = await file.read()
    filename = file.filename or "documento"

    cfdi_uuid = None
    is_xml = filename.lower().endswith(".xml") or (file.content_type or "").endswith("xml")
    if doc_type in FISCAL_XML_TYPES and is_xml:
        cfdi_uuid = _validate_fiscal_xml(content, doc_type)
        duplicate = db.query(Document).filter(Document.cfdi_uuid == cfdi_uuid).first()
        if duplicate:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Ya existe un documento con el folio fiscal {cfdi_uuid}",
            )
    elif doc_type == "carta_porte" and not is_xml and not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La Carta Porte debe cargarse como XML timbrado (o su representación impresa en PDF)",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid_lib.uuid4().hex}_{os.path.basename(filename)}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    with open(path, "wb") as fh:
        fh.write(content)

    doc = Document(
        vendor_id=vendor.id,
        doc_type=doc_type,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_path=path,
        cfdi_uuid=cfdi_uuid,
        pos=pos,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background.add_task(dispatch_event, "document.uploaded", {
        "document_id": doc.id,
        "po_numbers": [po.number for po in pos],
        "vendor_code": vendor.code,
        "doc_type": doc.doc_type,
        "filename": doc.filename,
        "cfdi_uuid": cfdi_uuid,
    })
    return serialize(doc)


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id, Document.vendor_id == vendor.id).first()
    if not doc or not os.path.exists(doc.storage_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
    return FileResponse(doc.storage_path, filename=doc.filename, media_type=doc.content_type)
