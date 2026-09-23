export const OUTFIT_PARTS = Object.freeze(["upper", "lower", "accessories", "hands"]);
export const PART_LABELS = Object.freeze({upper: "상의", lower: "하의", accessories: "액세서리", hands: "손"});
export const FRAGMENT_NUMBER_MAX = 32;
const RESERVED_NAMES = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i;

export function normalizeFragmentInclude(include) {
  const value = include && typeof include === "object" ? include : {};
  return {upper: Boolean(value.upper), lower: Boolean(value.lower), accessories: value.accessories !== false, hands: value.hands !== false};
}

export function defaultFragmentInclude() {
  return {upper: true, lower: false, accessories: true, hands: true};
}

export function fragmentNumberError(value) {
  const number = typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
  if (!number) return "이미지별 조각에는 번호가 필요합니다.";
  if (number.length > FRAGMENT_NUMBER_MAX) return `번호는 ${FRAGMENT_NUMBER_MAX}자 이하로 입력하세요.`;
  if (/[\u0000-\u001f\u007f]/.test(number)) return "번호에 제어 문자를 쓸 수 없습니다.";
  if (/[<>:"/\\|?*]/.test(number)) return "번호에 < > : \" / \\ | ? * 문자는 쓸 수 없습니다.";
  if (number !== number.trim()) return "번호의 앞뒤에 공백을 둘 수 없습니다.";
  if (number.endsWith(".")) return "번호는 마침표(.)로 끝날 수 없습니다.";
  if (RESERVED_NAMES.test(number)) return "CON, PRN, AUX, NUL, COM1~9, LPT1~9는 Windows 예약 이름이라 번호로 쓸 수 없습니다.";
  return null;
}

export function fragmentIncludeSummary(include) {
  const value = normalizeFragmentInclude(include);
  const parts = OUTFIT_PARTS.filter((name) => value[name]).map((name) => PART_LABELS[name]);
  return parts.length ? `포함: ${parts.join("·")}` : "포함: 의상 없음";
}

export function fragmentLabel(fragment) {
  if (!fragment) return "";
  const number = fragment.number ?? fragment.display_number;
  const hasNumber = number !== null && number !== undefined && String(number) !== "";
  return `${hasNumber ? `#${number} ` : ""}${fragment.name || ""}`.trim();
}

export function inclusionLabels(inclusion) {
  if (!inclusion || typeof inclusion !== "object") return [];
  return OUTFIT_PARTS.filter((name) => inclusion[name] !== undefined).map((name) => {
    const entry = inclusion[name];
    const included = entry && typeof entry === "object" ? Boolean(entry.included) : Boolean(entry);
    return `${PART_LABELS[name]}: ${included ? "포함" : "제외"}`;
  });
}

export function parseCheckFeatures(text) {
  return String(text ?? "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

export function checkFeaturesError(features) {
  if (features.length > 50) return "검사용 핵심 특징은 50개 이하로 입력하세요.";
  if (features.some((item) => item.length > 200)) return "검사용 핵심 특징은 한 줄에 200자 이하로 입력하세요.";
  return null;
}

export function duplicateNumberMessage(number, duplicates) {
  const names = (duplicates || []).map((item) => `${item.name || item.id}${item.archived ? "(보관됨)" : ""}`);
  const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? ` 외 ${names.length - 3}개` : "");
  return `번호 ${number}은(는) 이미 다른 조각(${shown})에서 사용 중입니다. 같은 번호로 저장하면 이미지 파일명에 (2) 같은 번호가 붙습니다. 저장할까요?`;
}

export function saveWarningMessages(warnings) {
  return (Array.isArray(warnings) ? warnings : []).map((warning) => warning?.code === "duplicate_number"
    ? `번호 ${warning.number}을(를) 다른 조각도 사용합니다. 이미지 파일명에 (2) 같은 번호가 붙을 수 있습니다.`
    : `저장 경고: ${warning?.code || "알 수 없음"}`);
}
