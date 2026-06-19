"""
Tests du cycle de vie des bons de commande : DRAFT -> SENT -> RECEIVED.

On teste directement la couche repository (logique métier), comme les autres tests.
Point clé : la réception entre le stock ET alimente le coût moyen pondéré (WAC)
à partir du prix d'achat (unit_price) — exigence du rapport de revue.
"""
import pytest

import models
import repository


def _items(product, qty=10, unit_price=5.0):
    return [{"product_id": product.id, "quantity": qty, "unit_price": unit_price}]


def test_create_po_is_draft_and_does_not_touch_stock(db, company, branch, human, product):
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=_items(product, qty=10, unit_price=5.0),
    )
    assert po.status == models.OrderStatus.DRAFT.value
    assert po.total_amount == 50.0          # 10 * 5.0
    assert len(po.items) == 1
    db.refresh(product)
    assert product.total_quantity == 0       # le brouillon ne touche pas au stock


def test_receive_forbidden_from_draft(db, company, branch, human, product):
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=_items(product),
    )
    # Recevoir directement depuis DRAFT (sans SENT) doit échouer.
    with pytest.raises(ValueError):
        repository.receive_purchase_order(db, po.id, company.id, human.id)


def test_full_cycle_increases_stock_and_updates_wac(db, company, branch, human, product):
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=_items(product, qty=10, unit_price=5.0),
    )
    po = repository.send_purchase_order(db, po.id, company.id, human.id)
    assert po.status == models.OrderStatus.SENT.value

    po = repository.receive_purchase_order(db, po.id, company.id, human.id)
    assert po.status == models.OrderStatus.RECEIVED.value
    assert po.received_at is not None

    db.refresh(product)
    assert product.total_quantity == 10              # stock entré
    assert product.cost_price == 5.0                 # WAC alimenté par unit_price


def test_double_receive_is_rejected(db, company, branch, human, product):
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=_items(product),
    )
    repository.send_purchase_order(db, po.id, company.id, human.id)
    repository.receive_purchase_order(db, po.id, company.id, human.id)
    # Une seconde réception doit être refusée (le BC n'est plus en statut SENT).
    with pytest.raises(ValueError):
        repository.receive_purchase_order(db, po.id, company.id, human.id)


def test_cancel_from_draft(db, company, branch, human, product):
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=_items(product),
    )
    po = repository.cancel_purchase_order(db, po.id, company.id, human.id)
    assert po.status == models.OrderStatus.CANCELLED.value
    db.refresh(product)
    assert product.total_quantity == 0               # annulation = pas de stock
