"""
Tests pour l'outil #2 : get_stock_valuation (GET /api/agent/valuation).
Vérifie :
  - scope stock:read + niveau READ_ONLY requis.
  - calcul correct de la valorisation au coût (WAC), pas au prix de vente.
  - filtrage optionnel par filiale.
"""
import pytest
import models
import repository
import agent_policy
import stock


def test_valuation_policy_enforcement():
    """Agent sans scope stock:read → refus."""
    agent = models.User(
        email="no@agent.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="other:scope",
        max_action_quantity=0, company_id=1,
    )
    err = agent_policy.authorize_agent_action(
        agent, required_scope="stock:read", required_level="read_only"
    )
    assert err is not None


def test_valuation_calculation(db, company, branch, product, human):
    """Vérifie que la valorisation est calculée au coût d'achat (WAC)."""
    # 1. Ajouter du stock avec un coût unitaire spécifique
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=5, company_id=company.id, actor_id=human.id,
        unit_cost=12.0  # coût WAC = 12.0
    )
    
    # 2. Créer un autre produit pour vérifier le cumul
    product_b = models.Product(
        name="Widget B", sku="W-B", price=25.0, cost_price=20.0,
        quantity=0, min_threshold=5, company_id=company.id,
    )
    db.add(product_b)
    db.commit()
    db.refresh(product_b)
    repository.restock_product(
        db, product_id=product_b.id, branch_id=branch.id,
        quantity=3, company_id=company.id, actor_id=human.id,
        unit_cost=20.0  # coût WAC = 20.0
    )

    # Valeur attendue : 5 * 12.0 + 3 * 20.0 = 60.0 + 60.0 = 120.0
    val = stock.stock_value_at_cost(db, company.id)
    assert val == 120.0


def test_valuation_branch_filtering(db, company, branch, product, human):
    """Vérifie le filtrage par filiale de la valorisation du stock."""
    # Filiale B
    branch_b = models.Branch(name="Dépôt B-val", city="Oran", company_id=company.id)
    db.add(branch_b)
    db.commit()
    db.refresh(branch_b)

    # Stock branch A : 10 unités à 5.0 = 50.0
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=10, company_id=company.id, actor_id=human.id,
        unit_cost=5.0
    )

    # Stock branch B : 4 unités à 5.0 (même produit, même WAC globale) = 20.0
    repository.restock_product(
        db, product_id=product.id, branch_id=branch_b.id,
        quantity=4, company_id=company.id, actor_id=human.id,
        unit_cost=5.0
    )

    val_global = stock.stock_value_at_cost(db, company.id)
    val_branch_a = stock.stock_value_at_cost(db, company.id, branch_id=branch.id)
    val_branch_b = stock.stock_value_at_cost(db, company.id, branch_id=branch_b.id)

    assert val_global == 70.0
    assert val_branch_a == 50.0
    assert val_branch_b == 20.0
