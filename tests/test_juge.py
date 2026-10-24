import asyncio
import json
from pathlib import Path

from pydantic_ai.models.test import TestModel

import consensus.juge as juge_mod
from consensus.accord import analyser
from consensus.domaines import TECHNIQUE
from consensus.juge import GroupeIdees, construire_prompt, recouvrement_juge
from main import charger_trace
from tests.test_accord import rep, res


def test_prompt_anonymise_sans_confiance_ni_nom_de_modele():
    valides = {"openai/gpt-x": rep(conf=0.93), "anthropic/claude-y": rep(conf=0.42)}
    prompt = construire_prompt("Q ?", "logs", valides, TECHNIQUE)
    assert "Réponse A" in prompt and "Réponse B" in prompt
    assert "gpt" not in prompt and "claude" not in prompt
    assert "0.93" not in prompt and "0.42" not in prompt and "confiance" not in prompt.lower()
    assert "A1. Le pare-feu bloque le port 443" in prompt


def test_recouvrement_juge_compte_les_groupes_partages_et_ignore_les_references_inconnues():
    groupes = [
        GroupeIdees(idee="pgbouncer", elements=["A1", "B2"]),
        GroupeIdees(idee="seul", elements=["A2"]),
        GroupeIdees(idee="même réponse", elements=["C1", "C2"]),  # une seule réponse : pas partagé
        GroupeIdees(idee="inventé", elements=["Z9", "B7"]),       # références inconnues
    ]
    rec = recouvrement_juge(groupes, {"A": 2, "B": 2, "C": 2})
    assert rec == {"A": 0.5, "B": 0.5, "C": 0.0}


def test_juge_bout_en_bout_avec_modele_factice(monkeypatch):
    resultats = [res("a", rep()), res("b", rep())]
    a = analyser(resultats)
    monkeypatch.setattr(juge_mod, "OpenAIChatModel", lambda *args, **kw: TestModel())
    monkeypatch.setattr(juge_mod, "_client", lambda: None)
    monkeypatch.setattr(juge_mod, "OpenAIProvider", lambda **kw: None)
    monkeypatch.setattr(juge_mod, "NativeOutput", lambda schema: schema)  # le modèle factice ne gère pas le mode natif
    rj = asyncio.run(juge_mod.juger("Q ?", None, resultats, a, TECHNIQUE, "factice"))
    assert rj.ok and rj.lettres == {"A": "a", "B": "b"}
    assert rj.score is not None and 0 <= rj.score <= 1


def test_charger_trace_relit_une_ancienne_trace_sans_domaine(tmp_path):
    trace = {"question": "Q ?", "contexte": None, "reponses": [
        {"modele": "m1", "ok": True, "erreur": None, "duree_s": 1.0, "tokens_entree": 1, "tokens_sortie": 1,
         "reponse": rep().model_dump(mode="json")},
        {"modele": "m2", "ok": False, "erreur": "timeout", "duree_s": 9.0, "tokens_entree": 0, "tokens_sortie": 0,
         "reponse": None}]}
    chemin = Path(tmp_path) / "t.json"
    chemin.write_text(json.dumps(trace), encoding="utf-8")
    domaine, question, contexte, resultats = charger_trace(chemin)
    assert domaine is TECHNIQUE and question == "Q ?"
    assert resultats[0].ok and not resultats[1].ok
