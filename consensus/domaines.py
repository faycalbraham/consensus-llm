"""Un domaine = des consignes, un schéma de réponse et les champs que le moteur compare.

Le calcul d'accord est le même pour tous les domaines :
  - champ_categorie (liste fermée, poids 0,5) ;
  - `gravite` (échelle commune, poids 0,2) ;
  - champs_listes (deux listes de phrases, poids 0,3).
"""

from dataclasses import dataclass

from pydantic import BaseModel

from . import domaine as technique
from . import domaine_sante as sante
from .schema import ReponseModele, ReponseSante


@dataclass(frozen=True)
class Domaine:
    nom: str
    instructions: str
    schema: type[BaseModel]
    exemples: list[dict]
    champ_categorie: str
    libelle_categorie: str            # ex. « la cause racine », pour les messages
    titre_categorie: str              # ex. « Cause », pour le tableau
    champs_listes: tuple[str, str]
    libelles_listes: tuple[str, str]  # ex. (« points clés », « actions recommandées »)
    titre_reponse: str                # ex. « Diagnostic retenu »


TECHNIQUE = Domaine(
    nom="technique",
    instructions=technique.INSTRUCTIONS,
    schema=ReponseModele,
    exemples=technique.EXEMPLES,
    champ_categorie="categorie_cause",
    libelle_categorie="la cause racine",
    titre_categorie="Cause",
    champs_listes=("points_cles", "actions_recommandees"),
    libelles_listes=("points clés", "actions recommandées"),
    titre_reponse="Diagnostic retenu",
)

SANTE = Domaine(
    nom="sante",
    instructions=sante.INSTRUCTIONS,
    schema=ReponseSante,
    exemples=sante.EXEMPLES,
    champ_categorie="consulter_medecin",
    libelle_categorie="le besoin de consulter",
    titre_categorie="Consulter",
    champs_listes=("recommandations", "a_eviter"),
    libelles_listes=("recommandations", "choses à éviter"),
    titre_reponse="Conseil retenu",
)

DOMAINES = {d.nom: d for d in (TECHNIQUE, SANTE)}
