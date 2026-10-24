"""Mesure de l'accord entre modèles et mini-synthèse.

L'indicateur de confiance repose sur l'accord entre modèles, jamais sur la confiance
auto-déclarée (affichée à part, pour comparaison). Trois composantes :
  - catégorie de cause racine (poids 0,5) : part des modèles alignés sur la majorité ;
  - gravité (poids 0,2) : écart maximal sur l'échelle faible → critique ;
  - contenu (poids 0,3) : part des points clés et actions repris par au moins un autre modèle.
Le rapprochement des textes est lexical (mots normalisés, coefficient de Dice) :
simple et sans appel externe, il sera remplacé par un juge LLM après la maquette.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .domaines import TECHNIQUE, Domaine
from .llm import ResultatModele
from .schema import ORDRE_GRAVITE

POIDS = {"categorie": 0.5, "gravite": 0.2, "contenu": 0.3}
SEUIL_SIMILARITE = 0.4
SEUIL_ALERTE_CALIBRATION = 0.25

MOTS_VIDES = set("""
les des une un le la du de en et ou au aux sur sous par pour dans avec sans est sont etre ete
pas plus moins que qui quoi dont cette ces cet son sa ses leur leurs nos vos tout tous toute
fait faire peut peuvent entre lors apres avant tres bien ainsi donc car mais aussi elle il ils
the and for with from that this are was not
""".split())


def _normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def mots(texte: str) -> set[str]:
    """Mots porteurs de sens, sans accents, tronqués à 6 lettres (racinisation grossière)."""
    return {m[:6] for m in re.findall(r"[a-z0-9]+", _normaliser(texte))
            if len(m) >= 3 and m not in MOTS_VIDES}


def similarite(a: str, b: str) -> float:
    ma, mb = mots(a), mots(b)
    if not ma or not mb:
        return 0.0
    return 2 * len(ma & mb) / (len(ma) + len(mb))


@dataclass
class Groupe:
    """Un même point exprimé par un ou plusieurs modèles."""
    textes: dict[str, str] = field(default_factory=dict)  # modèle -> formulation

    @property
    def modeles(self) -> list[str]:
        return list(self.textes)

    @property
    def representant(self) -> str:
        return next(iter(self.textes.values()))


def regrouper(items: dict[str, list[str]]) -> list[Groupe]:
    """Regroupe les points proches, au plus un point par modèle dans chaque groupe."""
    groupes: list[Groupe] = []
    for modele, textes in items.items():
        for texte in textes:
            candidats = [
                (max(similarite(texte, t) for t in g.textes.values()), g)
                for g in groupes if modele not in g.textes
            ]
            score, meilleur = max(candidats, key=lambda c: c[0], default=(0.0, None))
            if meilleur is not None and score >= SEUIL_SIMILARITE:
                meilleur.textes[modele] = texte
            else:
                groupes.append(Groupe({modele: texte}))
    return groupes


def _recouvrement(groupes: list[Groupe], items: dict[str, list[str]]) -> dict[str, float]:
    """Pour chaque modèle, part de ses points repris par au moins un autre modèle."""
    partages = Counter(m for g in groupes if len(g.textes) >= 2 for m in g.textes)
    return {m: partages[m] / len(t) if t else 0.0 for m, t in items.items()}


@dataclass
class Analyse:
    modeles_valides: list[str]
    modeles_en_echec: dict[str, str]
    repartition_categories: dict[str, list[str]]
    categorie_majoritaire: str | None
    accord_categorie: float
    gravites: dict[str, str]
    accord_gravite: float
    accord_contenu: float
    score_consensus: float | None
    niveau: str
    confiance_declaree_moyenne: float | None
    convergences: list[Groupe]
    actions_convergentes: list[Groupe]
    divergences: list[tuple[str, str]]
    contradictions: list[str]
    diagnostic_retenu: tuple[str, str] | None
    alertes: list[str]


def niveau_confiance(score: float) -> str:
    if score >= 0.75:
        return "élevée"
    if score >= 0.5:
        return "modérée"
    return "faible"


def analyser(resultats: list[ResultatModele], domaine: Domaine = TECHNIQUE) -> Analyse:
    valides = {r.modele: r.reponse for r in resultats if r.ok}
    echecs = {r.modele: r.erreur or "" for r in resultats if not r.ok}
    n = len(valides)

    # Catégorie (la cause en technique) : (effectif majoritaire - 1) / (n - 1), soit 1 si unanimité, 0 si tous différents.
    repartition: dict[str, list[str]] = {}
    for m, rep in valides.items():
        repartition.setdefault(getattr(rep, domaine.champ_categorie).value, []).append(m)
    majoritaire, partisans = max(repartition.items(), key=lambda kv: len(kv[1]), default=(None, []))
    accord_cat = (len(partisans) - 1) / (n - 1) if n >= 2 else 0.0
    if n >= 2 and len(partisans) == 1:
        majoritaire = None  # aucune catégorie partagée

    # Gravité : 1 - écart maximal sur l'échelle ordinale.
    rangs = {m: ORDRE_GRAVITE.index(rep.gravite) for m, rep in valides.items()}
    ecart = (max(rangs.values()) - min(rangs.values())) if rangs else 0
    accord_grav = 1 - ecart / (len(ORDRE_GRAVITE) - 1) if n >= 2 else 0.0

    # Contenu : les deux listes du domaine (points clés et actions en technique), recoupées entre modèles.
    champ_a, champ_b = domaine.champs_listes
    points = {m: getattr(rep, champ_a) for m, rep in valides.items()}
    actions = {m: getattr(rep, champ_b) for m, rep in valides.items()}
    groupes_points, groupes_actions = regrouper(points), regrouper(actions)
    rec_points = _recouvrement(groupes_points, points)
    rec_actions = _recouvrement(groupes_actions, actions)
    rec_modele = {m: (rec_points[m] + rec_actions[m]) / 2 for m in valides}
    accord_contenu = sum(rec_modele.values()) / n if n >= 2 else 0.0

    score = None
    if n >= 2:
        score = round(POIDS["categorie"] * accord_cat + POIDS["gravite"] * accord_grav
                      + POIDS["contenu"] * accord_contenu, 3)

    # Contradictions : désaccords francs sur la cause ou la gravité.
    contradictions = []
    if n >= 2 and majoritaire is None:
        detail = ", ".join(f"{m} → {c}" for c, ms in repartition.items() for m in ms)
        contradictions.append(f"Aucun accord sur {domaine.libelle_categorie} : {detail}.")
    elif majoritaire is not None:
        for c, ms in repartition.items():
            if c != majoritaire:
                for m in ms:
                    contradictions.append(
                        f"{m} choisit « {c} » pour {domaine.libelle_categorie} alors que {', '.join(partisans)} "
                        f"retien{'nent' if len(partisans) > 1 else 't'} « {majoritaire} ».")
    if ecart >= 2:
        detail = ", ".join(f"{m} → {valides[m].gravite.value}" for m in valides)
        contradictions.append(f"Gravité très divergente : {detail}.")

    # Divergences : points avancés par un seul modèle.
    divergences = [(g.modeles[0], g.representant) for g in groupes_points if len(g.textes) == 1]

    # Diagnostic retenu : parmi les modèles majoritaires, celui dont le contenu est le plus recoupé.
    diagnostic = None
    if valides:
        pool = partisans if majoritaire is not None else list(valides)
        meilleur = max(pool, key=lambda m: rec_modele.get(m, 0.0))
        diagnostic = (meilleur, valides[meilleur].reponse)

    confiance_moy = (sum(r.confiance for r in valides.values()) / n) if n else None

    alertes = []
    if n < 2:
        alertes.append("Moins de deux réponses valides : aucun consensus mesurable.")
    if score is not None and confiance_moy is not None and confiance_moy - score > SEUIL_ALERTE_CALIBRATION:
        alertes.append(f"Les modèles se disent confiants ({confiance_moy:.0%}) bien au-delà de leur "
                       f"accord réel ({score:.0%}) : ne pas se fier à la confiance auto-déclarée.")

    return Analyse(
        modeles_valides=list(valides),
        modeles_en_echec=echecs,
        repartition_categories=repartition,
        categorie_majoritaire=majoritaire,
        accord_categorie=round(accord_cat, 3),
        gravites={m: rep.gravite.value for m, rep in valides.items()},
        accord_gravite=round(accord_grav, 3),
        accord_contenu=round(accord_contenu, 3),
        score_consensus=score,
        niveau=niveau_confiance(score) if score is not None else "indéterminée",
        confiance_declaree_moyenne=round(confiance_moy, 3) if confiance_moy is not None else None,
        convergences=[g for g in groupes_points if len(g.textes) >= 2],
        actions_convergentes=[g for g in groupes_actions if len(g.textes) >= 2],
        divergences=divergences,
        contradictions=contradictions,
        diagnostic_retenu=diagnostic,
        alertes=alertes,
    )
