# main.py  uvicorn "code pour telecharger des videos:app" --reload
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import yt_dlp
import uuid
import os
import logging
from datetime import datetime, timedelta
import asyncio
import re
import urllib.parse
import subprocess
import shutil

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
TEMP_DIR = "./temp"
STATIC_DIR = "./static"
TEMPLATES_DIR = "./templates"
MAX_FILE_AGE_MINUTES = 30  # Fichiers supprimés après 30 minutes

def init_directories():
    """Initialise les dossiers nécessaires pour l'application"""
    directories = [DOWNLOAD_DIR, TEMP_DIR, STATIC_DIR, TEMPLATES_DIR]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logging.info(f"Dossier créé/vérifié : {directory}")

init_directories()

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

class CutRequest(BaseModel):
    filename: str
    start_time: str
    end_time: str

class DivideRequest(BaseModel):
    filename: str
    segments: int

class CommentRequest(BaseModel):
    filename: str
    text: str
    time: str
    duration: int

class ExportRequest(BaseModel):
    filename: str
    format: str

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
        # Configuration avancée pour yt-dlp
        ydl.params.update({
            'nocheckcertificate': True,
            'no_warnings': False,
            'extract_flat': False,
            'youtube_include_dash_manifest': True,
            'format': 'best',
        })
        
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
        # Configuration mise à jour pour le téléchargement
        ydl_opts = {
            'format': data.format,
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s-%(format_id)s.%(ext)s'),
            'quiet': True,
            'noplaylist': True,
            'writethumbnail': True,
            'nocheckcertificate': True,
            'no_check_certificate': True,
            'prefer_insecure': True
        }

        # Si c'est un format audio uniquement
        if data.format.lower() in ['bestaudio', 'mp3']:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'extractaudio': True,
                'audioformat': 'mp3',
                'audioquality': '0',  # Meilleure qualité
                'final_ext': 'mp3',  # Force l'extension finale en mp3
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
        # Configuration mise à jour pour yt-dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': False,  # Activer les avertissements pour le débogage
            'extract_flat': False,
            'format': 'best',
            'nocheckcertificate': True,
            'no_check_certificate': True,
            'prefer_insecure': True,
            'ignoreerrors': True,  # Ignorer les erreurs non critiques
            'youtube_include_dash_manifest': True,  # Inclure les formats DASH
            'youtube_include_hls_manifest': True,   # Inclure les formats HLS
            'verbose': True,  # Activer le mode verbeux pour le débogage
        }
        
        logging.info(f"Tentative de récupération des formats pour l'URL: {url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise ValueError("Impossible d'extraire les informations de la vidéo")
                
                logging.info(f"Formats trouvés: {len(info.get('formats', []))}")
                
                # Filtrer pour obtenir les meilleurs formats
                best_formats = filter_best_formats(info.get('formats', []))
                
                if not best_formats:
                    raise ValueError("Aucun format compatible n'a été trouvé")
                
                # Convertir en FormatInfo
                formats = []
                for f in best_formats:
                    try:
                        format_note = []
                        
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
                        
                        formats.append(FormatInfo(
                            format_id=f.get('format_id', ''),
                            ext=f.get('ext', ''),
                            resolution=f"{int(f.get('height', 0) or 0)}p" if f.get('height') else None,
                            filesize=float(f.get('filesize', 0) or 0),
                            format_note=' - '.join(format_note) if format_note else "Format inconnu",
                            vcodec=f.get('vcodec'),
                            acodec=f.get('acodec')
                        ))
                    except (TypeError, ValueError) as e:
                        logging.warning(f"Erreur lors du traitement d'un format: {str(e)}")
                        continue

                if not formats:
                    raise ValueError("Aucun format valide n'a été trouvé après le filtrage")

                return VideoInfo(
                    title=info.get('title', ''),
                    formats=formats,
                    thumbnail=info.get('thumbnail'),
                    duration=info.get('duration')
                )

            except yt_dlp.utils.DownloadError as e:
                logging.error(f"Erreur yt-dlp lors de l'extraction: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Erreur lors de l'extraction des informations: {str(e)}"
                )

    except Exception as e:
        logging.error(f"Erreur lors de la récupération des formats: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors de la récupération des formats: {str(e)}"
        )

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        logging.error(f"Erreur lors du rendu de index.html: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/video_editor", response_class=HTMLResponse)
async def editor(request: Request):
    try:
        return templates.TemplateResponse("video_editor.html", {"request": request})
    except Exception as e:
        logging.error(f"Erreur lors du rendu de video_editor.html: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Fonctions d'édition vidéo
def cut_video(input_file: str, output_file: str, start_time: str, end_time: str) -> bool:
    try:
        cmd = [
            'ffmpeg', '-i', input_file,
            '-ss', start_time,
            '-to', end_time,
            '-c', 'copy',
            output_file
        ]
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Erreur lors du découpage de la vidéo: {str(e)}")
        return False

def divide_video(input_file: str, segments: int, output_pattern: str) -> List[str]:
    try:
        # Obtenir la durée totale de la vidéo
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_file]
        duration = float(subprocess.check_output(cmd).decode().strip())
        
        # Calculer la durée de chaque segment
        segment_duration = duration / segments
        output_files = []
        
        for i in range(segments):
            start_time = i * segment_duration
            output_file = output_pattern.format(i + 1)
            
            cmd = [
                'ffmpeg', '-i', input_file,
                '-ss', str(start_time),
                '-t', str(segment_duration),
                '-c', 'copy',
                output_file
            ]
            subprocess.run(cmd, check=True)
            output_files.append(os.path.basename(output_file))
        
        return output_files
    except (subprocess.CalledProcessError, ValueError) as e:
        logging.error(f"Erreur lors de la division de la vidéo: {str(e)}")
        return []

def add_comment_to_video(input_file: str, output_file: str, text: str, time: str, duration: int) -> bool:
    try:
        # Convertir le temps en secondes
        h, m, s = map(int, time.split(':'))
        start_seconds = h * 3600 + m * 60 + s
        
        cmd = [
            'ffmpeg', '-i', input_file,
            '-vf', f"drawtext=text='{text}':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-10:enable='between(t,{start_seconds},{start_seconds + duration})'",
            '-c:a', 'copy',
            output_file
        ]
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Erreur lors de l'ajout du commentaire: {str(e)}")
        return False

# Routes pour l'édition vidéo
@app.post("/api/edit/cut")
async def edit_cut_video(request: CutRequest):
    input_file = os.path.join(DOWNLOAD_DIR, request.filename)
    if not os.path.exists(input_file):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    output_file = os.path.join(TEMP_DIR, f"cut_{uuid.uuid4()}.mp4")
    if cut_video(input_file, output_file, request.start_time, request.end_time):
        shutil.move(output_file, input_file)
        return {"success": True, "message": "Vidéo découpée avec succès"}
    else:
        raise HTTPException(status_code=500, detail="Erreur lors du découpage de la vidéo")

@app.post("/api/edit/divide")
async def edit_divide_video(request: DivideRequest):
    input_file = os.path.join(DOWNLOAD_DIR, request.filename)
    if not os.path.exists(input_file):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    output_pattern = os.path.join(TEMP_DIR, f"segment_{uuid.uuid4()}_{{0}}.mp4")
    output_files = divide_video(input_file, request.segments, output_pattern)
    
    if output_files:
        return {"success": True, "files": output_files}
    else:
        raise HTTPException(status_code=500, detail="Erreur lors de la division de la vidéo")

@app.post("/api/edit/comment")
async def edit_add_comment(request: CommentRequest):
    input_file = os.path.join(DOWNLOAD_DIR, request.filename)
    if not os.path.exists(input_file):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    output_file = os.path.join(TEMP_DIR, f"comment_{uuid.uuid4()}.mp4")
    if add_comment_to_video(input_file, output_file, request.text, request.time, request.duration):
        shutil.move(output_file, input_file)
        return {"success": True, "message": "Commentaire ajouté avec succès"}
    else:
        raise HTTPException(status_code=500, detail="Erreur lors de l'ajout du commentaire")

@app.post("/api/edit/export")
async def edit_export_video(request: ExportRequest):
    input_file = os.path.join(DOWNLOAD_DIR, request.filename)
    if not os.path.exists(input_file):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    output_file = os.path.join(TEMP_DIR, f"export_{uuid.uuid4()}.{request.format}")
    try:
        cmd = ['ffmpeg', '-i', input_file, output_file]
        subprocess.run(cmd, check=True)
        shutil.move(output_file, input_file)
        return {"success": True, "message": "Vidéo exportée avec succès"}
    except subprocess.CalledProcessError as e:
        logging.error(f"Erreur lors de l'export de la vidéo: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'export de la vidéo")

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        filename = f"upload_{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        return {"filename": filename}
    except Exception as e:
        logging.error(f"Erreur lors de l'upload du fichier: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'upload du fichier")
