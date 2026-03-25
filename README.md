# 🎵 Musikat - For Navidrome and local downloads

> **Catalog:** Choose **Deezer** (default, no API key) or **Spotify** (optional credentials) in the web UI or via `DEFAULT_METADATA_PROVIDER` in `.env`.

A modern web application that searches **Deezer** or **Spotify** for tracks and albums, downloads audio from YouTube, then adds files to your Navidrome server or local downloads with metadata and album art.

## Screenshots

### Main Interface
![Main Interface](images/main-interface.png)

### Download Queue with Progress Bars
![Download Queue](images/download-queue.png)

## Features

- 🎵 Search with **Deezer** (no API key) or **Spotify** (optional)
- 📥 Automatic download from YouTube using metadata
- 🏷️ Automatic ID3 tagging with artist, album, album art, and metadata
- 📂 Direct upload to Navidrome server or local downloads
- 🎨 Modern, clean web interface with download queue
- ⚡ Real-time download status updates with progress bars
- 📊 Visual download queue showing all active downloads
- 🔄 Choose between local downloads (browser) or Navidrome server upload

## Architecture

- **Frontend**: Vanilla JavaScript, HTML, CSS
- **Backend**: Python FastAPI
- **Deezer API**: Public catalog search (no key)
- **Spotify Web API**: Optional; requires Client ID + Secret
- **yt-dlp**: For downloading audio from YouTube
- **mutagen**: For ID3 tagging
- **Navidrome**: Music server integration

## Prerequisites

**For Docker (Recommended):**
- Docker and Docker Compose

**For Manual Installation:**
- Python 3.8+ (Python 3.11 recommended, avoid 3.13 due to compatibility issues)
- FFmpeg (required by yt-dlp for audio conversion)
- Navidrome server (optional, for direct server uploads)

**Deezer** needs no API key. **Spotify** requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env` if you select it in the UI.

## Installation

### Option 1: Docker Compose (Recommended - Easiest!)

**Just 3 steps:**

```bash
# 1. Clone the repo
git clone https://github.com/soggy8/musikat.git
cd musikat

# 2. Setup environment (optional)
cp backend/env.example backend/.env
# Edit backend/.env: Navidrome path, optional Spotify credentials, DEFAULT_METADATA_PROVIDER

# 3. Run it!
docker-compose up -d
```

Open http://localhost:8000 in your browser. Done! 🎉

> **Note:** If you want to use Navidrome, edit `docker-compose.yml` to mount your Navidrome music directory. See [DOCKER.md](DOCKER.md) for details.

### Option 2: Manual Installation

See [SETUP.md](SETUP.md) for detailed setup instructions.

#### 1. Clone the repository

```bash
git clone <your-repo-url>
cd musikat
```

### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

Or use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install FFmpeg

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from [FFmpeg website](https://ffmpeg.org/download.html) and add to PATH

### 4. Configure environment variables

Create a `.env` file in the `backend` directory:

```env
# Catalog default: deezer | spotify (UI can override)
DEFAULT_METADATA_PROVIDER=deezer
# SPOTIFY_CLIENT_ID=
# SPOTIFY_CLIENT_SECRET=

# Navidrome Configuration
NAVIDROME_MUSIC_PATH=/path/to/navidrome/music
NAVIDROME_API_URL=http://localhost:4533
NAVIDROME_USERNAME=admin
NAVIDROME_PASSWORD=password

# Download Configuration
OUTPUT_FORMAT=mp3
AUDIO_QUALITY=128

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### 5. Configure Navidrome Path

Set `NAVIDROME_MUSIC_PATH` to the directory where Navidrome stores its music library. This path must be:
- Writable by the user running the backend
- Accessible (local filesystem, NFS mount, or similar)

## Running the Application

### Backend

```bash
cd backend
python app.py
```

Or with uvicorn directly:

```bash
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The application (both frontend and API) will be available at `http://localhost:8000`

The frontend is automatically served from the backend, so no separate frontend server is needed.

## Usage

1. Open the web interface in your browser (http://localhost:8000)
2. Choose download location: "My Downloads Folder" or "Navidrome Server"
3. Search for a song, artist, or album
4. Browse the search results
5. Click "Download" on any track you want
6. Watch the progress in the download queue at the top
7. Downloads complete automatically:
   - **Local downloads**: Files are saved to your browser's Downloads folder
   - **Navidrome uploads**: Files are added to your Navidrome library (Artist/Album structure)

## How It Works

1. **Search**: Uses Deezer or Spotify (your choice) for track/album metadata
2. **Download**: Uses yt-dlp to search YouTube and download audio
3. **Tagging**: Applies ID3 tags from the chosen catalog (title, artist, album, cover art)
4. **Upload**: Copies the file to Navidrome's music directory in organized folders (Artist/Album/)
5. **Scan**: Optionally triggers Navidrome to scan for new files (if API credentials are configured)

## API Endpoints

- `GET /api/metadata/providers` - List catalog options and whether Spotify is configured
- `POST /api/search` - Search tracks
  - Body: `{ "query": "...", "limit": 20, "provider": "deezer" | "spotify" }`
- `GET /api/track/{track_id}` - Track details (`?provider=deezer|spotify`)
- `POST /api/download` - Start download
  - Body: `{ "track_id": "...", "location": "local"|"navidrome", "provider": "deezer"|"spotify", ... }`

- `GET /api/download/status/{track_id}` - Get download status

- `GET /api/health` - Health check endpoint

## Project Structure

```
musikat/
├── backend/
│   ├── app.py                 # FastAPI main application
│   ├── config.py              # Configuration management
│   ├── requirements.txt       # Python dependencies
│   ├── env.example            # Environment variables template
│   ├── static                 # Static files
│   │   ├── app.js             # Frontend JavaScript
│   │   └── styles.css         # Styling
│   ├── templates              # Templates
│   │   └── index.html         # Main HTML page
│   ├── services/
│   │   ├── deezer.py          # Deezer catalog (no API key)
│   │   ├── spotify.py         # Spotify catalog (optional)
│   │   ├── youtube.py         # YouTube download with yt-dlp
│   │   ├── metadata.py        # ID3 tagging
│   │   └── navidrome.py       # Navidrome integration
│   └── utils/
│       └── file_handler.py    # File operations
├── images/                    # Screenshots and images for README
├── Dockerfile                 # Docker image definition
├── docker-compose.yml         # Docker Compose configuration
├── DOCKER.md                  # Docker deployment guide
├── DEPLOYMENT.md              # Server deployment guide
├── SETUP.md                   # Manual setup guide
└── README.md                  # This file
```

## Troubleshooting

### Search Returns No Results

- Try the other catalog (Deezer vs Spotify) from the **Catalog** dropdown
- Use more specific queries (artist + song title)

### YouTube Download Fails

- Ensure FFmpeg is installed and in your PATH
- Check your internet connection
- Some videos may be region-locked or unavailable

### YouTube Bot Detection ("Sign in to confirm you're not a bot")

If you see errors like "Sign in to confirm you're not a bot", YouTube is blocking automated requests. You can bypass this by using YouTube cookies:

1. **Export cookies from your browser:**
   - Install a browser extension like "Get cookies.txt LOCALLY" (Chrome/Firefox)
   - Visit youtube.com and log in
   - Export cookies in Netscape format to a file (e.g., `youtube_cookies.txt`)

2. **For Docker:**
   - Mount the cookies file in `docker-compose.yml`:
     ```yaml
     volumes:
       - /path/to/youtube_cookies.txt:/app/youtube_cookies.txt:ro
     ```
   - Set environment variable:
     ```yaml
     environment:
       - YOUTUBE_COOKIES_PATH=/app/youtube_cookies.txt
     ```

3. **For manual installation:**
   - Add to `backend/.env`:
     ```env
     YOUTUBE_COOKIES_PATH=/path/to/youtube_cookies.txt
     ```

**Alternative:** Use yt-dlp to export cookies:
```bash
yt-dlp --cookies-from-browser chrome --cookies youtube_cookies.txt "https://www.youtube.com"
```

**Note:** Cookies expire periodically. Re-export them if downloads start failing again.

### Navidrome Upload Fails

- Verify `NAVIDROME_MUSIC_PATH` is correct and writable
- Check file permissions on the Navidrome music directory
- Ensure the path exists

### CORS Errors

- Update `CORS_ORIGINS` in `.env` to include your frontend URL
- Make sure the frontend is accessing the correct API URL

## Legal Considerations

- This tool is for personal use only
- Respect copyright laws in your jurisdiction
- Deezer, Spotify, and YouTube each have their own terms of use
- YouTube Terms of Service apply
- Use responsibly and ethically

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Description

Musikat streamlines adding music to Navidrome: search **Deezer** or **Spotify**, download from **YouTube**, and get ID3 tags and artwork from the catalog you picked.

**Key Benefits:**
- 🚀 **Fast & Efficient**: Single-click downloads with automatic processing
- 📊 **Rich Metadata**: ID3 tags from Deezer or Spotify (artist, album, year, artwork)
- 🗂️ **Auto-Organization**: Files automatically organized in Artist/Album/ structure
- 🔄 **Auto-Sync**: Automatically triggers Navidrome library scans
- 💻 **Self-Hosted**: Full control over your data and downloads
- 🎨 **Modern UI**: Clean, responsive web interface with visual download queue
- 📥 **Dual Download Options**: Choose between local browser downloads or direct Navidrome server upload
- 📈 **Progress Tracking**: Real-time progress bars and status updates for all downloads
- 🐳 **Docker Ready**: One-command deployment with Docker Compose

Perfect for music enthusiasts who want to expand their Navidrome library quickly and efficiently!

## Documentation

- **[DOCKER.md](DOCKER.md)** - Docker deployment guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production server deployment guide
- **[SETUP.md](SETUP.md)** - Manual installation guide

