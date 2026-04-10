export type Provider = "openrouter" | "gemini" | "nvidia";

export type VisualStyle = "notebooklm" | "modern" | "dark" | "auto";

export interface AgentModels {
  analyzer?: string | null;
  planner?: string | null;
  designer?: string | null;
  assembler?: string | null;
  critic?: string | null;
}

export interface RenderOptions {
  provider?: Provider | null;
  models?: AgentModels | null;
  model_all?: string | null;
  visual_style?: VisualStyle | null;
  max_iterations?: number | null;
  pass_threshold?: number | null;
  design_seed?: number | null;
  html_only?: boolean;
  credential_ids?: string[] | null;
}

export interface RenderJsonBody extends RenderOptions {
  text?: string | null;
  structured?: Record<string, unknown> | null;
}

export interface UserOut {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface JobOut {
  id: string;
  status: string;
  error_message: string | null;
  input_filename: string | null;
  output_pdf_path: string | null;
  result_json: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

export interface PreferencesOut {
  settings: Record<string, unknown>;
}

export interface PreferencesBody {
  provider?: Provider | null;
  models?: AgentModels | null;
  model_all?: string | null;
  visual_style?: VisualStyle | null;
  max_iterations?: number | null;
  pass_threshold?: number | null;
  max_data_chars?: number | null;
}

export interface LLMKeyOut {
  id: string;
  provider: string;
  label: string;
  masked_hint: string;
  created_at: string;
}

export interface LLMKeyCreate {
  provider: Provider;
  api_key: string;
  label?: string;
}

export interface ChatThreadOut {
  id: string;
  title: string;
  created_at: string;
}

export interface ChatMessageOut {
  id: string;
  thread_id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface ChatMessageCreate {
  role: "user" | "assistant" | "system";
  content: string;
}
