# OMISTOCK - Système de Gestion de Stock Intelligent

OMISTOCK est une plateforme web moderne de gestion d'inventaire multi-tenant, conçue pour les entreprises multisites. Elle permet un suivi précis des stocks, des ventes et des rapports financiers en temps réel.

## 🚀 Fonctionnalités Clés

- **Dashboard Dynamique** : Visualisation instantanée des KPIs (Valeur du stock, alertes, ventes).
- **Gestion Multi-sites** : Support natif pour plusieurs filiales (ex: Alger, Oran, Constantine) avec isolation des données.
- **Inventaire Universel** : Adapté à tout type de secteur (Électronique, Pharmacie, Alimentaire, etc.).
- **Rapports & Analyses** : Graphiques avancés avec Chart.js et calcul de bénéfices.
- **Exportation Professionnelle** : Génération de factures HTML et export de rapports au format PDF.
- **Sécurité Multi-Tenant** : Authentification JWT avec isolation stricte par entreprise (Company ID).

## 🛠️ Stack Technique

- **Backend** : FastAPI (Python 3.10+), SQLAlchemy (ORM), SQLite.
- **Frontend** : Vanilla JS, TailwindCSS, Chart.js.
- **Authentification** : OAuth2 avec Password flow et jetons JWT.

## 📦 Installation

Consultez le fichier [Installation Rapide](docs/installation.md) pour les instructions détaillées.

## 🤖 Lancer le serveur MCP

Le serveur MCP permet aux agents IA d'interagir intelligemment avec l'inventaire d'Omistock.


1. **Installer les dépendances** :
   ```bash
   pip install -r mcp/requirements.txt
   ```

2. **Configurer les variables d'environnement** :
   - `API_BASE_URL` : URL de l'API backend FastAPI (par défaut `http://localhost:8000`).
   - `AGENT_API_KEY` : Clé API Agent émise par un administrateur.

3. **Lancer le serveur** :
   ```bash
   cd mcp
   python server.py
   ```

## 📄 Licence
Propriété de l'utilisateur - Usage démonstration et académique.

