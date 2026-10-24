"""Human-in-the-loop : un humain corrige les résultats, les corrections s'accumulent dans un fichier.

Chaque correction est ajoutée en fin de `corrections.jsonl` (une ligne JSON par correction, rien
n'est effacé). Le bilan mesure ensuite si la confiance affichée par le moteur correspond à des
réponses justes : c'est la validation du moteur par les humains.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Justesse = Literal["juste", "partielle", "fausse"]


class Correction(BaseModel):
    date: str
    trace: str
    domaine: str
    question: str
    # Ce que le moteur avait conclu
    choix_moteur: str | None
    score: float | None
    niveau: str
    modele_retenu: str | None
    score_juge: float | None = None
    niveau_juge: str | None = None
    # Ce que l'humain corrige
    justesse: Justesse = Field(description="La réponse retenue était-elle juste ?")
    bon_choix: str | None = Field(None, description="La bonne valeur de la case principale.")
    erreurs_juge_a_tort: list[str] = Field(default_factory=list,
                                           description="Erreurs signalées par le juge qui n'en étaient pas.")
    manque: str | None = Field(None, description="Contradiction ou erreur que le moteur n'a pas vue.")
    commentaire: str | None = None


def depuis_trace(trace: dict, chemin: str, justesse: Justesse, bon_choix: str | None = None,
                 erreurs_juge_a_tort: list[str] | None = None, manque: str | None = None,
                 commentaire: str | None = None) -> Correction:
    """Construit une correction à partir d'une trace runs/*.json et des réponses de l'humain."""
    a, juge = trace["analyse"], trace.get("juge") or {}
    retenu = a.get("diagnostic_retenu")
    return Correction(
        date=datetime.now().isoformat(timespec="seconds"), trace=chemin,
        domaine=trace.get("domaine") or "technique", question=trace["question"],
        choix_moteur=a.get("categorie_majoritaire"), score=a.get("score_consensus"), niveau=a.get("niveau", ""),
        modele_retenu=retenu[0] if retenu else None,
        score_juge=juge.get("score"), niveau_juge=juge.get("niveau"),
        justesse=justesse, bon_choix=bon_choix or a.get("categorie_majoritaire"),
        erreurs_juge_a_tort=erreurs_juge_a_tort or [], manque=manque, commentaire=commentaire,
    )


def ajouter(fichier: Path, c: Correction) -> None:
    with fichier.open("a", encoding="utf-8") as f:
        f.write(c.model_dump_json() + "\n")


def lire(fichier: Path) -> list[Correction]:
    if not fichier.exists():
        return []
    return [Correction.model_validate_json(ligne) for ligne in fichier.read_text(encoding="utf-8").splitlines()
            if ligne.strip()]


def bilan(corrections: list[Correction]) -> dict:
    """Justesse des réponses selon le niveau de confiance annoncé, avec et sans juge."""
    def par_niveau(cle):
        table = defaultdict(Counter)
        for c in corrections:
            niveau = getattr(c, cle)
            if niveau:
                table[niveau][c.justesse] += 1
        return {n: dict(table[n]) for n in ("élevée", "modérée", "faible", "indéterminée") if n in table}

    avec_choix = [c for c in corrections if c.choix_moteur]
    return {
        "total": len(corrections),
        "par_niveau": par_niveau("niveau"),
        "par_niveau_juge": par_niveau("niveau_juge"),
        "case_principale_correcte": (sum(c.choix_moteur == c.bon_choix for c in avec_choix), len(avec_choix)),
        "erreurs_juge_a_tort": sum(len(c.erreurs_juge_a_tort) for c in corrections),
        "manques_signales": sum(bool(c.manque) for c in corrections),
    }
