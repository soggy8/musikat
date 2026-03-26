const METADATA_PROVIDER_STORAGE = 'musikat_metadata_provider';

function getMetadataProvider() {
    const el = document.getElementById('metadataProvider');
    return el && el.value ? el.value : 'deezer';
}

async function initMetadataProvider() {
    const el = document.getElementById('metadataProvider');
    if (!el) {
        setTimeout(initMetadataProvider, 100);
        return;
    }
    try {
        const r = await fetch('api/metadata/providers');
        if (!r.ok) return;
        const data = await r.json();
        const saved = localStorage.getItem(METADATA_PROVIDER_STORAGE);
        const def = data.default || 'deezer';
        el.innerHTML = (data.providers || []).map((p) => {
            const disabled = p.id === 'spotify' && !p.configured;
            const label = p.label || p.id;
            return `<option value="${p.id}" ${disabled ? 'disabled' : ''}>${escapeHtml(label)}${disabled ? ' (not configured)' : ''}</option>`;
        }).join('');
        const pick = saved && [...el.options].some((o) => o.value === saved && !o.disabled) ? saved : def;
        el.value = [...el.options].some((o) => o.value === pick && !o.disabled) ? pick : 'deezer';
        el.addEventListener('change', () => {
            localStorage.setItem(METADATA_PROVIDER_STORAGE, el.value);
        });
    } catch (e) {
        console.warn('metadata providers:', e);
    }
}

// DOM elements
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const loading = document.getElementById('loading');
const error = document.getElementById('error');
const results = document.getElementById('results');
const tracksList = document.getElementById('tracksList');
const albumsList = document.getElementById('albumsList');
const downloadStatus = document.getElementById('downloadStatus');
const statusContent = document.getElementById('statusContent');

// Track download status tracking
const activeDownloads = new Map();

// Search type: 'tracks' or 'albums'
let searchType = 'tracks';

// Format and quality options (loaded on page init)
let availableFormats = [];
let availableQualities = [];
let defaultFormat = 'mp3';
let defaultQuality = '128';

// DOM elements for format/quality (will be set when DOM is ready)
let audioFormatSelect;
let audioQualitySelect;

// Load available formats and qualities on page load
async function loadFormatOptions() {
    // Get elements fresh each time in case DOM wasn't ready
    audioFormatSelect = document.getElementById('audioFormat');
    audioQualitySelect = document.getElementById('audioQuality');
    
    if (!audioFormatSelect || !audioQualitySelect) {
        console.error('Format/Quality select elements not found. Retrying in 100ms...');
        setTimeout(loadFormatOptions, 100);
        return;
    }
    
    try {
        const response = await fetch('/api/formats');
        if (response.ok) {
            const data = await response.json();
            availableFormats = data.formats || [];
            availableQualities = data.qualities || [];
            defaultFormat = data.default_format || 'mp3';
            defaultQuality = data.default_quality || '128';
            
            // Populate format dropdown
            audioFormatSelect.innerHTML = availableFormats.map(fmt => 
                `<option value="${fmt.value}" ${fmt.value === defaultFormat ? 'selected' : ''}>${fmt.label} - ${fmt.description}</option>`
            ).join('');
            
            // Populate quality dropdown based on default format
            updateQualityOptions(defaultFormat);
            
            // Update quality options when format changes
            audioFormatSelect.addEventListener('change', (e) => {
                updateQualityOptions(e.target.value);
            });
        } else {
            const errorText = await response.text();
            console.error('Failed to load format options:', response.status, errorText);
            // Fallback to basic options
            audioFormatSelect.innerHTML = '<option value="mp3">MP3</option>';
            audioQualitySelect.innerHTML = '<option value="128">128 kbps</option>';
        }
    } catch (err) {
        console.error('Error loading format options:', err);
        // Fallback to basic options
        if (audioFormatSelect) audioFormatSelect.innerHTML = '<option value="mp3">MP3</option>';
        if (audioQualitySelect) audioQualitySelect.innerHTML = '<option value="128">128 kbps</option>';
    }
}

// Function to update quality options based on selected format
function updateQualityOptions(selectedFormat) {
    if (!audioQualitySelect) {
        audioQualitySelect = document.getElementById('audioQuality');
        if (!audioQualitySelect) return;
    }
    
    if (selectedFormat === 'flac') {
        // FLAC is lossless, only show lossless option
        audioQualitySelect.innerHTML = '<option value="lossless" selected>Lossless - No quality loss</option>';
    } else {
        // For lossy formats, show all quality options
        const currentQuality = audioQualitySelect.value || defaultQuality;
        audioQualitySelect.innerHTML = availableQualities
            .filter(qual => qual.value !== 'lossless') // Hide lossless for non-FLAC formats
            .map(qual => 
                `<option value="${qual.value}" ${qual.value === currentQuality ? 'selected' : ''}>${qual.label} - ${qual.description}</option>`
            ).join('');
    }
}

// Initialize on page load (wait for DOM to be ready)
function initializeFormatOptions() {
    const run = () => {
        loadFormatOptions();
        initMetadataProvider();
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run);
    } else {
        setTimeout(run, 50);
    }
}

initializeFormatOptions();

// Event listeners
searchBtn.addEventListener('click', handleSearch);
searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        handleSearch();
    }
});

// Search type toggle
document.getElementById('searchTracks')?.addEventListener('click', () => {
    searchType = 'tracks';
    document.getElementById('searchTracks').classList.add('active');
    document.getElementById('searchAlbums').classList.remove('active');
    // Re-search if there's a query
    if (searchInput.value.trim()) handleSearch();
});

document.getElementById('searchAlbums')?.addEventListener('click', () => {
    searchType = 'albums';
    document.getElementById('searchAlbums').classList.add('active');
    document.getElementById('searchTracks').classList.remove('active');
    // Re-search if there's a query
    if (searchInput.value.trim()) handleSearch();
});

async function handleSearch() {
    const query = searchInput.value.trim();
    
    if (!query) {
        showError('Please enter a search query');
        return;
    }

    // Reverse flow: YouTube / YouTube Music URL pasted into search box
    if (isYouTubeUrl(query)) {
        hideError();
        showLoading();
        hideResults();
        hideReverseResults();

        try {
            const data = await reverseLookupYouTube(query);
            hideLoading();
            showReverseResults(data);
            return;
        } catch (err) {
            hideLoading();
            showError(`Reverse lookup failed: ${err.message}`);
            return;
        }
    }
    
    hideError();
    showLoading();
    hideResults();
    hideReverseResults();
    
    try {
        if (searchType === 'albums') {
            const albums = await searchAlbums(query);
            displayAlbums(albums);
        } else {
            const tracks = await searchTracks(query);
            await displayTracks(tracks);
        }
        hideLoading();
        showResults();
    } catch (err) {
        hideLoading();
        showError(`Search failed: ${err.message}`);
    }
}

async function searchTracks(query) {
    const response = await fetch(`api/search`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query, limit: 20, provider: getMetadataProvider() }),
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Search failed');
    }
    
    return await response.json();
}

// ============ REVERSE (YouTube -> Spotify) ============

let reverseState = {
    youtubeUrl: null,
    youtubeInfo: null,
    selectedSpotifyTrackId: null,
    manualMetadata: null,
};

function isYouTubeUrl(input) {
    try {
        const u = new URL(input);
        const host = u.hostname.toLowerCase();
        return host === 'www.youtube.com' || host === 'youtube.com' || host === 'music.youtube.com' || host.endsWith('.youtube.com') || host === 'youtu.be';
    } catch {
        return false;
    }
}

async function reverseLookupYouTube(url) {
    const response = await fetch(`api/reverse/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, provider: getMetadataProvider() })
    });

    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Reverse lookup failed');
    }

    return await response.json();
}

function hideReverseResults() {
    document.getElementById('reverseResults')?.classList.add('hidden');
}

function showReverseResults(data) {
    const reverseResults = document.getElementById('reverseResults');
    const ytInfoDiv = document.getElementById('reverseYouTubeInfo');
    const spList = document.getElementById('reverseSpotifyList');
    const manualBtn = document.getElementById('reverseManualBtn');
    const manualForm = document.getElementById('reverseManualForm');
    const finalize = document.getElementById('reverseFinalize');
    const selectedLabel = document.getElementById('reverseSelectedLabel');

    if (!reverseResults || !ytInfoDiv || !spList) return;

    reverseState = {
        youtubeUrl: data?.youtube?.webpage_url || null,
        youtubeInfo: data?.youtube || null,
        selectedSpotifyTrackId: null,
        manualMetadata: null,
    };

    // Normalize youtube url
    reverseState.youtubeUrl = data?.youtube?.webpage_url || null;
    if (!reverseState.youtubeUrl && reverseState.youtubeInfo?.video_id) {
        reverseState.youtubeUrl = `https://www.youtube.com/watch?v=${encodeURIComponent(reverseState.youtubeInfo.video_id)}`;
    }

    const ytTitle = escapeHtml(data?.youtube?.title || '');
    const ytUploader = escapeHtml(data?.youtube?.uploader || '');
    const ytUrl = data?.youtube?.webpage_url || reverseState.youtubeUrl;
    const ytThumb = data?.youtube?.thumbnail || '';

    ytInfoDiv.innerHTML = `
        <div><strong>YouTube title:</strong> ${ytTitle}</div>
        <div><strong>Channel:</strong> ${ytUploader}</div>
        <div><strong>URL:</strong> <a href="${ytUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(ytUrl)}</a></div>
        <div><strong>Search query:</strong> ${escapeHtml(data?.query || '')}</div>
        ${ytThumb ? `<div style="margin-top:10px;"><img src="${ytThumb}" alt="thumbnail" style="max-width:180px;border-radius:10px;border:1px solid var(--border-color);"/></div>` : ''}
    `;

    const candidates = data?.spotify_candidates || [];
    if (!candidates.length) {
        spList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No matches found. Use manual metadata.</p>';
    } else {
        spList.innerHTML = candidates.map(track => `
            <div class="track-card">
                <img src="${track.album_art || 'https://via.placeholder.com/80?text=No+Image'}" alt="${escapeHtml(track.album)}" class="track-art" />
                <div class="track-info">
                    <div class="track-name">${escapeHtml(track.name)}</div>
                    <div class="track-artist">${escapeHtml(track.artist)}</div>
                    <div class="track-album">${escapeHtml(track.album)} • ${formatDuration(track.duration_ms)}</div>
                </div>
                <div class="track-actions">
                    <button class="btn btn-download" data-spotify-track-id="${track.id}">Select</button>
                </div>
            </div>
        `).join('');

        spList.querySelectorAll('button[data-spotify-track-id]').forEach(btn => {
            btn.addEventListener('click', () => {
                const trackId = btn.dataset.spotifyTrackId;
                reverseState.selectedSpotifyTrackId = trackId;
                reverseState.manualMetadata = null;
                manualForm?.classList.add('hidden');
                finalize?.classList.remove('hidden');
                if (selectedLabel) selectedLabel.textContent = `Selected track: ${trackId}`;
            });
        });
    }

    manualBtn?.addEventListener('click', () => {
        manualForm?.classList.toggle('hidden');
    });

    document.getElementById('reverseUseManual')?.addEventListener('click', () => {
        const artist = document.getElementById('manualArtist')?.value?.trim() || '';
        const name = document.getElementById('manualName')?.value?.trim() || '';
        const albumArtist = document.getElementById('manualAlbumArtist')?.value?.trim() || '';
        const album = document.getElementById('manualAlbum')?.value?.trim() || '';
        const trackNumber = document.getElementById('manualTrackNumber')?.value?.trim() || '';
        const releaseDate = document.getElementById('manualReleaseDate')?.value?.trim() || '';

        if (!artist || !name) {
            showError('Manual metadata requires Artist and Song title');
            return;
        }

        reverseState.manualMetadata = {
            artist,
            name,
            album_artist: albumArtist,
            album,
            track_number: trackNumber ? Number(trackNumber) : 1,
            release_date: releaseDate,
        };
        reverseState.selectedSpotifyTrackId = null;
        finalize?.classList.remove('hidden');
        if (selectedLabel) selectedLabel.textContent = `Using manual metadata: ${artist} - ${name}`;
    });

    document.getElementById('reverseDownloadBtn')?.addEventListener('click', () => {
        startReverseDownload();
    });

    reverseResults.classList.remove('hidden');
}

async function startReverseDownload() {
    const youtubeUrl = reverseState.youtubeUrl || reverseState.youtubeInfo?.webpage_url;
    if (!youtubeUrl) {
        showError('Missing YouTube URL');
        return;
    }

    const downloadLocation = document.getElementById('downloadLocation')?.value || 'local';

    // Ensure one source of metadata
    if (!reverseState.selectedSpotifyTrackId && !reverseState.manualMetadata) {
        showError('Select a track or use manual metadata first');
        return;
    }

    const payload = {
        youtube_url: youtubeUrl,
        location: downloadLocation,
        spotify_track_id: reverseState.selectedSpotifyTrackId,
        metadata: reverseState.manualMetadata,
        provider: getMetadataProvider(),
    };

    // Mark as downloading using synthetic id returned by API
    try {
        showDownloadStatus();
        const response = await fetch(`api/reverse/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Reverse download failed');
        }

        const result = await response.json();
        const jobId = result.job_id;

        const trackLike = {
            id: jobId,
            name: reverseState.manualMetadata?.name || reverseState.youtubeInfo?.title || 'YouTube download',
            artist: reverseState.manualMetadata?.artist || reverseState.youtubeInfo?.uploader || '',
            album: reverseState.manualMetadata?.album || '',
            album_art: null,
        };

        activeDownloads.set(jobId, { status: 'queued', progress: 0, track: trackLike });
        addStatusItem(jobId, trackLike, 'queued', 'Reverse download queued...', 0);
        pollDownloadStatus(jobId, trackLike);

    } catch (err) {
        showError(err.message || String(err));
    }
}

async function searchAlbums(query) {
    const response = await fetch(`api/search/albums`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query, limit: 20, provider: getMetadataProvider() }),
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Album search failed');
    }
    
    return await response.json();
}

async function displayTracks(tracks) {
    // Show tracks list, hide albums list
    tracksList.classList.remove('hidden');
    albumsList.classList.add('hidden');
    
    if (tracks.length === 0) {
        tracksList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No tracks found</p>';
        return;
    }
    
    // Check which tracks are already downloaded
    const downloadedTracks = new Set();
    const downloadLocation = document.getElementById('downloadLocation')?.value || 'local';
    const checkPromises = tracks.map(async (track) => {
        try {
            const response = await fetch(
                `api/track/${encodeURIComponent(track.id)}/exists?provider=${encodeURIComponent(getMetadataProvider())}&location=${encodeURIComponent(downloadLocation)}`
            );
            if (response.ok) {
                const data = await response.json();
                if (data.exists) {
                    downloadedTracks.add(track.id);
                }
            }
        } catch (err) {
            // Silently fail - just won't show as downloaded
        }
    });
    
    await Promise.all(checkPromises);
    
    tracksList.innerHTML = tracks.map(track => createTrackCard(track, downloadedTracks.has(track.id))).join('');
    
    // Add event listeners to download buttons
    tracks.forEach(track => {
        const downloadBtn = document.getElementById(`download-${track.id}`);
        if (downloadBtn && !downloadedTracks.has(track.id)) {
            downloadBtn.addEventListener('click', () => downloadTrack(track));
        }
    });
}

function createTrackCard(track, isDownloaded = false) {
    const albumArt = track.album_art || 'https://via.placeholder.com/80?text=No+Image';
    const duration = formatDuration(track.duration_ms);
    const isDownloading = activeDownloads.has(track.id);
    
    return `
        <div class="track-card">
            <img src="${albumArt}" alt="${track.album}" class="track-art" />
            <div class="track-info">
                <div class="track-name">${escapeHtml(track.name)}</div>
                <div class="track-artist">${escapeHtml(track.artist)}</div>
                <div class="track-album">${escapeHtml(track.album)} • ${duration}</div>
            </div>
            <div class="track-actions">
                ${isDownloaded ? `
                    <span class="downloaded-badge">✓ Downloaded</span>
                ` : `
                    <button 
                        id="download-${track.id}" 
                        class="btn btn-download"
                        ${isDownloading ? 'disabled' : ''}
                    >
                        ${isDownloading ? 'Downloading...' : 'Download'}
                    </button>
                `}
            </div>
        </div>
    `;
}

async function downloadTrack(track, selectedVideoId = null) {
    const trackId = track.id;

    // Get download location preference
    const downloadLocation = document.getElementById('downloadLocation').value;
    
    // If no video selected, first check if we need user confirmation
    if (!selectedVideoId) {
        try {
            updateDownloadButton(trackId, true);
            console.log('Fetching YouTube candidates for:', trackId);
            const candidatesResponse = await fetch(`api/youtube/candidates/${encodeURIComponent(trackId)}?provider=${encodeURIComponent(getMetadataProvider())}`);
            
            if (candidatesResponse.ok) {
                const data = await candidatesResponse.json();
                console.log('Candidates response:', data);
                
                // If confidence is low, show candidate selection modal
                if (data.needs_confirmation && data.candidates && data.candidates.length > 0) {
                    console.log('Low confidence, showing modal. Best score:', data.best_score);
                    updateDownloadButton(trackId, false);
                    showCandidateModal(track, data.candidates, downloadLocation);
                    return;
                }
                
                // High confidence - use best match's video ID
                if (data.candidates && data.candidates.length > 0) {
                    console.log('High confidence, auto-selecting:', data.candidates[0].title);
                    selectedVideoId = data.candidates[0].video_id;
                }
            } else {
                // If candidates endpoint failed, try to get error message
                let errorMsg = 'Failed to search YouTube';
                try {
                    const errorData = await candidatesResponse.json();
                    errorMsg = errorData.detail || errorMsg;
                } catch (e) {
                    // If we can't parse error, use default message
                }
                
                console.error('Candidates fetch failed:', candidatesResponse.status, errorMsg);
                
                // Show error to user and don't proceed with download
                showError(`Cannot search YouTube: ${errorMsg}. This may be due to YouTube blocking requests (403). Please configure YouTube cookies (see documentation) or try again later.`);
                updateDownloadButton(trackId, false);
                return;
            }
        } catch (err) {
            console.error('Candidate check failed:', err);
            showError(`Failed to check YouTube candidates: ${err.message}. Please try again or configure YouTube cookies.`);
            updateDownloadButton(trackId, false);
            return;
        }
    }
    
    // Mark as downloading
    activeDownloads.set(trackId, { status: 'queued', progress: 0, track: track });
    updateDownloadButton(trackId, true);
    
    try {
        // Show download status section
        showDownloadStatus();
        addStatusItem(trackId, track, 'queued', 'Download queued...', 0);
        
        // Get format and quality preferences
        const formatSelect = document.getElementById('audioFormat');
        const qualitySelect = document.getElementById('audioQuality');
        const format = (formatSelect && formatSelect.value) ? formatSelect.value : defaultFormat;
        const quality = (qualitySelect && qualitySelect.value) ? qualitySelect.value : defaultQuality;
        
        // Start download
        const response = await fetch(`api/download`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                track_id: trackId,
                location: downloadLocation,
                video_id: selectedVideoId,
                format: format,
                quality: quality,
                provider: getMetadataProvider(),
            }),
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            const msg = error.detail || 'Download failed';
            throw new Error(msg);
        }
        
        // Poll for status updates
        pollDownloadStatus(trackId, track);
        
    } catch (err) {
        updateDownloadButton(trackId, false);
        activeDownloads.delete(trackId);
        showError(err.message || String(err));
    }
}

// Candidate selection modal
let pendingTrack = null;
let pendingLocation = null;

function getYouTubeUrl(videoId, source = 'yt-dlp') {
    const baseUrl = source === 'ytmusic' ? 'https://music.youtube.com' : 'https://www.youtube.com';
    return `${baseUrl}/watch?v=${encodeURIComponent(videoId)}`;
}

const EXTERNAL_LINK_SVG = `
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
  <path d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3z"></path>
  <path d="M5 5h6v2H7v10h10v-4h2v6H5V5z"></path>
</svg>`;

function showCandidateModal(track, candidates, location) {
    pendingTrack = track;
    pendingLocation = location;
    
    const modal = document.getElementById('candidateModal');
    const trackInfoDisplay = document.getElementById('trackInfoDisplay');
    const candidatesList = document.getElementById('candidatesList');
    
    // Show track info
    trackInfoDisplay.innerHTML = `
        <div class="looking-for">
            <strong>Looking for:</strong> ${escapeHtml(track.name)} by ${escapeHtml(track.artist)}
        </div>
    `;
    
    // Show candidates
    candidatesList.innerHTML = candidates.map((candidate) => `
        <div class="candidate-card" data-video-id="${candidate.video_id}">
            <div class="candidate-info">
                <div class="candidate-title-row">
                    <div class="candidate-title">${escapeHtml(candidate.title)}</div>
                    <a
                        class="candidate-external"
                        href="${getYouTubeUrl(candidate.video_id, candidate.source)}"
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Open on YouTube"
                        aria-label="Open on YouTube"
                    >${EXTERNAL_LINK_SVG}</a>
                </div>
                <div class="candidate-channel">${escapeHtml(candidate.channel)}</div>
                <div class="candidate-meta">
                    <span class="candidate-duration">${formatDuration(candidate.duration * 1000)}</span>
                    <span class="candidate-score ${getScoreClass(candidate.score)}">${Math.round(candidate.score * 100)}% match</span>
                </div>
            </div>
            <button class="btn btn-download candidate-select" data-video-id="${candidate.video_id}">
                Select
            </button>
        </div>
    `).join('');
    
    // Add click handlers
    candidatesList.querySelectorAll('.candidate-select').forEach(btn => {
        btn.addEventListener('click', () => {
            const videoId = btn.dataset.videoId;
            const trackToDownload = pendingTrack;
            const locationToUse = pendingLocation;
            hideCandidateModal();
            // Preserve the user's chosen location from when they clicked Download
            if (locationToUse) {
                const locationSelect = document.getElementById('downloadLocation');
                if (locationSelect) locationSelect.value = locationToUse;
            }
            downloadTrack(trackToDownload, videoId);
        });
    });
    
    modal.classList.remove('hidden');
}

function hideCandidateModal() {
    const modal = document.getElementById('candidateModal');
    modal.classList.add('hidden');
    pendingTrack = null;
    pendingLocation = null;
}

function getScoreClass(score) {
    if (score >= 0.8) return 'score-high';
    if (score >= 0.5) return 'score-medium';
    return 'score-low';
}

// Modal event listeners
document.getElementById('modalClose')?.addEventListener('click', hideCandidateModal);
document.getElementById('cancelSelection')?.addEventListener('click', hideCandidateModal);
document.getElementById('candidateModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'candidateModal') hideCandidateModal();
});

/** Resolve relative API paths against <base href> so file download URLs hit the right origin. */
function resolveAppUrl(relativeOrAbsolute) {
    if (!relativeOrAbsolute) return relativeOrAbsolute;
    if (/^https?:\/\//i.test(relativeOrAbsolute)) return relativeOrAbsolute;
    const baseTag = document.querySelector('base');
    const base = baseTag?.href || `${window.location.origin}${window.location.pathname.replace(/[^/]*$/, '')}`;
    try {
        return new URL(relativeOrAbsolute, base).href;
    } catch {
        return relativeOrAbsolute;
    }
}

/** Only one status poller per track id (avoids parallel loops each firing a file download). */
const pollDownloadActiveForTrack = new Set();

/**
 * Single GET for temp file, then save via blob URL — avoids extra browser navigation/prefetch
 * hits to the same URL after the server deletes the temp file (which caused 404 spam).
 */
const localFileFetchInFlight = new Set();

async function fetchLocalTrackFileOnce(trackId, downloadUrl, filePath) {
    if (localFileFetchInFlight.has(trackId)) return false;
    localFileFetchInFlight.add(trackId);
    const release = () => {
        setTimeout(() => localFileFetchInFlight.delete(trackId), 3000);
    };
    try {
        const url = resolveAppUrl(downloadUrl);
        const r = await fetch(url, { credentials: 'same-origin' });
        if (!r.ok) {
            release();
            const msg = `File download failed (${r.status})`;
            showError(msg);
            return false;
        }
        const blob = await r.blob();
        const fname = (filePath && filePath.split('/').pop()) || 'download.mp3';
        const objUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objUrl;
        link.download = fname;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(objUrl), 120000);
        release();
        return true;
    } catch (err) {
        localFileFetchInFlight.delete(trackId);
        showError(err.message || String(err));
        return false;
    }
}

/**
 * Poll download job status. Chained timeouts + one poller per track + single file fetch.
 */
function pollDownloadStatus(trackId, track) {
    if (pollDownloadActiveForTrack.has(trackId)) {
        return;
    }
    pollDownloadActiveForTrack.add(trackId);

    const POLL_MS = 2000;
    let stopped = false;

    const finishPoll = () => {
        pollDownloadActiveForTrack.delete(trackId);
    };

    const finishError = (msg) => {
        stopped = true;
        finishPoll();
        updateStatusItem(trackId, 'error', msg);
        updateDownloadButton(trackId, false);
        activeDownloads.delete(trackId);
    };

    const tick = async () => {
        if (stopped) return;
        try {
            const response = await fetch(`api/download/status/${encodeURIComponent(trackId)}`);

            if (!response.ok) {
                finishError('Failed to check status');
                return;
            }

            const status = await response.json();
            status.track = track;
            activeDownloads.set(trackId, status);

            const progress = status.progress !== undefined ? status.progress : getProgressFromStatus(status.status, status.message);
            updateStatusItem(trackId, status.status, status.message, progress);

            if (status.status === 'completed' || status.status === 'error') {
                stopped = true;
                updateDownloadButton(trackId, false);
                updateQueueCount();

                if (status.status === 'completed') {
                    if (status.download_url) {
                        const ok = await fetchLocalTrackFileOnce(trackId, status.download_url, status.file_path);
                        if (ok) {
                            updateStatusItem(trackId, 'completed', 'Download started - check your Downloads folder', 100);
                        } else {
                            updateStatusItem(trackId, 'error', 'Could not fetch the file from the server');
                        }
                    } else {
                        updateTrackToDownloaded(trackId);
                    }

                    setTimeout(() => {
                        removeStatusItem(trackId);
                        activeDownloads.delete(trackId);
                        finishPoll();
                    }, 5000);
                } else {
                    activeDownloads.delete(trackId);
                    finishPoll();
                }
                return;
            }

            updateQueueCount();
            setTimeout(tick, POLL_MS);
        } catch (err) {
            finishError(`Error: ${err.message}`);
        }
    };

    setTimeout(tick, POLL_MS);
}

function addStatusItem(trackId, track, status, message, progress = 0) {
    // Remove existing item if present
    const existing = document.getElementById(`status-${trackId}`);
    if (existing) {
        existing.remove();
    }
    
    const statusItem = document.createElement('div');
    statusItem.id = `status-${trackId}`;
    statusItem.className = `status-item status-${status}`;
    
    const progressBar = status === 'completed' || status === 'error' ? '' : `
        <div class="progress-bar-container">
            <div class="progress-bar" style="width: ${progress}%"></div>
        </div>
    `;
    
    const albumArt = track.album_art || 'https://via.placeholder.com/50?text=No+Image';
    
    statusItem.innerHTML = `
        <div class="status-item-header">
            <img src="${albumArt}" alt="${track.album}" class="status-art" />
            <div class="status-item-info">
                <h3>${escapeHtml(track.name)}</h3>
                <p class="status-artist">${escapeHtml(track.artist)}</p>
            </div>
            <div class="status-badge status-badge-${status}">${getStatusLabel(status)}</div>
        </div>
        <p class="status-message">${escapeHtml(message)}</p>
        ${progressBar}
    `;
    statusContent.appendChild(statusItem);
}

function updateStatusItem(trackId, status, message, progress = 0) {
    const statusItem = document.getElementById(`status-${trackId}`);
    if (statusItem) {
        statusItem.className = `status-item status-${status}`;
        
        // Update message
        const messageP = statusItem.querySelector('.status-message');
        if (messageP) {
            messageP.textContent = message;
        }
        
        // Update status badge
        const badge = statusItem.querySelector('.status-badge');
        if (badge) {
            badge.className = `status-badge status-badge-${status}`;
            badge.textContent = getStatusLabel(status);
        }
        
        // Update progress bar
        const progressBar = statusItem.querySelector('.progress-bar');
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
        } else if (status !== 'completed' && status !== 'error') {
            // Add progress bar if it doesn't exist
            const progressContainer = document.createElement('div');
            progressContainer.className = 'progress-bar-container';
            progressContainer.innerHTML = `<div class="progress-bar" style="width: ${progress}%"></div>`;
            statusItem.appendChild(progressContainer);
        }
    }
}

function getStatusLabel(status) {
    const labels = {
        'queued': 'Queued',
        'processing': 'Processing',
        'completed': 'Completed',
        'error': 'Error'
    };
    return labels[status] || status;
}

function getProgressFromStatus(status, message) {
    if (status === 'completed') return 100;
    if (status === 'error') return 0;
    if (status === 'queued') return 0;
    
    // Estimate progress based on message
    const lowerMessage = message.toLowerCase();
    if (lowerMessage.includes('fetching') || lowerMessage.includes('fetch')) return 10;
    if (lowerMessage.includes('preparing')) return 15;
    if (lowerMessage.includes('searching') || lowerMessage.includes('downloading') || lowerMessage.includes('download')) return 50;
    if (lowerMessage.includes('metadata') || lowerMessage.includes('applying') || lowerMessage.includes('tagging')) return 85;
    if (lowerMessage.includes('copying') || lowerMessage.includes('navidrome')) return 90;
    
    return 30; // Default progress for processing
}

function removeStatusItem(trackId) {
    const statusItem = document.getElementById(`status-${trackId}`);
    if (statusItem) {
        statusItem.remove();
        
        // Hide status section if no items left
        if (statusContent.children.length === 0) {
            hideDownloadStatus();
        }
    }
}

function updateDownloadButton(trackId, downloading) {
    const button = document.getElementById(`download-${trackId}`);
    if (button) {
        button.disabled = downloading;
        button.textContent = downloading ? 'Downloading...' : 'Download';
    }
}

function updateTrackToDownloaded(trackId) {
    const button = document.getElementById(`download-${trackId}`);
    if (button) {
        const trackCard = button.closest('.track-card');
        if (trackCard) {
            const actionsDiv = trackCard.querySelector('.track-actions');
            if (actionsDiv) {
                actionsDiv.innerHTML = '<span class="downloaded-badge">✓ Downloaded</span>';
            }
        }
    }
}

function formatDuration(ms) {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showLoading() {
    loading.classList.remove('hidden');
}

function hideLoading() {
    loading.classList.add('hidden');
}

function showError(message) {
    error.textContent = message;
    error.classList.remove('hidden');
}

function hideError() {
    error.classList.add('hidden');
}

function showResults() {
    results.classList.remove('hidden');
}

function hideResults() {
    results.classList.add('hidden');
}

function showDownloadStatus() {
    downloadStatus.classList.remove('hidden');
    updateQueueCount();
}

function hideDownloadStatus() {
    downloadStatus.classList.add('hidden');
}

function updateQueueCount() {
    const queueCount = document.getElementById('queueCount');
    if (queueCount) {
        const activeCount = Array.from(activeDownloads.values()).filter(s => s.status !== 'completed' && s.status !== 'error').length;
        queueCount.textContent = activeCount > 0 ? `(${activeCount} active)` : '';
    }
}

// ============ ALBUM FUNCTIONS ============

function displayAlbums(albums) {
    // Show albums list, hide tracks list
    albumsList.classList.remove('hidden');
    tracksList.classList.add('hidden');
    
    if (albums.length === 0) {
        albumsList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No albums found</p>';
        return;
    }
    
    albumsList.innerHTML = albums.map(album => createAlbumCard(album)).join('');
    
    // Add click handlers
    albums.forEach(album => {
        const card = document.getElementById(`album-${album.id}`);
        if (card) {
            card.addEventListener('click', () => showAlbumDetails(album.id));
        }
    });
}

function createAlbumCard(album) {
    const albumArt = album.album_art || 'https://via.placeholder.com/120?text=No+Image';
    const year = album.release_date ? album.release_date.split('-')[0] : '';
    
    return `
        <div class="album-card" id="album-${album.id}">
            <img src="${albumArt}" alt="${escapeHtml(album.name)}" class="album-art" />
            <div class="album-info">
                <div class="album-name">${escapeHtml(album.name)}</div>
                <div class="album-artist">${escapeHtml(album.artist)}</div>
                <div class="album-meta">${album.total_tracks} tracks${year ? ' • ' + year : ''}</div>
            </div>
        </div>
    `;
}

let currentAlbum = null;

async function showAlbumDetails(albumId) {
    try {
        const response = await fetch(`api/album/${encodeURIComponent(albumId)}?provider=${encodeURIComponent(getMetadataProvider())}`);
        if (!response.ok) throw new Error('Failed to fetch album');
        
        const album = await response.json();
        currentAlbum = album;
        
        const modal = document.getElementById('albumModal');
        const title = document.getElementById('albumModalTitle');
        const details = document.getElementById('albumDetails');
        const tracksList = document.getElementById('albumTracksList');
        
        title.textContent = album.name;
        
        const albumArt = album.album_art || 'https://via.placeholder.com/150?text=No+Image';
        const year = album.release_date ? album.release_date.split('-')[0] : '';
        
        details.innerHTML = `
            <div class="album-header">
                <img src="${albumArt}" alt="${escapeHtml(album.name)}" class="album-detail-art" />
                <div class="album-header-info">
                    <h3>${escapeHtml(album.name)}</h3>
                    <p class="album-header-artist">${escapeHtml(album.artist)}</p>
                    <p class="album-header-meta">${album.total_tracks} tracks${year ? ' • ' + year : ''}</p>
                </div>
            </div>
        `;
        
        tracksList.innerHTML = album.tracks.map((track, index) => `
            <div class="album-track">
                <span class="track-number">${track.track_number || index + 1}</span>
                <div class="track-details">
                    <span class="track-title">${escapeHtml(track.name)}</span>
                    <span class="track-duration">${formatDuration(track.duration_ms)}</span>
                </div>
            </div>
        `).join('');
        
        modal.classList.remove('hidden');
    } catch (err) {
        showError(`Failed to load album: ${err.message}`);
    }
}

function hideAlbumModal() {
    document.getElementById('albumModal').classList.add('hidden');
    currentAlbum = null;
}

async function downloadAlbum() {
    if (!currentAlbum) return;
    
    const downloadLocation = document.getElementById('downloadLocation').value;
    const formatSelect = document.getElementById('audioFormat');
    const qualitySelect = document.getElementById('audioQuality');
    const format = (formatSelect && formatSelect.value) ? formatSelect.value : defaultFormat;
    const quality = (qualitySelect && qualitySelect.value) ? qualitySelect.value : defaultQuality;
    
    try {
        const response = await fetch(`api/download/album`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                album_id: currentAlbum.id,
                location: downloadLocation,
                format: format,
                quality: quality,
                provider: getMetadataProvider(),
            })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to start album download');
        }
        
        const result = await response.json();
        
        // Show download status
        showDownloadStatus();

        const queuedIds = new Set(result.queued_track_ids || []);
        const tracksToPoll = currentAlbum.tracks.filter(t => queuedIds.has(t.id));

        tracksToPoll.forEach(track => {
            activeDownloads.set(track.id, { status: 'queued', progress: 0, track: track });
            addStatusItem(track.id, track, 'queued', `Queued (Album: ${currentAlbum.name})`, 0);
            pollDownloadStatus(track.id, track);
        });
        
        hideAlbumModal();
        
    } catch (err) {
        showError(`Album download failed: ${err.message}`);
    }
}

// Album modal event listeners
document.getElementById('albumModalClose')?.addEventListener('click', hideAlbumModal);
document.getElementById('closeAlbumModal')?.addEventListener('click', hideAlbumModal);
document.getElementById('downloadAlbumBtn')?.addEventListener('click', downloadAlbum);
document.getElementById('albumModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'albumModal') hideAlbumModal();
});

