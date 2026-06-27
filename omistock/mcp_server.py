"""
Omistock MCP Server — exposes the /api/agent/* endpoints as Claude tools.
Run with: python mcp_server.py
"""
import httpx
import os
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("OMISTOCK_API_URL", "https://omistock3.onrender.com").rstrip("/")
API_KEY = os.environ.get("OMISTOCK_API_KEY", "LYbY2GIHx0vznA8BDF_P5TeZEA9D56KbIco47YqomiI")
HEADERS = {"X-API-Key": API_KEY}

mcp = FastMCP("omistock")


def _get(path: str, params: dict = None) -> dict:
    try:
        with httpx.Client() as client:
            r = client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            return {"ok": True, "data": r.json()}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"{e.response.status_code} {e.response.reason_phrase}", "detail": e.response.text}
    except httpx.RequestError as e:
        return {"ok": False, "error": "network_error", "detail": str(e)}


def _post(path: str, body: dict) -> dict:
    try:
        with httpx.Client() as client:
            r = client.post(f"{BASE_URL}{path}", headers=HEADERS, json=body, timeout=30)
            r.raise_for_status()
            return {"ok": True, "data": r.json()}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"{e.response.status_code} {e.response.reason_phrase}", "detail": e.response.text}
    except httpx.RequestError as e:
        return {"ok": False, "error": "network_error", "detail": str(e)}


@mcp.tool()
def get_capabilities() -> dict:
    """Return the agent's autonomy level, scopes, and action limits."""
    return _get("/api/agent/capabilities")


@mcp.tool()
def get_alerts() -> dict:
    """List products whose stock is below the reorder point."""
    return _get("/api/agent/alerts")


@mcp.tool()
def get_inventory(branch_id: int = None, low_stock_only: bool = False) -> dict:
    """
    Return real stock per product/branch.
    branch_id: filter by branch (optional).
    low_stock_only: return only items below reorder point.
    """
    params = {}
    if branch_id is not None:
        params["branch_id"] = branch_id
    if low_stock_only:
        params["low_stock_only"] = "true"
    return _get("/api/agent/inventory", params)


@mcp.tool()
def get_valuation(branch_id: int = None) -> dict:
    """Return total stock valuation at weighted average cost (WAC)."""
    params = {}
    if branch_id is not None:
        params["branch_id"] = branch_id
    return _get("/api/agent/valuation", params)


@mcp.tool()
def get_reorder_suggestions() -> dict:
    """Return restock suggestions using ROP + Wilson EOQ formula."""
    return _get("/api/agent/reorder-suggestions")


@mcp.tool()
def get_expiring_lots(days: int = 30) -> dict:
    """Return lots expiring within `days` days (FEFO management)."""
    return _get("/api/agent/expiring-lots", {"days": days})


@mcp.tool()
def get_forecast(product_id: int) -> dict:
    """Return demand forecast and analysis for a product. Requires SUGGEST level."""
    return _get(f"/api/agent/forecast/{product_id}")


@mcp.tool()
def list_my_proposals(status: str = None) -> dict:
    """
    List proposals created by this agent.
    status: filter by PENDING, APPROVED, REJECTED, or EXECUTED (optional).
    """
    params = {}
    if status:
        params["status"] = status
    return _get("/api/agent/proposals/mine", params)


@mcp.tool()
def propose_restock(product_id: int, branch_id: int, quantity: int, rationale: str = "") -> dict:
    """
    Submit a restock proposal for human approval (PROPOSE level required).
    Returns proposal_id with status pending_human_approval.
    """
    return _post("/api/agent/proposals/restock", {
        "product_id": product_id,
        "branch_id": branch_id,
        "quantity": quantity,
        "rationale": rationale,
    })


@mcp.tool()
def propose_transfer(from_branch_id: int, to_branch_id: int, product_id: int, quantity: int, rationale: str = "") -> dict:
    """
    Submit an inter-branch transfer proposal for human approval (PROPOSE level required).
    """
    return _post("/api/agent/proposals/transfer", {
        "from_branch_id": from_branch_id,
        "to_branch_id": to_branch_id,
        "product_id": product_id,
        "quantity": quantity,
        "rationale": rationale,
    })


@mcp.tool()
def propose_reverse(movement_id: int, rationale: str = "") -> dict:
    """
    Submit a stock movement reversal proposal for human approval (PROPOSE level required).
    """
    return _post("/api/agent/proposals/reverse", {
        "movement_id": movement_id,
        "rationale": rationale,
    })


@mcp.tool()
def auto_restock(product_id: int, branch_id: int, quantity: int, unit_cost: float = 0.0) -> dict:
    """
    Execute a restock immediately without human approval (AUTO level + restock:auto scope required).
    """
    return _post("/api/agent/restock", {
        "product_id": product_id,
        "branch_id": branch_id,
        "quantity": quantity,
        "unit_cost": unit_cost,
    })


if __name__ == "__main__":
    mcp.run()
