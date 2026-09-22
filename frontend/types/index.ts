export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  sources?: SourceRef[];
  verification?: VerificationResult;
}

export interface SourceRef {
  id: string;
  document_id: string;
  title: string;
  chunk_index: number;
  snippet: string;
  score: number;
}

export interface VerificationResult {
  accuracy: 'high' | 'medium' | 'low' | string;
  has_hallucination: boolean;
  issues: string[];
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface Settings {
  openaiApiKey: string;
  model: string;
}
