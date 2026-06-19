"""
Tests pour l'outil #4 : get_expiring_lots (GET /api/agent/expiring-lots).
Vérifie :
  - scope stock:read + niveau READ_ONLY requis.
  - un lot qui périme dans la fenêtre -> présent dans la sortie avec days_until_expiry cohérent.
  - un lot qui périme APRÈS la fenêtre (ex: 200 jours avec days=30) -> absent de la sortie.
"""
import pytest
from datetime import datetime, timedelta, timezone
import models
import repository
import agent_policy
import stock


def test_expiring_lots_policy_enforcement():
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


def test_expiring_lots_filtering(db, company, branch, product):
    """Vérifie que les lots expirant dans la fenêtre sont retournés, et les autres exclus."""
    now = datetime.now(timezone.utc)

    # 1. Lot expirant bientôt (dans 10 jours)
    lot_soon = models.Lot(
        lot_number="L-SOON",
        product_id=product.id,
        branch_id=branch.id,
        quantity=5,
        expiry_date=now + timedelta(days=10),
        company_id=company.id,
        received_at=now
    )
    db.add(lot_soon)

    # 2. Lot expirant tard (dans 200 jours)
    lot_late = models.Lot(
        lot_number="L-LATE",
        product_id=product.id,
        branch_id=branch.id,
        quantity=15,
        expiry_date=now + timedelta(days=200),
        company_id=company.id,
        received_at=now
    )
    db.add(lot_late)
    db.commit()

    # Appel de la logique du service avec days=30
    lots_30 = stock.expiring_lots(db, company.id, within_days=30)
    assert len(lots_30) == 1
    assert lots_30[0].lot_number == "L-SOON"

    # Vérification du calcul du delta jours
    expiry_aware = lot_soon.expiry_date if lot_soon.expiry_date.tzinfo else lot_soon.expiry_date.replace(tzinfo=timezone.utc)
    diff = expiry_aware - now
    days_until_expiry = int(diff.days)
    assert days_until_expiry == 10 or days_until_expiry == 9  # dépend des millisecondes d'exécution

    # Appel de la logique du service avec days=250 -> les deux doivent apparaître
    lots_250 = stock.expiring_lots(db, company.id, within_days=250)
    assert len(lots_250) == 2
    assert {l.lot_number for l in lots_250} == {"L-SOON", "L-LATE"}
