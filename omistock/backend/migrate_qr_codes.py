"""
OMISTOCK — Migration unique : attribution d'un QR code normalisé à TOUS les produits.

Objectif (Mission 1) : s'assurer que 100% des produits possèdent un QR code fonctionnel
et unique, y compris les produits créés avant l'introduction de la colonne `qr_code`.

Règle : le QR encode le SKU (clé métier stable et lisible par le scanner mobile).
Sans SKU, on génère un identifiant `PROD-{id}`. L'unicité est garantie par entreprise.

Usage (depuis le dossier backend) :
    python migrate_qr_codes.py

Le script est idempotent : il peut être relancé sans risque (il ne réécrit que les
produits sans QR, et résout les éventuelles collisions).
"""
import os
import sys

# Permettre l'exécution directe depuis le dossier backend ou la racine projet.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import inspect, text  # noqa: E402

import models  # noqa: E402
import repository  # noqa: E402
from database import SessionLocal, engine  # noqa: E402


def _ensure_qr_column() -> None:
    """Crée la colonne qr_code si elle n'existe pas (équivalent de run_db_migrations)."""
    insp = inspect(engine)
    if "products" not in insp.get_table_names():
        print("[MIGRATE-QR] Table 'products' introuvable : rien à faire.")
        return
    present = {c["name"] for c in insp.get_columns("products")}
    if "qr_code" not in present:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN qr_code VARCHAR"))
            conn.commit()
        print("[MIGRATE-QR] Colonne 'qr_code' ajoutée à la table products.")


def run() -> dict:
    _ensure_qr_column()
    models.Base.metadata.create_all(bind=engine)

    stats = {"total": 0, "updated": 0, "skipped": 0}
    db = SessionLocal()
    try:
        products = db.query(models.Product).all()
        stats["total"] = len(products)
        for p in products:
            # Idempotent : on ne touche que les produits sans QR valide.
            if (p.qr_code or "").strip():
                stats["skipped"] += 1
                continue
            before = p.qr_code
            repository._ensure_qr_code(db, p)
            db.flush()
            if p.qr_code != before:
                stats["updated"] += 1
                print(f"  -> Produit #{p.id} '{p.name}' : qr_code = {p.qr_code}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return stats


if __name__ == "__main__":
    print("=== Migration QR Codes OMISTOCK ===")
    result = run()
    print(
        f"\n[RÉCAP] Produits: {result['total']} | "
        f"QR attribués: {result['updated']} | Déjà pourvus: {result['skipped']}"
    )
