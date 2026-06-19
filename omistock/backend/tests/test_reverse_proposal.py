"""
Tests pour la proposition d'annulation de vente (REVERSE) par un agent IA.
Cas couverts :
  1. Un agent PROPOSE crée bien une AgentProposal (action_type=REVERSE, status=PENDING).
  2. Un admin approuve → la vente passe REVERSED et le stock est réintégré.
  3. Une double approbation est rejetée (proposition déjà traitée).
  4. Un agent sans le scope correct est refusé.
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

def _make_agent(db, company, branch, scopes="reverse:propose", level="propose"):
    agent = models.User(
        email="agent_rev@agent.local",
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
        email="admin_rev@acme.test",
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


def _make_confirmed_sale(db, company, branch, product, human):
    """Crée un produit en stock et enregistre une vente confirmée."""
    # Mise en stock initiale
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=10, company_id=company.id, actor_id=human.id,
    )
    # Vente de 3 unités
    sale = repository.create_sale(
        db,
        {"branch_id": branch.id, "items": [{"product_id": product.id, "quantity": 3, "unit_price": 10.0}]},
        company_id=company.id,
        agent_id=human.id,
    )
    return sale


def _stock_qty(db, product_id, branch_id):
    inv = db.query(models.Inventory).filter(
        models.Inventory.product_id == product_id,
        models.Inventory.branch_id == branch_id,
    ).first()
    return inv.quantity if inv else 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_proposes_reverse_creates_pending_proposal(db, company, branch, product, human):
    """Un agent autorisé crée une proposition REVERSE avec status PENDING."""
    agent = _make_agent(db, company, branch)
    sale = _make_confirmed_sale(db, company, branch, product, human)
    corr = audit.new_correlation_id()

    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="REVERSE",
        payload=json.dumps({"sale_id": sale.id, "rationale": "Stock error"}),
        rationale="Stock error", correlation_id=corr,
    )

    assert prop.id is not None
    assert prop.action_type == "REVERSE"
    assert prop.status == "PENDING"
    assert prop.agent_id == agent.id
    assert prop.company_id == company.id


def test_admin_approves_reverse_sale_reversed_and_stock_reinstated(db, company, branch, product, human):
    """Admin approuve REVERSE → vente REVERSED + stock réintégré exactement."""
    agent = _make_agent(db, company, branch)
    admin = _make_admin(db, company, branch)
    sale = _make_confirmed_sale(db, company, branch, product, human)

    qty_after_sale = _stock_qty(db, product.id, branch.id)  # 10 - 3 = 7

    corr = audit.new_correlation_id()
    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="REVERSE",
        payload=json.dumps({"sale_id": sale.id}),
        rationale="", correlation_id=corr,
    )

    # Simule le handler admin : appelle reverse_sale sous identité admin
    payload = json.loads(prop.payload)
    reversed_sale = repository.reverse_sale(
        db, sale_id=payload["sale_id"], company_id=company.id,
        actor_id=admin.id, correlation_id=corr,
    )
    prop.status = "EXECUTED"
    prop.reviewer_id = admin.id
    db.commit()

    # Vérifications
    db.refresh(reversed_sale)
    assert reversed_sale.status == "REVERSED"

    qty_after_reverse = _stock_qty(db, product.id, branch.id)
    assert qty_after_reverse == qty_after_sale + 3  # stock réintégré

    db.refresh(prop)
    assert prop.status == "EXECUTED"


def test_double_reverse_approval_is_rejected(db, company, branch, product, human):
    """Une proposition déjà traitée (EXECUTED) est rejetée par le guard status != PENDING."""
    agent = _make_agent(db, company, branch)
    admin = _make_admin(db, company, branch)
    sale = _make_confirmed_sale(db, company, branch, product, human)
    corr = audit.new_correlation_id()

    prop = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="REVERSE",
        payload=json.dumps({"sale_id": sale.id}),
        rationale="", correlation_id=corr,
    )

    # Première approbation
    payload = json.loads(prop.payload)
    repository.reverse_sale(
        db, sale_id=payload["sale_id"], company_id=company.id,
        actor_id=admin.id, correlation_id=corr,
    )
    prop.status = "EXECUTED"
    db.commit()

    # Deuxième tentative → doit lever ValueError (vente déjà annulée)
    with pytest.raises(ValueError, match="annulée"):
        repository.reverse_sale(
            db, sale_id=payload["sale_id"], company_id=company.id,
            actor_id=admin.id, correlation_id=corr,
        )


def test_agent_without_scope_cannot_propose_reverse(db, company, branch):
    """Un agent sans le scope 'reverse:propose' est refusé par agent_policy."""
    agent = _make_agent(db, company, branch, scopes="stock:read", level="propose")

    err = agent_policy.authorize_agent_action(
        agent, required_scope="reverse:propose",
        required_level=models.AutonomyLevel.PROPOSE.value,
    )
    assert err is not None
    assert "Scope" in err
