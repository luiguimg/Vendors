# Portal de Proveedores — Natureganix

Plataforma web de colaboración entre proveedores y Business Central (u otro ERP):
gestión de órdenes de compra, confirmación de fechas de entrega, embarques (ASN),
Carta Porte, expediente documental, CFDI y estado de cuenta — con una **API REST de
integración para ERPs** (API Key + webhooks).

## Arquitectura

```
┌─────────────┐     /api/v1 (Bearer)      ┌──────────────────────┐
│  Proveedor  │ ────────────────────────► │  Portal (FastAPI)    │
│  (SPA web)  │                           │  · OC / Fechas       │
└─────────────┘                           │  · ASN / Carta Porte │
                                          │  · Documentos / CFDI │
┌─────────────┐   /api/erp/v1 (X-API-Key) │  · Estado de cuenta  │
│  ERP (BC)   │ ◄───────────────────────► │  SQLite/SQLAlchemy   │
│  WMS / CxP  │ ◄── webhooks (HMAC) ───── └──────────────────────┘
└─────────────┘
```

## Ejecución

```bash
pip install -r requirements.txt
python run.py            # http://localhost:8000
```

| Recurso | URL |
|---|---|
| Portal (frontend) | http://localhost:8000/ |
| Documentación OpenAPI (Swagger) | http://localhost:8000/docs |
| Documentación ReDoc | http://localhost:8000/redoc |

**Credenciales demo** (se crean automáticamente al primer arranque):

- Proveedor: `proveedor@demo.com` / `demo123`
- API Key ERP: `erp_demo_bc_natureganix_2026` (header `X-API-Key`)

Variables de entorno: `PORT`, `HOST`, `DATABASE_URL` (por defecto SQLite local),
`UPLOAD_DIR` (almacenamiento de documentos).

## Módulos del portal (API `/api/v1`, autenticación Bearer)

| Módulo | Endpoints | Descripción |
|---|---|---|
| Autenticación | `POST /auth/login`, `/auth/logout`, `GET /auth/me` | Sesión del proveedor |
| Órdenes de compra | `GET /purchase-orders`, `POST /{id}/respond`, `POST /{id}/confirm-date`, `POST /{id}/status` | Aceptar/rechazar/solicitar cambio; confirmar o proponer fecha; marcar producción |
| Embarques | `GET/POST /asn` | ASN con líneas, transportista y ETA; valida SKUs contra la OC |
| Documentos / Carta Porte | `GET/POST /documents`, `GET /documents/{id}/download` | Expediente digital por **pedido o grupo de pedidos**. La Carta Porte se timbra fuera del portal: el proveedor carga el XML timbrado y el portal valida estructura, complemento y timbre, extrae el folio fiscal (UUID) y rechaza duplicados |
| CFDI | `GET/POST /cfdi` | Validación de UUID, duplicados, método de pago y **3-way match** (OC vs recibo vs factura) |
| Estado de cuenta | `GET /account-statement` | Saldos, vencimientos, pagos y Complementos de Pago (REP) |

### Estatus de la OC

`enviada → en_revision → confirmada → en_produccion → embarcada → recibida`,
con ramas `rechazada`, `modificacion_solicitada` y `cancelada` — igual al diseño
funcional del portal.

## API de integración ERP (`/api/erp/v1`, header `X-API-Key`)

Flujo típico con Business Central:

1. **Maestro de proveedores** — `PUT /vendors` (idempotente por código de proveedor).
2. **Publicar OC** — `POST /purchase-orders`; el portal calcula el total y la deja en `enviada`.
3. **Recuperar respuestas** — `GET /purchase-orders?status=confirmada&updated_since=...`
   (o recibirlas por webhook).
4. **ASN → WMS** — `GET /asn?pending=true` devuelve embarques nuevos para crear el
   recibo esperado; `POST /asn/{id}/ack` confirma la sincronización.
5. **Recepción** — `PATCH /purchase-orders/{number}/status` con `recibida` (habilita el 3-way match).
6. **CFDI → CxP** — `GET /cfdi?status=aprobada&synced=false` y `POST /cfdi/{uuid}/synced`;
   revisión manual con `PATCH /cfdi/{uuid}/review`.
7. **Pagos y REP** — `POST /payments` registra el pago (total o parcial) y publica el
   Complemento de Pago en el estado de cuenta del proveedor.
8. **Documentos** — `GET /documents?pending=true` y `PATCH /documents/{id}/review`.

### Ejemplo: publicar una OC

```bash
curl -X POST http://localhost:8000/api/erp/v1/purchase-orders \
  -H "X-API-Key: erp_demo_bc_natureganix_2026" \
  -H "Content-Type: application/json" \
  -d '{
    "number": "OC-2026-0102",
    "vendor_code": "PROV-001",
    "requested_date": "2026-07-15",
    "lines": [{"line_no": 1, "sku": "ORG-CHIA-25",
               "description": "Chía orgánica 25 kg",
               "quantity": 10, "unit_price": 1850.0}]
  }'
```

### Webhooks salientes

El ERP puede suscribirse para recibir eventos push en lugar de hacer polling:

```bash
curl -X POST http://localhost:8000/api/erp/v1/webhooks \
  -H "X-API-Key: erp_demo_bc_natureganix_2026" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://mi-erp/portal-hook", "events": ["*"], "secret": "mi-secreto"}'
```

Eventos: `po.confirmed`, `po.rejected`, `po.change_requested`, `po.date_confirmed`,
`po.date_proposed`, `po.status_changed`, `asn.created`, `document.uploaded`
(incluye `cfdi_uuid` si el documento es una Carta Porte o CFDI), `cfdi.uploaded`,
`cfdi.approved`, `cfdi.rejected`.

Cada entrega incluye los headers `X-Portal-Event` y `X-Portal-Signature`
(HMAC-SHA256 del cuerpo con el secreto de la suscripción) y se registra en la
tabla `webhook_deliveries`.

## Estructura del proyecto

```
backend/app/
├── main.py            # App FastAPI, montaje del frontend y arranque
├── database.py        # Engine y sesión SQLAlchemy
├── models.py          # Vendor, PurchaseOrder, ASN, CartaPorte, Document, CFDI, Payment, Webhooks
├── schemas.py         # Esquemas Pydantic
├── security.py        # Sesiones de proveedor (Bearer) y API Keys ERP (X-API-Key)
├── webhooks.py        # Despacho de eventos firmados HMAC-SHA256
├── seed.py            # Datos de demostración
└── routers/           # auth, purchase_orders, asn, carta_porte, documents, cfdi, payments, erp
frontend/              # SPA (HTML/CSS/JS) con el diseño Fluent del portal
run.py                 # python run.py → http://localhost:8000
```

## Notas de implementación

- El portal **no genera ni timbra** CFDIs de traslado / Carta Porte: el proveedor
  los timbra con su PAC y los carga como documentación del pedido o grupo de
  pedidos. El portal valida la estructura del XML (CFDI tipo T/I, complemento
  Carta Porte, Timbre Fiscal Digital) y extrae el UUID (`routers/documents.py`).
- La verificación del estatus del CFDI ante el SAT está **simulada**; en
  producción se sustituye por el servicio de verificación del SAT
  (punto de extensión en `routers/cfdi.py`).
- La autenticación usa tokens de sesión y hash de contraseñas simples para la demo;
  para producción se recomienda OAuth2/OIDC (p. ej. Entra ID) y `bcrypt`/`argon2`.
