const PREFIX = "/api/v1";
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(PREFIX + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const value = await response
      .json()
      .catch(() => ({ message: response.statusText }));
    throw new Error(value.message ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export function command<T = { accepted: boolean; new_run_id?: string }>(
  id: string,
  type: string,
  payload: object = {},
) {
  return post<T>(`/simulations/${id}/commands`, {
    command_id: crypto.randomUUID(),
    type,
    payload,
  });
}
