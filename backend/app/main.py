"""Portal de Proveedores — Natureganix.

Aplicación FastAPI que sirve:
  · API del portal (proveedores)     →  /api/v1/...
  · API de integración ERP           →  /api/erp/v1/...  (X-API-Key)
  · Documentación OpenAPI            →  /docs  y  /redoc
  · Frontend (SPA)                   →  /
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .routers import asn, auth, cfdi, documents, erp, payments, purchase_orders
from .seed import seed

app = FastAPI(
    title="Portal de Proveedores — Natureganix",
    description=(
        "Plataforma de colaboración con proveedores: órdenes de compra, "
        "confirmación de fechas, embarques (ASN), documentación (incluida la Carta Porte "
        "timbrada externamente), CFDI y estado de cuenta.\n\n"
        "**Integración ERP**: los endpoints bajo `/api/erp/v1` están diseñados para "
        "conectarse con Business Central u otros ERPs mediante API Key (`X-API-Key`) "
        "y webhooks salientes firmados con HMAC-SHA256."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, purchase_orders, asn, documents, cfdi, payments, erp):
    app.include_router(module.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@app.get("/api/health", tags=["Sistema"])
def health():
    return {"status": "ok", "service": "portal-proveedores"}


# El frontend se sirve al final para no interceptar las rutas /api
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
