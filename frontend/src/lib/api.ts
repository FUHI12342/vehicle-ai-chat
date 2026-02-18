import { API_BASE } from "./constants";
import type {
  ChatRequest,
  ChatResponse,
  VehicleMatch,
  ProviderListResponse,
} from "./types";

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  return fetchJSON<ChatResponse>(`${API_BASE}/chat`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function searchVehicles(
  query: string,
  limit = 10
): Promise<VehicleMatch[]> {
  const data = await fetchJSON<{ results: VehicleMatch[] }>(
    `${API_BASE}/vehicles/search?q=${encodeURIComponent(query)}&limit=${limit}`
  );
  return data.results;
}

export async function getProviders(): Promise<ProviderListResponse> {
  return fetchJSON<ProviderListResponse>(`${API_BASE}/providers`);
}

export async function setActiveProvider(provider: string): Promise<void> {
  await fetchJSON(`${API_BASE}/providers/active`, {
    method: "PUT",
    body: JSON.stringify({ provider }),
  });
}
