/** Shared, serializable fragment-list state.  Selection uses the immutable
 * fragment revision so it remains valid while a user pages or searches. */
export function fragmentReference(item) {
  if (!item?.id || !Number.isInteger(Number(item.revision)) || Number(item.revision) < 1) {
    throw new Error("조각의 ID와 revision이 필요합니다.");
  }
  return { id: String(item.id), revision: Number(item.revision) };
}

export function fragmentKey(reference) {
  const value = fragmentReference(reference);
  return `${value.id}@${value.revision}`;
}

export function sameFragmentReference(left, right) {
  return fragmentKey(left) === fragmentKey(right);
}

export function fragmentListPath({ query = "", categoryId = "", archived = false, limit = 25, offset = 0, sort = "name" } = {}) {
  const params = new URLSearchParams({ archived: String(Boolean(archived)), limit: String(limit), offset: String(Math.max(0, offset)) });
  if (sort) params.set("sort", sort);
  if (String(query).trim()) params.set("q", String(query).trim());
  if (categoryId) params.set("category_id", categoryId);
  return `/v1/prompt-fragments?${params}`;
}

export function pageOffsetForTotal(offset, limit, total) {
  if (!total) return 0;
  return Math.min(Math.max(0, offset), Math.floor((total - 1) / limit) * limit);
}

export function preserveSelection(selection, item, checked) {
  const next = new Map((selection || []).map((value) => [fragmentKey(value), fragmentReference(value)]));
  const reference = fragmentReference(item);
  if (checked) next.set(fragmentKey(reference), reference); else next.delete(fragmentKey(reference));
  return [...next.values()];
}
