"""Notificación de eventos del portal hacia el ERP (webhooks salientes).

Eventos emitidos:
  po.confirmed, po.rejected, po.change_requested, po.date_confirmed,
  po.date_proposed, po.status_changed, asn.created,
  document.uploaded (incluye cfdi_uuid si es Carta Porte/CFDI),
  cfdi.uploaded, cfdi.approved, cfdi.rejected
Cada entrega se firma con HMAC-SHA256 en el header `X-Portal-Signature`.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime

import httpx

from .database import SessionLocal
from .models import WebhookDelivery, WebhookSubscription

logger = logging.getLogger("portal.webhooks")


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _matches(subscription_events: str, event: str) -> bool:
    events = [e.strip() for e in subscription_events.split(",")]
    return "*" in events or event in events or event.split(".")[0] + ".*" in events


def dispatch_event(event: str, data: dict) -> None:
    """Envía el evento a todas las suscripciones activas. Pensado para BackgroundTasks."""
    db = SessionLocal()
    try:
        subs = db.query(WebhookSubscription).filter(WebhookSubscription.active).all()
        if not subs:
            return
        payload = {
            "event": event,
            "emitted_at": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }
        body = json.dumps(payload, default=str).encode()
        for sub in subs:
            if not _matches(sub.events, event):
                continue
            delivery = WebhookDelivery(subscription_id=sub.id, event=event, payload=body.decode())
            try:
                resp = httpx.post(
                    sub.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Portal-Event": event,
                        "X-Portal-Signature": _sign(sub.secret, body),
                    },
                    timeout=10,
                )
                delivery.response_status = resp.status_code
                delivery.success = 200 <= resp.status_code < 300
            except Exception as exc:  # red caída, URL inválida, etc.
                logger.warning("Webhook %s falló hacia %s: %s", event, sub.url, exc)
                delivery.success = False
            db.add(delivery)
        db.commit()
    finally:
        db.close()
