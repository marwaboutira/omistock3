# OMISTOCK — Rapport des modifications

> Ce document explique **chaque modification apportée au projet** et **comment elle a
> été réalisée** (approche technique), depuis la refonte répondant au rapport de revue
> jusqu'aux corrections fonctionnelles issues des tests manuels.
>
> **État final :** le code compile, l'application démarre, le serveur MCP s'importe avec
> ses 9 outils, et la **suite de tests passe intégralement (65 tests, 0 échec)**.

---

## Sommaire

**Partie A — Refonte répondant au rapport de revue**
1. Serveur MCP installable et lançable
2. Hachage des clés API des agents (bcrypt)
3. Rollback gouverné exposé à l'agent
4. Finalisation des propositions de transfert
5. Extension de la couche d'outils MCP (de 3 à 9)
6. Cycle de vie complet du bon de commande
7. Renommage de l'interface assistant humaine

**Partie B — Corrections et compléments fonctionnels (tests manuels)**
8. Alignement du panneau « Accès Agent » sur le hachage des clés
9. Gestion des agents : révocation et rotation de clé
10. Création de fournisseur (fonctionnalité absente)
11. Export Excel réel du rapport de performance
12. Lisibilité dans Excel de l'export des logs d'audit

---

# Partie A — Refonte répondant au rapport de revue

## 1. Serveur MCP installable et lançable

**Problème.** `mcp/server.py` importait `FastMCP` et `httpx`, mais ces dépendances
n'étaient déclarées nulle part → `ModuleNotFoundError`, le serveur ne démarrait pas.

**Comment c'est fait.**
1. Création d'un fichier dédié `mcp/requirements.txt` listant les dépendances réellement
   importées par le serveur (`mcp[cli]`, `httpx`), avec versions épinglées.
2. Le SDK `mcp` exigeant des versions récentes, alignement des versions du backend dans
   `backend/requirements.txt` (`fastapi`, `uvicorn`, `starlette`, `pydantic`, `httpx`)
   pour lever les conflits de dépendances.
3. Ajout d'un test « de fumée » (`backend/tests/test_mcp_smoke.py`) qui importe
   dynamiquement `mcp/server.py` via `importlib` (pour éviter la collision de nom avec
   le paquet installé `mcp`) et vérifie qu'il se charge.
4. Documentation de la procédure de lancement dans `README.md`.

**Vérification.** Le serveur s'importe avec ses outils ; la suite de tests reste verte
après l'alignement des dépendances.

---

## 2. Hachage des clés API des agents (sécurité)

**Problème.** Les clés API des agents (`User.api_key`) étaient stockées et comparées
**en clair** en base.

**Comment c'est fait.** On applique aux clés le même principe que les mots de passe
(hachage bcrypt via le module `security` existant), en gérant la rétrocompatibilité :
1. **À la création** (`repository.create_agent`) : la clé générée est hachée avant
   insertion ; la clé en clair n'est renvoyée qu'une seule fois à l'appelant.
2. **À la rotation** (`routers/auth.py`) : même traitement.
3. **À l'authentification** (`dependencies._user_from_api_key`) : comme un hash n'est
   pas « recherchable » directement, on parcourt les agents actifs et on compare par
   `security.verify_password`. Une **migration douce** est prévue : si une clé en base
   est encore en clair (ancienne), elle est acceptée puis **immédiatement re-hachée**.

```python
if stored_key.startswith("$2"):                      # hash bcrypt
    if security.verify_password(x_api_key, stored_key): ...
else:                                                # ancienne clé en clair
    if stored_key == x_api_key:
        user.api_key = security.get_password_hash(x_api_key)   # migration à la volée
        db.commit()
```

**Vérification.** `backend/tests/test_agent_auth.py` : authentification correcte,
rejet d'une mauvaise clé, migration d'une clé legacy.

---

## 3. Rollback gouverné exposé à l'agent

**Problème.** La fonction `repository.reverse_sale()` (annulation par compensation)
existait mais n'était accessible par aucun agent.

**Comment c'est fait.** On réutilise le motif « proposition + validation humaine » déjà
en place pour le réapprovisionnement :
1. Schéma `AgentReverseProposal` (`schemas.py`).
2. Route `POST /api/agent/proposals/reverse` (`routers/agent.py`, scope
   `reverse:propose`, niveau `PROPOSE`) : l'agent **crée une proposition**, il n'exécute
   jamais l'annulation lui-même.
3. Branche `REVERSE` dans le gestionnaire d'approbation (`routers/admin.py`) :
   à la validation, `reverse_sale()` est appelée **sous l'identité de l'administrateur**,
   avec le `correlation_id` de la proposition (traçabilité bout-en-bout).

**Vérification.** `test_reverse_proposal.py` : création, approbation (vente `REVERSED`
+ stock réintégré), double annulation rejetée, refus si scope manquant.

---

## 4. Finalisation des propositions de transfert

**Problème.** Le gestionnaire d'approbation ne traitait que `RESTOCK` ; une proposition
`TRANSFER` levait « type non supporté ».

**Comment c'est fait.** On ajoute la branche manquante en **réutilisant la logique de
transfert existante** (aucune duplication) :
1. Schéma `AgentTransferProposal` et route `POST /api/agent/proposals/transfer`.
2. Branche `TRANSFER` dans l'approbation, qui enchaîne les fonctions déjà présentes
   `create_transfer_request` → `approve_transfer_request` (débit source) →
   `confirm_transfer_request` (crédit destination), sous l'identité de l'admin.

**Vérification.** `test_transfer_proposal.py` : stock source décrémenté, destination
incrémentée, refus si scope manquant.

---

## 5. Extension de la couche d'outils MCP (de 3 à 9)

**Problème.** Seuls 3 outils existaient ; le rapport en recommandait ~13–16.

**Comment c'est fait.** Chaque outil est un **wrapper fin** au-dessus de la logique déjà
présente dans `stock.py` / `repository.py`, ajouté selon un motif identique : une route
`/api/agent/*` (scope + niveau d'autonomie adaptés), un outil `@mcp.tool()` dans
`mcp/server.py` renvoyant du **JSON structuré**, et une trace d'audit.

| Outil ajouté | Route | S'appuie sur |
|--------------|-------|--------------|
| `get_inventory` | `/api/agent/inventory` | `repository.get_products` |
| `get_stock_valuation` | `/api/agent/valuation` | `stock.stock_value_at_cost` (coût moyen pondéré) |
| `get_reorder_suggestions` | `/api/agent/reorder-suggestions` | `stock.economic_order_quantity` (EOQ) |
| `get_expiring_lots` | `/api/agent/expiring-lots` | `stock.expiring_lots` (FEFO) |
| `list_my_proposals` | `/api/agent/proposals/mine` | `repository.get_agent_proposals` |
| `get_my_capabilities` | `/api/agent/capabilities` | `agent_policy.parse_scopes` |

**Points de méthode importants :**
- **Aucune donnée inventée** (`get_reorder_suggestions`) : les hypothèses de l'EOQ (coût
  de commande, taux de possession) sont externalisées dans `config.py` et **renvoyées
  dans la réponse** (bloc `assumptions`). Si la demande ou le coût sont nuls, l'outil
  renvoie `null` + une raison explicite, jamais un chiffre fabriqué.
- **Isolation par agent** (`list_my_proposals`) : on étend `get_agent_proposals` avec un
  paramètre optionnel `agent_id` (rétrocompatible) pour qu'un agent ne voie que ses
  propres propositions.
- **Auto-introspection sans scope** (`get_my_capabilities`) : protégée par
  `get_current_agent` seulement, pour qu'un agent puisse toujours lire ses propres droits.

**Vérification.** 19 tests dédiés (un fichier par outil).

---

## 6. Cycle de vie complet du bon de commande

**Problème.** Le bon de commande n'était qu'une impression HTML ; le prix d'achat
n'était jamais capté, faussant les marges et la valorisation.

**Comment c'est fait.**
1. Fonctions repository `create_purchase_order` (DRAFT), `send_purchase_order` (SENT),
   `receive_purchase_order` (RECEIVED), `cancel_purchase_order`, `get_purchase_orders`,
   `get_purchase_order_by_id`. À la réception, on **réutilise `restock_product`** pour
   chaque ligne, ce qui alimente le **coût moyen pondéré (WAC) à partir du prix d'achat**.
2. Routeur `routers/purchase_orders.py` (6 endpoints REST humains, RBAC admin), monté
   dans `main.py`, chaque transition tracée dans l'audit (`PO_CREATE`/`PO_SEND`/
   `PO_RECEIVE`/`PO_CANCEL`).
3. Consolidation des modèles/schemas `PurchaseOrder` (une seule définition, ajout de
   `creator_id` / `created_at`).

```python
for item in po.items:
    restock_product(db, product_id=item.product_id, branch_id=po.branch_id,
                    quantity=item.quantity, unit_cost=item.unit_price, ...)
po.status = models.OrderStatus.RECEIVED.value
```

**Vérification.** `test_purchase_order.py` : cycle complet `DRAFT→SENT→RECEIVED`
(stock augmenté **et WAC mis à jour**), réception interdite depuis DRAFT, double
réception rejetée.

---

## 7. Renommage de l'interface assistant humaine

**Problème.** Les endpoints `/api/mcp/chat` et `/api/mcp/analyze` étaient des routes
**humaines** mal nommées « MCP », brouillant la séparation des deux interfaces.

**Comment c'est fait.** On renomme vers `/api/assistant/*` tout en garantissant la
rétrocompatibilité par **empilement de décorateurs** sur la même fonction (donc aucune
duplication de logique), l'ancien chemin étant marqué `deprecated` :

```python
@router.post("/api/assistant/chat")
@router.post("/api/mcp/chat", deprecated=True)   # alias rétrocompatible
async def mcp_sandbox_chat(...):
```

Les appels frontend (`dashboard.html`, `test-mcp.html`) sont migrés vers les nouveaux
chemins, et le fichier dupliqué `outil_test_mcp.html` est supprimé.

**Vérification.** `test_assistant_routes.py` : présence des nouveaux chemins, des alias,
et même fonction cible pour les deux chemins.

---

# Partie B — Corrections et compléments fonctionnels (tests manuels)

> Anomalies détectées en testant l'application page par page, puis corrigées.

## 8. Alignement du panneau « Accès Agent » sur le hachage des clés

**Problème.** Après le hachage des clés (§2), la page `settings.html` affichait
« undefined » à la place des clés (le backend ne renvoie plus la clé en clair), et la
clé nouvellement générée n'était jamais montrée.

**Comment c'est fait.** Correction côté frontend pour s'aligner sur le comportement
sécurisé du backend :
- La liste affiche désormais `api_key_masked` (indicateur masqué) + le niveau
  d'autonomie et les scopes.
- À la génération, la clé renvoyée (une seule fois) est affichée dans un **bandeau**
  dédié (« copiez-la maintenant, elle ne sera plus affichée »).

**Méthode.** Aucune modification backend ; on consomme simplement les champs déjà
exposés par la route de liste (`api_key_masked`, `autonomy_level`, `agent_scopes`).

---

## 9. Gestion des agents : révocation et rotation de clé

**Problème.** La liste des agents s'accumulait sans aucune action possible (ni révoquer,
ni renouveler une clé) — peu utile.

**Comment c'est fait.**
- **Backend** : ajout de `DELETE /api/agents/{id}` qui **révoque** un agent en le
  désactivant (`is_active = False`) — sa clé cesse immédiatement de fonctionner — sans
  supprimer la ligne (l'historique d'audit est conservé). L'action est auditée
  (`AGENT_REVOKED`). La liste est filtrée pour n'afficher que les agents actifs. La
  **rotation** de clé réutilise l'endpoint existant `/api/agents/{id}/rotate-key`.
- **Frontend** (`settings.html`) : deux boutons par agent — « Nouvelle clé » (rotation,
  affiche la nouvelle clé une fois) et « Révoquer ». Le formulaire de génération est
  aussi enrichi d'un choix de **niveau d'autonomie** et de **scopes**, indispensable pour
  produire une clé exploitable par les outils MCP.

---

## 10. Création de fournisseur (fonctionnalité absente)

**Problème.** Le bouton « Nouveau Fournisseur » n'avait aucun gestionnaire, et il
n'existait **aucune route backend** pour créer un fournisseur (seulement `GET`).

**Comment c'est fait.**
- **Backend** : fonction `repository.create_supplier` + route `POST /api/suppliers`
  (validation via le schéma `SupplierCreate` existant).
- **Frontend** (`suppliers.html`) : ajout du gestionnaire `onclick` sur le bouton, d'un
  **modal** de saisie (nom, contact, email, téléphone, adresse) au style cohérent avec le
  modal de réapprovisionnement, et des fonctions d'ouverture/fermeture/soumission qui
  POSTent puis rechargent la liste.

---

## 11. Export Excel réel du rapport de performance

**Problème.** Le bouton « Exporter Excel » était un **faux** : il affichait seulement une
alerte « le téléchargement va démarrer » sans produire de fichier.

**Comment c'est fait.** Sans ajouter de dépendance, on génère un **CSV compatible Excel**
en réutilisant le motif d'export déjà présent pour les logs (`StreamingResponse` + module
`csv`) :
- **Backend** : route `GET /api/reports/export` qui écrit un CSV avec, par produit :
  stock total, point de commande (ROP), prix de vente, coût (WAC) et valeur du stock au
  coût. On ajoute un **BOM UTF-8** (accents corrects dans Excel) et le **séparateur `;`**
  (attendu par Excel en locale FR).
- **Frontend** (`reports.html`) : `exportExcel()` récupère le fichier en `blob` et
  déclenche un vrai téléchargement (motif `createObjectURL` + `<a download>`).

> Le bouton « Exporter en PDF » voisin, lui, fonctionnait déjà (il utilise `window.print()`
> → « Enregistrer au format PDF » du navigateur).

---

## 12. Lisibilité dans Excel de l'export des logs d'audit

**Problème.** L'export des logs (`/api/audit/export`) utilisait la virgule comme
séparateur et pas de BOM → Excel (locale FR) mettait toutes les données dans une seule
colonne et cassait les accents.

**Comment c'est fait.** On applique à cet export le même traitement qu'au §11 : ajout du
**BOM UTF-8**, passage au **séparateur `;`**, et en-têtes en français. Les colonnes
s'ouvrent alors proprement dans Excel.

---

# Récapitulatif de vérification

| Contrôle | Résultat |
|----------|----------|
| Compilation de tout le code Python | ✅ aucune erreur de syntaxe |
| Import des modèles + configuration des mappers | ✅ |
| Import du serveur MCP | ✅ 9 outils |
| Démarrage de l'application | ✅ pages et documentation servies (HTTP 200) |
| **Suite de tests** | ✅ **65 tests, 0 échec** |

Les trois axes du rapport sont traités : **sécurité** (secret externalisé, CORS,
restore verrouillé, clés agents hachées, révocation), **théorie de gestion de stock**
(source de vérité unique, ROP, coût moyen pondéré, EOQ, FEFO, cycle complet du bon de
commande, exports exploitables) et **plateforme agent-ready** (deux interfaces distinctes,
niveaux d'autonomie, scopes, audit chaîné infalsifiable, human-in-the-loop, rollback
gouverné, gestion des accès agents).
