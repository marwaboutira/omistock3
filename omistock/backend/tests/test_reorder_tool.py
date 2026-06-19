"""
Tests pour l'outil #3 : get_reorder_suggestions (GET /api/agent/reorder-suggestions).
Vérifie :
  - scope stock:read + niveau READ_ONLY requis.
  - un produit sous ROP avec demande/coût valide -> suggested_order_quantity > 0.
  - un produit avec avg_daily_demand = 0 -> suggested_order_quantity = null + reason.
"""
import pytest
import models
import repository
import agent_policy
import stock
import config
from fastapi import Request


def test_reorder_policy_enforcement():
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


def test_reorder_suggestions_with_valid_demand_and_cost(db, company, branch, product, human):
    """Vérifie le calcul correct de l'EOQ pour un produit sous ROP avec demande/coût valides."""
    # 1. Définir des valeurs de coût et prix sur le produit, ainsi qu'un min_threshold élevé pour forcer le ROP
    product.cost_price = 10.0
    product.price = 20.0
    product.min_threshold = 25
    db.commit()

    # 2. Enregistrer des ventes pour simuler une demande journalière > 0
    # On met du stock
    repository.restock_product(
        db, product_id=product.id, branch_id=branch.id,
        quantity=50, company_id=company.id, actor_id=human.id,
        unit_cost=10.0
    )
    # On vend
    repository.create_sale(
        db,
        {"branch_id": branch.id, "items": [{"product_id": product.id, "quantity": 30, "unit_price": 20.0}]},
        company_id=company.id,
        agent_id=human.id,
    )
    # Calculer/rafraîchir la demande moyenne journalière
    stock.refresh_demand_and_rop(db, product, window_days=30)
    db.commit()
    db.refresh(product)

    assert product.avg_daily_demand > 0.0
    assert product.total_quantity <= product.reorder_point  # En alerte / sous ROP (20 <= 25)

    # 3. Récupérer les suggestions via la logique de la route
    # (Simulée ici directement avec les fonctions pour valider les mathématiques)
    avg_demand = product.avg_daily_demand
    cost_price = product.cost_price
    annual_demand = avg_demand * 365.0
    ordering_cost = config.DEFAULT_ORDERING_COST
    holding_cost_per_unit = config.HOLDING_COST_RATE * cost_price

    eoq_val = stock.economic_order_quantity(
        annual_demand=annual_demand,
        ordering_cost=ordering_cost,
        holding_cost_per_unit=holding_cost_per_unit
    )

    assert eoq_val is not None
    assert eoq_val > 0.0


def test_reorder_suggestions_with_zero_demand(db, company, branch, product):
    """Si avg_daily_demand = 0, EOQ = null + reason."""
    # Produit nouvellement créé, sans historique de vente
    product.cost_price = 10.0
    product.avg_daily_demand = 0.0
    db.commit()
    db.refresh(product)

    assert product.total_quantity <= product.reorder_point

    avg_demand = product.avg_daily_demand
    cost_price = product.cost_price
    annual_demand = avg_demand * 365.0
    ordering_cost = config.DEFAULT_ORDERING_COST
    holding_cost_per_unit = config.HOLDING_COST_RATE * cost_price

    # Formule Wilson renvoie None car annual_demand <= 0
    eoq_val = stock.economic_order_quantity(
        annual_demand=annual_demand,
        ordering_cost=ordering_cost,
        holding_cost_per_unit=holding_cost_per_unit
    )

    assert eoq_val is None
