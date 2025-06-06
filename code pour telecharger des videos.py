# main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from typing import Optional
import yt_dlp
import uuid
import os
import logging
from datetime import datetime, timedelta
import asyncio
import re
import urllib.parse

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_downloader.log'),
        logging.StreamHandler()
    ]
)

app = FastAPI(title="Video Downloader API")

# Configuration CORS plus permissive
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Autorise toutes les origines en développement
    allow_credentials=True,
    allow_methods=["*"],  # Autorise toutes les méthodes
    allow_headers=["*"],  # Autorise tous les en-têtes
    expose_headers=["*"],  # Expose tous les en-têtes
    max_age=3600,  # Cache la pré-vérification pendant 1 heure
)

# Configuration des templates et fichiers statiques
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Constants
DOWNLOAD_DIR = "./downloads"
MAX_FILE_AGE_MINUTES = 30  # Fichiers supprimés après 30 minutes
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Liste des domaines bloqués
BLOCKED_DOMAINS = [
    "netflix.com",
    "primevideo.com",
    "amazon.com",
    "disneyplus.com",
    "hulu.com",
    "hbomax.com",
    "peacocktv.com",
    "paramountplus.com",
    "crunchyroll.com",
    "funimation.com",
    "deezer.com",
    "spotify.com",
    "tidal.com",
    "apple.com",
    "play.google.com"
]

class DownloadRequest(BaseModel):
    url: HttpUrl
    format: str = "mp4"

    @property
    def sanitized_format(self):
        return re.sub(r'[^a-zA-Z0-9]', '', self.format)

    def is_blocked_url(self):
        parsed_url = urllib.parse.urlparse(str(self.url))
        domain = parsed_url.netloc.lower()
        return any(blocked in domain for blocked in BLOCKED_DOMAINS)

class DownloadResponse(BaseModel):
    filename: str
    format: str
    title: Optional[str]
    duration: Optional[float]
    thumbnail: Optional[str]

class FormatInfo(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str]
    filesize: Optional[float]
    format_note: Optional[str]
    vcodec: Optional[str]
    acodec: Optional[str]

class VideoInfo(BaseModel):
    title: str
    formats: list[FormatInfo]
    thumbnail: Optional[str]
    duration: Optional[float]

async def cleanup_old_files():
    """Supprime les fichiers plus vieux que MAX_FILE_AGE_MINUTES"""
    while True:
        try:
            current_time = datetime.now()
            for filename in os.listdir(DOWNLOAD_DIR):
                file_path = os.path.join(DOWNLOAD_DIR, filename)
                file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                if current_time - file_modified > timedelta(minutes=MAX_FILE_AGE_MINUTES):
                    os.remove(file_path)
                    logging.info(f"Fichier supprimé: {filename}")
        except Exception as e:
            logging.error(f"Erreur lors du nettoyage: {str(e)}")
        await asyncio.sleep(300)  # Vérifie toutes les 5 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_files())

def get_best_format(ydl, url, requested_format):
    """
    Détermine le meilleur format disponible pour la vidéo.
    """
    try:
        # Extraction des informations sans téléchargement
        info = ydl.extract_info(url, download=False)
        
        if requested_format.lower() == "mp3":
            # Pour MP3, on cherche le meilleur format audio
            return 'bestaudio/best'
        
        # Pour les vidéos, on cherche le meilleur format compatible
        available_formats = info.get('formats', [])
        
        # Filtrer les formats vidéo
        video_formats = [f for f in available_formats if f.get('vcodec') != 'none']
        
        if not video_formats:
            return 'best'  # Si aucun format vidéo n'est trouvé
            
        # Trier par qualité (résolution)
        video_formats.sort(key=lambda f: (
            f.get('height', 0) if f.get('height') else 0,
            f.get('tbr', 0) if f.get('tbr') else 0
        ), reverse=True)
        
        # Sélectionner le meilleur format disponible
        best_format = video_formats[0]
        format_id = best_format.get('format_id', 'best')
        
        return f"{format_id}+bestaudio/best"
        
    except Exception as e:
        logging.error(f"Erreur lors de la vérification des formats: {str(e)}")
        return 'best'  # Format par défaut en cas d'erreur

@app.post("/download", response_model=DownloadResponse)
async def download_video(data: DownloadRequest):
    if data.is_blocked_url():
        raise HTTPException(
            status_code=403,
            detail="Cette source est protégée par des droits d'auteur et ne peut pas être téléchargée"
        )

    try:
        # Configuration pour le téléchargement
        ydl_opts = {
            'format': data.format,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s-%(format_id)s.%(ext)s'),
            'quiet': True,
            'noplaylist': True,
            'writethumbnail': True,
        }

        # Si c'est un format audio uniquement
        if data.format == 'bestaudio':
            ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'format': 'bestaudio/best',
            })

        logging.info(f"Début du téléchargement: {data.url} (format: {data.format})")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(data.url), download=True)
            filename = ydl.prepare_filename(info)
            
            # Nettoyer le nom de fichier des caractères spéciaux
            clean_filename = os.path.basename(filename)
            clean_filename = "".join(c for c in clean_filename if c.isalnum() or c in ('-', '_', '.'))
            
            # Si c'est un format audio, s'assurer que l'extension est .mp3
            if data.format == 'bestaudio' and not clean_filename.endswith('.mp3'):
                clean_filename = os.path.splitext(clean_filename)[0] + '.mp3'
            
            # Renommer le fichier si nécessaire
            if os.path.basename(filename) != clean_filename:
                new_path = os.path.join(DOWNLOAD_DIR, clean_filename)
                os.rename(filename, new_path)
                filename = new_path
        
        response_data = DownloadResponse(
            filename=os.path.basename(filename),
            format=data.format,
            title=info.get('title'),
            duration=info.get('duration'),
            thumbnail=info.get('thumbnail')
        )
        
        logging.info(f"Téléchargement réussi: {response_data.filename}")
        return response_data
    
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Erreur de téléchargement: {error_msg}")
        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors du téléchargement: {error_msg}"
        )

@app.get("/file/{filename}")
def get_file(filename: str):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    return FileResponse(
        file_path,
        media_type='application/octet-stream',
        filename=filename
    )

@app.get("/health")
def health_check():
    return {"status": "ok"}

def filter_best_formats(formats):
    """
    Sélectionne les formats vidéo selon la qualité :
    - La plus haute qualité disponible
    - 3 qualités moyennes
    - Une qualité plus basse
    - La meilleure qualité audio
    """
    video_formats = []
    audio_formats = []
    
    # Séparer les formats vidéo et audio
    for f in formats:
        try:
            if f.get('vcodec', 'none') != 'none' and f.get('acodec', 'none') != 'none':
                height = int(f.get('height', 0) or 0)
                fps = float(f.get('fps', 0) or 0)
                filesize = float(f.get('filesize', 0) or 0)
                # Score basé sur la résolution, FPS et taille
                score = height + (fps / 30)
                if height > 0:  # Ignorer les formats sans résolution
                    video_formats.append((score, height, filesize, f))
            elif f.get('vcodec', 'none') == 'none' and f.get('acodec', 'none') != 'none':
                # Format audio uniquement
                abr = float(f.get('abr', 0) or 0)
                if abr > 0:  # Ignorer les formats sans bitrate
                    audio_formats.append((abr, f))
        except (TypeError, ValueError):
            continue

    selected_formats = []

    # Sélection des formats vidéo
    if video_formats:
        # Trier par score décroissant
        video_formats.sort(key=lambda x: x[0], reverse=True)
        
        # 1. La plus haute qualité
        selected_formats.append(video_formats[0][3])
        
        # 2. Trois qualités moyennes
        if len(video_formats) > 4:
            middle_range = video_formats[1:-1]  # Exclure le plus haut et le plus bas
            step = len(middle_range) // 3
            if step > 0:
                for i in range(3):
                    idx = min(i * step, len(middle_range) - 1)
                    if middle_range[idx][3] not in selected_formats:
                        selected_formats.append(middle_range[idx][3])
        
        # 3. Une qualité basse (mais pas la plus basse)
        if len(video_formats) > 2:
            low_quality_idx = max(len(video_formats) // 4, 1)
            if video_formats[-low_quality_idx][3] not in selected_formats:
                selected_formats.append(video_formats[-low_quality_idx][3])

    # Ajouter le meilleur format audio
    if audio_formats:
        # Trier par bitrate décroissant
        audio_formats.sort(key=lambda x: x[0], reverse=True)
        best_audio = audio_formats[0][1]
        selected_formats.append(best_audio)

    return selected_formats

@app.get("/formats")
async def get_formats(url: str):
    """Récupère les formats disponibles pour une URL donnée."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extraction des informations sans téléchargement
            info = ydl.extract_info(url, download=False)
            
            # Filtrer pour obtenir les meilleurs formats
            best_formats = filter_best_formats(info.get('formats', []))
            
            # Convertir en FormatInfo
            formats = []
            for f in best_formats:
                try:
                    format_note = []
                    
                    # Construire une description claire et simple
                    if f.get('vcodec', 'none') != 'none':
                        height = int(f.get('height', 0) or 0)
                        if height > 0:
                            format_note.append(f"{height}p")
                        
                        fps = float(f.get('fps', 0) or 0)
                        if fps > 30:
                            format_note.append(f"{int(fps)}fps")
                    
                    if f.get('acodec', 'none') != 'none':
                        if f.get('vcodec', 'none') == 'none':
                            format_note.append("Audio")
                        abr = float(f.get('abr', 0) or 0)
                        if abr > 0:
                            format_note.append(f"{int(abr)}kbps")
                    
                    filesize = float(f.get('filesize', 0) or 0)
                    if filesize > 0:
                        size_mb = filesize / (1024 * 1024)
                        if size_mb >= 1024:
                            format_note.append(f"{size_mb/1024:.1f}GB")
                        else:
                            format_note.append(f"{size_mb:.1f}MB")
                    
                    formats.append(FormatInfo(
                        format_id=f.get('format_id', ''),
                        ext=f.get('ext', ''),
                        resolution=f"{int(f.get('height', 0) or 0)}p" if f.get('height') else None,
                        filesize=filesize,
                        format_note=' - '.join(format_note) if format_note else "Format inconnu",
                        vcodec=f.get('vcodec'),
                        acodec=f.get('acodec')
                    ))
                except (TypeError, ValueError):
                    # Ignorer les formats avec des valeurs invalides
                    continue

            if not formats:
                raise HTTPException(
                    status_code=400,
                    detail="Aucun format valide n'a été trouvé pour cette URL"
                )

            return VideoInfo(
                title=info.get('title', ''),
                formats=formats,
                thumbnail=info.get('thumbnail'),
                duration=info.get('duration')
            )

    except Exception as e:
        logging.error(f"Erreur lors de la récupération des formats: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors de la récupération des formats: {str(e)}"
        )

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Video Downloader</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .input-group {
                margin-bottom: 20px;
            }
            input[type="url"] {
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            button {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                cursor: pointer;
                width: 100%;
            }
            button:hover {
                background-color: #0056b3;
            }
            #result {
                margin-top: 20px;
                padding: 10px;
                border-radius: 4px;
            }
            .success {
                background-color: #d4edda;
                color: #155724;
            }
            .error {
                background-color: #f8d7da;
                color: #721c24;
            }
            #formats {
                margin-top: 10px;
            }
            .format-option {
                margin: 5px 0;
                padding: 10px;
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                cursor: pointer;
            }
            .format-option:hover {
                background-color: #e9ecef;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Video Downloader</h1>
            <div class="input-group">
                <input type="url" id="videoUrl" placeholder="Entrez l'URL de la vidéo" required>
                <button onclick="checkFormats()">Vérifier les formats disponibles</button>
            </div>
            <div id="formats"></div>
            <div id="result"></div>
        </div>

        <script>
            async function checkFormats() {
                const url = document.getElementById('videoUrl').value;
                const resultDiv = document.getElementById('result');
                const formatsDiv = document.getElementById('formats');
                
                if (!url) {
                    resultDiv.className = 'error';
                    resultDiv.textContent = 'Veuillez entrer une URL valide';
                    return;
                }

                try {
                    resultDiv.textContent = 'Recherche des formats disponibles...';
                    const response = await fetch(`/formats?url=${encodeURIComponent(url)}`);
                    const data = await response.json();
                    
                    if (!response.ok) {
                        throw new Error(data.detail || 'Erreur lors de la récupération des formats');
                    }

                    formatsDiv.innerHTML = '<h3>Formats disponibles:</h3>';
                    data.formats.forEach(format => {
                        const formatDiv = document.createElement('div');
                        formatDiv.className = 'format-option';
                        formatDiv.onclick = () => downloadVideo(url, format.format_id);
                        formatDiv.textContent = `${format.format_note || format.resolution || 'Format inconnu'}`;
                        formatsDiv.appendChild(formatDiv);
                    });

                    resultDiv.className = 'success';
                    resultDiv.textContent = 'Cliquez sur un format pour démarrer le téléchargement';
                } catch (error) {
                    resultDiv.className = 'error';
                    resultDiv.textContent = error.message;
                }
            }

            async function downloadVideo(url, format) {
                const resultDiv = document.getElementById('result');
                try {
                    resultDiv.textContent = 'Téléchargement en cours...';
                    const response = await fetch('/download', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            url: url,
                            format: format
                        })
                    });

                    const data = await response.json();
                    
                    if (!response.ok) {
                        throw new Error(data.detail || 'Erreur lors du téléchargement');
                    }

                    const downloadLink = document.createElement('a');
                    downloadLink.href = `/file/${data.filename}`;
                    downloadLink.download = data.filename;
                    downloadLink.click();

                    resultDiv.className = 'success';
                    resultDiv.textContent = 'Téléchargement démarré !';
                } catch (error) {
                    resultDiv.className = 'error';
                    resultDiv.textContent = error.message;
                }
            }
        </script>
    </body>
    </html>
    """
