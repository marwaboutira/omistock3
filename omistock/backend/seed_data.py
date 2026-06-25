
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
            # Pharmaceutique (Pharmacie)
            {"name": "Doliprane 500 mg", "sku": "PHA-DOL-500", "price": 250.0, "qty": 500, "min": 100, "sid": s_saidal.id},
            {"name": "Amoxicilline 1 g", "sku": "PHA-AMO-1G", "price": 300.0, "qty": 200, "min": 50, "sid": s_saidal.id},
            {"name": "Ibuprofène 400 mg", "sku": "PHA-IBU-400", "price": 350.0, "qty": 300, "min": 60, "sid": s_saidal.id},
            {"name": "Paracétamol 1 g", "sku": "PHA-PAR-1G", "price": 200.0, "qty": 400, "min": 80, "sid": s_saidal.id},
            {"name": "Vitamine C 1000 mg", "sku": "PHA-VITC-1000", "price": 900.0, "qty": 200, "min": 40, "sid": s_saidal.id},
            {"name": "Sérum Physiologique", "sku": "PHA-SER-PHY", "price": 120.0, "qty": 180, "min": 40, "sid": s_saidal.id},
            {"name": "Oméprazole 20 mg", "sku": "PHA-OME-20", "price": 450.0, "qty": 150, "min": 30, "sid": s_saidal.id},
            {"name": "Solution Antiseptique", "sku": "PHA-SOL-ANT", "price": 280.0, "qty": 250, "min": 50, "sid": s_saidal.id},

            # Cosmétique
            {"name": "Crème Hydratante Visage 50ml", "sku": "COS-CRE-HYD-50", "price": 1800.0, "qty": 120, "min": 30, "sid": s_biopharm.id},
            {"name": "Écran Solaire SPF50 100ml", "sku": "COS-SOL-SPF50", "price": 2200.0, "qty": 90, "min": 20, "sid": s_biopharm.id},
            {"name": "Gel Nettoyant Visage 200ml", "sku": "COS-GEL-NET-200", "price": 1500.0, "qty": 140, "min": 40, "sid": s_biopharm.id},
            {"name": "Baume à Lèvres Réparateur", "sku": "COS-BAU-LEV", "price": 450.0, "qty": 200, "min": 50, "sid": s_biopharm.id},
            {"name": "Shampooing Dermatologique 250ml", "sku": "COS-SHA-DER-250", "price": 1300.0, "qty": 110, "min": 25, "sid": s_biopharm.id},
            {"name": "Lotion Micellaire 400ml", "sku": "COS-LOT-MIC-400", "price": 1600.0, "qty": 95, "min": 20, "sid": s_biopharm.id},

            # Autres (Dispositifs & Consommables)
            {"name": "Masques Chirurgicaux", "sku": "MAT-MSK-CHIR", "price": 80.0, "qty": 400, "min": 80, "sid": s_biopharm.id},
            {"name": "Gants Jetables", "sku": "MAT-GNT-JET", "price": 50.0, "qty": 500, "min": 100, "sid": s_biopharm.id},
            {"name": "Thermomètre Digital", "sku": "MAT-THM-DIG", "price": 250.0, "qty": 100, "min": 20, "sid": s_biopharm.id},
            {"name": "Tensiomètre Électronique", "sku": "MAT-TEN-ELEC", "price": 4500.0, "qty": 30, "min": 5, "sid": s_biopharm.id},
            {"name": "Pansements Stériles", "sku": "MAT-PAN-STE", "price": 150.0, "qty": 300, "min": 50, "sid": s_biopharm.id},
            {"name": "Compresses Stériles", "sku": "MAT-CMP-STE", "price": 60.0, "qty": 300, "min": 60, "sid": s_biopharm.id},
            {"name": "Seringues Usage Unique", "sku": "MAT-SER-UNI", "price": 30.0, "qty": 600, "min": 150, "sid": s_biopharm.id},
            {"name": "Gel Hydroalcoolique 500 ml", "sku": "MAT-GEL-HYD", "price": 350.0, "qty": 250, "min": 60, "sid": s_biopharm.id},
            {"name": "Test de Grossesse", "sku": "MAT-TST-GRO", "price": 200.0, "qty": 120, "min": 30, "sid": s_biopharm.id},
            {"name": "Bandelettes Glycémie", "sku": "MAT-BAN-GLY", "price": 1200.0, "qty": 80, "min": 15, "sid": s_biopharm.id},
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
        for p in products:
            # Répartition 70% Alger / 30% Oran
            q_alg = int(p.quantity * 0.7)
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
