"""
OMISTOCK — Interface DÉDIÉE aux agents IA.

Séparation stricte des interfaces (best practice agent-ready) :
- Les humains utilisent les routes /api/* avec JWT.
- Les agents utilisent /api/agent/* avec X-API-Key, des SCOPES explicites et un
  NIVEAU D'AUTONOMIE borné. Un agent ne peut PAS appeler les routes humaines de
  mutation directe ; il passe par cette surface restreinte et auditée.

Modèle d'autorisation :
- READ_ONLY  : lecture (alertes, résumé, prévision).
- SUGGEST    : idem + analyses.
- PROPOSE    : peut créer des PROPOSITIONS (restock/transfert) en attente de
               validation humaine (human-in-the-loop).
- AUTO       : peut exécuter directement, dans la limite de max_action_quantity
               et des scopes "...:auto".
Toutes les actions agent sont tracées (audit chaîné) avec correlation_id.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import repository
import models
import schemas
import stock
import audit
import agent_policy
import services
from dependencies import get_current_agent
from database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _corr(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or audit.new_correlation_id()


# ---- Lecture (READ_ONLY+) ----------------------------------------------------

@router.get("/alerts")
def agent_alerts(
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    alerts = stock.get_alerts(db, agent.company_id)
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_ALERTS",
                 company_id=agent.company_id, entity_type="alerts", correlation_id=_corr(request),
                 new_value={"count": len(alerts)})
    return [{"id": p.id, "name": p.name, "on_hand": p.total_quantity,
             "reorder_point": p.reorder_point} for p in alerts]


@router.get("/inventory")
def agent_get_inventory(
    request: Request,
    branch_id: int = None,
    low_stock_only: bool = False,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Stock réel par produit/filiale. Scope stock:read, READ_ONLY+.
    Paramètres optionnels : branch_id (filtre filiale), low_stock_only (sous ROP uniquement).
    """
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)

    products = repository.get_products(db, agent.company_id, branch_id=branch_id)

    result = []
    for p in products:
        on_hand = p.total_quantity
        if low_stock_only and on_hand > p.reorder_point:
            continue
        # Stock par filiale (détail si branch_id non filtré)
        inventory_detail = [
            {"branch_id": inv.branch_id, "branch_name": inv.branch.name, "quantity": inv.quantity}
            for inv in (p.inventory or [])
            if branch_id is None or inv.branch_id == branch_id
        ]
        result.append({
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "on_hand": on_hand,
            "reorder_point": p.reorder_point,
            "min_threshold": p.min_threshold,
            "cost_price": p.cost_price,
            "price": p.price,
            "inventory": inventory_detail,
        })

    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_INVENTORY",
                 company_id=agent.company_id, entity_type="inventory",
                 correlation_id=_corr(request),
                 new_value={"count": len(result), "branch_id": branch_id, "low_stock_only": low_stock_only})
    return result


@router.get("/valuation")
def agent_get_valuation(
    request: Request,
    branch_id: int = None,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Valorisation du stock au coût moyen pondéré (WAC). Scope stock:read, READ_ONLY+.
    Paramètre optionnel : branch_id (filtre filiale).
    """
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)

    total_value = stock.stock_value_at_cost(db, agent.company_id, branch_id=branch_id)

    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_VALUATION",
                 company_id=agent.company_id, entity_type="stock",
                 correlation_id=_corr(request),
                 new_value={"total_value": total_value, "branch_id": branch_id})
    return {"valuation": total_value, "branch_id": branch_id}


@router.get("/reorder-suggestions")
def agent_get_reorder_suggestions(
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Suggestions de réapprovisionnement basées sur le ROP et la formule de Wilson (EOQ).
    Scope stock:read, READ_ONLY+.
    """
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)

    import config

    # Récupérer tous les produits de l'entreprise
    products = db.query(models.Product).filter(models.Product.company_id == agent.company_id).all()

    suggestions = []
    for p in products:
        on_hand = p.total_quantity
        rop = p.reorder_point
        # Un produit a besoin de commande si stock disponible <= ROP
        if on_hand <= rop:
            # EOQ inputs
            avg_demand = p.avg_daily_demand or 0.0
            cost_price = p.cost_price or 0.0
            
            annual_demand = avg_demand * 365.0
            ordering_cost = config.DEFAULT_ORDERING_COST
            holding_cost_per_unit = config.HOLDING_COST_RATE * cost_price

            eoq = None
            reason = None
            
            if avg_demand <= 0:
                reason = "demande ou coût insuffisant pour calculer l'EOQ"
            elif cost_price <= 0:
                reason = "demande ou coût insuffisant pour calculer l'EOQ"
            else:
                eoq_val = stock.economic_order_quantity(
                    annual_demand=annual_demand,
                    ordering_cost=ordering_cost,
                    holding_cost_per_unit=holding_cost_per_unit
                )
                if eoq_val is None or eoq_val <= 0:
                    reason = "demande ou coût insuffisant pour calculer l'EOQ"
                else:
                    eoq = eoq_val

            suggestions.append({
                "product_id": p.id,
                "name": p.name,
                "on_hand": on_hand,
                "reorder_point": rop,
                "suggested_order_quantity": eoq,
                "reason": reason,
                "assumptions": {
                    "annual_demand": round(annual_demand, 2),
                    "ordering_cost": ordering_cost,
                    "holding_cost_per_unit": round(holding_cost_per_unit, 4)
                }
            })

    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_REORDER_SUGGESTIONS",
                 company_id=agent.company_id, entity_type="reorder_suggestions",
                 correlation_id=_corr(request),
                 new_value={"count": len(suggestions)})
    return suggestions


@router.get("/expiring-lots")
def agent_get_expiring_lots(
    request: Request,
    days: int = 30,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Lots dont la péremption approche (gestion FEFO). Scope stock:read, READ_ONLY+.
    """
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)

    # Borner days à >= 1
    days_checked = max(days, 1)

    lots = stock.expiring_lots(db, agent.company_id, within_days=days_checked)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    result = []
    for lot in lots:
        expiry_aware = lot.expiry_date if lot.expiry_date.tzinfo else lot.expiry_date.replace(tzinfo=timezone.utc)
        diff = expiry_aware - now
        days_until_expiry = int(diff.days)

        result.append({
            "lot_id": lot.id,
            "lot_number": lot.lot_number,
            "product_id": lot.product_id,
            "product_name": lot.product.name if lot.product else None,
            "branch_id": lot.branch_id,
            "quantity": lot.quantity,
            "expiry_date": expiry_aware.isoformat(),
            "days_until_expiry": days_until_expiry,
        })

    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_EXPIRING_LOTS",
                 company_id=agent.company_id, entity_type="lot",
                 correlation_id=_corr(request),
                 new_value={"count": len(result), "days": days_checked})
    return result


@router.get("/proposals/mine")
def agent_list_my_proposals(
    request: Request,
    status: Optional[str] = None,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Liste les propositions faites par l'agent connecté.
    Scope stock:read, READ_ONLY+.
    """
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.READ_ONLY.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)

    if status is not None and status not in {"PENDING", "APPROVED", "REJECTED", "EXECUTED"}:
        raise HTTPException(status_code=400, detail="Statut invalide. Choisir parmi PENDING, APPROVED, REJECTED, EXECUTED.")

    proposals = repository.get_agent_proposals(
        db, company_id=agent.company_id, status=status, agent_id=agent.id
    )

    result = []
    for prop in proposals:
        parsed_payload = None
        if prop.payload:
            try:
                parsed_payload = json.loads(prop.payload)
            except Exception:
                parsed_payload = prop.payload

        result.append({
            "proposal_id": prop.id,
            "action_type": prop.action_type,
            "status": prop.status,
            "rationale": prop.rationale,
            "payload": parsed_payload,
            "correlation_id": prop.correlation_id,
            "created_at": prop.created_at.isoformat() if prop.created_at else None,
            "reviewed_at": prop.reviewed_at.isoformat() if prop.reviewed_at else None,
        })

    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_LIST_PROPOSALS",
                 company_id=agent.company_id, entity_type="agent_proposal",
                 correlation_id=_corr(request),
                 new_value={"count": len(result), "status_filter": status})
    return result


@router.get("/capabilities")
def agent_get_capabilities(
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Auto-introspection de l'agent : retourne ses propres droits, scopes et plafonds.
    Aucun scope requis — accessible à tout agent authentifié (get_current_agent suffit).
    """
    scopes = agent_policy.parse_scopes(agent)
    expires_at = (
        agent.api_key_expires_at.isoformat()
        if agent.api_key_expires_at else None
    )
    payload = {
        "autonomy_level": agent.autonomy_level,
        "scopes": scopes,
        "max_action_quantity": agent.max_action_quantity,
        "api_key_expires_at": expires_at,
        "company_id": agent.company_id,
        # Ordre croissant de niveau pour que l'agent se situe
        "autonomy_levels_order": [
            models.AutonomyLevel.READ_ONLY.value,
            models.AutonomyLevel.SUGGEST.value,
            models.AutonomyLevel.PROPOSE.value,
            models.AutonomyLevel.AUTO.value,
        ],
    }
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_READ_CAPABILITIES",
                 company_id=agent.company_id, entity_type="capabilities",
                 correlation_id=_corr(request),
                 new_value={"autonomy_level": agent.autonomy_level, "scopes": scopes})
    return payload


@router.get("/forecast/{product_id}")
def agent_forecast(
    product_id: int,
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level=models.AutonomyLevel.SUGGEST.value
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    try:
        result = services.analyze_product_mcp(db, product_id, agent.company_id, agent.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_FORECAST",
                 company_id=agent.company_id, entity_type="product", entity_id=product_id,
                 correlation_id=_corr(request), new_value=result)
    return result


# ---- Propositions (PROPOSE+) : human-in-the-loop -----------------------------

@router.post("/proposals/restock")
def agent_propose_restock(
    data: schemas.AgentRestockProposal,
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="restock:propose",
        required_level=models.AutonomyLevel.PROPOSE.value, quantity=None,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    corr = _corr(request)
    payload = data.model_dump()
    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=agent.company_id, action_type="RESTOCK",
        payload=json.dumps(payload), rationale=data.rationale or "", correlation_id=corr,
    )
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_PROPOSE_RESTOCK",
                 company_id=agent.company_id, entity_type="proposal", entity_id=prop.id,
                 correlation_id=corr, new_value=payload)
    return {"status": "pending_human_approval", "proposal_id": prop.id}


@router.post("/proposals/reverse")
def agent_propose_reverse(
    data: schemas.AgentReverseProposal,
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="reverse:propose",
        required_level=models.AutonomyLevel.PROPOSE.value, quantity=None,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    corr = _corr(request)
    payload = data.model_dump()
    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=agent.company_id, action_type="REVERSE",
        payload=json.dumps(payload), rationale=data.rationale or "", correlation_id=corr,
    )
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_PROPOSE_REVERSE",
                 company_id=agent.company_id, entity_type="proposal", entity_id=prop.id,
                 correlation_id=corr, new_value=payload)
    return {"status": "pending_human_approval", "proposal_id": prop.id}


@router.post("/proposals/transfer")
def agent_propose_transfer(
    data: schemas.AgentTransferProposal,
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="transfer:propose",
        required_level=models.AutonomyLevel.PROPOSE.value, quantity=None,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    corr = _corr(request)
    payload = data.model_dump()
    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=agent.company_id, action_type="TRANSFER",
        payload=json.dumps(payload), rationale=data.rationale or "", correlation_id=corr,
    )
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_PROPOSE_TRANSFER",
                 company_id=agent.company_id, entity_type="proposal", entity_id=prop.id,
                 correlation_id=corr, new_value=payload)
    return {"status": "pending_human_approval", "proposal_id": prop.id}


# ---- Exécution directe (AUTO) : bornée par scope + plafond quantité ----------

@router.post("/restock")
def agent_auto_restock(
    data: schemas.AgentRestockProposal,
    request: Request,
    agent: models.User = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    err = agent_policy.authorize_agent_action(
        agent, required_scope="restock:auto",
        required_level=models.AutonomyLevel.AUTO.value, quantity=data.quantity,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    corr = _corr(request)
    try:
        mv = repository.restock_product(
            db, product_id=data.product_id, branch_id=data.branch_id, quantity=data.quantity,
            company_id=agent.company_id, actor_id=agent.id, unit_cost=data.unit_cost or 0.0,
            reason="Réappro auto (agent IA)", correlation_id=corr,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(db, user_id=agent.id, actor_type="AGENT", action="AGENT_AUTO_RESTOCK",
                 company_id=agent.company_id, entity_type="stock_movement", entity_id=mv.id,
                 correlation_id=corr, new_value={"qty": data.quantity, "product": data.product_id})
    return {"status": "executed", "movement_id": mv.id}
