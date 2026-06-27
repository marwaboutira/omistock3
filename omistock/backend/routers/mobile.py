"""
Mobile API — actions physiques des employés de stock.
Chaque action met à jour le stock réel (+/-) et log un audit.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import models, repository, audit
from dependencies import get_current_user
from database import get_db
from services import log_audit
import stock as stock_module

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


def _corr(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or audit.new_correlation_id()


# ── Schemas ──────────────────────────────────────────────────────────────────

class SupplierReceiveIn(BaseModel):
    product_id: int
    quantity: int
    supplier_id: Optional[int] = None
    note: Optional[str] = None

class QuickSaleIn(BaseModel):
    product_id: int
    quantity: int
    unit_price: Optional[float] = None
    note: Optional[str] = None


# ── 1. Recherche produit ──────────────────────────────────────────────────────

@router.get("/products/search")
def search_products(
    q: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recherche un produit par nom ou code-barre."""
    results = (
        db.query(models.Product)
        .filter(
            models.Product.company_id == current_user.company_id,
            models.Product.name.ilike(f"%{q}%") | models.Product.barcode.ilike(f"%{q}%")
        )
        .limit(20)
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "barcode": p.barcode,
            "unit": p.unit,
            "price": p.price,
            "cost_price": p.cost_price,
            "total_quantity": p.total_quantity,
            "stock_by_branch": [
                {"branch_id": inv.branch_id, "branch_name": inv.branch.name if inv.branch else None, "quantity": inv.quantity}
                for inv in p.inventory
            ],
        }
        for p in results
    ]


@router.get("/products/{product_id}/pending-transfers")
def get_pending_transfers_for_product(
    product_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retourne les transferts en attente d'action pour ce produit, filtrés par filiale de l'employé."""
    branch_id = current_user.branch_id
    transfers = (
        db.query(models.TransferRequest)
        .filter(
            models.TransferRequest.product_id == product_id,
            models.TransferRequest.company_id == current_user.company_id,
            models.TransferRequest.status.in_([
                models.TransferStatus.APPROVED.value,
                models.TransferStatus.SHIPPED.value,
            ]),
        )
        .all()
    )
    result = []
    for t in transfers:
        action = None
        if t.status == models.TransferStatus.APPROVED.value and t.from_branch_id == branch_id:
            action = "ship"   # cet employé doit expédier
        elif t.status == models.TransferStatus.SHIPPED.value and t.to_branch_id == branch_id:
            action = "receive"  # cet employé doit confirmer réception
        if action:
            result.append({
                "id": t.id,
                "quantity": t.quantity,
                "status": t.status,
                "action": action,
                "from_branch": t.from_branch.name if t.from_branch else None,
                "to_branch": t.to_branch.name if t.to_branch else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
    return result


# ── 2. Confirmer expédition (stock - source) ──────────────────────────────────

@router.post("/transfers/{transfer_id}/ship")
def ship_transfer(
    transfer_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Employé source confirme expédition physique → stock - filiale source."""
    corr = _corr(request)
    try:
        req = repository.ship_transfer_request(db, transfer_id, current_user.id)
        log_audit(
            db, current_user.id, "TRANSFER_SHIPPED",
            {"status": "approuvé"},
            {"status": "expédié", "shipped_by": current_user.email},
            current_user.company_id,
            actor_type=current_user.user_type,
            entity_type="transfer", entity_id=transfer_id, correlation_id=corr,
        )
        return {
            "status": "success",
            "message": f"Expédition confirmée — stock -{req.quantity} à {req.from_branch.name if req.from_branch else req.from_branch_id}",
            "transfer_id": req.id,
            "new_status": req.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 3. Confirmer réception transfert (stock + destination) ────────────────────

@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(
    transfer_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Employé destination confirme réception physique → stock + filiale destination."""
    corr = _corr(request)
    try:
        req = repository.confirm_transfer_request(db, transfer_id, current_user.id)
        log_audit(
            db, current_user.id, "TRANSFER_RECEIVED",
            {"status": req.status},
            {"status": "confirmé", "received_by": current_user.email},
            current_user.company_id,
            actor_type=current_user.user_type,
            entity_type="transfer", entity_id=transfer_id, correlation_id=corr,
        )
        return {
            "status": "success",
            "message": f"Réception confirmée — stock +{req.quantity} à {req.to_branch.name if req.to_branch else req.to_branch_id}",
            "transfer_id": req.id,
            "new_status": req.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 4. Réception fournisseur (stock + filiale employé) ───────────────────────

@router.post("/receive/supplier")
def receive_from_supplier(
    data: SupplierReceiveIn,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Employé reçoit marchandise d'un fournisseur → stock + filiale employé."""
    corr = _corr(request)
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="Aucune filiale associée à cet utilisateur")

    product = repository.get_product_by_id(db, data.product_id)
    if not product or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    try:
        inv = (
            db.query(models.Inventory)
            .filter(
                models.Inventory.product_id == data.product_id,
                models.Inventory.branch_id == branch_id,
            )
            .with_for_update()
            .first()
        )
        if inv:
            inv.quantity += data.quantity
        else:
            inv = models.Inventory(
                product_id=data.product_id,
                branch_id=branch_id,
                quantity=data.quantity,
                min_threshold=5,
            )
            db.add(inv)

        db.add(models.StockMovement(
            product_id=data.product_id,
            branch_id=branch_id,
            quantity=data.quantity,
            reason=f"Réception fournisseur (mobile){' — ' + data.note if data.note else ''}",
            company_id=current_user.company_id,
            movement_type="IN",
            actor_id=current_user.id,
        ))

        db.flush()
        stock_module.recompute_product_quantity(db, product)
        db.commit()

        log_audit(
            db, current_user.id, "SUPPLIER_RECEIVE_MOBILE",
            None,
            {"product_id": data.product_id, "qty": data.quantity, "branch_id": branch_id},
            current_user.company_id,
            actor_type=current_user.user_type,
            entity_type="product", entity_id=data.product_id, correlation_id=corr,
        )
        return {
            "status": "success",
            "message": f"Stock +{data.quantity} enregistré pour {product.name}",
            "new_quantity": inv.quantity,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── 5. Vente rapide (stock - filiale employé) ─────────────────────────────────

@router.post("/sale/quick")
def quick_sale(
    data: QuickSaleIn,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Vente rapide depuis mobile → stock - filiale employé."""
    corr = _corr(request)
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="Aucune filiale associée à cet utilisateur")

    product = repository.get_product_by_id(db, data.product_id)
    if not product or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    try:
        inv = (
            db.query(models.Inventory)
            .filter(
                models.Inventory.product_id == data.product_id,
                models.Inventory.branch_id == branch_id,
            )
            .with_for_update()
            .first()
        )
        if not inv or inv.quantity < data.quantity:
            raise HTTPException(status_code=400, detail="Stock insuffisant")

        unit_price = data.unit_price or product.price
        total = round(unit_price * data.quantity, 2)

        inv.quantity -= data.quantity

        sale = models.Sale(
            company_id=current_user.company_id,
            branch_id=branch_id,
            seller_id=current_user.id,
            total_amount=total,
            total_cost=round((product.cost_price or 0) * data.quantity, 2),
            status="COMPLETED",
        )
        db.add(sale)
        db.flush()

        db.add(models.SaleItem(
            sale_id=sale.id,
            product_id=data.product_id,
            quantity=data.quantity,
            unit_price=unit_price,
            cost_price=product.cost_price or 0,
        ))

        db.add(models.StockMovement(
            product_id=data.product_id,
            branch_id=branch_id,
            quantity=-data.quantity,
            reason=f"Vente rapide mobile#{sale.id}{' — ' + data.note if data.note else ''}",
            company_id=current_user.company_id,
            movement_type="OUT",
            actor_id=current_user.id,
        ))

        stock_module.recompute_product_quantity(db, product)
        db.commit()

        log_audit(
            db, current_user.id, "QUICK_SALE_MOBILE",
            None,
            {"sale_id": sale.id, "product_id": data.product_id, "qty": data.quantity, "total": total},
            current_user.company_id,
            actor_type=current_user.user_type,
            entity_type="sale", entity_id=sale.id, correlation_id=corr,
        )
        return {
            "status": "success",
            "message": f"Vente enregistrée — {data.quantity}x {product.name} = {total} DA",
            "sale_id": sale.id,
            "new_quantity": inv.quantity,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
