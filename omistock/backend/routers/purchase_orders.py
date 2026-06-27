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
import services
from dependencies import get_current_admin
from database import get_db

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])


def _serialize(po: models.PurchaseOrder) -> dict:
    """Construit la réponse structurée d'un bon de commande + ses lignes."""
    return {
        "id": po.id,
        "order_number": po.order_number,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier.name if po.supplier else None,
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
                # Nom du produit exposé pour l'affichage (évite N+1 au frontend).
                "product_name": it.product.name if it.product else None,
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


@router.post("/auto-from-alerts")
def auto_order_from_alerts(
    payload: dict | None = None,
    current_user: models.User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Automatisation des commandes depuis le Dashboard (Mission 3).

    Récupère les produits en alerte critique, identifie le fournisseur de chacun,
    et génère en arrière-plan UN bon de commande PAR fournisseur (regroupement),
    sans remplir le formulaire manuellement.

    Options (body JSON optionnel) :
      - product_ids: liste d'IDs pour limiter à certains produits (commande ciblée).
      - branch_id:   filiale de réception (sinon première filiale de l'entreprise).

    Retourne le récapitulatif des bons créés.
    """
    payload = payload or {}
    product_ids = payload.get("product_ids")
    branch_id = payload.get("branch_id")

    # Filiale de réception par défaut (la première de l'entreprise).
    if branch_id is None:
        first_branch = (
            db.query(models.Branch)
            .filter(models.Branch.company_id == current_user.company_id)
            .order_by(models.Branch.id.asc())
            .first()
        )
        if not first_branch:
            raise HTTPException(status_code=400, detail="Aucune filiale disponible pour la réception.")
        branch_id = first_branch.id
    else:
        # Validation multi-tenant de la filiale.
        branch = (
            db.query(models.Branch)
            .filter(
                models.Branch.id == branch_id,
                models.Branch.company_id == current_user.company_id,
            )
            .first()
        )
        if not branch:
            raise HTTPException(status_code=400, detail="Filiale invalide ou hors entreprise.")

    # Produits en alerte (critère ROP).
    alerts = services.stock.get_alerts(db, current_user.company_id, branch_id=branch_id)
    if product_ids is not None:
        wanted = set(int(x) for x in product_ids)
        alerts = [p for p in alerts if p.id in wanted]

    if not alerts:
        return {"created": [], "count": 0,
                "message": "Aucun produit en alerte à commander."}

    # Regroupement par fournisseur. Les produits sans fournisseur vont dans un
    # groupe "sans fournisseur" (supplier_id=None) — un seul BC global pour eux.
    by_supplier: dict = {}
    for p in alerts:
        sid = p.supplier_id
        by_supplier.setdefault(sid, []).append(p)

    corr = audit.new_correlation_id()
    created_pos = []
    errors = []
    for supplier_id, prods in by_supplier.items():
        # Quantité commandée = quantité manquante jusqu'au ROP (min 1),
        # prix d'achat = coût moyen pondéré connu (WAC), sinon 0.
        items = []
        for p in prods:
            on_hand = (
                sum((inv.quantity or 0) for inv in p.inventory if inv.branch_id == branch_id)
                if branch_id is not None
                else p.total_quantity
            )
            missing = max((p.reorder_point or 0) - on_hand, 1)
            items.append({
                "product_id": p.id,
                "quantity": missing,
                "unit_price": float(p.cost_price or 0.0),
            })
        try:
            po = repository.create_purchase_order(
                db,
                supplier_id=supplier_id,
                branch_id=branch_id,
                company_id=current_user.company_id,
                actor_id=current_user.id,
                items=items,
            )
            audit.record(
                db, user_id=current_user.id, actor_type=current_user.user_type,
                action="PO_AUTO_CREATE",
                company_id=current_user.company_id, entity_type="purchase_order",
                entity_id=po.id, correlation_id=corr,
                new_value={"order_number": po.order_number, "total": po.total_amount,
                           "supplier_id": supplier_id, "lines": len(items)},
            )
            created_pos.append({
                "id": po.id,
                "order_number": po.order_number,
                "supplier_id": supplier_id,
                "supplier_name": (po.supplier.name if po.supplier else "Sans fournisseur"),
                "total_amount": po.total_amount,
                "items_count": len(items),
            })
        except Exception as e:
            errors.append({"supplier_id": supplier_id, "error": str(e)})

    return {
        "created": created_pos,
        "count": len(created_pos),
        "errors": errors,
        "message": (
            f"{len(created_pos)} bon(s) de commande créé(s) en brouillon "
            f"pour {len(by_supplier)} fournisseur(s)."
        ),
    }


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
