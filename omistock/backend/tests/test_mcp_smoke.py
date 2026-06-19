"""
Smoke test pour vérifier l'importabilité du serveur MCP local.
"""
import importlib.util
import os

def test_mcp_server_importable():
    # Déterminer le chemin vers le fichier mcp/server.py local
    backend_tests_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(backend_tests_dir))
    server_path = os.path.join(project_root, "mcp", "server.py")
    
    assert os.path.exists(server_path), f"Le fichier {server_path} n'existe pas."

    # Import dynamique du fichier local pour éviter les conflits de nommage avec la bibliothèque 'mcp'
    spec = importlib.util.spec_from_file_location("mcp_server_local", server_path)
    mcp_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp_server)
    
    assert mcp_server.mcp is not None
