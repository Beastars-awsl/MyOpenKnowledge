"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ollamaApi,
  type OllamaModelInfo,
} from "@/lib/api";
import {
  SUPPORTED_MODELS,
  type ModelConfig,
} from "@/stores/settings";

export type DetectedModel = ModelConfig & { embeddingOnly?: boolean };

interface OllamaModelsState {
  available: boolean;
  detected: DetectedModel[];
  loading: boolean;
  refresh: () => void;
}

function toModelConfig(info: OllamaModelInfo): DetectedModel {
  const sizeGB = info.size ? ` · ${(info.size / 1e9).toFixed(1)}GB` : "";
  const typeLabel = info.embedding_only ? "嵌入模型" : "对话模型";
  return {
    id: info.name,
    name: `${info.name} (本地 Ollama)`,
    provider: "ollama",
    description: `本地已安装 · ${typeLabel}${sizeGB}`,
    embeddingOnly: info.embedding_only,
  };
}

/**
 * 拉取本地 Ollama 已安装模型（含嵌入模型，供设置页展示）。
 * 探测失败时 detected 为空，由 mergeWithStaticModels 保留静态提示项。
 */
export function useOllamaModels(): OllamaModelsState {
  const [available, setAvailable] = useState(false);
  const [detected, setDetected] = useState<DetectedModel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    ollamaApi.listModels().then((res) => {
      if (cancelled) return;
      setAvailable(res.available);
      setDetected(res.models.map(toModelConfig));
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    ollamaApi.listModels().then((res) => {
      if (cancelled) return;
      setAvailable(res.available);
      setDetected(res.models.map(toModelConfig));
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return { available, detected, loading, refresh };
}

/**
 * 用检测到的本地模型替换静态 ollama 项；纯嵌入模型不进入对话选择列表；
 * 探测失败（无对话模型）时保留静态项作为 pull 提示。
 */
export function mergeWithStaticModels(detected: DetectedModel[]): ModelConfig[] {
  const chatModels = detected.filter((m) => !m.embeddingOnly);
  const nonOllama = SUPPORTED_MODELS.filter((m) => m.provider !== "ollama");
  if (chatModels.length === 0) {
    return [...SUPPORTED_MODELS];
  }
  return [...chatModels, ...nonOllama];
}
