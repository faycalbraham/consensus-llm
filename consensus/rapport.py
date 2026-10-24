"""Affichage console et sauvegarde JSON d'une exécution."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markup import escape as e
from rich.panel import Panel
from rich.table import Table

from .accord import Analyse
from .domaines import TECHNIQUE, Domaine
from .juge import ResultatJuge
from .llm import ResultatModele

# e() protège les crochets des logs et des modèles ([error], [gc]...), sinon Rich les efface.
COULEUR_NIVEAU = {"élevée": "green", "modérée": "yellow", "faible": "red", "indéterminée": "white"}


def afficher(console: Console, question: str, contexte: str | None,
             resultats: list[ResultatModele], a: Analyse, d: Domaine = TECHNIQUE) -> None:
    console.print(Panel(e(question), title="Question", border_style="cyan"))
    if contexte:
        console.print(Panel(e(contexte), title="Contexte envoyé aux modèles", border_style="cyan"))

    t = Table(title="Réponses des modèles", show_lines=False)
    t.add_column("Modèle", no_wrap=True)
    for col in (d.titre_categorie, "Gravité", "Confiance déclarée", "Durée", "Statut"):
        t.add_column(col)
    for r in resultats:
        if r.ok:
            rep = r.reponse
            t.add_row(r.modele, getattr(rep, d.champ_categorie).value, rep.gravite.value,
                      f"{rep.confiance:.0%}", f"{r.duree_s:.1f} s", "[green]JSON valide[/]")
        else:
            t.add_row(r.modele, "–", "–", "–", f"{r.duree_s:.1f} s", f"[red]échec[/] {e(r.erreur[:60])}")
    console.print(t)

    for r in resultats:
        if r.ok:
            console.print(f"[bold]{r.modele}[/] : {e(r.reponse.reponse)}")
    console.print()

    couleur = COULEUR_NIVEAU[a.niveau]
    if a.score_consensus is not None:
        entete = (f"[bold {couleur}]Confiance par consensus : {a.score_consensus:.0%} ({a.niveau})[/]\n"
                  f"  {d.titre_categorie.lower()} {a.accord_categorie:.0%} · gravité {a.accord_gravite:.0%} · "
                  f"contenu {a.accord_contenu:.0%}\n"
                  f"  [dim]confiance auto-déclarée moyenne : {a.confiance_declaree_moyenne:.0%} "
                  f"(non utilisée dans le score)[/]")
    else:
        entete = f"[bold {couleur}]Confiance par consensus : indéterminée[/]"

    lignes = [entete, ""]
    if a.diagnostic_retenu:
        modele, texte = a.diagnostic_retenu
        choix = a.categorie_majoritaire or "aucun choix majoritaire"
        lignes += [f"[bold]{d.titre_reponse}[/] ({d.titre_categorie.lower()} : {choix}, formulation de {modele}) :", f"  {e(texte)}", ""]

    def section(titre, elements):
        lignes.append(f"[bold]{titre}[/]")
        lignes.extend(elements or ["  [dim]aucune[/]"])
        lignes.append("")

    section(f"Convergences sur les {d.libelles_listes[0]}",
            [f"  ✔ {e(g.representant)} [dim]({', '.join(g.modeles)})[/]" for g in a.convergences])
    section(f"Convergences sur les {d.libelles_listes[1]}",
            [f"  → {e(g.representant)} [dim]({', '.join(g.modeles)})[/]" for g in a.actions_convergentes])
    section(f"Divergences sur les {d.libelles_listes[0]} (un seul modèle)",
            [f"  • {e(texte)} [dim]({m})[/]" for m, texte in a.divergences])
    section("Contradictions", [f"  ✘ {e(c)}" for c in a.contradictions])
    if a.alertes or a.modeles_en_echec:
        section("Alertes", [f"  ⚠ {x}" for x in a.alertes]
                + [f"  ⚠ {m} n'a pas fourni de réponse valide." for m in a.modeles_en_echec])

    console.print(Panel("\n".join(lignes).rstrip(), title="Synthèse", border_style=couleur))


def afficher_juge(console: Console, rj: ResultatJuge, a: Analyse, d: Domaine = TECHNIQUE) -> None:
    titre = f"Juge LLM ({rj.modele_juge})"
    if not rj.ok:
        console.print(Panel(f"[red]Le juge n'a pas rendu de verdict :[/] {e(rj.erreur or '')}",
                            title=titre, border_style="red"))
        return
    v = rj.verdict
    nom = lambda lettre: rj.lettres.get(lettre.strip().upper(), lettre)  # noqa: E731
    couleur = COULEUR_NIVEAU[rj.niveau]
    lignes = []
    if rj.score is not None:
        lignes += [f"[bold {couleur}]Confiance avec le juge : {rj.score:.0%} ({rj.niveau})[/]"
                   f"   [dim]score par mots : {a.score_consensus:.0%}[/]",
                   f"  contenu : {rj.accord_contenu:.0%} avec le juge, contre {a.accord_contenu:.0%} par mots "
                   f"[dim]({d.titre_categorie.lower()} et gravité inchangées)[/]", ""]
    fond = "[green]oui[/]" if v.accord_sur_le_fond else "[red]non[/]"
    lignes += [f"[bold]Accord sur le fond :[/] {fond} — {e(v.explication_fond)}", ""]

    def section(titre_s, elements):
        lignes.append(f"[bold]{titre_s}[/]")
        lignes.extend(elements or ["  [dim]aucune[/]"])
        lignes.append("")

    def partages(groupes):
        sortie = []
        for g in groupes:
            lettres = sorted({r.strip().upper()[:1] for r in g.elements})
            if len(lettres) >= 2:
                sortie.append(f"  ✔ {e(g.idee)} [dim]({', '.join(nom(x) for x in lettres)})[/]")
        return sortie

    section(f"Idées partagées : {d.libelles_listes[0]}", partages(v.groupes_liste_1))
    section(f"Idées partagées : {d.libelles_listes[1]}", partages(v.groupes_liste_2))
    section("Contradictions de contenu",
            [f"  ✘ {e(c.sujet)} : " + " ; ".join(f"{nom(p.reponse)} → {e(p.position)}" for p in c.positions)
             for c in v.contradictions])
    section("Erreurs par rapport au contexte",
            [f"  ⚠ {nom(x.reponse)} : « {e(x.citation)} » — {e(x.explication)}" for x in v.erreurs_contexte])
    lignes += ["[bold]Synthèse du juge[/]", f"  {e(v.synthese)}"]
    console.print(Panel("\n".join(lignes), title=titre, border_style="magenta"))


def sauvegarder(dossier: Path, question: str, contexte: str | None,
                resultats: list[ResultatModele], a: Analyse, d: Domaine = TECHNIQUE,
                rj: ResultatJuge | None = None, source: str | None = None,
                langfuse_trace_id: str | None = None) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"run-{datetime.now():%Y%m%d-%H%M%S}.json"
    donnees = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "source": source,  # trace d'origine quand on juge une exécution existante
        "langfuse_trace_id": langfuse_trace_id,  # pour rattacher plus tard les corrections humaines
        "domaine": d.nom,
        "question": question,
        "contexte": contexte,
        "reponses": [
            {"modele": r.modele, "ok": r.ok, "erreur": r.erreur, "duree_s": round(r.duree_s, 2),
             "tokens_entree": r.tokens_entree, "tokens_sortie": r.tokens_sortie,
             "reponse": r.reponse.model_dump(mode="json") if r.ok else None}
            for r in resultats
        ],
        "analyse": asdict(a),
    }
    if rj is not None:
        donnees["juge"] = {
            "modele": rj.modele_juge, "lettres": rj.lettres, "erreur": rj.erreur,
            "duree_s": round(rj.duree_s, 2), "accord_contenu": rj.accord_contenu,
            "score": rj.score, "niveau": rj.niveau,
            "verdict": rj.verdict.model_dump(mode="json") if rj.ok else None,
        }
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin
