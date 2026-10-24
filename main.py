"""Moteur de consensus multi-modèles : point d'entrée en ligne de commande.

Exemples :
  python main.py --exemple 1
  python main.py "Pourquoi mon service renvoie des 504 ?" --contexte logs.txt
  python main.py --demo            # sans clé ni appel réseau
  python main.py --domaine sante --exemple 1
  python main.py --exemple 2 --juge                        # ajoute le juge LLM
  python main.py --juger runs/run-20261024-123043.json     # juge une trace existante, sans rappeler les modèles
  python main.py --corriger runs/run-20261024-154417.json  # human-in-the-loop : corriger un résultat
  python main.py --bilan                                   # la confiance annoncée correspond-elle à des réponses justes ?
"""

import argparse
import asyncio
import json
import sys
from contextlib import nullcontext
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape as e
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from consensus import corrections, observabilite
from consensus.accord import analyser
from consensus.domaines import DOMAINES, TECHNIQUE
from consensus.juge import MODELE_JUGE_PAR_DEFAUT, juger
from consensus.llm import MODELES_PAR_DEFAUT, ResultatModele, interroger_modeles
from consensus.rapport import afficher, afficher_juge, sauvegarder
from consensus.schema import ReponseModele

RACINE = Path(__file__).parent
DONNEES_DEMO = RACINE / "consensus" / "demo_reponses.json"


def resultats_demo() -> list[ResultatModele]:
    """Réponses enregistrées pour l'exemple 1, validées par le même schéma que les vraies."""
    brut = json.loads(DONNEES_DEMO.read_text(encoding="utf-8"))
    return [ResultatModele(modele=m, reponse=ReponseModele.model_validate(r), duree_s=0.0)
            for m, r in brut.items()]


def charger_trace(chemin: Path):
    """Relit une trace runs/*.json : domaine, question, contexte et réponses revalidées par le schéma."""
    t = json.loads(chemin.read_text(encoding="utf-8"))
    domaine = DOMAINES[t.get("domaine") or "technique"]  # les premières traces n'avaient pas de domaine
    resultats = [
        ResultatModele(modele=r["modele"], erreur=r["erreur"], duree_s=r["duree_s"],
                       tokens_entree=r["tokens_entree"], tokens_sortie=r["tokens_sortie"],
                       reponse=domaine.schema.model_validate(r["reponse"]) if r["ok"] else None)
        for r in t["reponses"]
    ]
    return domaine, t["question"], t["contexte"], resultats


def corriger(console: Console, chemin: Path, fichier: Path) -> None:
    """Human-in-the-loop : l'humain relit une trace et enregistre sa correction."""
    trace = json.loads(chemin.read_text(encoding="utf-8"))
    domaine = DOMAINES[trace.get("domaine") or "technique"]
    a, juge = trace["analyse"], trace.get("juge") or {}
    choix = [x.value for x in domaine.schema.model_fields[domaine.champ_categorie].annotation]
    retenu = a.get("diagnostic_retenu") or ["", ""]

    console.print(Panel(
        f"[bold]Question :[/] {e(trace['question'])}\n\n"
        f"[bold]{domaine.titre_reponse}[/] ({retenu[0]}) :\n  {e(retenu[1])}\n\n"
        f"[bold]{domaine.titre_categorie} majoritaire :[/] {a.get('categorie_majoritaire')}   "
        f"[bold]Score :[/] {a['score_consensus']:.0%} ({a['niveau']})"
        + (f"   [bold]Avec le juge :[/] {juge['score']:.0%} ({juge['niveau']})" if juge.get("score") else ""),
        title=f"Correction de {chemin.name}", border_style="cyan"))

    justesse = Prompt.ask("La réponse retenue est-elle juste ?", choices=["juste", "partielle", "fausse"])
    bon_choix = Prompt.ask(f"Bonne valeur pour « {domaine.titre_categorie.lower()} » ?", choices=choix,
                           default=a.get("categorie_majoritaire") or choix[0])
    erreurs = ((juge.get("verdict") or {}).get("erreurs_contexte")) or []
    a_tort = []
    if erreurs:
        for i, x in enumerate(erreurs, 1):
            console.print(f"  {i}. {e(x['citation'])} — {e(x['explication'])}")
        nums = Prompt.ask("Numéros des erreurs signalées À TORT par le juge (ex. 1,2 ; Entrée = aucune)", default="")
        a_tort = [erreurs[int(n) - 1]["citation"] for n in nums.replace(" ", "").split(",")
                  if n.isdigit() and 1 <= int(n) <= len(erreurs)]
    manque = Prompt.ask("Contradiction ou erreur que le moteur n'a pas vue (Entrée = aucune)", default="")
    commentaire = Prompt.ask("Commentaire (Entrée = aucun)", default="")

    c = corrections.depuis_trace(trace, str(chemin), justesse, bon_choix, a_tort, manque or None, commentaire or None)
    corrections.ajouter(fichier, c)
    console.print(f"[green]Correction enregistrée dans {fichier}[/]")
    if observabilite.envoyer_correction(trace.get("langfuse_trace_id"), c):
        observabilite.terminer()
        console.print("[green]Correction envoyée aussi à Langfuse, sur la trace d'origine.[/]")


def afficher_bilan(console: Console, fichier: Path) -> None:
    liste = corrections.lire(fichier)
    if not liste:
        console.print(f"Aucune correction dans {fichier}. Utilisez --corriger TRACE.")
        return
    couleur = {"juste": "green", "partielle": "yellow", "fausse": "red"}
    niveau = lambda s, nv: f"{s:.0%} {nv}" if s is not None else "–"  # noqa: E731

    t = Table(title="Corrections humaines : la confiance annoncée était-elle justifiée ?")
    for col in ("N°", "Question", "Par mots", "Avec le juge", "Verdict humain", "Bonne case ?"):
        t.add_column(col)
    for i, c in enumerate(liste, 1):
        question = c.question if len(c.question) <= 45 else c.question[:44] + "…"
        t.add_row(str(i), e(question), niveau(c.score, c.niveau), niveau(c.score_juge, c.niveau_juge),
                  f"[{couleur[c.justesse]}]{c.justesse}[/]",
                  "oui" if c.choix_moteur == c.bon_choix else f"non ({c.bon_choix})")
    console.print(t)

    # Résumé en phrases : pour chaque score, part de réponses justes à chaque niveau annoncé.
    b = corrections.bilan(liste)
    for cle, nom in (("par_niveau", "Par mots"), ("par_niveau_juge", "Avec le juge")):
        if b[cle]:
            morceaux = [f"confiance {nv} → juste {c.get('juste', 0)} fois sur {sum(c.values())}"
                        for nv, c in b[cle].items()]
            console.print(f"[bold]{nom}[/] : " + " ; ".join(morceaux) + ".")
    ok, n = b["case_principale_correcte"]
    console.print(f"Case principale correcte {ok} fois sur {n}. "
                  f"Erreurs signalées à tort par le juge : {b['erreurs_juge_a_tort']}. "
                  f"Manques signalés par les humains : {b['manques_signales']}.")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # accents et symboles sous Windows
    sys.stderr.reconfigure(encoding="utf-8")
    load_dotenv(RACINE / ".env")

    p = argparse.ArgumentParser(description="Interroge plusieurs LLM et mesure leur consensus.")
    p.add_argument("question", nargs="?", help="Question à poser (sinon utiliser --exemple).")
    p.add_argument("--contexte", type=Path, help="Fichier texte d'éléments (logs, métriques...).")
    p.add_argument("--domaine", choices=DOMAINES, default="technique",
                   help="technique (incidents, par défaut) ou sante (conseils sans médicament).")
    p.add_argument("--exemple", type=int, help="Numéro d'un exemple du domaine choisi.")
    p.add_argument("--modeles", nargs="+", default=MODELES_PAR_DEFAUT, help="Identifiants OpenRouter.")
    p.add_argument("--demo", action="store_true", help="Réponses enregistrées, sans appel réseau.")
    p.add_argument("--juge", action="store_true", help="Ajoute le juge LLM après les réponses des modèles.")
    p.add_argument("--juger", type=Path, metavar="TRACE",
                   help="Juge une trace existante (runs/*.json) sans rappeler les modèles.")
    p.add_argument("--modele-juge", default=MODELE_JUGE_PAR_DEFAUT, help="Modèle OpenRouter du juge.")
    p.add_argument("--corriger", type=Path, metavar="TRACE",
                   help="Human-in-the-loop : corriger le résultat d'une trace existante.")
    p.add_argument("--bilan", action="store_true", help="Bilan des corrections humaines enregistrées.")
    p.add_argument("--corrections", type=Path, default=RACINE / "corrections.jsonl",
                   help="Fichier des corrections humaines.")
    p.add_argument("--sortie", type=Path, default=RACINE / "runs", help="Dossier des traces JSON.")
    args = p.parse_args()

    console = Console()
    if args.corriger:
        return corriger(console, args.corriger, args.corrections)
    if args.bilan:
        return afficher_bilan(console, args.corrections)
    domaine = DOMAINES[args.domaine]
    avec_juge = args.juge or args.juger is not None

    resultats = None  # None = il faut interroger les modèles
    if args.juger:
        domaine, question, contexte, resultats = charger_trace(args.juger)
    elif args.demo:
        if domaine is not TECHNIQUE:
            p.error("--demo n'existe que pour le domaine technique")
        ex = TECHNIQUE.exemples[0]
        question, contexte = ex["question"], ex["contexte"]
        resultats = resultats_demo()
    elif args.exemple:
        if not 1 <= args.exemple <= len(domaine.exemples):
            p.error(f"exemples du domaine {domaine.nom} : "
                    + " ; ".join(f"{i} = {e['titre']}" for i, e in enumerate(domaine.exemples, 1)))
        ex = domaine.exemples[args.exemple - 1]
        question, contexte = ex["question"], ex["contexte"]
    elif args.question:
        question = args.question
        contexte = args.contexte.read_text(encoding="utf-8") if args.contexte else None
    else:
        p.error("donnez une question, --exemple N, --demo ou --juger TRACE")

    # Une trace Langfuse par exécution (si les clés sont dans .env ; jamais en mode démo).
    nom_trace = "jugement" if args.juger else "consensus"
    details = {"modeles": ", ".join(args.modeles), "juge": args.modele_juge if avec_juge else "aucun",
               "source": str(args.juger) if args.juger else ""}
    trace = (observabilite.execution(nom_trace, question, contexte, domaine.nom, details)
             if not args.demo else nullcontext())
    with trace as span:
        if resultats is None:
            with console.status(f"Interrogation de {len(args.modeles)} modèles via OpenRouter..."):
                resultats = asyncio.run(interroger_modeles(question, contexte, args.modeles, domaine))

        analyse = analyser(resultats, domaine)
        afficher(console, question, contexte, resultats, analyse, domaine)

        rj = None
        if avec_juge:
            with console.status(f"Le juge {args.modele_juge} relit les réponses..."):
                rj = asyncio.run(juger(question, contexte, resultats, analyse, domaine, args.modele_juge))
            afficher_juge(console, rj, analyse, domaine)

        tid = observabilite.trace_id() if span is not None else None
        observabilite.envoyer_resultats(span, tid, analyse, rj)

    source = str(args.juger) if args.juger else None
    chemin = sauvegarder(args.sortie, question, contexte, resultats, analyse, domaine, rj, source, tid)
    console.print(f"[dim]Trace complète : {chemin}[/]")
    if tid:
        console.print(f"[dim]Trace Langfuse : {tid}[/]")
    observabilite.terminer()


if __name__ == "__main__":
    main()
