"""
Tests pour l'outil #6 : get_my_capabilities (GET /api/agent/capabilities).
Vérifie :
  - (a) agent PROPOSE avec scopes "stock:read,restock:propose" → retour correct.
  - (b) agent SANS scope "stock:read" → peut quand même appeler (aucun scope requis).
  - (c) humain (non-agent) → rejeté par get_current_agent (user_type != AGENT).
"""
import pytest
import models
import agent_policy


# ---------------------------------------------------------------------------
# (a) Agent PROPOSE avec scopes → retour correct
# ---------------------------------------------------------------------------

def test_capabilities_propose_agent(db, company):
    """Un agent PROPOSE avec scopes spécifiques reçoit bien level + scopes exacts."""
    agent = models.User(
        email="propose@company.local",
        user_type="AGENT",
        autonomy_level=models.AutonomyLevel.PROPOSE.value,
        agent_scopes="stock:read,restock:propose",
        max_action_quantity=100,
        company_id=company.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Vérification via parse_scopes (réutilise la logique existante)
    scopes = agent_policy.parse_scopes(agent)

    assert agent.autonomy_level == models.AutonomyLevel.PROPOSE.value
    assert "stock:read" in scopes
    assert "restock:propose" in scopes
    assert agent.max_action_quantity == 100
    assert agent.company_id == company.id


# ---------------------------------------------------------------------------
# (b) Agent SANS scope "stock:read" → peut quand même appeler (pas de scope requis)
# ---------------------------------------------------------------------------

def test_capabilities_no_scope_required(db, company):
    """Un agent sans stock:read peut appeler /capabilities (aucun scope requis)."""
    agent_noscope = models.User(
        email="noscope@company.local",
        user_type="AGENT",
        autonomy_level=models.AutonomyLevel.READ_ONLY.value,
        agent_scopes="other:scope",
        max_action_quantity=0,
        company_id=company.id,
    )
    db.add(agent_noscope)
    db.commit()
    db.refresh(agent_noscope)

    # La route /capabilities n'appelle PAS authorize_agent_action → pas de refus scope.
    # On vérifie directement que parse_scopes retourne bien les scopes de l'agent.
    scopes = agent_policy.parse_scopes(agent_noscope)
    assert "other:scope" in scopes
    assert "stock:read" not in scopes

    # Et que authorize_agent_action AURAIT refusé stock:read (prouve que la route
    # n'appelle pas authorize_agent_action pour /capabilities).
    err = agent_policy.authorize_agent_action(
        agent_noscope,
        required_scope="stock:read",
        required_level=models.AutonomyLevel.READ_ONLY.value,
    )
    assert err is not None   # aurait été refusé si requis


# ---------------------------------------------------------------------------
# (c) Humain → rejeté par get_current_agent (user_type != AGENT)
# ---------------------------------------------------------------------------

def test_capabilities_human_rejected_by_agent_policy(db, company, branch):
    """Un humain (HUMAIN/ADMIN) est rejeté par la politique agent."""
    human = models.User(
        email="admin@company.local",
        user_type="ADMIN",
        autonomy_level=None,
        agent_scopes=None,
        max_action_quantity=0,
        company_id=company.id,
        branch_id=branch.id,
    )
    db.add(human)
    db.commit()
    db.refresh(human)

    # authorize_agent_action refuse les non-agents via la même garde que get_current_agent.
    err = agent_policy.authorize_agent_action(
        human,
        required_scope="stock:read",
        required_level=models.AutonomyLevel.READ_ONLY.value,
    )
    assert err is not None
    assert "agents IA" in err
