# Poker Jetons ♠♥♣♦

Des jetons virtuels pour jouer au poker avec de vraies cartes. Chaque joueur mise depuis son téléphone.

## Lancer

Seul Python 3 est nécessaire (il est déjà installé sur macOS) :

```bash
python3 server.py
```

Le terminal affiche deux adresses :
- `http://localhost:8000` : à ouvrir sur l'ordinateur
- `http://192.168.x.x:8000` : l'adresse que les téléphones utilisent (ils doivent être sur **le même Wi-Fi**)

## Jouer

1. Crée une partie (pseudo, jetons de départ, blindes). Tu deviens l'**organisateur**.
2. Partage le lien ou le QR code affiché : chaque joueur choisit un pseudo et s'assoit.
3. L'organisateur appuie sur **Nouvelle main** : le donneur tourne et les blindes sont prélevées automatiquement.
4. Chacun joue depuis son téléphone : se coucher, checker, suivre, miser ou relancer (avec les jetons +10, +20…), ou faire tapis.
5. L'organisateur appuie sur **Carte suivante** (flop, turn, river), puis sur **Désigner le gagnant**. Le pot va au gagnant, ou il est partagé si plusieurs joueurs sont cochés.

L'organisateur peut aussi ajuster le tapis d'un joueur (recave), retirer un joueur, changer les blindes ou annuler une main.

## Limites
- Les parties sont gardées en mémoire : si tu arrêtes le serveur, elles sont perdues.
- Les pots secondaires (side pots) ne sont pas calculés automatiquement. En cas de tapis inégaux, ajuste les tapis à la main.

## Mettre en ligne sur Render (gratuit)

1. Sur github.com, crée un dépôt (ex. `poker-jetons`), puis choisis « uploading an existing file » et glisse-y **tout le contenu** de ce dossier, y compris le dossier `static`. Valide avec « Commit changes ».
2. Sur render.com, connecte-toi avec ton compte GitHub, puis choisis **New → Web Service** et sélectionne le dépôt.
3. Réglages : Language **Python 3**, Build Command `echo ok`, Start Command `python3 server.py`, Instance Type **Free**. Clique sur **Deploy**.
4. Au bout de 1 à 2 minutes, ton site est en ligne à une adresse du type `https://poker-jetons-xxxx.onrender.com`.

Bon à savoir avec l'offre gratuite : après 15 minutes sans joueur, le site se met en veille. La première visite suivante prend alors environ 1 minute, et les parties en cours sont effacées.
