# Analyse Technique pour le Jury - OMISTOCK V3

## 📋 Points Essentiels à Présenter

---

## 1. CONTEXTE ET PROBLÉMATIQUE

### Pourquoi OMISTOCK V3 ?
- **Problème** : Les ERP traditionnels (SAP, Odoo) sont trop coûteux et complexes pour les PME algériennes
- **Rupture conceptuelle** : Les logiciels actuels sont conçus pour des humains (clics, formulaires) mais pas pour les agents IA
- **Solution** : Un ERP bi-cible qui sert à la fois les humains (interface web) ET les agents IA (interface sémantique MCP)

### Points clés à mentionner :
- "Nous avons identifié un gap technologique : les systèmes actuels ne sont pas 'agent-ready'"
- "Notre solution s'adapte à l'entreprise hybride de 2026 : humains + agents IA autonomes"

---

## 2. ARCHITECTURE TECHNIQUE

### Stack Technologique
**Backend** :
- FastAPI (Python) - Framework API moderne et performant
- SQLAlchemy ORM - Abstraction base de données
- SQLite - Base de données légère (migration PostgreSQL prévue)
- Pydantic - Validation des données

**Frontend** :
- HTML5 + Tailwind CSS - Interface responsive
- JavaScript - Navigation et interactions
- PWA (Progressive Web App) - Application mobile

**Sécurité** :
- JWT Bearer - Authentification humaine
- X-API-Key - Authentification agent avec scopes
- bcrypt - Hashage des mots de passe

### Architecture 3-Tiers
```
Frontend (Web UI + PWA)
    ↓ HTTP/REST
FastAPI (Application Server)
    ↓ SQLAlchemy ORM
SQLite (Database)
```

### Multi-Tenancy
- **Isolation stricte** : Chaque entreprise (company_id) est isolée
- **Clé étrangère globale** : Toutes les tables filtrent par company_id
- **Sécurité** : Un utilisateur ne voit que les données de son entreprise

---

## 3. ALGORITHMES MÉTIERS (THÉORIE DE GESTION DE STOCK)

### WAC - Weighted Average Cost (Coût Moyen Pondéré)
**Formule** :
```
WAC = (stock_actuel × coût_actuel + qté_reçue × coût_reçu) / (stock_actuel + qté_reçue)
```

**Pourquoi c'est important** :
- Valorisation du stock au COÛT (pas au prix de vente)
- Recalcul automatique à chaque réception
- Conformité aux normes comptables

**Code** : `stock.py` - fonction `apply_weighted_average_cost()`

---

### ROP - Reorder Point (Point de Commande)
**Formule** :
```
ROP = (demande_moyenne_journalière × délai_approvisionnement) + stock_sécurité
```

**Pourquoi c'est important** :
- Déclenchement automatique des alertes de stock
- Évite les ruptures de stock
- Basé sur l'historique réel des ventes (30 derniers jours)

**Code** : `models.py` - propriété hybride `reorder_point`

---

### EOQ - Economic Order Quantity (Formule de Wilson)
**Formule** :
```
EOQ = √((2 × demande_annuelle × coût_commande) / coût_stockage_unitaire)
```

**Pourquoi c'est important** :
- Optimise les quantités de commande
- Minimise les coûts totaux (commande + stockage)
- Suggestion automatique pour les agents IA

**Code** : `stock.py` - fonction `economic_order_quantity()`

---

### FEFO - First Expired First Out
**Principe** :
- Consommer d'abord les lots les plus proches de la péremption
- Essentiel pour pharma/agroalimentaire

**Implémentation** :
- Tri des lots par `expiry_date ASC`
- Décrémentation automatique lors des ventes
- Alertes pour lots périmés dans 30 jours

**Code** : `stock.py` - fonction `consume_lots_fefo()`

---

## 4. INNOVATION : MCP ET AGENTS IA

### Qu'est-ce que MCP ?
- **MCP** = Model Context Protocol (protocole open-source d'Anthropic, 2024)
- Standard universel pour connecter les LLM aux systèmes d'information
- Permet aux agents IA d'interagir avec l'ERP via une API sémantique

### Notre Implémentation MCP
**9 outils MCP développés** (`mcp/server.py`) :
1. `get_stock_alerts` - Liste les produits sous le point de commande
2. `predict_stockout` - Prédit le risque de rupture
3. `propose_restock` - Propose un réapprovisionnement (human-in-the-loop)
4. `get_inventory` - Inventaire par produit/filiale
5. `get_stock_valuation` - Valorisation du stock au coût
6. `get_reorder_suggestions` - Suggestions EOQ
7. `get_expiring_lots` - Lots proches de la péremption
8. `list_my_proposals` - Propositions de l'agent
9. `get_my_capabilities` - Auto-introspection des droits

### Séparation des Interfaces
**Interface Humaine** (`/api/*`) :
- Authentification JWT
- Accès complet (RBAC classique)
- Interface web graphique

**Interface Agentique** (`/api/agent/*`) :
- Authentification X-API-Key
- Scopes précis (stock:read, restock:propose, etc.)
- Pas d'interface graphique, purement sémantique

---

## 5. GOUVERNANCE ET SÉCURITÉ DES AGENTS IA

### 4 Niveaux d'Autonomie
1. **READ_ONLY** - Lecture seule (alertes, résumés)
2. **SUGGEST** - Lecture + analyses
3. **PROPOSE** - Peut créer des propositions soumises à validation humaine
4. **AUTO** - Peut exécuter directement (avec plafond quantité)

### Scopes (Principe du moindre privilège)
- `stock:read` - Lire le stock
- `restock:propose` - Proposer un réapprovisionnement
- `restock:auto` - Exécuter un réapprovisionnement
- `transfer:propose` - Proposer un transfert

### Human-in-the-Loop
- Les agents NE MODIFIENT JAMAIS le stock directement
- Ils émettent des PROPOSITIONS (`AgentProposal`)
- Un humain doit APPROUVER/REJETER
- Toutes les actions sont tracées avec `correlation_id`

### Audit Chaîné (Anti-falsification)
- Chaque entrée d'audit contient :
  - `prev_hash` - Hash de l'entrée précédente
  - `entry_hash` - Hash de cette entrée
  - `hash_ts` - Horodatage canonique
- Toute altération brise la chaîne (comme une blockchain)
- Permet la non-répudiation des transactions

---

## 6. PATTERNS DE CONCEPTION

### Repository Pattern
**Pourquoi ?** :
- Isolation de la logique d'accès aux données
- Facilite les tests unitaires
- Maintenance sans régression

**Code** : `repository.py` - Toutes les opérations SQLAlchemy centralisées

### Source de Vérité Unique
**Règle** :
- La table `Inventory` (par filiale) est la SEULE source de vérité
- `Product.quantity` n'est qu'un cache dérivé
- Recalcul automatique via `recompute_product_quantity()`

### Correlation ID
- Identifiant unique traversant toutes les couches
- Permet la traçabilité bout-en-bout
- Généré par middleware et propagé dans les headers

---

## 7. DÉPLOIEMENT ET PRODUCTION

### Dockerisation
- Images Docker multi-stages
- `docker-compose.yml` pour orchestration
- Portabilité et reproductibilité

### Cloud Deployment
- Déployé sur Render (cloud PaaS)
- Expose l'API publique sécurisée
- Pipeline CI/CD automatisé

### Tests
- Tests unitaires avec pytest
- Validation des outils MCP avec MCP Inspector
- Tests d'intégration API

---

## 8. PERSPECTIVES D'AVENIR

### Améliorations identifiées
1. **Migration PostgreSQL** - Pour gérer une concurrence élevée
2. **Jetons JIT éphémères** - Sécurisation renforcée des agents
3. **Webhooks en mode Push** - Alertes temps réel
4. **Algorithmes prédictifs** - Deep-learning pour la demande
5. **Déploiement Kubernetes** - Scalabilité production

---

## 🎯 Points à Mettre en Avant Devant le Jury

### Innovation
- "Nous avons créé le premier ERP algérien 'agent-ready'"
- "Notre solution anticipe l'entreprise hybride de 2026"

### Rigueur Technique
- "Nous appliquons les best practices : Repository Pattern, Multi-tenancy, Audit chaîné"
- "Notre code est testé, documenté et industrialisé"

### Sécurité
- "Nous avons implémenté une gouvernance stricte des agents IA avec 4 niveaux d'autonomie"
- "Toutes les actions sont tracées et non-répudiables"

### Valeur Métier
- "Nos algorithmes (WAC, ROP, EOQ, FEFO) sont basés sur la théorie de gestion de stock"
- "Nous valorisons le stock au COÛT, pas au prix de vente"

---

## 📚 Références Code

### Fichiers Clés à Connaître
- `backend/main.py` - Point d'entrée FastAPI
- `backend/models.py` - Modèles SQLAlchemy (17 tables)
- `backend/repository.py` - DAL (997 lignes)
- `backend/stock.py` - Algorithmes métiers
- `backend/agent_policy.py` - Gouvernance des agents
- `backend/routers/agent.py` - Interface agentique
- `mcp/server.py` - Serveur MCP (9 outils)

### Statistiques
- ~17 tables dans la base de données
- ~1000 lignes de code dans repository.py
- 9 outils MCP implémentés
- 4 niveaux d'autonomie
- 4 algorithmes métiers (WAC, ROP, EOQ, FEFO)

---

## 💡 Questions Potentielles du Jury et Réponses

### Q : Pourquoi MCP et pas une API REST classique pour les agents ?
A : MCP est un standard universel qui permet aux LLM de comprendre le contexte sémantique des données. Une API REST classique ne fournit que des données brutes, MCP fournit des outils avec des descriptions riches que les agents peuvent utiliser intelligemment.

### Q : Comment garantissez-vous la sécurité avec les agents IA ?
A : Nous avons 3 couches de protection : (1) 4 niveaux d'autonomie bornés, (2) Scopes précis (principe du moindre privilège), (3) Human-in-the-loop pour les écritures critiques. De plus, toutes les actions sont tracées avec audit chaîné SHA-256.

### Q : Pourquoi SQLite et pas PostgreSQL directement ?
A : SQLite est idéal pour le développement et les petites structures. Nous avons prévu la migration PostgreSQL dans nos perspectives pour gérer une concurrence élevée en production.

### Q : Comment fonctionne le multi-tenancy ?
A : Chaque entreprise a un `company_id` unique. Toutes les requêtes filtrent automatiquement par ce `company_id` via nos dépendances FastAPI. L'isolation est stricte et garantie au niveau base de données.

### Q : Quelle est la valeur ajoutée de votre projet ?
A : Nous avons créé une solution qui résout un problème réel des PME algériennes (coût/complexité des ERP) tout en anticipant l'avenir (agents IA). Notre innovation est d'avoir conçu un système bi-cible dès le départ, pas de manière rétroactive.
