# Video Downloader API

Une API FastAPI pour télécharger des vidéos avec différentes options de qualité.

## Fonctionnalités

- Téléchargement de vidéos en différentes qualités
- Option de téléchargement audio uniquement (MP3)
- Suppression automatique des fichiers après 30 minutes
- Protection contre le téléchargement de contenu protégé
- Interface web simple et intuitive

## Installation locale

1. Cloner le repository :
```bash
git clone <votre-repo>
cd <votre-repo>
```

2. Installer les dépendances :
```bash
pip install -r requirements.txt
```

3. Lancer le serveur :
```bash
uvicorn "code pour telecharger des videos:app" --reload
```

## Déploiement sur Render

1. Créer un compte sur [Render.com](https://render.com)
2. Connecter votre repository GitHub
3. Créer un nouveau Web Service
4. Sélectionner votre repository
5. Les configurations sont déjà définies dans `render.yaml`

## Variables d'environnement

- `PORT` : Port du serveur (défini automatiquement par Render)

## Utilisation

L'API sera accessible à l'adresse :
- Locale : `http://localhost:8000`
- Production : `https://<votre-app>.onrender.com`

## Sécurité

- Les fichiers sont automatiquement supprimés après 30 minutes
- Les domaines protégés sont bloqués
- Pas de stockage permanent des fichiers

## Licence

MIT 