import { useEffect, useState } from "react";

export type ApiState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
};

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (import.meta.env.DEV && import.meta.env.VITE_USE_BACKEND !== "true" && path.startsWith("/api")) {
    throw new Error("Modo demo local: backend nao conectado.");
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null as T;
  }
  return response.json() as Promise<T>;
}

export function useApi<T>(path: string): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, loading: true, error: null });
    apiRequest<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error: error.message });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return state;
}
