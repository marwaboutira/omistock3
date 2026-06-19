"""
OMISTOCK — Serveur MCP (interface agent IA).

ALIGNEMENT REFACTOR :
- Les agents IA possèdent une surface DÉDIÉE et SÉPARÉE de l'interface humaine :
  ils appellent /api/agent/* (et non les routes humaines /api/*), avec une
  X-API-Key scoped + expirante. La séparation des interfaces est une best
  practice "agent-ready".
- Les LECTURES (alertes, prévision) passent par /api/agent/alerts et
  /api/agent/forecast/{id} (niveaux READ_ONLY / SUGGEST).
- Les ÉCRITURES ne sont JAMAIS directes depuis l'outil de chat : l'agent émet une
  PROPOSITION (/api/agent/proposals/restock) soumise à validation humaine
  (human-in-the-loop). L'exécution directe /api/agent/restock n'est possible
  qu'avec un niveau AUTO + scope "restock:auto" + plafond quantité, et reste
  contrôlée côté backend par agent_policy.
- Le backend renvoie désormais `on_hand` (stock réel agrégé, source de vérité =
  Inventory) et `reorder_point` (ROP = demande*délai + stock de sécurité), et non
  plus un simple champ `quantity`/`min_threshold`.

Toutes les actions sont tracées côté backend (audit chaîné + correlation_id).
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Omistock Intelligence")

# URL du backend FastAPI.
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
# Clé API agent (scoped + expirante), émise par un admin. JAMAIS un JWT humain.
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")


def get_headers() -> dict:
    """Authentification agent par X-API-Key (jamais de JWT humain)."""
    if not AGENT_API_KEY:
        raise ValueError(
            "AGENT_API_KEY non définie. Configurez la variable d'environnement "
            "avec une clé API agent émise par un administrateur."
        )
    return {"X-API-Key": AGENT_API_KEY}


def _handle_http_error(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    if code == 401:
        return "🔒 Authentification refusée : clé API agent absente, invalide ou EXPIRÉE."
    if code == 403:
        # agent_policy : niveau d'autonomie ou scope insuffisant.
        return f"⛔ Action refusée par la politique d'autonomie de l'agent : {e.response.text}"
    return f"Erreur API ({code}) : {e.response.text}"


@mcp.tool()
def get_stock_alerts() -> str:
    """
    Liste les produits dont le stock réel est sous le point de commande (ROP).
    Interface agent dédiée : GET /api/agent/alerts (scope stock:read, READ_ONLY+).
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/api/agent/alerts",
            headers=get_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        alertes = response.json()

        if not alertes:
            return "✅ Tout est en ordre. Aucun produit sous le point de commande."

        reponse = "⚠️ ALERTE STOCK (stock réel <= point de commande) :\n"
        for p in alertes:
            on_hand = p.get("on_hand", 0)
            rop = p.get("reorder_point", 0)
            reponse += f"- {p['name']} : {on_hand} en stock (ROP = {rop})\n"
        return reponse

    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except Exception as e:
        return f"Erreur lors de l'appel à l'API : {str(e)}"


@mcp.tool()
def predict_stockout(product_id: int) -> str:
    """
    Prédit le risque de rupture pour un produit (demande moyenne, ROP, jours
    avant rupture). Interface agent dédiée : GET /api/agent/forecast/{id}
    (scope stock:read, niveau SUGGEST+). Le calcul est fait côté backend
    (données réelles), aucune estimation fabriquée côté agent.
    """
    try:
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/forecast/{product_id}",
            headers=get_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        f = r.json()

        name = f.get("name", f"Produit {product_id}")
        on_hand = f.get("on_hand", f.get("quantity", 0))
        avg = f.get("avg_daily_demand", 0)
        rop = f.get("reorder_point", 0)
        days = f.get("days_until_stockout")
        lead = f.get("lead_time_days", 0)

        msg = (
            f"{name} : {on_hand} en stock, demande ~{avg}/jour, "
            f"point de commande (ROP) = {rop}, délai d'appro = {lead} j."
        )
        if days is not None:
            if days <= lead:
                msg = f"🔴 RISQUE ÉLEVÉ — rupture dans ~{days} j (< délai d'appro {lead} j). " + msg
            else:
                msg = f"🟢 Stock suffisant — rupture estimée dans ~{days} j. " + msg
        return msg

    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except Exception as e:
        return f"Erreur lors de l'appel à l'API : {str(e)}"


@mcp.tool()
def propose_restock(product_id: int, branch_id: int, quantity: int,
                    unit_cost: float = 0.0, rationale: str = "") -> str:
    """
    Émet une PROPOSITION de réapprovisionnement soumise à validation HUMAINE
    (human-in-the-loop). POST /api/agent/proposals/restock
    (scope restock:propose, niveau PROPOSE+).

    L'agent ne modifie JAMAIS le stock directement via cet outil : il propose, un
    humain approuve/rejette ensuite (séparation des responsabilités). La proposition
    et son éventuelle exécution sont auditées avec un correlation_id partagé.
    """
    try:
        payload = {
            "product_id": product_id,
            "branch_id": branch_id,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "rationale": rationale,
        }
        r = httpx.post(
            f"{API_BASE_URL}/api/agent/proposals/restock",
            headers=get_headers(),
            json=payload,
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        return (
            f"📝 Proposition de réappro créée (#{data.get('proposal_id')}). "
            f"Statut : {data.get('status')}. En attente de validation par un humain."
        )
    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except Exception as e:
        return f"Erreur lors de l'appel à l'API : {str(e)}"


@mcp.tool()
def get_inventory(branch_id: int = None, low_stock_only: bool = False) -> list:
    """
    Retourne le stock réel par produit (et par filiale si branch_id fourni).
    Paramètres :
      - branch_id       : filtre sur une filiale (optionnel).
      - low_stock_only  : si True, ne retourne que les produits sous leur ROP.
    Scope requis : stock:read / READ_ONLY.
    """
    try:
        params = {}
        if branch_id is not None:
            params["branch_id"] = branch_id
        if low_stock_only:
            params["low_stock_only"] = "true"
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/inventory",
            headers=get_headers(),
            params=params,
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return [{"error": _handle_http_error(e)}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def get_stock_valuation(branch_id: int = None) -> dict:
    """
    Retourne la valorisation globale du stock au coût (WAC) (par filiale si branch_id fourni).
    Scope requis : stock:read / READ_ONLY.
    """
    try:
        params = {}
        if branch_id is not None:
            params["branch_id"] = branch_id
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/valuation",
            headers=get_headers(),
            params=params,
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": _handle_http_error(e)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_reorder_suggestions() -> list:
    """
    Retourne la liste des produits sous le point de commande (ROP) avec suggestion de quantité EOQ.
    Scope requis : stock:read / READ_ONLY.
    """
    try:
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/reorder-suggestions",
            headers=get_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return [{"error": _handle_http_error(e)}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def get_expiring_lots(days: int = 30) -> list:
    """
    Retourne la liste des lots dont la péremption approche (gestion FEFO).
    Paramètres :
      - days : Horizon en jours pour le filtrage (défaut 30, borné à >= 1).
    Scope requis : stock:read / READ_ONLY.
    """
    try:
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/expiring-lots",
            headers=get_headers(),
            params={"days": days},
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return [{"error": _handle_http_error(e)}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def list_my_proposals(status: str = None) -> list:
    """
    Retourne la liste des propositions d'actions soumises par l'agent lui-même.
    Paramètres :
      - status : Filtre optionnel parmi PENDING, APPROVED, REJECTED, EXECUTED.
    Scope requis : stock:read / READ_ONLY.
    """
    try:
        params = {}
        if status is not None:
            params["status"] = status
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/proposals/mine",
            headers=get_headers(),
            params=params,
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return [{"error": _handle_http_error(e)}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def get_my_capabilities() -> dict:
    """
    Retourne les droits propres de l'agent (auto-introspection) :
    niveau d'autonomie, scopes, plafond de quantité, expiration de clé.
    Aucun scope requis.
    """
    try:
        r = httpx.get(
            f"{API_BASE_URL}/api/agent/capabilities",
            headers=get_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": _handle_http_error(e)}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()





