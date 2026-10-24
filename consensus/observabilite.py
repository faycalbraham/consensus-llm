"""Observabilité avec Langfuse (optionnelle).

Sans LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY dans .env, rien n'est envoyé et le moteur
fonctionne comme avant. Avec les clés :
  - Pydantic AI émet ses traces (OpenTelemetry) : chaque appel de modèle, avec prompt, JSON, jetons, durée ;
  - ce module les regroupe dans une trace par exécution ;
  - il y ajoute nos scores (par mots, avec le juge) et, plus tard, les corrections humaines.
"""

import os
from contextlib import contextmanager

_client = None


def actif() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def client():
    """Client Langfuse, créé à la première utilisation ; None si les clés sont absentes."""
    global _client
    if _client is None and actif():
        from langfuse import get_client
        from pydantic_ai import Agent

        _client = get_client()
        Agent.instrument_all()  # Pydantic AI émet ses traces, que le client Langfuse reçoit
    return _client


@contextmanager
def execution(nom: str, question: str, contexte: str | None, domaine: str, details: dict):
    """Ouvre la trace d'une exécution : tous les appels faits dans le bloc y sont rattachés."""
    c = client()
    if c is None:
        yield None
        return
    from langfuse import propagate_attributes

    with c.start_as_current_observation(name=nom, as_type="span",
                                        input={"question": question, "contexte": contexte},
                                        metadata={"domaine": domaine, **details}) as span:
        with propagate_attributes(trace_name=nom, tags=[domaine]):
            yield span


def trace_id() -> str | None:
    c = client()
    return c.get_current_trace_id() if c else None


def _score(tid, nom, valeur, type_="NUMERIC", commentaire=None):
    if valeur is not None:
        client().create_score(trace_id=tid, name=nom, value=valeur, data_type=type_, comment=commentaire)


def envoyer_resultats(span, tid: str | None, analyse, rj=None) -> None:
    """Attache à la trace la synthèse du moteur et nos scores (Pydantic AI ne les connaît pas)."""
    if span is None or tid is None:
        return
    a = analyse
    span.update(output={"choix_majoritaire": a.categorie_majoritaire, "diagnostic_retenu": a.diagnostic_retenu,
                        "contradictions": a.contradictions, "alertes": a.alertes})
    _score(tid, "score_par_mots", a.score_consensus)
    _score(tid, "accord_categorie", a.accord_categorie)
    _score(tid, "accord_gravite", a.accord_gravite)
    _score(tid, "accord_contenu_par_mots", a.accord_contenu)
    _score(tid, "niveau_par_mots", a.niveau, "CATEGORICAL")
    if rj is not None and rj.ok:
        v = rj.verdict
        _score(tid, "score_avec_juge", rj.score)
        _score(tid, "accord_contenu_juge", rj.accord_contenu)
        _score(tid, "niveau_avec_juge", rj.niveau, "CATEGORICAL")
        _score(tid, "juge_accord_sur_le_fond", 1 if v.accord_sur_le_fond else 0, "BOOLEAN", v.explication_fond)
        _score(tid, "juge_contradictions", len(v.contradictions))
        _score(tid, "juge_erreurs_contexte", len(v.erreurs_contexte))
        _score(tid, "juge_lecons_recues", len(rj.lecons))


def envoyer_correction(tid: str | None, c) -> bool:
    """Human-in-the-loop : la correction devient un score humain sur la trace d'origine."""
    if tid is None or client() is None:
        return False
    _score(tid, "humain_justesse", c.justesse, "CATEGORICAL", c.commentaire)
    _score(tid, "humain_bonne_case", c.bon_choix, "CATEGORICAL")
    if c.erreurs_juge_a_tort:
        _score(tid, "humain_erreurs_juge_a_tort", len(c.erreurs_juge_a_tort))
    if c.manque:
        _score(tid, "humain_manque", c.manque, "TEXT")
    return True


def terminer() -> None:
    """Envoie ce qui reste en attente avant la fin du programme."""
    if _client is not None:
        _client.flush()
