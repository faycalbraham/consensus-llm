from consensus.accord import analyser, mots, regrouper, similarite
from consensus.llm import ResultatModele
from consensus.schema import ReponseModele


def rep(cat="reseau", grav="elevee", points=None, actions=None, conf=0.9):
    return ReponseModele(
        reponse="diag", categorie_cause=cat, gravite=grav, raisonnement="r",
        points_cles=points or ["Le pare-feu bloque le port 443", "La route par défaut a changé"],
        actions_recommandees=actions or ["Vérifier les règles du pare-feu"],
        hypotheses=[], confiance=conf,
    )


def res(nom, r):
    return ResultatModele(modele=nom, reponse=r)


def test_normalisation_ignore_accents_et_mots_vides():
    assert mots("Les requêtes échouées") == mots("requetes echouees")


def test_similarite_paraphrase_vs_sujet_different():
    assert similarite("Le pare-feu bloque le port 443", "port 443 bloqué par le pare-feu") > 0.5
    assert similarite("Le pare-feu bloque le port 443", "Fuite mémoire dans le worker") == 0


def test_regrouper_un_point_par_modele_et_par_groupe():
    groupes = regrouper({"a": ["port 443 bloqué", "port 443 fermé"], "b": ["port 443 bloqué"]})
    assert all(len(set(g.modeles)) == len(g.modeles) for g in groupes)
    assert any(len(g.modeles) == 2 for g in groupes)


def test_unanimite_donne_confiance_elevee():
    a = analyser([res("a", rep()), res("b", rep()), res("c", rep())])
    assert a.score_consensus == 1.0 and a.niveau == "élevée"
    assert not a.contradictions and len(a.convergences) == 2


def test_desaccord_total_donne_confiance_faible_et_contradiction():
    a = analyser([
        res("a", rep("reseau", "faible", ["Le pare-feu bloque le port 443", "DNS mal résolu"], ["Ouvrir le port"])),
        res("b", rep("base_de_donnees", "critique", ["Index manquant sur commandes", "Verrous en attente"], ["Ajouter un index"])),
        res("c", rep("code_applicatif", "moyenne", ["Boucle infinie dans le parseur", "Exception non gérée"], ["Corriger le parseur"])),
    ])
    assert a.accord_categorie == 0 and a.categorie_majoritaire is None
    assert a.niveau == "faible"
    assert any("Aucun accord sur la cause racine" in c for c in a.contradictions)
    assert any("Gravité très divergente" in c for c in a.contradictions)


def test_score_ignore_la_confiance_auto_declaree_et_alerte():
    base = [res("a", rep("reseau", conf=0.1)), res("b", rep("securite", "faible", ["Clé expirée", "Certificat invalide"], ["Renouveler"], conf=0.1))]
    sur = [res("a", rep("reseau", conf=1.0)), res("b", rep("securite", "faible", ["Clé expirée", "Certificat invalide"], ["Renouveler"], conf=1.0))]
    a1, a2 = analyser(base), analyser(sur)
    assert a1.score_consensus == a2.score_consensus
    assert a2.alertes and not a1.alertes


def test_modele_en_echec_exclu_du_calcul():
    a = analyser([res("a", rep()), res("b", rep()), ResultatModele(modele="c", erreur="timeout")])
    assert a.score_consensus == 1.0 and "c" in a.modeles_en_echec


def test_une_seule_reponse_pas_de_consensus():
    a = analyser([res("a", rep()), ResultatModele(modele="b", erreur="x")])
    assert a.score_consensus is None and a.niveau == "indéterminée"


def test_domaine_sante_utilise_ses_propres_champs():
    from consensus.domaines import SANTE
    from consensus.schema import ReponseSante

    def sante(consulter):
        return ReponseSante(
            reponse="r", consulter_medecin=consulter, gravite="faible", raisonnement="r",
            recommandations=["Boire beaucoup d'eau chaude", "Bouillon de légumes salé"],
            a_eviter=["Miel en grande quantité à cause de la glycémie"],
            signaux_alerte=["Fièvre au-delà de trois jours"], hypotheses=[], confiance=0.8,
        )

    a = analyser([res("a", sante("si_persistance")), res("b", sante("si_persistance")),
                  res("c", sante("rapidement"))], SANTE)
    assert a.categorie_majoritaire == "si_persistance" and a.accord_categorie == 0.5
    assert a.accord_contenu == 1.0
    assert any("le besoin de consulter" in c for c in a.contradictions)
