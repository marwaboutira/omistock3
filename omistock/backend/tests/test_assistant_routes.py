"""
Vérifie le renommage de l'interface assistant HUMAINE (/api/assistant/*) et la
rétrocompatibilité des anciens chemins /api/mcp/* (alias deprecated).

But : réserver le terme "MCP" au vrai serveur agent (/api/agent/* + mcp/server.py)
sans casser les appels existants. On inspecte la table de routage des routeurs
(pas de HTTP / pas d'auth nécessaires).
"""
from routers import admin, products


def _paths(router):
    return {r.path for r in router.routes}


def test_assistant_chat_route_and_deprecated_mcp_alias():
    paths = _paths(admin.router)
    assert "/api/assistant/chat" in paths      # nouveau chemin canonique
    assert "/api/mcp/chat" in paths            # ancien chemin conservé (rétrocompat)


def test_assistant_analyze_route_and_deprecated_mcp_alias():
    paths = _paths(products.router)
    assert "/api/assistant/analyze" in paths   # nouveau chemin canonique
    assert "/api/mcp/analyze" in paths         # ancien chemin conservé (rétrocompat)


def test_deprecated_mcp_routes_point_to_same_handler():
    """Les deux chemins (nouveau + alias) doivent appeler la MÊME fonction."""
    chat_routes = [r for r in admin.router.routes if r.path in ("/api/assistant/chat", "/api/mcp/chat")]
    assert len({r.endpoint for r in chat_routes}) == 1
    analyze_routes = [r for r in products.router.routes if r.path in ("/api/assistant/analyze", "/api/mcp/analyze")]
    assert len({r.endpoint for r in analyze_routes}) == 1
