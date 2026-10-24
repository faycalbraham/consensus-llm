"""Schéma typé imposé à chaque modèle, validé par Pydantic AI."""

from enum import Enum

from pydantic import BaseModel, Field


class CategorieCause(str, Enum):
    reseau = "reseau"
    configuration = "configuration"
    ressources_systeme = "ressources_systeme"
    code_applicatif = "code_applicatif"
    base_de_donnees = "base_de_donnees"
    dependance_externe = "dependance_externe"
    securite = "securite"
    materiel = "materiel"
    inconnue = "inconnue"


class Gravite(str, Enum):
    faible = "faible"
    moyenne = "moyenne"
    elevee = "elevee"
    critique = "critique"


ORDRE_GRAVITE = list(Gravite)


class ReponseModele(BaseModel):
    """Diagnostic structuré produit par un modèle."""

    reponse: str = Field(description="Diagnostic principal en une à trois phrases.")
    categorie_cause: CategorieCause = Field(description="Catégorie de la cause racine la plus probable.")
    gravite: Gravite = Field(description="Gravité de l'incident pour le service.")
    raisonnement: str = Field(description="Raisonnement qui mène au diagnostic, étape par étape, de façon concise.")
    points_cles: list[str] = Field(
        min_length=2, max_length=6,
        description="Faits ou indices déterminants, une phrase courte chacun.",
    )
    actions_recommandees: list[str] = Field(
        min_length=1, max_length=5,
        description="Actions concrètes à mener, par ordre de priorité.",
    )
    hypotheses: list[str] = Field(
        max_length=5,
        description="Hypothèses posées faute d'information, ou causes alternatives envisagées.",
    )
    confiance: float = Field(ge=0, le=1, description="Confiance du modèle dans son diagnostic, entre 0 et 1.")


# --- Domaine santé / bien-être -------------------------------------------------

class ConsulterMedecin(str, Enum):
    non_necessaire = "non_necessaire"
    si_persistance = "si_persistance"
    rapidement = "rapidement"


class ReponseSante(BaseModel):
    """Conseil de bien-être structuré produit par un modèle (pas un avis médical)."""

    reponse: str = Field(description="Conseil principal en une à trois phrases.")
    consulter_medecin: ConsulterMedecin = Field(description="Faut-il consulter un médecin ?")
    gravite: Gravite = Field(description="Gravité estimée de la situation décrite.")
    raisonnement: str = Field(description="Raisonnement, en tenant compte du contexte de la personne.")
    recommandations: list[str] = Field(
        min_length=2, max_length=6,
        description="Aliments, boissons ou gestes conseillés, une phrase courte chacun.",
    )
    a_eviter: list[str] = Field(
        min_length=1, max_length=5,
        description="Ce qu'il vaut mieux éviter, en particulier à cause du contexte de la personne.",
    )
    signaux_alerte: list[str] = Field(
        min_length=1, max_length=5,
        description="Symptômes qui doivent amener à consulter rapidement.",
    )
    hypotheses: list[str] = Field(max_length=5, description="Ce que tu supposes faute d'information.")
    confiance: float = Field(ge=0, le=1, description="Confiance du modèle dans son conseil, entre 0 et 1.")
