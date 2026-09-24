export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatRequest {
  message: string;
  conversationId?: string;
  apiKey: string;
  model: string;
}

export interface OllamaModelInfo {
  name: string;
  size: number;
  modified_at?: string | null;
  embedding_only?: boolean;
}

export interface OllamaModelsResponse {
  available: boolean;
  models: OllamaModelInfo[];
}

export const ollamaApi = {
  listModels: async (): Promise<OllamaModelsResponse> => {
    try {
      const response = await fetch(`${API_BASE_URL}/ollama/models`, {
        cache: "no-store",
      });
      if (!response.ok) return { available: false, models: [] };
      return response.json();
    } catch {
      return { available: false, models: [] };
    }
  },
};

export const chatApi = {
  sendMessage: async (
    data: ChatRequest,
  ): Promise<ReadableStream<Uint8Array>> => {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });

    if (!response.body) {
      throw new Error("No response body");
    }

    return response.body;
  },
};
