"""Centro de documentación: expediente digital por OC."""
import os
import uuid as uuid_lib

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


def _serialize(doc: Document) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.po_number = doc.po.number
    return out


@router.get("", response_model=list[DocumentOut])
def list_documents(
    po_number: str | None = None,
    vendor: Vendor = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    q = db.query(Document).filter(Document.vendor_id == vendor.id)
    if po_number:
        q = q.join(PurchaseOrder).filter(PurchaseOrder.number == po_number)
    return [_serialize(d) for d in q.order_by(Document.uploaded_at.desc()).all()]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    po_number: str = Form(...),
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
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.number == po_number, PurchaseOrder.vendor_id == vendor.id,
    ).first()
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Orden de compra no encontrada")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid_lib.uuid4().hex}_{os.path.basename(file.filename or 'documento')}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(path, "wb") as fh:
        fh.write(content)

    doc = Document(
        po_id=po.id,
        vendor_id=vendor.id,
        doc_type=doc_type,
        filename=file.filename or safe_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_path=path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background.add_task(dispatch_event, "document.uploaded", {
        "document_id": doc.id,
        "po_number": po.number,
        "vendor_code": vendor.code,
        "doc_type": doc.doc_type,
        "filename": doc.filename,
    })
    return _serialize(doc)


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
