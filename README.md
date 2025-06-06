# Video Downloader

Une application web pour télécharger des vidéos avec différentes options de qualité. Développée avec FastAPI pour le backend et React pour le frontend.

## Fonctionnalités

- Téléchargement de vidéos en plusieurs qualités (HD, moyenne, basse)
- Conversion audio en MP3
- Détection automatique des formats disponibles
- Interface utilisateur moderne et réactive
- Suppression automatique des fichiers après 30 minutes
- Protection contre le téléchargement de contenu protégé par copyright
- Gestion des erreurs et retours utilisateur

## Prérequis

- Python 3.8 ou supérieur
- Node.js 14 ou supérieur
- pip (gestionnaire de paquets Python)
- npm (gestionnaire de paquets Node.js)

## Installation locale

1. Cloner le repository :
```bash
git clone https://github.com/jospinherve/Videodownloader.git
cd Videodownloader
```

2. Installer les dépendances Python :
```bash
pip install -r requirements.txt
```

3. Lancer le serveur backend :
```bash
uvicorn "code pour telecharger des videos:app" --reload
```

Le backend sera accessible à l'adresse : `http://localhost:8000`

## API Endpoints

- `POST /download` : Télécharger une vidéo
- `GET /formats` : Obtenir les formats disponibles pour une URL
- `GET /file/{filename}` : Récupérer un fichier téléchargé
- `GET /health` : Vérifier l'état du serveur

## Sécurité

- Suppression automatique des fichiers après 30 minutes
- Blocage des domaines protégés par copyright (Netflix, Amazon Prime, etc.)
- Validation des URLs entrantes
- Gestion sécurisée des fichiers temporaires

## Déploiement

L'application est configurée pour être déployée sur Render.com. Les fichiers de configuration nécessaires sont inclus dans le repository.

1. Connectez votre compte GitHub à Render.com
2. Créez un nouveau Web Service
3. Sélectionnez ce repository
4. Les configurations de déploiement sont automatiquement détectées via `render.yaml`

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.

## Licence

MIT 