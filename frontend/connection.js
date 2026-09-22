export async function autoConnection(ApiClient) {
  const api = new ApiClient();
  try {
    await api.get("/health");
    return {kind: "connected", api};
  } catch (healthError) {
    if (healthError?.status !== 401 && healthError?.status !== 403) return {kind: "unreachable", api, error: healthError};
  }
  try {
    const connection = await api.get("/v1/frontend-connection");
    return {kind: "connection_settings", api, connection};
  } catch (error) {
    if (error?.status === 404) return {kind: "manual", api, error};
    if (error?.status === 401 || error?.status === 403) return {kind: "auth_required", api, error};
    return {kind: "unreachable", api, error};
  }
}

export function connectionMessage(result, publicOrigin) {
  if (result.kind === "auth_required") return `Core 인증이 필요합니다. Cloudflare Access를 사용한다면 ${publicOrigin}에서 로그인한 뒤 설정의 Core 연결로 돌아오세요.`;
  if (result.kind === "unreachable") return `Core에 연결할 수 없습니다. 서비스와 네트워크를 확인하세요. Cloudflare Access를 사용한다면 ${publicOrigin}의 로그인 상태도 확인하세요.`;
  return "Core 연결 설정에서 Bearer 토큰으로 연결할 수 있습니다.";
}
