import os
import sys

# Fix: Ajouter le dossier backend au path pour permettre les imports quand on lance depuis la racine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import models
import security
from database import SessionLocal, engine
from sqlalchemy.sql import func


def init_db():
    # Créer les tables si elles n'existent pas
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # Nettoyage pour repartir sur du propre pour la démo Pharma
    db.query(models.StockMovement).delete()
    db.query(models.SaleItem).delete()
    db.query(models.Sale).delete()
    db.query(models.Customer).delete()
    db.query(models.Inventory).delete()
    db.query(models.Product).delete()
    db.query(models.Supplier).delete()
    db.query(models.User).delete()
    db.query(models.Branch).delete()
    db.query(models.Company).delete()
    db.commit()

    # 1. Création de l'Entreprise Mère
    print("Création de OMISTOCK BUSINESS SOLUTIONS...")
    company = models.Company(name="OMISTOCK BUSINESS SOLUTIONS")
    db.add(company)
    db.commit()
    db.refresh(company)

    # 2. Création des Filiales (Branches)
    print("Création des filiales...")
    b_alger = models.Branch(
        name="Dépôt Central Alger", city="Alger", company_id=company.id
    )
    b_oran = models.Branch(name="Unité Oran", city="Oran", company_id=company.id)
    db.add_all([b_alger, b_oran])
    db.commit()
    db.refresh(b_alger)
    db.refresh(b_oran)

    # 3. Création des utilisateurs
    print("Création des utilisateurs...")
    admin = models.User(
        email="admin@test.com",
        hashed_password=security.get_password_hash("password123"),
        company_id=company.id,
        branch_id=b_alger.id,
        user_type="ADMIN",
    )
    oran_admin = models.User(
        email="oran@test.com",
        hashed_password=security.get_password_hash("password123"),
        company_id=company.id,
        branch_id=b_oran.id,
        user_type="ADMIN",
    )
    db.add_all([admin, oran_admin])
    db.commit()

    # 4. Création des Fournisseurs
    print("Création des fournisseurs...")
    s_saidal = models.Supplier(
        name="Saidal",
        contact_name="Direction",
        email="contact@saidal.dz",
        company_id=company.id,
    )
    s_biopharm = models.Supplier(
        name="Biopharm",
        contact_name="Logistique",
        email="supply@biopharm.com",
        company_id=company.id,
    )
    db.add_all([s_saidal, s_biopharm])
    db.commit()
    db.refresh(s_saidal)
    db.refresh(s_biopharm)

    # 5. Création du Catalogue Produits
    print("Ajout du catalogue pharma/parapharma...")
    products_data = [
        {
            "name": "Doliprane 500mg (Boîte 16)",
            "sku": "PHA-DOL-500",
            "barcode": "1001",
            "price": 250.0,
            "qty": 500,
            "min": 100,
            "sid": s_saidal.id,
        },
        {
            "name": "Amoxicilline 1g (Boîte 12)",
            "sku": "PHA-AMO-1G",
            "barcode": "1002",
            "price": 1200.0,
            "qty": 180,
            "min": 60,
            "sid": s_saidal.id,
        },
        {
            "name": "Ibuprofène 400mg",
            "sku": "PHA-IBU-400",
            "barcode": "1003",
            "price": 450.0,
            "qty": 340,
            "min": 90,
            "sid": s_saidal.id,
        },
        {
            "name": "Vitamine C 1000mg",
            "sku": "PHA-VIT-C",
            "barcode": "1004",
            "price": 650.0,
            "qty": 410,
            "min": 100,
            "sid": s_biopharm.id,
        },
        {
            "name": "Sérum Physiologique 500ml",
            "sku": "PHA-SER-500",
            "barcode": "1005",
            "price": 120.0,
            "qty": 850,
            "min": 180,
            "sid": s_biopharm.id,
        },
        {
            "name": "Gants Latex Taille M",
            "sku": "PHA-GAN-M",
            "barcode": "1006",
            "price": 45.0,
            "qty": 2300,
            "min": 500,
            "sid": s_biopharm.id,
        },
        {
            "name": "Masques Chirurgicaux Boîte 50",
            "sku": "PHA-MAS-50",
            "barcode": "1007",
            "price": 35.0,
            "qty": 1500,
            "min": 300,
            "sid": s_biopharm.id,
        },
        {
            "name": "Alcool Médical 1L",
            "sku": "PHA-ALC-1L",
            "barcode": "1008",
            "price": 890.0,
            "qty": 270,
            "min": 90,
            "sid": s_biopharm.id,
        },
        {
            "name": "Paracétamol Sirop Enfant",
            "sku": "PHA-PAR-SIR",
            "barcode": "1009",
            "price": 380.0,
            "qty": 160,
            "min": 70,
            "sid": s_saidal.id,
        },
        {
            "name": "Thermomètre Digital",
            "sku": "PHA-THER-DIG",
            "barcode": "1010",
            "price": 1600.0,
            "qty": 95,
            "min": 100,
            "sid": s_biopharm.id,
        },
        {
            "name": "Tensiomètre Bras",
            "sku": "PHA-TENS-BR",
            "barcode": "1011",
            "price": 4200.0,
            "qty": 60,
            "min": 70,
            "sid": s_biopharm.id,
        },
        {
            "name": "Compresses Stériles",
            "sku": "PHA-COMP-STER",
            "barcode": "1012",
            "price": 180.0,
            "qty": 700,
            "min": 150,
            "sid": s_biopharm.id,
        },
    ]

    products = []
    inventories = {}
    for idx, pdata in enumerate(products_data):
        product = models.Product(
            name=pdata["name"],
            sku=pdata["sku"],
            barcode=pdata["barcode"],
            price=pdata["price"],
            min_threshold=pdata["min"],
            company_id=company.id,
            supplier_id=pdata["sid"],
        )
        db.add(product)
        products.append(product)
    db.commit()
    for product in products:
        db.refresh(product)

    # 6. Création des Clients
    print("Création des clients de test...")
    c1 = models.Customer(
        name="Pharmacie Centrale Alger",
        email="contact@pharmacie-centrale.dz",
        phone="021000000",
        company_id=company.id,
    )
    c2 = models.Customer(
        name="Clinique Es-Saada",
        email="contact@clinique-essaada.dz",
        phone="041000000",
        company_id=company.id,
    )
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    # 7. État Initial des Stocks (Inventaire par Branche)
    print("Initialisation des stocks par branche...")
    movement_in = []
    for pdata, product in zip(products_data, products):
        qty_alger = int(pdata["qty"] * 0.65)
        qty_oran = pdata["qty"] - qty_alger

        inv_alg = models.Inventory(
            branch_id=b_alger.id,
            product_id=product.id,
            quantity=qty_alger,
            min_threshold=pdata["min"],
        )
        inv_orn = models.Inventory(
            branch_id=b_oran.id,
            product_id=product.id,
            quantity=qty_oran,
            min_threshold=pdata["min"],
        )
        db.add_all([inv_alg, inv_orn])
        inventories[product.sku] = {"alger": inv_alg, "oran": inv_orn}

        movement_in.extend(
            [
                models.StockMovement(
                    product_id=product.id,
                    branch_id=b_alger.id,
                    quantity=qty_alger,
                    reason="Stock initial",
                    company_id=company.id,
                    movement_type="IN",
                ),
                models.StockMovement(
                    product_id=product.id,
                    branch_id=b_oran.id,
                    quantity=qty_oran,
                    reason="Stock initial",
                    company_id=company.id,
                    movement_type="IN",
                ),
            ]
        )

    db.commit()

    # 8. Mouvements initiaux "IN"
    print("Enregistrement des mouvements initiaux...")
    db.add_all(movement_in)
    db.commit()

    # 9. Simulation de Transfert inter-filiales (DÉSACTIVÉ POUR LA DÉMO MANUELLE)
    print("Prêt pour la démo de transfert Alger -> Oran.")

    sku_map = {product.sku: product for product in products}
    p_dol = sku_map["PHA-DOL-500"]
    p_amo = sku_map["PHA-AMO-1G"]
    p_ser = sku_map["PHA-SER-500"]

    # 10. Simulation de Ventes
    print("Simulation de ventes...")
    sale1 = models.Sale(
        customer_id=c1.id,
        company_id=company.id,
        branch_id=b_alger.id,
        total_amount=(30 * p_amo.price + 20 * p_dol.price),
    )
    db.add(sale1)
    db.commit()
    db.refresh(sale1)

    si1 = models.SaleItem(
        sale_id=sale1.id, product_id=p_amo.id, quantity=30, unit_price=p_amo.price
    )
    si2 = models.SaleItem(
        sale_id=sale1.id, product_id=p_dol.id, quantity=20, unit_price=p_dol.price
    )
    db.add_all([si1, si2])

    m_out1 = models.StockMovement(
        product_id=p_amo.id,
        branch_id=b_alger.id,
        quantity=30,
        reason="Vente Client",
        company_id=company.id,
        movement_type="OUT",
    )
    m_out2 = models.StockMovement(
        product_id=p_dol.id,
        branch_id=b_alger.id,
        quantity=20,
        reason="Vente Client",
        company_id=company.id,
        movement_type="OUT",
    )
    db.add_all([m_out1, m_out2])

    inventories["PHA-AMO-1G"]["alger"].quantity -= 30
    inventories["PHA-DOL-500"]["alger"].quantity -= 20

    sale2 = models.Sale(
        customer_id=c2.id,
        company_id=company.id,
        branch_id=b_oran.id,
        total_amount=(25 * p_ser.price),
    )
    db.add(sale2)
    db.commit()
    db.refresh(sale2)

    si3 = models.SaleItem(
        sale_id=sale2.id, product_id=p_ser.id, quantity=25, unit_price=p_ser.price
    )
    db.add(si3)

    m_out3 = models.StockMovement(
        product_id=p_ser.id,
        branch_id=b_oran.id,
        quantity=25,
        reason="Vente Client",
        company_id=company.id,
        movement_type="OUT",
    )
    db.add(m_out3)

    inventories["PHA-SER-500"]["oran"].quantity -= 25

    db.commit()

    # 11. Mettre à jour la quantité globale dans la table Product pour le dashboard (somme des filiales)
    for product in products:
        inv = inventories[product.sku]
        product.quantity = inv["alger"].quantity + inv["oran"].quantity
    db.commit()

    # --- 12. Création de la DEUXIÈME entreprise : AGRO-INDUSTRIE DZ ---
    print("Création de AGRO-INDUSTRIE DZ...")
    company2 = models.Company(name="AGRO-INDUSTRIE DZ")
    db.add(company2)
    db.commit()
    db.refresh(company2)

    # Filiale Constantine
    b_const = models.Branch(
        name="Dépôt Constantine", city="Constantine", company_id=company2.id
    )
    db.add(b_const)
    db.commit()
    db.refresh(b_const)

    # Admin Alimentation
    admin2 = models.User(
        email="food_admin@test.com",
        hashed_password=security.get_password_hash("password123"),
        company_id=company2.id,
        branch_id=b_const.id,
    )
    db.add(admin2)
    db.commit()

    # Produits Alimentation
    print("Ajout du catalogue Alimentation...")
    pa1 = models.Product(
        name="Couscous 1kg",
        sku="ALI-COU-1K",
        barcode="5001",
        price=150.0,
        quantity=500,
        min_threshold=100,
        company_id=company2.id,
    )
    pa2 = models.Product(
        name="Huile d'olive 1L",
        sku="ALI-HUI-1L",
        barcode="5002",
        price=950.0,
        quantity=120,
        min_threshold=30,
        company_id=company2.id,
    )
    db.add_all([pa1, pa2])
    db.commit()

    # Inventaire Alimentation
    inv_pa1 = models.Inventory(branch_id=b_const.id, product_id=pa1.id, quantity=500)
    inv_pa2 = models.Inventory(branch_id=b_const.id, product_id=pa2.id, quantity=120)
    db.add_all([inv_pa1, inv_pa2])
    db.commit()

    db.close()
    print("Initialisation complète (Multi-Entreprise) terminée avec succès !")


if __name__ == "__main__":
    init_db()
