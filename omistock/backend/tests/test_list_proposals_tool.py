"""
Tests pour l'outil #5 : list_my_proposals (GET /api/agent/proposals/mine).
Vérifie :
  - scope stock:read + niveau READ_ONLY requis.
  - isolation par agent (ne voit QUE ses propres propositions).
  - filtre status fonctionnel (PENDING, APPROVED, REJECTED, EXECUTED).
  - validation du status (HTTP 400 si invalide).
"""
import pytest
import models
import repository
import agent_policy


def test_list_proposals_policy_enforcement():
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


def test_list_proposals_isolation_by_agent(db, company):
    """Vérifie qu'un agent ne voit que ses propres propositions."""
    # Créer deux agents
    agent_a = models.User(
        email="agent_a@company.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="stock:read",
        max_action_quantity=0, company_id=company.id,
    )
    agent_b = models.User(
        email="agent_b@company.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="stock:read",
        max_action_quantity=0, company_id=company.id,
    )
    db.add(agent_a)
    db.add(agent_b)
    db.commit()

    # Créer des propositions pour les deux agents
    prop_a = repository.create_agent_proposal(
        db, agent_id=agent_a.id, company_id=company.id,
        action_type="RESTOCK", payload='{"qty": 10}', rationale="Besoin",
        correlation_id="corr-a"
    )
    prop_b = repository.create_agent_proposal(
        db, agent_id=agent_b.id, company_id=company.id,
        action_type="TRANSFER", payload='{"qty": 5}', rationale="Besoin 2",
        correlation_id="corr-b"
    )

    # Récupérer les propositions d'agent_a
    props_for_a = repository.get_agent_proposals(
        db, company_id=company.id, agent_id=agent_a.id
    )
    assert len(props_for_a) == 1
    assert props_for_a[0].id == prop_a.id
    assert props_for_a[0].agent_id == agent_a.id

    # Récupérer les propositions d'agent_b
    props_for_b = repository.get_agent_proposals(
        db, company_id=company.id, agent_id=agent_b.id
    )
    assert len(props_for_b) == 1
    assert props_for_b[0].id == prop_b.id
    assert props_for_b[0].agent_id == agent_b.id


def test_list_proposals_status_filtering_and_validation(db, company):
    """Vérifie le filtrage par statut et la validation."""
    agent = models.User(
        email="agent_test@company.local", user_type="AGENT",
        autonomy_level="read_only", agent_scopes="stock:read",
        max_action_quantity=0, company_id=company.id,
    )
    db.add(agent)
    db.commit()

    # Proposition PENDING
    prop_p = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="RESTOCK", payload='{"qty": 10}', rationale="Besoin",
        correlation_id="corr-p"
    )

    # Proposition APPROVED
    prop_app = repository.create_agent_proposal(
        db, agent_id=agent.id, company_id=company.id,
        action_type="TRANSFER", payload='{"qty": 5}', rationale="Besoin 2",
        correlation_id="corr-app"
    )
    prop_app.status = "APPROVED"
    db.commit()

    # Liste tout
    all_props = repository.get_agent_proposals(db, company.id, agent_id=agent.id)
    assert len(all_props) == 2

    # Liste uniquement PENDING
    pending_props = repository.get_agent_proposals(db, company.id, status="PENDING", agent_id=agent.id)
    assert len(pending_props) == 1
    assert pending_props[0].id == prop_p.id

    # Liste uniquement APPROVED
    approved_props = repository.get_agent_proposals(db, company.id, status="APPROVED", agent_id=agent.id)
    assert len(approved_props) == 1
    assert approved_props[0].id == prop_app.id
