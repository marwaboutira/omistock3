"""
Tests couvrant les Missions 1, 2 et 3 :

Mission 1 — Standardisation des QR Codes
  - Génération automatique du qr_code à la création produit
  - Fallback PROD-{id} si aucun SKU fourni
  - Unicité du QR au sein d'une entreprise
  - Recherche par code (scan) : qr_code > sku > barcode

Mission 2 — Bons de commande multi-lignes (cycle complet)
  - Tests existants déjà couverts dans test_purchase_order.py
  - Ce fichier ajoute le test de sérialisation avec product_name / supplier_name

Mission 3 — Automatisation depuis le Dashboard
  - Endpoint auto-from-alerts : regroupement par fournisseur
  - Endpoints avec liste restreinte de product_ids
  - Aucune alerte → message clair (pas d'erreur)
"""
import pytest

import models
import repository


# =============================================================================
# MISSION 1 : QR Codes
# =============================================================================

def test_create_product_generates_qr_code_from_sku(db, company, branch):
    """Un produit créé avec un SKU reçoit automatiquement qr_code = SKU."""
    from schemas import ProductCreate
    data = ProductCreate(name="Test SKU", sku="SKU-123", price=5.0)
    p = repository.create_product(db, data, company_id=company.id)
    assert p.qr_code == "SKU-123"
    assert p.sku == "SKU-123"


def test_create_product_without_sku_generates_prod_id(db, company):
    """Sans SKU, le système génère un QR code déterministe PROD-{id}."""
    from schemas import ProductCreate
    data = ProductCreate(name="No SKU", price=5.0)
    p = repository.create_product(db, data, company_id=company.id)
    assert p.qr_code is not None
    assert p.qr_code.startswith("PROD-")
    assert p.sku == p.qr_code  # le sku est aussi synchronisé


def test_create_product_qr_uniqueness_across_company(db, company):
    """Deux produits avec le même SKU reçoivent des QR uniques (suffixe incrémental)."""
    from schemas import ProductCreate
    data = ProductCreate(name="Prod A", sku="DUP-SKU", price=5.0)
    a = repository.create_product(db, data, company_id=company.id)
    data2 = ProductCreate(name="Prod B", sku="DUP-SKU", price=5.0)
    b = repository.create_product(db, data2, company_id=company.id)
    # Même SKU → QR différents (uniquité garantie).
    assert a.qr_code != b.qr_code
    assert a.qr_code == "DUP-SKU"
    assert b.qr_code == "DUP-SKU-2"


def test_scan_by_qr_code(db, company, product):
    """get_product_by_code trouve le produit via son qr_code."""
    # Les fixtures product() ne génèrent pas de qr_code automatiquement
    # (créées via ORM direct). On en attribue un manuellement.
    product.qr_code = "SCAN-ME"
    product.sku = "W-1"
    db.commit()
    found = repository.get_product_by_code(db, "SCAN-ME", company.id)
    assert found is not None
    assert found.id == product.id


def test_scan_fallback_to_sku(db, company, product):
    """get_product_by_code cherche dans sku si le qr_code ne matche pas."""
    product.sku = "FIND-BY-SKU"
    product.qr_code = None
    db.commit()
    found = repository.get_product_by_code(db, "FIND-BY-SKU", company.id)
    assert found is not None
    assert found.id == product.id


def test_scan_multi_tenant_isolation(db, company):
    """Le scan ne retourne pas un produit d'une autre entreprise."""
    other_co = models.Company(name="Other Corp")
    db.add(other_co)
    db.flush()
    p = models.Product(name="Secret", sku="SECRET", qr_code="SECRET", company_id=other_co.id)
    db.add(p)
    db.flush()
    found = repository.get_product_by_code(db, "SECRET", company.id)
    assert found is None  # pas de cross-tenant


# =============================================================================
# MISSION 2 : Sérialisation BC (product_name / supplier_name)
# =============================================================================

def test_po_serialization_includes_product_name(db, company, branch, human, product):
    """Le BC sérialisé inclut product_name pour chaque ligne."""
    po = repository.create_purchase_order(
        db, supplier_id=None, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=[{"product_id": product.id, "quantity": 3, "unit_price": 5.0}],
    )
    from routers.purchase_orders import _serialize
    data = _serialize(po)
    assert data["items"][0]["product_name"] == "Widget"


def test_po_serialization_includes_supplier_name(db, company, branch, human, product):
    """Le BC sérialisé inclut supplier_name si un fournisseur est lié."""
    sup = models.Supplier(name="SupplierCo", company_id=company.id)
    db.add(sup)
    db.flush()
    product.supplier_id = sup.id
    db.flush()
    po = repository.create_purchase_order(
        db, supplier_id=sup.id, branch_id=branch.id, company_id=company.id,
        actor_id=human.id, items=[{"product_id": product.id, "quantity": 1, "unit_price": 2.0}],
    )
    from routers.purchase_orders import _serialize
    data = _serialize(po)
    assert data["supplier_name"] == "SupplierCo"


# =============================================================================
# MISSION 3 : Auto-order from alerts
# =============================================================================

def _setup_alert(db, company, branch, supplier, qty=2, min_threshold=5):
    """Crée un produit en alerte critique (stock < seuil)."""
    p = models.Product(
        name="LowStock", sku="LOW-1", price=10.0, min_threshold=min_threshold,
        company_id=company.id, supplier_id=supplier.id,
    )
    db.add(p)
    db.flush()
    inv = models.Inventory(product_id=p.id, branch_id=branch.id, quantity=qty,
                          min_threshold=min_threshold)
    db.add(inv)
    db.flush()
    return p


def _admin_client(human):
    """Client TestClient avec la dépendance get_current_admin court-circuitée
    sur l'utilisateur fourni (évite la validation JWT en test)."""
    # L'endpoint auto-from-alerts requiert un ADMIN ; on force le type.
    human.user_type = "ADMIN"
    from fastapi.testclient import TestClient
    import main
    from dependencies import get_current_admin

    main.app.dependency_overrides[get_current_admin] = lambda: human
    return TestClient(main.app)


def _clear_overrides():
    import main
    main.app.dependency_overrides = {}


def test_auto_order_groups_by_supplier(db, company, branch, human):
    """auto-from-alerts crée un BC par fournisseur distinct."""
    sup1 = models.Supplier(name="Supplier A", company_id=company.id)
    sup2 = models.Supplier(name="Supplier B", company_id=company.id)
    db.add_all([sup1, sup2])
    db.flush()
    p1 = _setup_alert(db, company, branch, sup1, qty=1)
    p2 = _setup_alert(db, company, branch, sup2, qty=0)
    db.refresh(p1)
    db.refresh(p2)
    # COMMIT : l'endpoint utilise une session distincte (get_db) qui ne voit
    # que les données effectivement validées.
    db.commit()

    try:
        c = _admin_client(human)
        r = c.post("/api/purchase-orders/auto-from-alerts",
                   headers={"Authorization": "Bearer fake"},
                   json={"branch_id": branch.id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2  # un BC par fournisseur
        assert len(body["created"]) == 2
        # Vérifier que les deux BC ont des suppliers différents.
        sids = {po["supplier_id"] for po in body["created"]}
        assert len(sids) == 2
    finally:
        _clear_overrides()


def test_auto_order_with_product_ids_filter(db, company, branch, human):
    """auto-from-alerts ne commande que les product_ids demandés."""
    sup = models.Supplier(name="Sup", company_id=company.id)
    db.add(sup)
    db.flush()
    p1 = _setup_alert(db, company, branch, sup, qty=1)
    p2 = _setup_alert(db, company, branch, sup, qty=0)
    db.refresh(p1)

    try:
        c = _admin_client(human)
        r = c.post("/api/purchase-orders/auto-from-alerts",
                   headers={"Authorization": "Bearer fake"},
                   json={"product_ids": [p1.id], "branch_id": branch.id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        assert body["created"][0]["items_count"] == 1
    finally:
        _clear_overrides()


def test_auto_order_no_alerts(db, company, branch, human):
    """auto-from-alerts retourne un message clair si aucune alerte."""
    try:
        c = _admin_client(human)
        r = c.post("/api/purchase-orders/auto-from-alerts",
                   headers={"Authorization": "Bearer fake"},
                   json={})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 0
        assert "Aucun" in r.json()["message"]
    finally:
        _clear_overrides()
