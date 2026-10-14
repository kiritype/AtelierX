const PREFIX = 'atelierx.update-notice.';
const CHECKED_AT = `${PREFIX}checked-at`;
const AVAILABLE = `${PREFIX}available-version`;
const NOTIFIED = `${PREFIX}notified-version`;
const PENDING_NOTICE = `${PREFIX}pending-notice`;
const RESULT = `${PREFIX}reported-result`;
export const UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000;

export type UpdateSummary = { current: string; latest: string; newer: boolean };
type UpdateResult = { state: 'ok' | 'failed'; version?: string; from?: string };

let inFlight: Promise<UpdateSummary> | null = null;
let memoryCheckedAt = 0;
let memoryAvailable: string | null = null;
let memoryNotified: string | null = null;
let memoryPendingNotice: UpdateSummary | null = null;
let memoryReportedResult: string | null = null;
let memoryOnlyStorage = false;

function read(storage: Storage | null, key: string, fallback: string | null) {
  if (!storage || memoryOnlyStorage) return fallback;
  try {
    return storage.getItem(key);
  } catch {
    memoryOnlyStorage = true;
    return fallback;
  }
}

function write(storage: Storage | null, key: string, value: string) {
  if (!storage || memoryOnlyStorage) return;
  try {
    storage.setItem(key, value);
  } catch {
    memoryOnlyStorage = true;
    // Module memory keeps the current session coherent when browser storage is unavailable.
  }
}

function remove(storage: Storage | null, key: string) {
  if (!storage || memoryOnlyStorage) return;
  try {
    storage.removeItem(key);
  } catch {
    memoryOnlyStorage = true;
    // Module memory is cleared by the caller as well.
  }
}

function pendingNotice(storage: Storage | null) {
  if (memoryPendingNotice) return memoryPendingNotice;
  const saved = read(storage, PENDING_NOTICE, null);
  if (!saved) return null;
  try {
    const parsed = JSON.parse(saved) as UpdateSummary;
    return parsed && typeof parsed.latest === 'string' && parsed.newer ? parsed : null;
  } catch {
    return null;
  }
}

export function startupUpdateState(storage: Storage | null, now = Date.now()) {
  const savedCheckedAt = Number(read(storage, CHECKED_AT, String(memoryCheckedAt)) ?? 0);
  const availableVersion = read(storage, AVAILABLE, memoryAvailable) || null;
  return {
    shouldCheck: !savedCheckedAt || now - savedCheckedAt >= UPDATE_CHECK_INTERVAL,
    availableVersion,
    pendingNotice: !!pendingNotice(storage),
  };
}

export function saveStartupUpdate(storage: Storage | null, result: UpdateSummary, now = Date.now()) {
  memoryCheckedAt = now;
  write(storage, CHECKED_AT, String(now));
  if (!result.newer) {
    memoryAvailable = null;
    memoryPendingNotice = null;
    remove(storage, AVAILABLE);
    remove(storage, PENDING_NOTICE);
    return { available: false, shouldNotify: false };
  }
  memoryAvailable = result.latest;
  write(storage, AVAILABLE, result.latest);
  const wasNotified = read(storage, NOTIFIED, memoryNotified) === result.latest;
  const shouldNotify = !wasNotified;
  if (shouldNotify) {
    memoryPendingNotice = result;
    write(storage, PENDING_NOTICE, JSON.stringify(result));
  }
  return { available: true, shouldNotify };
}

export function takeStartupUpdateNotice(storage: Storage | null) {
  const result = pendingNotice(storage);
  if (!result) return null;
  if (read(storage, NOTIFIED, memoryNotified) === result.latest) {
    memoryPendingNotice = null;
    remove(storage, PENDING_NOTICE);
    return null;
  }
  memoryNotified = result.latest;
  memoryPendingNotice = null;
  write(storage, NOTIFIED, result.latest);
  remove(storage, PENDING_NOTICE);
  return result;
}

// The request and unresolved notice outlive a screen component so route changes cannot lose a result.
export function beginStartupUpdateCheck(storage: Storage | null, check: () => Promise<UpdateSummary>, now = Date.now()) {
  if (inFlight) return inFlight;
  if (!startupUpdateState(storage, now).shouldCheck) return null;
  memoryCheckedAt = now;
  write(storage, CHECKED_AT, String(now));
  const started = Promise.resolve()
    .then(check)
    .then((result) => {
      saveStartupUpdate(storage, result);
      return result;
    })
    .finally(() => {
      if (inFlight === started) inFlight = null;
    });
  inFlight = started;
  return started;
}

export function shouldReportUpdateResult(storage: Storage | null, result: UpdateResult) {
  const key = `${result.state}:${result.version ?? ''}:${result.from ?? ''}`;
  if (read(storage, RESULT, memoryReportedResult) === key) return false;
  memoryReportedResult = key;
  write(storage, RESULT, key);
  return true;
}
