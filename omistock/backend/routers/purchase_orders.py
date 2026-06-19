"""
OMISTOCK — Bons de commande fournisseur (Purchase Orders).

Cycle de vie minimal : DRAFT -> SENT -> RECEIVED (ou CANCELLED depuis DRAFT/SENT).
La réception (RECEIVED) entre la marchandise en stock via repository.restock_product,
ce qui alimente le coût moyen pondéré (WAC) à partir du prix d'achat (unit_price).

Routes HUMAINES uniquement (RBAC admin). Chaque transition est tracée dans l'audit
chaîné avec un correlation_id.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import repository
import models
import schemas
import audit
from dependencies import get_current_admin
from database import get_db

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])


def _serialize(po: models.PurchaseOrder) -> dict:
    """Construit la réponse structurée d'un bon de commande + ses lignes."""
    return {
        "id": po.id,
        "order_number": po.order_number,
        "supplier_id": po.supplier_id,
        "branch_id": po.branch_id,
        "company_id": po.company_id,
        "status": po.status,
        "total_amount": po.total_amount,
        "creator_id": po.creator_id,
        "created_at": po.created_at,
        "received_at": po.received_at,
        "items": [
            {
                "id": it.id,
                "product_id": it.product_id,
                "quantity": it.quantity,
                "unit_price": it.unit_price,
            }
            for it in (po.items or [])
        ],
    }


@router.get("", response_model=list[schemas.PurchaseOrderResponse])
def list_purchase_orders(
    status: Optional[str] = None,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    orders = repository.get_purchase_orders(db, current_user.company_id, status=status)
    return [_serialize(po) for po in orders]


@router.get("/{po_id}", response_model=schemas.PurchaseOrderResponse)
def get_purchase_order(
    po_id: int,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    po = repository.get_purchase_order_by_id(db, po_id, current_user.company_id)
    if not po:
        raise HTTPException(status_code=404, detail="Bon de commande introuvable.")
    return _serialize(po)


@router.post("", response_model=schemas.PurchaseOrderResponse)
def create_purchase_order(
    data: schemas.PurchaseOrderCreate,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not data.items:
        raise HTTPException(status_code=400, detail="Un bon de commande doit comporter au moins une ligne.")
    corr = audit.new_correlation_id()
    try:
        po = repository.create_purchase_order(
            db,
            supplier_id=data.supplier_id,
            branch_id=data.branch_id,
            company_id=current_user.company_id,
            actor_id=current_user.id,
            items=[item.model_dump() for item in data.items],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(
        db, user_id=current_user.id, actor_type=current_user.user_type, action="PO_CREATE",
        company_id=current_user.company_id, entity_type="purchase_order", entity_id=po.id,
        correlation_id=corr, new_value={"order_number": po.order_number, "total": po.total_amount},
    )
    return _serialize(po)


@router.post("/{po_id}/send", response_model=schemas.PurchaseOrderResponse)
def send_purchase_order(
    po_id: int,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    corr = audit.new_correlation_id()
    try:
        po = repository.send_purchase_order(db, po_id, current_user.company_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(
        db, user_id=current_user.id, actor_type=current_user.user_type, action="PO_SEND",
        company_id=current_user.company_id, entity_type="purchase_order", entity_id=po.id,
        correlation_id=corr, new_value={"status": po.status},
    )
    return _serialize(po)


@router.post("/{po_id}/receive", response_model=schemas.PurchaseOrderResponse)
def receive_purchase_order(
    po_id: int,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    corr = audit.new_correlation_id()
    try:
        po = repository.receive_purchase_order(db, po_id, current_user.company_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(
        db, user_id=current_user.id, actor_type=current_user.user_type, action="PO_RECEIVE",
        company_id=current_user.company_id, entity_type="purchase_order", entity_id=po.id,
        correlation_id=corr, new_value={"status": po.status, "received_at": str(po.received_at)},
    )
    return _serialize(po)


@router.post("/{po_id}/cancel", response_model=schemas.PurchaseOrderResponse)
def cancel_purchase_order(
    po_id: int,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    corr = audit.new_correlation_id()
    try:
        po = repository.cancel_purchase_order(db, po_id, current_user.company_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(
        db, user_id=current_user.id, actor_type=current_user.user_type, action="PO_CANCEL",
        company_id=current_user.company_id, entity_type="purchase_order", entity_id=po.id,
        correlation_id=corr, new_value={"status": po.status},
    )
    return _serialize(po)
