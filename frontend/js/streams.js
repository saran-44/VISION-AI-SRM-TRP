import { el, icon, setState } from './ui.js';

function demoPlaceholder(label) {
  return el('div', { class: 'camera-placeholder' }, [
    icon('bx-cctv'),
    el('span', { text: 'Demo footage' }),
    el('span', { class: 'muted', text: 'No live stream configured', style: 'color:#cbd5e1;font-size:.75rem;font-weight:500;' }),
  ]);
}

function hlsPlayer(url, stateHost) {
  const video = el('video', {
    class: 'camera-stream',
    autoplay: true,
    muted: true,
    playsinline: true,
    controls: false,
    'aria-label': 'Configured HLS camera stream',
  });
  const Hls = window.Hls;
  if (Hls && Hls.isSupported()) {
    const player = new Hls({ lowLatencyMode: true });
    player.loadSource(url);
    player.attachMedia(video);
    player.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) setState(stateHost, 'error', 'The configured HLS stream could not be played.');
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = url;
  } else {
    setState(stateHost, 'error', 'This browser cannot play the configured HLS stream.');
  }
  return video;
}

function mjpegPlayer(url, stateHost) {
  const image = el('img', {
    class: 'camera-stream',
    src: url,
    alt: 'Configured MJPEG camera stream',
  });
  image.addEventListener('error', () => setState(stateHost, 'error', 'The configured MJPEG stream could not be loaded.'));
  return image;
}

export function renderCameras(host, cameras = []) {
  host.replaceChildren();
  if (!cameras.length) {
    setState(host, 'empty', 'No camera tiles are configured.');
    return;
  }
  cameras.forEach((camera) => {
    const badge = el('span', {
      class: `status-badge stream-badge ${camera.demo ? 'demo' : 'live'}`.trim(),
    }, [
      icon(camera.demo ? 'bx-video-off' : 'bx-broadcast'),
      el('span', { text: camera.demo ? 'Demo footage' : 'Live stream' }),
    ]);
    const stateHost = el('div', { class: 'camera-state' });
    const container = el('div', { class: 'camera-container' }, [stateHost]);
    if (camera.demo) {
      container.append(demoPlaceholder(camera.label));
    } else if (camera.stream_type === 'hls') {
      container.append(hlsPlayer(camera.stream_url, stateHost));
    } else if (camera.stream_type === 'mjpeg') {
      container.append(mjpegPlayer(camera.stream_url, stateHost));
    } else {
      container.append(demoPlaceholder(camera.label));
    }
    host.append(el('div', { class: 'card camera-tile' }, [
      el('div', { class: 'card-header' }, [
        el('h2', { class: 'card-title', style: 'font-size:1rem;' }, [icon('bx-cctv'), el('span', { text: camera.label })]),
        badge,
      ]),
      container,
    ]));
  });
}
