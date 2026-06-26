
import os
import sys
from datetime import datetime, timedelta, timezone

# Ajouter le chemin du backend pour l'import des modèles
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine
import models, security
from sqlalchemy.orm import Session

def seed(admin_only=False):
    # S'assurer que les tables existent
    models.Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    
    try:
        # 1. Nettoyage Complet
        print("Nettoyage des anciennes données...")
        db.query(models.ActivityLog).delete()
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

        # 2. Création de l'Entreprise
        print("Création de l'entreprise : OMISTOCK BUSINESS SOLUTIONS...")
        company = models.Company(name="OMISTOCK BUSINESS SOLUTIONS")
        db.add(company)
        db.commit()
        db.refresh(company)

        # 3. Création des Filiales
        print("Création des dépôts Alger et Oran...")
        b_alger = models.Branch(name="Dépôt Alger", city="Alger", company_id=company.id)
        b_oran = models.Branch(name="Dépôt Oran", city="Oran", company_id=company.id)
        db.add_all([b_alger, b_oran])
        db.commit()
        db.refresh(b_alger)
        db.refresh(b_oran)

        # 4. Création des Administrateurs
        print("Création des comptes administrateurs (Alger, Oran, Constantine)...")
        admin = models.User(
            email="admin@test.com",
            hashed_password=security.get_password_hash("password123"),
            company_id=company.id,
            branch_id=b_alger.id,
            user_type="ADMIN"
        )
        oran_admin = models.User(
            email="oran@test.com",
            hashed_password=security.get_password_hash("password123"),
            company_id=company.id,
            branch_id=b_oran.id,
            user_type="ADMIN"
        )
        db.add_all([admin, oran_admin])
        
        # Deuxième entreprise
        print("Création de l'entreprise AGRO-INDUSTRIE DZ...")
        company2 = models.Company(name="AGRO-INDUSTRIE DZ")
        db.add(company2)
        db.commit()
        db.refresh(company2)
        
        b_const = models.Branch(name="Dépôt Constantine", city="Constantine", company_id=company2.id)
        db.add(b_const)
        db.commit()
        db.refresh(b_const)
        
        food_admin = models.User(
            email="food_admin@test.com",
            hashed_password=security.get_password_hash("password123"),
            company_id=company2.id,
            branch_id=b_const.id,
            user_type="ADMIN"
        )
        db.add(food_admin)
        db.commit()

        if admin_only:
            print("Auto-seed (Admin only) terminé avec succès !")
            db.commit()
            return

        # 5. Création des Fournisseurs (Saidal en priorité)
        print("Ajout des fournisseurs (Saidal Group)...")
        s_saidal = models.Supplier(name="Saidal Group", email="contact@saidal.dz", company_id=company.id)
        s_biopharm = models.Supplier(name="Biopharm", email="info@biopharm.com", company_id=company.id)
        db.add_all([s_saidal, s_biopharm])
        db.commit()
        db.refresh(s_saidal)
        # 6. Création des Produits Universels (IT, Santé, Agro)
        print("Ajout du catalogue pharmaceutique...")
        products_data = [
            # Produits pharmaceutiques
            {"name": "Amoxicilline 1g", "sku": "PHA-AME-1G", "price": 300.0, "qty": 200, "min": 50, "sid": s_saidal.id},
            {"name": "Ibuprofène 400mg", "sku": "PHA-IBU-400", "price": 200.0, "qty": 250, "min": 60, "sid": s_saidal.id},
            {"name": "Vitamine C 1000mg", "sku": "PHA-VITC-1000", "price": 150.0, "qty": 300, "min": 70, "sid": s_saidal.id},
            {"name": "Sérum Physiologique 500ml", "sku": "PHA-SER-500", "price": 120.0, "qty": 180, "min": 40, "sid": s_saidal.id},
            {"name": "Gants Latex", "sku": "PHA-GNT-LAT", "price": 50.0, "qty": 500, "min": 100, "sid": s_saidal.id},
            {"name": "Masques Chirurgicaux", "sku": "PHA-MSK-CHIR", "price": 80.0, "qty": 400, "min": 80, "sid": s_saidal.id},
            {"name": "Alcool Médical 1L", "sku": "PHA-ALC-1L", "price": 100.0, "qty": 150, "min": 30, "sid": s_saidal.id},
            {"name": "Paracétamol Sirop Enfant", "sku": "PHA-PAR-SIR", "price": 180.0, "qty": 120, "min": 40, "sid": s_saidal.id},
            {"name": "Thermomètre Digital", "sku": "PHA-THM-DIG", "price": 250.0, "qty": 100, "min": 20, "sid": s_saidal.id},
            {"name": "Compresses Stériles", "sku": "PHA-CMP-STER", "price": 60.0, "qty": 300, "min": 60, "sid": s_saidal.id},
            # Produits cosmétiques
            {"name": "Crème Hydratante Visage 50ml", "sku": "COS-CRH-50", "price": 450.0, "qty": 180, "min": 40, "sid": s_saidal.id},
            {"name": "Écran Solaire SPF50 100ml", "sku": "COS-ECS-SPF50", "price": 1200.0, "qty": 150, "min": 30, "sid": s_saidal.id},
            {"name": "Gel Nettoyant Visage 200ml", "sku": "COS-GNL-200", "price": 320.0, "qty": 220, "min": 50, "sid": s_saidal.id},
            {"name": "Baume à Lèvres Réparateur", "sku": "COS-BLM-RPR", "price": 180.0, "qty": 300, "min": 80, "sid": s_saidal.id},
            {"name": "Shampooing Dermatologique 250ml", "sku": "COS-SHD-DRM", "price": 550.0, "qty": 160, "min": 40, "sid": s_saidal.id},
            {"name": "Lotion Micellaire 400ml", "sku": "COS-LTM-400", "price": 480.0, "qty": 140, "min": 35, "sid": s_saidal.id},
            {"name": "Eau Thermale 300ml", "sku": "COS-ETP-300", "price": 350.0, "qty": 200, "min": 50, "sid": s_saidal.id},
            {"name": "Crème Mains Nourrissante", "sku": "COS-CMN-NRS", "price": 390.0, "qty": 175, "min": 45, "sid": s_saidal.id},
            # Produits Autres (MAT)
            {"name": "Test de Grossesse", "sku": "MAT-TST-GRS", "price": 80.0, "qty": 120, "min": 30, "sid": s_saidal.id},
            {"name": "Bandelettes Glycémie", "sku": "MAT-BGT-GLC", "price": 250.0, "qty": 250, "min": 60, "sid": s_saidal.id},
            {"name": "Tensiomètre Électronique", "sku": "MAT-TNS-ELE", "price": 3500.0, "qty": 80, "min": 20, "sid": s_saidal.id},
            {"name": "Seringues Usage Unique", "sku": "MAT-SRING-UN", "price": 150.0, "qty": 400, "min": 100, "sid": s_saidal.id},
            {"name": "Pansements Stériles", "sku": "MAT-PNS-ST", "price": 95.0, "qty": 350, "min": 70, "sid": s_saidal.id},
            {"name": "Solution Désinfectante Surface", "sku": "MAT-SDS-SRF", "price": 180.0, "qty": 200, "min": 50, "sid": s_saidal.id},
            {"name": "Boîte Collecteur Aiguilles", "sku": "MAT-BCA", "price": 220.0, "qty": 90, "min": 25, "sid": s_saidal.id},
        ]

        products = []
        for p in products_data:
            prod = models.Product(
                name=p["name"],
                sku=p["sku"],
                price=p["price"],
                quantity=p["qty"],
                min_threshold=p["min"],
                company_id=company.id,
                supplier_id=p["sid"]
            )
            db.add(prod)
            products.append(prod)
        db.commit()
        for p in products: db.refresh(p)

        # 7. Initialisation des Stocks et Inventaires
        print("Répartition du stock entre Alger et Oran...")
        ratios_alger = [0.82, 0.11, 0.45, 0.75, 0.60, 0.35, 0.68, 0.25, 0.55, 0.40,
            0.65, 0.20, 0.50, 0.70, 0.45, 0.30, 0.55, 0.40,
            0.58, 0.32, 0.42, 0.60, 0.48, 0.35, 0.45]
        for idx, p in enumerate(products):
            q_alg = int(p.quantity * ratios_alger[idx])
            q_orn = p.quantity - q_alg
            
            inv_alg = models.Inventory(branch_id=b_alger.id, product_id=p.id, quantity=q_alg, min_threshold=p.min_threshold)
            inv_orn = models.Inventory(branch_id=b_oran.id, product_id=p.id, quantity=q_orn, min_threshold=p.min_threshold)
            db.add_all([inv_alg, inv_orn])
            
            # Mouvement initial (Entrée)
            mov = models.StockMovement(
                product_id=p.id,
                branch_id=b_alger.id,
                quantity=p.quantity,
                reason="Réception Stock Initial",
                movement_type="IN",
                company_id=company.id,
                created_at=datetime.now(timezone.utc) - timedelta(days=2)
            )
            db.add(mov)

        # 8. Transactions entre Alger et Oran (Transfert)
        print("Simulation d'un transfert Alger -> Oran...")
        # Transférer 50 Doliprane d'Alger vers Oran
        doliprane = products[0]
        transfer_qty = 50
        
        # Sortie d'Alger
        mov_out = models.StockMovement(
            product_id=doliprane.id,
            branch_id=b_alger.id,
            quantity=-transfer_qty,
            reason="Transfert vers Oran",
            movement_type="OUT",
            company_id=company.id
        )
        # Entrée à Oran
        mov_in = models.StockMovement(
            product_id=doliprane.id,
            branch_id=b_oran.id,
            quantity=transfer_qty,
            reason="Réception de Alger",
            movement_type="IN",
            company_id=company.id
        )
        db.add_all([mov_out, mov_in])

        # 9. Statistiques de Performance (Ventes Saidal)
        print("Simulation de ventes pour générer des statistiques...")
        customer = models.Customer(name="Pharmacie El-Chifa", company_id=company.id)
        db.add(customer)
        db.commit()
        db.refresh(customer)

        # Ventes sur les 5 derniers jours pour le graphique
        for i in range(5):
            sale_date = datetime.now(timezone.utc) - timedelta(days=i)
            # Vente d'un produit Saidal (Doliprane ou Amoxicilline)
            p_saidal = products[i % 2] 
            sale = models.Sale(
                customer_id=customer.id,
                company_id=company.id,
                branch_id=b_alger.id,
                total_amount=p_saidal.price * 10,
                date=sale_date
            )
            db.add(sale)
            db.commit()
            db.refresh(sale)
            
            item = models.SaleItem(
                sale_id=sale.id,
                product_id=p_saidal.id,
                quantity=10,
                unit_price=p_saidal.price
            )
            db.add(item)
            
            # Déduire du stock (Mouvement OUT)
            mov_sale = models.StockMovement(
                product_id=p_saidal.id,
                branch_id=b_alger.id,
                quantity=-10,
                reason="Vente client",
                movement_type="OUT",
                company_id=company.id,
                created_at=sale_date
            )
            db.add(mov_sale)

        db.commit()
        print("Seeding terminé avec succès !")

    except Exception as e:
        db.rollback()
        print(f"Erreur lors du seeding : {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
