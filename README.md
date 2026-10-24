# Moteur de consensus multi-modèles pour l'aide à la décision

On pose une même question à trois LLM de fournisseurs différents. Chaque réponse est forcée dans
un schéma JSON typé et validé. Le moteur compare ensuite les réponses et produit une synthèse
(convergences, divergences, contradictions) avec un **indicateur de confiance fondé sur l'accord
entre modèles**, et non sur la confiance que chaque modèle déclare.

Un **juge LLM** peut relire les réponses pour les comparer par le sens, une **boucle humaine**
enregistre les corrections, et **Langfuse** trace chaque exécution.

> Nature du projet : un workflow orchestré par le code (plusieurs modèles, sorties structurées,
> évaluation), pas de l'IA agentique. La classe `Agent` de Pydantic AI sert ici à faire des appels
> structurés, sans outils ni décision autonome du modèle.

## Fonctionnement

```
question + contexte + domaine
        │
        ├──► GPT ────┐
        ├──► Claude ─┤  appels parallèles via OpenRouter ; Pydantic AI impose le schéma,
        └──► Gemini ─┘  valide le JSON et relance le modèle si besoin
                │
        calcul d'accord par mots ──► score par mots + synthèse
                │
        juge LLM (option) ──► regroupement par le sens, contradictions, erreurs, score avec le juge
                │
        affichage + trace JSON (runs/) ──► Langfuse (option)
                │
        humain : --corriger ──► corrections.jsonl ──► --bilan
```

### Le score de consensus

| Composante | Poids | Mesure |
|---|---|---|
| Case principale | 0,5 | part des modèles alignés sur le choix majoritaire (la cause, ou « consulter ? ») |
| Gravité | 0,2 | 1 − écart maximal sur l'échelle faible → critique |
| Contenu | 0,3 | part des éléments des deux listes repris par au moins un autre modèle |

Niveau : élevée ≥ 75 %, modérée ≥ 50 %, faible sinon. Le contenu est mesuré de deux façons :

- **par mots** : mots communs et coefficient de Dice, seuil 0,4 ;
- **avec le juge** : le juge LLM regroupe les éléments par le sens ; même formule ensuite.

La confiance déclarée par les modèles est affichée à part, et une alerte s'affiche quand elle
dépasse nettement l'accord réel.

### Le juge LLM

Un quatrième modèle (`claude-sonnet-5.5` par défaut, différent des trois interrogés) reçoit la
question, le contexte et les réponses **anonymisées** (A, B, C), sans nom de modèle, ni confiance
déclarée, ni notre score. Il rend un verdict structuré : idées partagées, accord sur le fond,
contradictions de contenu, erreurs par rapport au contexte, synthèse argumentée.

### La boucle humaine (human-in-the-loop)

`--corriger` affiche le résultat d'une exécution et demande à un humain si la réponse était juste,
quelle était la bonne case et si le juge s'est trompé. Chaque correction est ajoutée à
`corrections.jsonl`, sans rien effacer. `--bilan` indique ensuite si la confiance annoncée
correspondait à des réponses justes, avec et sans juge.

La boucle **mesure** aujourd'hui. La faire **apprendre** est la suite prévue : corrections données
en exemples au juge, calibrage des seuils, révision des catégories qui créent de la confusion.

### Domaines

| Domaine | Case principale | Listes comparées |
|---|---|---|
| `technique` (par défaut) | cause : réseau, configuration, ressources système, base de données… | points clés, actions recommandées |
| `sante` | consulter : non nécessaire, si persistance, rapidement | recommandations, choses à éviter |

Ajouter un domaine demande trois éléments : un fichier de consignes (`consensus/domaine_*.py`), un
schéma dans `consensus/schema.py` et une entrée dans `consensus/domaines.py`.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # puis renseigner OPENROUTER_API_KEY (et, en option, Langfuse)
```

## Utilisation

```bash
python main.py --demo                                    # réponses fictives, sans clé ni réseau
python main.py --exemple 2                               # incident d'exemple (1, 2 ou 3)
python main.py --exemple 2 --juge                        # avec le juge LLM
python main.py "Votre question" --contexte logs_test.txt # vos propres logs
python main.py --domaine sante --exemple 1               # domaine santé
python main.py --juger exemples/postgresql-lundi-avec-juge.json   # juger une trace existante
python main.py --corriger runs/run-XXXX.json             # corriger un résultat
python main.py --bilan                                   # bilan des corrections
pytest                                                   # 17 tests, sans réseau
```

Options utiles : `--modeles` (identifiants OpenRouter des modèles interrogés), `--modele-juge`.

**Langfuse** (optionnel) : avec `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` et
`LANGFUSE_BASE_URL` dans `.env`, chaque exécution devient une trace : les appels aux modèles et au
juge (prompt, JSON, jetons, durée, coût), les scores du moteur et les corrections humaines. Sans
ces clés, rien n'est envoyé.

## Exemples d'exécutions

Le dossier [exemples/](exemples/) contient trois exécutions réelles, lisibles sans clé :

| Fichier | Ce qu'il montre |
|---|---|
| `postgresql-lundi-avec-juge.json` | accord des trois modèles ; le juge regroupe par le sens (score 78 % par mots, 97 % avec le juge) et relève des affirmations absentes du contexte |
| `elasticsearch-fausse-alerte.json` | même diagnostic, mais cases différentes et vocabulaire de logs : score par mots 55 % alors que les modèles sont d'accord sur le fond |
| `sante-rhume.json` | domaine santé : contradiction sur le miel et erreur sur la glycémie, non détectées par le score par mots |

## Organisation du code

| Fichier | Rôle |
|---|---|
| `main.py` | ligne de commande, enchaînement des étapes |
| `consensus/domaines.py`, `domaine.py`, `domaine_sante.py` | profils de domaine : consignes, exemples, champs comparés |
| `consensus/schema.py` | schémas Pydantic imposés aux modèles |
| `consensus/llm.py` | appels parallèles via OpenRouter et Pydantic AI |
| `consensus/accord.py` | score par mots et synthèse |
| `consensus/juge.py` | juge LLM et score avec le juge |
| `consensus/corrections.py` | boucle humaine : corrections et bilan |
| `consensus/observabilite.py` | traces Langfuse |
| `consensus/rapport.py` | affichage et traces JSON |

## Limites connues

- Le score par mots rate les paraphrases et les sigles courts des logs (GC, ES…), et ne détecte
  pas les contradictions de contenu : c'est ce que corrige le juge.
- Le juge est lui-même un LLM : il peut regrouper trop largement ou se tromper. Il coûte environ
  90 % d'une exécution.
- Des catégories qui se recouvrent (« ressources système » ou « base de données » pour
  Elasticsearch) font baisser le score sans vrai désaccord.
- Un consensus fort n'est pas une preuve : des modèles peuvent se tromper ensemble.
- Seuils et poids sont fixés à la main ; il faudra les calibrer avec les corrections humaines.
- Les conseils du domaine santé ne sont pas un avis médical.
