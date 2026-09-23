/**
 * Shared "sort by name ascending" comparator used by every classification
 * tree/list in the Frontend (캐릭터 관리 tree, 조각 관리 list, 이미지 생성 trees).
 *
 * Users put ordering codes into names (e.g. "C001 - 이름"), so plain codepoint
 * order reads wrong once numbers reach two digits. `localeCompare` with
 * `numeric: true` treats embedded digit runs as numbers ("C2" < "C10").
 * Ties fall back to id so the order is deterministic across re-renders and
 * pages.
 */
export function compareByName(left, right) {
  const leftName = String(left?.name ?? "");
  const rightName = String(right?.name ?? "");
  const byName = leftName.localeCompare(rightName, "ko", { numeric: true, sensitivity: "base" });
  if (byName !== 0) return byName;
  const leftId = String(left?.id ?? "");
  const rightId = String(right?.id ?? "");
  return leftId < rightId ? -1 : leftId > rightId ? 1 : 0;
}

/** Returns a new array sorted by name ascending (does not mutate `items`). */
export function sortByName(items) {
  return Array.isArray(items) ? [...items].sort(compareByName) : [];
}
