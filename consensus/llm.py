"""Interrogation parallèle de plusieurs LLM via OpenRouter, sorties validées par Pydantic AI."""

import asyncio
import os
import time
from dataclasses import dataclass

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .domaines import TECHNIQUE, Domaine

OPENROUTER_URL = "https://openrouter.ai/api/v1"

MODELES_PAR_DEFAUT = [
    "openai/gpt-5.6-luna",
    "anthropic/claude-haiku-5.5",
    "google/gemini-3.8-flash",
]


@dataclass
class ResultatModele:
    modele: str
    reponse: object | None = None  # instance du schéma du domaine
    erreur: str | None = None
    duree_s: float = 0.0
    tokens_entree: int = 0
    tokens_sortie: int = 0

    @property
    def ok(self) -> bool:
        return self.reponse is not None


def _client() -> AsyncOpenAI:
    cle = os.getenv("OPENROUTER_API_KEY")
    if not cle:
        raise SystemExit("OPENROUTER_API_KEY absente : copiez .env.example en .env et renseignez la clé, "
                         "ou lancez avec --demo.")
    # Une seule bibliothèque : le client openai, pointé sur OpenRouter.
    return AsyncOpenAI(
        base_url=OPENROUTER_URL,
        api_key=cle,
        default_headers={"X-Title": "consensus-llm"},
        timeout=90,
    )


def _prompt(question: str, contexte: str | None) -> str:
    if contexte:
        return f"Question :\n{question}\n\nÉléments disponibles :\n{contexte}"
    return f"Question :\n{question}"


async def _interroger(agent: Agent, modele: str, prompt: str) -> ResultatModele:
    debut = time.perf_counter()
    try:
        res = await agent.run(prompt)
        usage = res.usage
        return ResultatModele(
            modele=modele,
            reponse=res.output,
            duree_s=time.perf_counter() - debut,
            tokens_entree=usage.input_tokens or 0,
            tokens_sortie=usage.output_tokens or 0,
        )
    except Exception as e:  # un modèle en échec ne doit pas bloquer les autres
        return ResultatModele(modele=modele, erreur=f"{type(e).__name__}: {e}"[:300],
                              duree_s=time.perf_counter() - debut)


async def interroger_modeles(question: str, contexte: str | None, modeles: list[str],
                            domaine: Domaine = TECHNIQUE) -> list[ResultatModele]:
    provider = OpenAIProvider(openai_client=_client())
    prompt = _prompt(question, contexte)
    taches = []
    for nom in modeles:
        agent = Agent(
            OpenAIChatModel(nom, provider=provider),
            output_type=domaine.schema,
            instructions=domaine.instructions,
            retries=2,  # Pydantic AI relance le modèle si le JSON ne valide pas le schéma
        )
        taches.append(_interroger(agent, nom, prompt))
    return list(await asyncio.gather(*taches))
