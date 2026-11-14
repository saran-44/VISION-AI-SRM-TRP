/**
 * Detection stages — the shared state behind the sticker / plate / vehicle
 * switches.
 *
 * The cascade runs server-side; the browser only chooses which stages it wants
 * for the scans it sends. The choice is kept in `localStorage` so the dashboard
 * and the Test Lab agree: an operator who turns sticker detection off on the
 * bench does not want it silently back on at the gate.
 */
import { clear, el } from './ui.js';

export const STAGES = [
  { key: 'sticker', label: 'Sticker', note: 'best.pt — reads the number off the sticker' },
  { key: 'plate', label: 'Number plate', note: 'fallback when the sticker reads nothing' },
  { key: 'vehicle', label: 'Vehicle type', note: 'bus / car / bike classification' },
];

const STORAGE_KEY = 'vision-stages';

/** Friendly names for the `cascade` value the API returns. */
const CASCADE_TEXT = { sticker: 'sticker', number_plate: 'number plate', vehicle: 'vehicle type' };

function readFlags() {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {};
  } catch (_error) {
    stored = {};
  }
  const flags = {};
  for (const stage of STAGES) flags[stage.key] = stored[stage.key] !== false;
  return flags;
}

let flags = readFlags();

/** Current switches, as a plain object. */
export function currentStageFlags() {
  return { ...flags };
}

/** Flip one stage and remember it. */
export function setStageFlag(key, value) {
  flags = { ...flags, [key]: Boolean(value) };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(flags));
  } catch (_error) {
    // Private mode with storage disabled: the switches still work for this page.
  }
  return currentStageFlags();
}

/** Add one form field per stage, so the backend sees the panel's choice. */
export function appendStagesToForm(body) {
  for (const stage of STAGES) body.append(stage.key, flags[stage.key] ? '1' : '0');
}

/** `number_plate` -> `number plate`; unknown values pass through. */
export function cascadeText(cascade) {
  return CASCADE_TEXT[cascade] || cascade || '';
}

/** One human sentence for a scan result, used by both pages. */
export function describeScan(payload = {}) {
  const vehicle = payload.vehicle || null;
  const vehicleText = vehicle ? ` · ${vehicle.label}` : '';
  const stage = cascadeText(payload.stage);
  if (payload.bus_number) {
    return {
      good: true,
      text: `Read ${payload.bus_number} (${Math.round((payload.confidence || 0) * 100)}%)`
        + (stage ? ` · from the ${stage}` : '') + vehicleText,
    };
  }
  if (vehicle) {
    return { good: true, text: `No number read · looks like a ${vehicle.label}` };
  }
  const detection = payload.detection || {};
  if (payload.reason === 'below_threshold') {
    return {
      good: false,
      text: `Plate seen, ${Math.round((detection.best_confidence || 0) * 100)}% — under the `
        + `${Math.round((detection.threshold || 0) * 100)}% threshold.`,
    };
  }
  if (payload.reason === 'unreadable') {
    return { good: false, text: 'Plate found, but the number could not be read.' };
  }
  return { good: false, text: 'Nothing found in this frame.' };
}

/** Draw one chip per stage: what ran, what was skipped and why. */
export function renderStageChips(host, stages) {
  if (!host) return;
  clear(host);
  for (const stage of stages || []) {
    const label = stage.label || stage.name;
    let text;
    let variant = '';
    if (stage.skipped === 'disabled') {
      text = `${label} off`;
      variant = 'is-off';
    } else if (stage.skipped === 'not_needed') {
      text = `${label} not needed`;
      variant = 'is-idle';
    } else if (stage.skipped) {
      text = `${label} unavailable`;
      variant = 'is-off';
    } else if (stage.result === 'identified') {
      text = `${label} ✓`;
      variant = 'is-ok';
    } else if (stage.result === 'seen_unreadable') {
      text = `${label} seen, unreadable`;
      variant = 'is-warn';
    } else {
      text = `${label} found nothing`;
      variant = 'is-idle';
    }
    host.append(el('span', { class: `stage-chip ${variant}`.trim(), text }));
  }
}
