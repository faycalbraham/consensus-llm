"""Paramètres propres au domaine : diagnostic technique d'incidents."""

INSTRUCTIONS = """\
Tu es un ingénieur SRE senior chargé de diagnostiquer des incidents techniques
(applications web, infrastructure, réseau, bases de données).
À partir de la question et des éléments fournis (logs, métriques, contexte) :
- identifie la cause racine la plus probable et sa catégorie ;
- évalue la gravité pour le service ;
- appuie-toi uniquement sur les éléments fournis ; ce que tu supposes va dans `hypotheses` ;
- propose des actions concrètes et vérifiables, par ordre de priorité.
Réponds en français. Sois factuel et concis.
"""

EXEMPLES = [
    {
        "titre": "502 intermittentes derrière Nginx",
        "question": (
            "Depuis le déploiement d'hier soir, environ 5 % des requêtes renvoient une erreur 502 "
            "derrière Nginx, surtout aux heures de pointe. Quelle est la cause probable et que faire ?"
        ),
        "contexte": (
            "nginx error.log :\n"
            "  upstream prematurely closed connection while reading response header from upstream\n"
            "  connect() failed (111: Connection refused) while connecting to upstream\n"
            "Application : Python/Gunicorn, 4 workers sync, timeout 30 s, 2 conteneurs de 512 Mo.\n"
            "Le déploiement a ajouté un export PDF généré de façon synchrone.\n"
            "dmesg sur un hôte : 'Out of memory: Killed process 2841 (gunicorn)'."
        ),
    },
    {
        "titre": "Base PostgreSQL lente le lundi matin",
        "question": (
            "Chaque lundi entre 8 h et 10 h, les temps de réponse de l'API passent de 120 ms à 4 s. "
            "Le reste de la semaine tout va bien. Que se passe-t-il ?"
        ),
        "contexte": (
            "API REST de l'application de commandes (Python/FastAPI), qui lit et écrit dans PostgreSQL.\n"
            "PostgreSQL 15, une instance de 4 vCPU.\n"
            "pg_stat_activity : nombreuses sessions 'idle in transaction', ~95 connexions sur max_connections=100.\n"
            "Un job de rapport hebdomadaire est planifié le lundi à 7 h 45.\n"
            "Pas de pgbouncer. CPU à 90 % pendant la plage concernée."
        ),
    },
    {
        "titre": "Certificats et appels sortants",
        "question": (
            "Depuis ce matin, tous les appels de notre service vers l'API de paiement échouent. "
            "Les autres appels sortants fonctionnent. Diagnostic ?"
        ),
        "contexte": (
            "Erreur côté client Java : javax.net.ssl.SSLHandshakeException: PKIX path building failed.\n"
            "Le prestataire de paiement a annoncé une rotation de certificat la semaine dernière.\n"
            "Notre image Docker de base n'a pas été reconstruite depuis 14 mois."
        ),
    },
]
