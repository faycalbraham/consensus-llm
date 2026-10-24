"""Juge LLM (LLM-as-a-judge).

Un quatrième modèle relit les réponses, anonymisées (A, B, C), et rend un verdict structuré :
  - il regroupe les éléments des deux listes par le sens, pas par les mots ;
  - il dit si les réponses s'accordent sur le fond, même quand les cases cochées diffèrent ;
  - il relève les contradictions de contenu et les erreurs par rapport au contexte ;
  - il rédige une synthèse argumentée.
Il ne reçoit ni le nom des modèles, ni leur confiance déclarée, ni notre score.
Le contenu est ensuite recalculé avec ses regroupements, selon la même formule que le score par mots.
"""

import re
import time
from dataclasses import dataclass, field
from string import ascii_uppercase

from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .accord import POIDS, Analyse, niveau_confiance
from .domaines import Domaine
from .llm import ResultatModele, _client

MODELE_JUGE_PAR_DEFAUT = "anthropic/claude-sonnet-5.5"


class GroupeIdees(BaseModel):
    idee: str = Field(description="L'idée commune, reformulée en une phrase courte.")
    elements: list[str] = Field(min_length=1,
                                description="Références des éléments qui expriment cette idée, ex. ['A1', 'C3'].")


class Position(BaseModel):
    reponse: str = Field(description="Lettre de la réponse, ex. 'B'.")
    position: str = Field(description="Ce que cette réponse affirme ou recommande sur ce sujet.")


class Contradiction(BaseModel):
    sujet: str
    positions: list[Position] = Field(min_length=2)


class ErreurContexte(BaseModel):
    reponse: str = Field(description="Lettre de la réponse, ex. 'A'.")
    citation: str = Field(description="Passage exact de la réponse qui pose problème.")
    explication: str = Field(description="Ce que dit réellement le contexte.")


class VerdictJuge(BaseModel):
    groupes_liste_1: list[GroupeIdees] = Field(description="Regroupement par le sens des éléments de la liste 1.")
    groupes_liste_2: list[GroupeIdees] = Field(description="Regroupement par le sens des éléments de la liste 2.")
    accord_sur_le_fond: bool = Field(
        description="Les réponses arrivent-elles à la même conclusion principale, même si leurs cases cochées diffèrent ?")
    explication_fond: str = Field(description="Justification en une ou deux phrases.")
    contradictions: list[Contradiction] = Field(
        description="Sujets sur lesquels des réponses affirment ou recommandent des choses incompatibles. Vide si aucun.")
    erreurs_contexte: list[ErreurContexte] = Field(
        description="Affirmations contredites par le contexte ou présentées comme des faits sans y figurer. Vide si aucune.")
    synthese: str = Field(description="Synthèse argumentée en 3 à 6 phrases, qui signale ce qui reste incertain.")


INSTRUCTIONS_JUGE = """\
Tu es un évaluateur impartial et rigoureux. Tu reçois une question, son contexte et plusieurs
réponses anonymes (A, B, C...) produites indépendamment par des assistants.
1. Pour chacune des deux listes, regroupe les éléments qui expriment la même idée, même avec des
   mots différents. Chaque élément (ex. A1) va dans un seul groupe ; un élément sans équivalent forme
   un groupe à lui seul. Les références sont propres à chaque liste.
2. Indique si les réponses s'accordent sur la conclusion principale, même si leurs cases cochées diffèrent.
3. Relève les contradictions de contenu : recommandations ou affirmations incompatibles entre réponses.
4. Vérifie chaque réponse contre le contexte : signale toute affirmation contredite par le contexte ou
   présentée comme un fait alors qu'elle n'y figure pas. Une hypothèse annoncée comme telle n'est pas une erreur.
5. Rédige une synthèse argumentée.
N'invente ni accord ni désaccord. Réponds en français.
"""


def lecons_passees(corrections: list, d: Domaine, limite: int = 5) -> list[str]:
    """Boucle humaine fermée : transforme les corrections passées en leçons pour le juge.

    On retient, pour le même domaine et des plus récentes aux plus anciennes, les erreurs que le
    juge a signalées à tort, ce qu'un humain a vu et que le moteur a manqué, et les cas où la bonne
    case n'était pas celle des modèles.
    """
    lecons = []
    for c in reversed(corrections):
        if c.domaine != d.nom:
            continue
        sujet = c.question if len(c.question) <= 90 else c.question[:89] + "…"
        for citation in c.erreurs_juge_a_tort:
            lecons.append(f"Sur « {sujet} », tu avais signalé comme erreur « {citation} » : "
                          "un humain a jugé que ce n'en était pas une (supposition raisonnable).")
        if c.manque:
            lecons.append(f"Sur « {sujet} », un humain a relevé ce que tu n'avais pas vu : « {c.manque} ».")
        if c.choix_moteur and c.bon_choix and c.choix_moteur != c.bon_choix:
            lecons.append(f"Sur « {sujet} », les modèles avaient choisi « {c.choix_moteur} » "
                          f"pour {d.libelle_categorie}, mais un humain a retenu « {c.bon_choix} ».")
        if len(lecons) >= limite:
            break
    return lecons[:limite]


def instructions_avec_lecons(lecons: list[str]) -> str:
    if not lecons:
        return INSTRUCTIONS_JUGE
    return (INSTRUCTIONS_JUGE + "\nLeçons tirées des corrections humaines de tes jugements passés. "
            "Tiens-en compte sans en exagérer la portée :\n" + "\n".join(f"- {x}" for x in lecons) + "\n")


def _champ(rep, nom):
    valeur = getattr(rep, nom)
    return valeur.value if hasattr(valeur, "value") else valeur


def construire_prompt(question: str, contexte: str | None, valides: dict[str, object], d: Domaine) -> str:
    """Prompt du juge : réponses anonymisées, sans nom de modèle ni confiance déclarée."""
    l1, l2 = d.champs_listes
    blocs = [f"Question :\n{question}", f"Contexte :\n{contexte or '(aucun)'}"]
    for lettre, rep in zip(ascii_uppercase, valides.values()):
        lignes = [f"=== Réponse {lettre} ===",
                  f"{d.titre_categorie} : {_champ(rep, d.champ_categorie)} ; gravité : {_champ(rep, 'gravite')}",
                  f"Réponse : {rep.reponse}",
                  f"Raisonnement : {rep.raisonnement}"]
        if rep.hypotheses:
            lignes.append("Hypothèses : " + " / ".join(rep.hypotheses))
        lignes.append(f"Liste 1 ({d.libelles_listes[0]}) :")
        lignes += [f"  {lettre}{i}. {t}" for i, t in enumerate(getattr(rep, l1), 1)]
        lignes.append(f"Liste 2 ({d.libelles_listes[1]}) :")
        lignes += [f"  {lettre}{i}. {t}" for i, t in enumerate(getattr(rep, l2), 1)]
        blocs.append("\n".join(lignes))
    return "\n\n".join(blocs)


def recouvrement_juge(groupes: list[GroupeIdees], tailles: dict[str, int]) -> dict[str, float]:
    """Pour chaque réponse, part de ses éléments placés dans un groupe partagé avec une autre réponse.

    Les références inconnues sont ignorées ; un élément que le juge a oublié compte comme non partagé.
    """
    partages = {lettre: set() for lettre in tailles}
    for g in groupes:
        refs = set()
        for r in g.elements:
            m = re.fullmatch(r"([A-Z])(\d+)", r.strip().upper())
            if m and m[1] in tailles and 1 <= int(m[2]) <= tailles[m[1]]:
                refs.add((m[1], int(m[2])))
        if len({lettre for lettre, _ in refs}) >= 2:
            for lettre, i in refs:
                partages[lettre].add(i)
    return {lettre: len(partages[lettre]) / n if n else 0.0 for lettre, n in tailles.items()}


@dataclass
class ResultatJuge:
    modele_juge: str
    lettres: dict[str, str] = field(default_factory=dict)  # lettre -> modèle
    verdict: VerdictJuge | None = None
    erreur: str | None = None
    accord_contenu: float | None = None
    score: float | None = None
    niveau: str = "indéterminée"
    duree_s: float = 0.0
    lecons: list[str] = field(default_factory=list)  # corrections humaines passées données au juge

    @property
    def ok(self) -> bool:
        return self.verdict is not None


def calculer_score(verdict: VerdictJuge, valides: dict[str, object], a: Analyse, d: Domaine):
    lettres = dict(zip(ascii_uppercase, valides))
    rec = []
    for groupes, champ in ((verdict.groupes_liste_1, d.champs_listes[0]), (verdict.groupes_liste_2, d.champs_listes[1])):
        tailles = {lt: len(getattr(valides[m], champ)) for lt, m in lettres.items()}
        rec.append(recouvrement_juge(groupes, tailles))
    par_reponse = {lt: (rec[0][lt] + rec[1][lt]) / 2 for lt in lettres}
    contenu = sum(par_reponse.values()) / len(par_reponse)
    score = POIDS["categorie"] * a.accord_categorie + POIDS["gravite"] * a.accord_gravite + POIDS["contenu"] * contenu
    return round(contenu, 3), round(score, 3)


async def juger(question: str, contexte: str | None, resultats: list[ResultatModele], a: Analyse,
                d: Domaine, modele_juge: str = MODELE_JUGE_PAR_DEFAUT,
                lecons: list[str] | None = None) -> ResultatJuge:
    valides = {r.modele: r.reponse for r in resultats if r.ok}
    rj = ResultatJuge(modele_juge=modele_juge, lettres=dict(zip(ascii_uppercase, valides)), lecons=lecons or [])
    if len(valides) < 2:
        rj.erreur = "moins de deux réponses valides : rien à juger"
        return rj
    # Sortie JSON native (json_schema) : certains fournisseurs refusent le mode « outil imposé » par défaut.
    agent = Agent(OpenAIChatModel(modele_juge, provider=OpenAIProvider(openai_client=_client())),
                  output_type=NativeOutput(VerdictJuge), instructions=instructions_avec_lecons(rj.lecons),
                  retries=2)
    debut = time.perf_counter()
    try:
        res = await agent.run(construire_prompt(question, contexte, valides, d))
        rj.verdict = res.output
    except Exception as e:
        rj.erreur = f"{type(e).__name__}: {e}"[:300]
    rj.duree_s = time.perf_counter() - debut
    if rj.ok and a.score_consensus is not None:
        rj.accord_contenu, rj.score = calculer_score(rj.verdict, valides, a, d)
        rj.niveau = niveau_confiance(rj.score)
    return rj
