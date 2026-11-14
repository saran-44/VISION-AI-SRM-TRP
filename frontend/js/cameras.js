/**
 * Camera access for the VISION AI - SRM TRP console.
 *
 * Three source kinds are supported:
 *
 *   1. `browser`  — the operator's own webcam through `getUserMedia`.
 *                   This is the "live camera now" path: it needs no server
 *                   and no extra hardware.
 *   2. `hls`      — an HLS playlist served by an NVR/DVR (or by a
 *                   MediaMTX/FFmpeg gateway that transcodes RTSP to HLS).
 *                   Played with the vendored hls.js.
 *   3. `mjpeg`    — a multipart MJPEG endpoint served by an NVR/DVR or the
 *                   backend's `/api/stream/<camera_id>` proxy.
 *
 * Raw RTSP is intentionally NOT supported: browsers cannot open an RTSP
 * socket. An RTSP camera must be bridged by a gateway/transcoder (MediaMTX,
 * FFmpeg, NVR's built-in "stream to HLS") and then consumed here as HLS or
 * MJPEG. See docs/CAMERAS.md for the recommended setups.
 */

import { el, icon, setState } from './ui.js';

const CAMERA_LABELS = {
  browser: 'This device (webcam)',
  hls: 'Live stream (HLS)',
  mjpeg: 'Live stream (MJPEG)',
  rtsp: 'RTSP source',
  demo: 'Not configured',
};

export function describeSource(source) {
  return CAMERA_LABELS[source] || 'Unknown source';
}

/* ------------------------------------------------------------------ */
/* Browser camera (getUserMedia)                                       */
/* ------------------------------------------------------------------ */

export function isBrowserCameraSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

/**
 * Ask the browser for the webcam and return the media stream.
 * Throws a friendly Error when permission is denied or no device exists.
 */
export async function requestWebcam({ deviceId = null, facingMode = 'environment' } = {}) {
  if (!isBrowserCameraSupported()) {
    throw new Error('This browser does not support camera access.');
  }
  const constraints = deviceId
    ? { video: { deviceId: { exact: deviceId } }, audio: false }
    : { video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false };

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (error) {
    if (error && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
      throw new Error('Camera permission was denied. Allow access in your browser and try again.');
    }
    if (error && error.name === 'NotFoundError') {
      throw new Error('No camera was found on this device.');
    }
    if (error && error.name === 'NotReadableError') {
      throw new Error('The camera is already in use by another application.');
    }
    throw new Error(`Could not start the camera: ${error?.message || 'unknown error'}.`);
  }
  return stream;
}

export function stopStream(stream) {
  if (!stream) return;
  stream.getTracks().forEach((track) => track.stop());
}

export async function listWebcams() {
  if (!isBrowserCameraSupported()) return [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((device) => device.kind === 'videoinput');
  } catch (_error) {
    return [];
  }
}

/* ------------------------------------------------------------------ */
/* Players                                                             */
/* ------------------------------------------------------------------ */

function hlsPlayer(url, stateHost) {
  const video = el('video', {
    class: 'camera-stream',
    autoplay: true,
    muted: true,
    playsinline: true,
    controls: false,
    'aria-label': 'Live HLS camera stream',
  });
  const Hls = window.Hls;
  if (Hls && Hls.isSupported()) {
    const player = new Hls({ lowLatencyMode: true, enableWorker: true });
    player.loadSource(url);
    player.attachMedia(video);
    player.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) {
        setState(stateHost, 'error', 'The HLS stream could not be played. Check the gateway or stream URL.');
      }
    });
    return video;
  }
  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = url;
    return video;
  }
  setState(stateHost, 'error', 'This browser cannot play the HLS stream.');
  return video;
}

function mjpegPlayer(url, stateHost) {
  const image = el('img', {
    class: 'camera-stream',
    src: url,
    alt: 'Live MJPEG camera stream',
  });
  image.addEventListener('error', () => {
    setState(stateHost, 'error', 'The MJPEG stream could not be loaded.');
  });
  return image;
}

function rtspNotice(url, stateHost) {
  // Raw RTSP cannot be played by a browser. Explain the gateway requirement
  // instead of silently showing a dead tile.
  setState(stateHost, 'error', 'Raw RTSP cannot be played in a browser.');
  return el('div', { class: 'camera-placeholder camera-rtsp-notice' }, [
    icon('bx-shield-quarter'),
    el('span', { text: 'RTSP gateway required' }),
    el('span', {
      class: 'muted',
      text: 'Bridge this camera through MediaMTX or FFmpeg to HLS/MJPEG, then point the stream URL at the gateway.',
      style: 'color:#d9cdf3;font-size:.72rem;font-weight:500;max-width:32ch;text-align:center;line-height:1.4;',
    }),
    el('code', {
      class: 'mono',
      text: 'rtsp://…',
      style: 'opacity:.6;font-size:.7rem;',
    }),
  ]);
}

/* ------------------------------------------------------------------ */
/* Tiles                                                               */
/* ------------------------------------------------------------------ */

/**
 * Grab the current video frame as a JPEG blob, at the camera's native size.
 *
 * Deliberately uses `videoWidth`/`videoHeight` and not the CSS box: the tile is
 * displayed letterboxed at 16:9, and a downscaled screenshot would hide the
 * exact detail the detector needs.
 */
async function grabFrame(video) {
  // A <video> that has just been created (or whose stream was replaced) has
  // readyState 0 and no videoWidth. drawImage on it paints nothing, so the
  // canvas stays empty and toBlob still hands back a perfectly valid JPEG of a
  // blank rectangle. The detector then reports "no boxes" and the operator is
  // told there is no plate in a frame that never contained one. Refuse instead:
  // a wrong answer is worse than a wait.
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    throw new Error(
      'The camera has not produced a frame yet. Wait for the preview to appear, then scan again.',
    );
  }
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('The browser could not encode this frame as a JPEG.'));
        return;
      }
      resolve(blob);
    }, 'image/jpeg', 0.92);
  });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = el('a', { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function frameFilename() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `frame-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
    + `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.jpg`;
}

/**
 * Render one camera tile.
 *
 * @param {object} options
 * @param {string} options.id
 * @param {string} options.label
 * @param {'browser'|'hls'|'mjpeg'|'rtsp'|'demo'} options.source
 * @param {string} [options.url]
 * @param {Function} [options.onCapture] called with a canvas blob of the frame
 * @returns {HTMLElement}
 */
export function renderCameraTile(options) {
  const {
    id,
    label,
    source = 'demo',
    url = null,
    onCapture = null,
  } = options;

  const badge = el('span', { class: `status-badge stream-badge ${source}` }, [
    icon(source === 'browser' ? 'bx-video' : source === 'demo' ? 'bx-video-off' : 'bx-broadcast'),
    el('span', { text: describeSource(source) }),
  ]);

  const stateHost = el('div', { class: 'camera-state' });
  const container = el('div', { class: 'camera-container' }, [stateHost]);
  const controls = el('div', { class: 'camera-controls' });
  let stream = null;
  let autoScanTimer = null;
  let autoScanBusy = false;

  const stop = () => {
    if (autoScanTimer) {
      clearInterval(autoScanTimer);
      autoScanTimer = null;
    }
    stopStream(stream);
    stream = null;
  };

  const setPlaceholder = (text) => {
    setState(stateHost, 'empty', text);
  };

  const attachMediaStream = (mediaStream) => {
    stream = mediaStream;
    const video = el('video', {
      class: 'camera-stream',
      autoplay: true,
      muted: true,
      playsinline: true,
      'aria-label': `Live camera: ${label}`,
    });
    video.srcObject = mediaStream;
    stateHost.replaceChildren();
    container.append(video);
    controls.replaceChildren(
      el('button', {
        class: 'btn btn-outline camera-btn',
        type: 'button',
        onclick: () => {
          stop();
          setPlaceholder('Camera stopped.');
        },
      }, [icon('bx-stop'), el('span', { text: 'Stop' })]),
    );
    // Download the exact frame the detector would receive, so a failure can be
    // replayed offline: python scripts/scan_image.py frame-<timestamp>.jpg
    controls.append(el('button', {
      class: 'btn btn-outline camera-btn',
      type: 'button',
      onclick: async () => {
        try {
          downloadBlob(await grabFrame(video), frameFilename());
        } catch (error) {
          setState(stateHost, 'error', error.message);
        }
      },
    }, [icon('bx-download'), el('span', { text: 'Save frame' })]));

    if (onCapture) {
      controls.append(el('button', {
        class: 'btn btn-primary camera-btn',
        type: 'button',
        onclick: async () => {
          try {
            await onCapture(await grabFrame(video), { cameraId: id, label });
          } catch (error) {
            setState(stateHost, 'error', error.message);
          }
        },
      }, [icon('bx-scan'), el('span', { text: 'Scan plate' })]));

      const autoScanButton = el('button', {
        class: 'btn btn-outline camera-btn',
        type: 'button',
        onclick: async () => {
          if (autoScanTimer) {
            clearInterval(autoScanTimer);
            autoScanTimer = null;
            autoScanButton.classList.remove('active');
            autoScanButton.replaceChildren(icon('bx-play'), el('span', { text: 'Auto scan' }));
            return;
          }
          const scan = async () => {
            if (autoScanBusy) return;
            autoScanBusy = true;
            try {
              await onCapture(await grabFrame(video), { cameraId: id, label, automatic: true });
            } catch (_error) {
              // A frame that is not ready yet is normal between ticks; the next
              // one will be. Stopping the timer here would hide a real failure.
            } finally {
              autoScanBusy = false;
            }
          };
          await scan();
          autoScanTimer = setInterval(scan, 3000);
          autoScanButton.classList.add('active');
          autoScanButton.replaceChildren(icon('bx-stop-circle'), el('span', { text: 'Stop auto' }));
        },
      }, [icon('bx-play'), el('span', { text: 'Auto scan' })]);
      controls.append(autoScanButton);
    }
    return video;
  };

  if (source === 'browser') {
    setPlaceholder('Starting camera…');
    requestWebcam()
      .then(attachMediaStream)
      .catch((error) => {
        setState(stateHost, 'error', error.message);
        controls.replaceChildren();
      });
  } else if (source === 'hls' && url) {
    container.append(hlsPlayer(url, stateHost));
  } else if (source === 'mjpeg' && url) {
    container.append(mjpegPlayer(url, stateHost));
  } else if (source === 'rtsp') {
    container.append(rtspNotice(url, stateHost));
  } else {
    setPlaceholder('No stream configured for this camera.');
  }

  const tile = el('div', { class: 'card camera-tile', 'data-camera-id': id }, [
    el('div', { class: 'card-header' }, [
      el('h2', { class: 'card-title', style: 'font-size:1rem;' }, [
        icon('bx-cctv'),
        el('span', { text: label }),
      ]),
      badge,
    ]),
    container,
    controls,
  ]);

  tile.addEventListener('DOMNodeRemovedFromDocument', stop);
  // Modern browsers no longer fire DOMNodeRemovedFromDocument; also clean up
  // when the tile is detached through any other path.
  const observer = new MutationObserver(() => {
    if (!document.body.contains(tile)) {
      stop();
      observer.disconnect();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  return tile;
}

/**
 * Render the whole camera wall.
 *
 * @param {HTMLElement} host
 * @param {Array} cameras
 * @param {object} [handlers]
 */
export function renderCameras(host, cameras = [], handlers = {}) {
  host.replaceChildren();
  const availableCameras = cameras.filter((camera) => !camera.demo && camera.stream_type);
  host.dataset.cameraCount = String(availableCameras.length);
  if (!availableCameras.length) {
    setState(host, 'empty', 'No camera tiles are configured.');
    return;
  }
  availableCameras.forEach((camera) => {
    host.append(renderCameraTile({
      id: camera.id,
      label: camera.label,
      source: camera.stream_type || (camera.demo ? 'demo' : 'demo'),
      url: camera.stream_url,
      onCapture: handlers.onCapture,
    }));
  });
}
