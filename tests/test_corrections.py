import json
from pathlib import Path

from rich.console import Console

import main
from consensus import corrections


def trace(majoritaire="base_de_donnees", score=0.865, niveau="élevée", juge=None):
    return {"domaine": "technique", "question": "Q ?",
            "analyse": {"categorie_majoritaire": majoritaire, "score_consensus": score, "niveau": niveau,
                        "diagnostic_retenu": ["openai/gpt", "Le job sature PostgreSQL."]},
            "juge": juge}


def test_corrections_ajoutees_sans_rien_effacer_puis_bilan(tmp_path):
    f = Path(tmp_path) / "corrections.jsonl"
    corrections.ajouter(f, corrections.depuis_trace(trace(), "t1.json", "juste"))
    corrections.ajouter(f, corrections.depuis_trace(trace(score=0.48, niveau="faible"), "t2.json", "juste",
                                                    bon_choix="ressources_systeme"))
    corrections.ajouter(f, corrections.depuis_trace(trace(), "t3.json", "fausse"))
    liste = corrections.lire(f)
    assert len(liste) == 3 and len(f.read_text(encoding="utf-8").splitlines()) == 3
    b = corrections.bilan(liste)
    assert b["par_niveau"] == {"élevée": {"juste": 1, "fausse": 1}, "faible": {"juste": 1}}
    assert b["case_principale_correcte"] == (2, 3)


def test_correction_interactive(tmp_path, monkeypatch):
    juge = {"score": 1.0, "niveau": "élevée", "verdict": {"erreurs_contexte": [
        {"reponse": "A", "citation": "~95 sessions idle", "explication": "le contexte dit nombreuses"},
        {"reponse": "C", "citation": "pas de timeout", "explication": "non mentionné"}]}}
    chemin = Path(tmp_path) / "run.json"
    chemin.write_text(json.dumps(trace(juge=juge)), encoding="utf-8")
    reponses = iter(["partielle", "base_de_donnees", "2", "", "Cause confirmée par les logs du job"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *a, **k: next(reponses))
    f = Path(tmp_path) / "corrections.jsonl"
    main.corriger(Console(file=open(Path(tmp_path) / "sortie.txt", "w", encoding="utf-8")), chemin, f)
    c = corrections.lire(f)[0]
    assert c.justesse == "partielle" and c.score_juge == 1.0
    assert c.erreurs_juge_a_tort == ["pas de timeout"] and c.manque is None
    assert c.commentaire == "Cause confirmée par les logs du job"
