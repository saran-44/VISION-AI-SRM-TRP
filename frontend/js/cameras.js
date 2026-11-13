/**
 * Camera access for the SRM TRP Transport console.
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

function withCacheBuster(rawUrl) {
  const separator = rawUrl.includes('?') ? '&' : '?';
  return `${rawUrl}${separator}_t=${Date.now()}`;
}

function mjpegPlayer(url, stateHost) {
  const REFRESH_MS = 45000;
  const RETRY_MS = 3000;
  let retryTimer = null;
  let disposed = false;

  const image = el('img', {
    class: 'camera-stream',
    src: withCacheBuster(url),
    alt: 'Live MJPEG camera stream',
  });

  const refresh = () => {
    if (disposed) return;
    if (!image.isConnected) {
      cleanup();
      return;
    }
    if (document.hidden) return;
    image.src = withCacheBuster(url);
  };

  const refreshTimer = window.setInterval(refresh, REFRESH_MS);

  const onLoad = () => {
    if (retryTimer) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    stateHost.replaceChildren();
  };

  const onError = () => {
    setState(stateHost, 'error', 'The MJPEG stream could not be loaded.');
    if (!disposed && image.isConnected && !document.hidden && !retryTimer) {
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        refresh();
      }, RETRY_MS);
    }
  };

  const onVisibilityChange = () => {
    if (!image.isConnected) {
      cleanup();
      return;
    }
    if (!document.hidden) {
      refresh();
    }
  };

  const cleanup = () => {
    if (disposed) return;
    disposed = true;
    window.clearInterval(refreshTimer);
    if (retryTimer) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    image.removeEventListener('load', onLoad);
    image.removeEventListener('error', onError);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    image.removeAttribute('src');
  };

  image.addEventListener('load', onLoad);
  image.addEventListener('error', onError);
  document.addEventListener('visibilitychange', onVisibilityChange);
  image._cleanupStream = cleanup;
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
      style: 'color:#cbd5e1;font-size:.72rem;font-weight:500;max-width:32ch;text-align:center;line-height:1.4;',
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
  let mjpegElement = null;

  const stop = () => {
    stopStream(stream);
    stream = null;
    if (mjpegElement && typeof mjpegElement._cleanupStream === 'function') {
      mjpegElement._cleanupStream();
      mjpegElement = null;
    }
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
    if (onCapture) {
      controls.append(el('button', {
        class: 'btn btn-primary camera-btn',
        type: 'button',
        onclick: async () => {
          const canvas = document.createElement('canvas');
          canvas.width = video.videoWidth || 1280;
          canvas.height = video.videoHeight || 720;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9));
          if (blob) await onCapture(blob, { cameraId: id, label });
        },
      }, [icon('bx-scan'), el('span', { text: 'Scan plate' })]));
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
    mjpegElement = mjpegPlayer(url, stateHost);
    container.append(mjpegElement);
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
  if (!cameras.length) {
    setState(host, 'empty', 'No camera tiles are configured.');
    return;
  }
  cameras.forEach((camera) => {
    host.append(renderCameraTile({
      id: camera.id,
      label: camera.label,
      source: camera.stream_type || (camera.demo ? 'demo' : 'demo'),
      url: camera.stream_url,
      onCapture: handlers.onCapture,
    }));
  });
}
