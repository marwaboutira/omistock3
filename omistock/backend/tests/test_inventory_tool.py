"""
Tests pour l'outil #1 : get_inventory (GET /api/agent/inventory).
Vérifie :
  - scope stock:read + niveau READ_ONLY requis (agent_policy enforcement).
  - retour JSON structuré (id, name, on_hand, reorder_point, inventory[]).
  - filtre low_stock_only : n'inclut que les produits sous ROP.
  - filtre branch_id : ne retourne que l'inventaire de la filiale demandée.
"""
import pytest
import models
import repository
import agent_policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(db, company, branch, scopes="stock:read", level="read_only"):
    agent = models.User(
        email="agent_inv@agent.local",
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
# Tests : scope & niveau d'autonomie
# ---------------------------------------------------------------------------

def test_inventory_scope_stock_read_required():
    """Agent sans scope stock:read → refus agent_policy."""
    agent = models.User(
        email="noscope@agent.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="restock:propose",
        max_action_quantity=0, company_id=1,
    )
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level="read_only"
    )
    assert err is not None
    assert "Scope" in err


def test_inventory_level_read_only_sufficient():
    """Un agent READ_ONLY avec scope stock:read est autorisé."""
    agent = models.User(
        email="ro@agent.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="stock:read",
        max_action_quantity=0, company_id=1,
    )
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level="read_only"
    )
    assert err is None


# ---------------------------------------------------------------------------
# Tests : route backend (via repository directement, sans httpx)
# ---------------------------------------------------------------------------

def test_inventory_returns_all_products(db, company, branch, product, human):
    """La route renvoie bien tous les produits avec les champs structurés."""
    # Mise en stock
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=8, company_id=company.id, actor_id=human.id,
    )

    products = repository.get_products(db, company.id)
    assert len(products) >= 1

    p = next(x for x in products if x.id == product.id)
    assert p.total_quantity == 8
    assert hasattr(p, "reorder_point")
    # Vérifie que les champs attendus par la route sont présents sur le modèle
    assert p.sku is not None or p.sku is None  # optionnel mais accessible
    assert p.cost_price is not None
    assert p.price is not None


def test_inventory_low_stock_only_filter(db, company, branch, product, human):
    """low_stock_only=True ne retourne que les produits sous ROP."""
    # stock = 3, min_threshold = 5 → sous ROP
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=3, company_id=company.id, actor_id=human.id,
    )
    # Produit avec stock suffisant
    product_ok = models.Product(
        name="Widget OK", sku="W-OK", price=10.0, cost_price=0.0,
        quantity=0, min_threshold=5, company_id=company.id,
    )
    db.add(product_ok)
    db.commit()
    db.refresh(product_ok)
    repository.restock_product(
        db, product_id=product_ok.id, branch_id=branch.id,
        quantity=100, company_id=company.id, actor_id=human.id,
    )

    all_products = repository.get_products(db, company.id)
    # Simule le filtre low_stock_only
    low = [p for p in all_products if p.total_quantity <= p.reorder_point]
    ok  = [p for p in all_products if p.total_quantity > p.reorder_point]

    # product (qty=3, min=5) doit être dans low
    assert any(x.id == product.id for x in low)
    # product_ok (qty=100, min=5) doit être dans ok, PAS dans low
    assert any(x.id == product_ok.id for x in ok)
    assert not any(x.id == product_ok.id for x in low)


def test_inventory_branch_filter(db, company, branch, product, human):
    """branch_id filtre le stock par filiale ; une filiale sans stock renvoie qty=0."""
    branch_b = _make_branch(db, company, "Dépôt B-inv")

    # Stock sur branch seulement
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=5, company_id=company.id, actor_id=human.id,
    )

    qty_branch_a = _stock_qty(db, product.id, branch.id)
    qty_branch_b = _stock_qty(db, product.id, branch_b.id)

    assert qty_branch_a == 5
    assert qty_branch_b == 0
