"""
Tests pour l'authentification et le hachage des clés API des agents.
"""
import pytest
from sqlalchemy.orm import Session
import models
from backend import repository
from backend.dependencies import _user_from_api_key

def test_agent_api_key_hashing_and_auth(db: Session, company):
    # 1. Création de l'agent via le repository
    raw_key = "my_super_secret_agent_key_123"
    agent_data = {
        "email": "agent_test@agent.local",
        "api_key": raw_key,
        "user_type": "AGENT",
        "autonomy_level": "read_only",
        "is_active": True
    }
    
    agent = repository.create_agent(db, agent_data, company.id)
    
    # Vérification que la clé est bien hachée dans la base de données
    assert agent.api_key.startswith("$2"), "La clé API stockée doit être un hash bcrypt"
    assert agent.api_key != raw_key, "La clé API ne doit pas être stockée en clair"

    # 2. Authentification avec la clé correcte
    auth_user = _user_from_api_key(raw_key, db)
    assert auth_user is not None
    assert auth_user.id == agent.id

    # 3. Rejet avec une mauvaise clé
    bad_auth = _user_from_api_key("wrong_key", db)
    assert bad_auth is None


def test_agent_api_key_retrocompatibility_and_soft_migration(db: Session, company):
    # 1. Création manuelle d'un agent avec clé en clair (legacy) pour tester la rétrocompatibilité
    legacy_key = "legacy_plaintext_key_abc"
    legacy_agent = models.User(
        email="legacy_agent@agent.local",
        user_type="AGENT",
        api_key=legacy_key,
        company_id=company.id,
        is_active=True
    )
    db.add(legacy_agent)
    db.commit()
    db.refresh(legacy_agent)

    # Vérification initiale : stockée en clair
    assert legacy_agent.api_key == legacy_key

    # 2. Authentification avec la clé en clair -> doit réussir
    auth_user = _user_from_api_key(legacy_key, db)
    assert auth_user is not None
    assert auth_user.id == legacy_agent.id

    # 3. Vérification de la migration douce à la volée
    db.refresh(legacy_agent)
    assert legacy_agent.api_key.startswith("$2"), "La clé legacy aurait dû être hachée à la volée"
    assert legacy_agent.api_key != legacy_key

    # 4. Authentification ultérieure avec la même clé en clair -> doit toujours réussir
    second_auth = _user_from_api_key(legacy_key, db)
    assert second_auth is not None
    assert second_auth.id == legacy_agent.id
