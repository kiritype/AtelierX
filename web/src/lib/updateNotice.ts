const PREFIX = 'atelierx.update-notice.';
const CHECKED_AT = `${PREFIX}checked-at`;
const AVAILABLE = `${PREFIX}available-version`;
const NOTIFIED = `${PREFIX}notified-version`;
const RESULT = `${PREFIX}reported-result`;
export const UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000;

type UpdateSummary = { current: string; latest: string; newer: boolean };
type UpdateResult = { state: 'ok' | 'failed'; version?: string; from?: string };

export function startupUpdateState(storage: Storage, now = Date.now()) {
  const checkedAt = Number(storage.getItem(CHECKED_AT) ?? 0);
  const availableVersion = storage.getItem(AVAILABLE);
  return {
    shouldCheck: !checkedAt || now - checkedAt >= UPDATE_CHECK_INTERVAL,
    availableVersion: availableVersion || null,
  };
}

export function saveStartupUpdate(storage: Storage, result: UpdateSummary, now = Date.now()) {
  storage.setItem(CHECKED_AT, String(now));
  if (!result.newer) {
    storage.removeItem(AVAILABLE);
    return { available: false, shouldNotify: false };
  }
  storage.setItem(AVAILABLE, result.latest);
  const shouldNotify = storage.getItem(NOTIFIED) !== result.latest;
  if (shouldNotify) storage.setItem(NOTIFIED, result.latest);
  return { available: true, shouldNotify };
}

export function shouldReportUpdateResult(storage: Storage, result: UpdateResult) {
  const key = `${result.state}:${result.version ?? ''}:${result.from ?? ''}`;
  if (storage.getItem(RESULT) === key) return false;
  storage.setItem(RESULT, key);
  return true;
}
