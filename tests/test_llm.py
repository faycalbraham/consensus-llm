import asyncio

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from consensus.llm import _interroger
from consensus.schema import ReponseModele


def test_chaine_pydantic_ai_produit_une_reponse_validee():
    agent = Agent(TestModel(), output_type=ReponseModele, instructions="x")
    r = asyncio.run(_interroger(agent, "test", "question"))
    assert r.ok and isinstance(r.reponse, ReponseModele) and r.tokens_entree > 0


def test_un_modele_en_erreur_ne_leve_pas_d_exception():
    class Casse(TestModel):
        async def request(self, *a, **k):
            raise RuntimeError("fournisseur indisponible")

    r = asyncio.run(_interroger(Agent(Casse(), output_type=ReponseModele), "casse", "q"))
    assert not r.ok and "fournisseur indisponible" in r.erreur
