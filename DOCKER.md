# Docker Deployment Guide

**Just clone the repo and run it!** The Dockerfile automatically uses your local files - no GitHub downloads needed.

## Prerequisites

- Docker and Docker Compose installed
- (Optional) Navidrome server

Default catalog is **Deezer** (no API key). Optional **Spotify**: set credentials in `backend/.env`.

## Quick Start (3 Steps!)

1. **Clone and setup**
   ```bash
   git clone https://github.com/soggy8/musikat.git
   cd musikat
   cp backend/env.example backend/.env
   ```

2. **Edit `backend/.env`** (optional) - Configure Navidrome path, etc. No API keys needed.

3. **Run it!**
   ```bash
   docker-compose up -d
   ```

**Done!** Open http://localhost:8000 in your browser.

### Optional: Connect to Navidrome

If you want to download directly to Navidrome, edit `docker-compose.yml`:
```yaml
volumes:
  - /path/to/your/navidrome/music:/music:rw
```

## Configuration

### Environment Variables

Edit `backend/.env` file with your settings:

```env
# DEFAULT_METADATA_PROVIDER=deezer
# Optional Spotify: SPOTIFY_CLIENT_ID= SPOTIFY_CLIENT_SECRET=

# Navidrome Configuration
NAVIDROME_MUSIC_PATH=/music  # Inside container, don't change
NAVIDROME_API_URL=http://host.docker.internal:4533  # If Navidrome on host
# Or: NAVIDROME_API_URL=http://navidrome:4533  # If Navidrome in Docker
NAVIDROME_USERNAME=admin
NAVIDROME_PASSWORD=your_password

# Download Configuration
OUTPUT_FORMAT=mp3
AUDIO_QUALITY=128

# YouTube Configuration (optional)
# Path to YouTube cookies file for bypassing bot detection
# See "YouTube Cookies Setup" section below for instructions
# YOUTUBE_COOKIES_PATH=/app/youtube_cookies.txt

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:8000
```

### Volume Mounts

The docker-compose.yml mounts:
- **Navidrome music directory**: Maps your host Navidrome music folder to `/music` in the container
- **Downloads directory**: Maps `./downloads` for temporary files (optional but recommended)
- **YouTube cookies file**: Optional, for bypassing YouTube bot detection (see below)

### YouTube Cookies Setup

If you encounter "Sign in to confirm you're not a bot" errors, you can use YouTube cookies to authenticate:

1. **Export cookies from your browser:**
   - Install a browser extension like "Get cookies.txt LOCALLY" (Chrome/Firefox)
   - Visit youtube.com and log in
   - Export cookies in Netscape format to a file (e.g., `youtube_cookies.txt`)

2. **Mount the cookies file in docker-compose.yml:**
   ```yaml
   volumes:
     - /path/to/youtube_cookies.txt:/app/youtube_cookies.txt:ro
   ```

3. **Set the environment variable in docker-compose.yml:**
   ```yaml
   environment:
     - YOUTUBE_COOKIES_PATH=/app/youtube_cookies.txt
   ```

4. **Or set it in backend/.env:**
   ```env
   YOUTUBE_COOKIES_PATH=/app/youtube_cookies.txt
   ```

**Alternative method using yt-dlp:**
```bash
# Export cookies directly using yt-dlp
yt-dlp --cookies-from-browser chrome --cookies youtube_cookies.txt "https://www.youtube.com"
```

**Note:** Cookies expire periodically. You may need to re-export them if downloads start failing again.

### Navidrome Integration

#### If Navidrome is running on the host machine:
```yaml
environment:
  - NAVIDROME_API_URL=http://host.docker.internal:4533
```

#### If Navidrome is running in Docker:
1. Connect to the same network or use external network
2. Use Navidrome service name:
```yaml
environment:
  - NAVIDROME_API_URL=http://navidrome:4533
networks:
  - navidrome-network
networks:
  navidrome-network:
    external: true
```

## Docker Compose Commands

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild and restart
docker-compose up -d --build

# View running containers
docker-compose ps
```

## Troubleshooting

### Container can't access Navidrome

- If Navidrome is on host: Use `host.docker.internal:4533` (Linux may need `172.17.0.1` instead)
- If Navidrome is in Docker: Ensure both containers are on the same network

### Permission errors with music directory

Make sure the Docker container can write to the mounted volume:
```bash
sudo chown -R 1000:1000 /path/to/navidrome/music
# Or adjust permissions as needed
```

### FFmpeg not found

FFmpeg is installed in the Docker image. If you see errors, ensure you're using the provided Dockerfile.

### Port already in use

Change the port mapping in docker-compose.yml:
```yaml
ports:
  - "8001:8000"  # Use port 8001 on host instead
```

## Building the Image Manually

```bash
docker build -t musikat .
docker run -p 8000:8000 \
  -v /path/to/navidrome/music:/music \
  -v $(pwd)/backend/.env:/app/backend/.env \
  musikat
```

## Production Deployment

For production:
1. Use environment variables instead of .env file (more secure)
2. Set up a reverse proxy (nginx/traefik) for HTTPS
3. Use Docker secrets for sensitive data
4. Consider using Docker volumes for downloads directory persistence
5. Set resource limits in docker-compose.yml:
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 2G
   ```

