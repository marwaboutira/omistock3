"""
Tests bout-en-bout pour la proposition de transfert inter-filiales (TRANSFER) par un agent IA.
Cas couverts :
  1. Agent autorisé crée une proposition TRANSFER (status=PENDING).
  2. Admin approuve → stock décrémenté source, incrémenté destination, mouvements tracés.
  3. Agent sans le scope correct est refusé par agent_policy.
"""
import json
import pytest
import models
import repository
import agent_policy
import audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(db, company, branch, scopes="transfer:propose", level="propose"):
    agent = models.User(
        email="agent_transfer@agent.local",
        user_type="AGENT",
        autonomy_level=level,
        agent_scopes=scopes,
        max_action_quantity=0,
        company_id=company.id,
        branch_id=branch.id,
        is_active=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _make_admin(db, company, branch):
    admin = models.User(
        email="admin_transfer@acme.test",
        hashed_password="x",
        user_type="ADMIN",
        company_id=company.id,
        branch_id=branch.id,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _make_branch(db, company, name="Dépôt B"):
    b = models.Branch(name=name, city="Oran", company_id=company.id)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _stock_qty(db, product_id, branch_id):
    inv = db.query(models.Inventory).filter(
        models.Inventory.product_id == product_id,
        models.Inventory.branch_id == branch_id,
    ).first()
    return inv.quantity if inv else 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_proposes_transfer_creates_pending_proposal(db, company, branch, product, human):
    """Un agent autorisé crée une proposition TRANSFER avec status PENDING."""
    branch_b = _make_branch(db, company)
    agent = _make_agent(db, company, branch)
    corr = audit.new_correlation_id()

    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="TRANSFER",
        payload=json.dumps({
            "product_id": product.id,
            "from_branch_id": branch.id,
            "to_branch_id": branch_b.id,
            "quantity": 4,
        }),
        rationale="Rééquilibrage automatique", correlation_id=corr,
    )

    assert prop.id is not None
    assert prop.action_type == "TRANSFER"
    assert prop.status == "PENDING"
    assert prop.agent_id == agent.id


def test_admin_approves_transfer_stock_moved(db, company, branch, product, human):
    """Admin approuve TRANSFER → stock décrémenté source et incrémenté destination."""
    branch_b = _make_branch(db, company, "Dépôt B2")
    agent = _make_agent(db, company, branch)
    admin = _make_admin(db, company, branch)

    # Mise en stock initiale sur la source
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=10, company_id=company.id, actor_id=human.id,
    )
    qty_source_before = _stock_qty(db, product.id, branch.id)      # 10
    qty_dest_before   = _stock_qty(db, product.id, branch_b.id)    # 0

    corr = audit.new_correlation_id()
    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="TRANSFER",
        payload=json.dumps({
            "product_id": product.id,
            "from_branch_id": branch.id,
            "to_branch_id": branch_b.id,
            "quantity": 4,
        }),
        rationale="", correlation_id=corr,
    )

    # Simule le handler admin : create → approve → confirm
    payload = json.loads(prop.payload)
    req = repository.create_transfer_request(
        db,
        {
            "product_id": payload["product_id"],
            "to_branch_id": payload["to_branch_id"],
            "quantity": payload["quantity"],
            "requester_id": admin.id,
            "company_id": company.id,
            "origin": "AGENT",
        },
        from_branch_id=payload["from_branch_id"],
    )
    repository.approve_transfer_request(db, req.id, admin.id)
    repository.confirm_transfer_request(db, req.id, admin.id)

    prop.status = "EXECUTED"
    prop.reviewer_id = admin.id
    db.commit()

    # Vérifications stock
    qty_source_after = _stock_qty(db, product.id, branch.id)
    qty_dest_after   = _stock_qty(db, product.id, branch_b.id)

    assert qty_source_after == qty_source_before - 4   # 10 - 4 = 6
    assert qty_dest_after   == qty_dest_before   + 4   # 0  + 4 = 4

    # Mouvements tracés
    movements = db.query(models.StockMovement).filter(
        models.StockMovement.product_id == product.id
    ).all()
    move_types = {m.movement_type for m in movements}
    assert "OUT" in move_types   # sortie source
    assert "IN"  in move_types   # entrée destination

    db.refresh(prop)
    assert prop.status == "EXECUTED"


def test_agent_without_scope_cannot_propose_transfer(db, company, branch):
    """Un agent sans le scope 'transfer:propose' est refusé par agent_policy."""
    agent = _make_agent(db, company, branch, scopes="stock:read", level="propose")

    err = agent_policy.authorize_agent_action(
        agent, required_scope="transfer:propose",
        required_level=models.AutonomyLevel.PROPOSE.value,
    )
    assert err is not None
    assert "Scope" in err
