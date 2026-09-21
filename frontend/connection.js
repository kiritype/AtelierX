export async function autoConnection(ApiClient) {
  const api = new ApiClient();
  try {
    await api.get("/health");
    return {kind: "connected", api};
  } catch (healthError) {
    if (healthError?.status !== 401) return {kind: "unreachable", error: healthError};
  }
  try {
    const connection = await api.get("/v1/frontend-connection");
    return {kind: "connection_settings", api, connection};
  } catch (error) {
    if (error?.status === 404) return {kind: "manual", error};
    if (error?.status === 401 || error?.status === 403) return {kind: "auth_required", error};
    return {kind: "unreachable", error};
  }
}

export function connectionMessage(result, publicOrigin) {
  if (result.kind === "auth_required") return `Core 인증이 필요합니다. Cloudflare Access를 사용한다면 ${publicOrigin}에서 로그인한 뒤 다시 시도하세요. 기존 Core라면 아래에 토큰을 입력하세요.`;
  if (result.kind === "unreachable") return `Core에 연결할 수 없습니다. 서비스와 네트워크를 확인하세요. Cloudflare Access를 사용한다면 ${publicOrigin}에서 로그인 상태도 확인하세요.`;
  return "Core 토큰을 입력해 연결하세요.";
}
