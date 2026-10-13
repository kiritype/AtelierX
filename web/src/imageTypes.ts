// Answers of the image API that several screens read (#159). Server message fields are ServerMsg (translate with tm).
import type { ServerMsg } from './i18n';
import type { Method } from './lib/toolMethods';

// A ComfyUI tool: usable, or why not (ComfyUI not reachable, or nodes missing). Check `available` before the rest.
type Unavailable = { available: false; reason?: 'offline' | 'nodes'; error?: ServerMsg | string };
type Available<T> = T & { available: true; reason?: undefined; error?: undefined };
export type ToolInfo = Unavailable | Available<object>;

// GET /api/image/tools/tagger; the excluded tags come either way.
export type TaggerInfo = (Unavailable | Available<{ models: string[]; defaults: { model: string; threshold: number; character_threshold: number } }>) & {
  exclude?: string[];
};

// GET /api/image/tools/postprocess
export type PostInfo = Unavailable | Available<{ prefix: string; ops: Record<string, ServerMsg>; upscale_models: string[]; rembg: boolean }>;

// GET /api/image/tools/methods
export type ToolMethods = { methods: Method[]; features: Record<string, string[]> };

// Settings → image → training (23-lora-training).
export type Training = { trainer_dir: string; trainer_python: string; lora_dir: string; bases: Record<string, { dit: string; text_encoder: string; vae: string }> };

// GET /api/image/training/status
export type TrainingStatus = {
  settings: Training;
  trainer_found: boolean;
  python_found: boolean;
  patched: boolean;
  lora_dir_found: boolean;
  files: Record<string, boolean>;
  bases: { id: string; label: string }[];
  methods: { id: string; label: string }[];
};

export type LoraRef = { name: string; strength?: number; model_strength?: number; clip_strength?: number };

export type GenerationSettings = {
  model?: string;
  family?: string;
  sampler?: string;
  scheduler?: string;
  steps?: number;
  cfg?: number;
  width?: number;
  height?: number;
  loras?: LoraRef[];
  [key: string]: unknown;
};

// The generation record next to an image (data-model: 생성 기록), as much as the screens read.
export type GenerationRecord = {
  postprocessing?: { op?: string; source_image?: string | null };
  op?: string;
  source?: { source?: string; path?: string | null };
  positive?: string;
  negative?: string;
  seed?: number;
  image_size?: number[];
  created_at?: string;
  generation_preset?: { name?: string } | null;
  settings?: GenerationSettings;
  common_ids?: string[] | null;
  style_ids?: string[] | null; // before #169
  artist?: { positive?: string; negative?: string } | null;
  [key: string]: unknown;
};

export type SingleService = 'comfyui' | 'novelai' | 'pixai';
export type SingleRequest = {
  positive: string;
  negative: string;
  service: SingleService;
  settings: Record<string, unknown>;
  preset_id: string;
};
export type SingleRun = {
  id: string;
  status: 'queued' | 'running' | 'cancelling' | 'done' | 'failed' | 'cancelled' | 'interrupted';
  created_at: string;
  service: SingleService;
  seed: number;
  request: SingleRequest | null;
  actual: { positive: string; negative: string; settings: Record<string, unknown> };
  image_url?: string | null;
  path?: string | null;
  error?: ServerMsg | string | null;
};
export type SingleRuns = { runs: SingleRun[] };

export type ReviewHistoryEntry = { at: string; path: string; from: string; to: string; source?: string };

export type GalleryToolsResponse = { ok: boolean; added: { id: string; path: string }[]; items: { id: string; path: string }[] };
export type DeployTarget = { id: string; name: string; ready: boolean; path_format: string; public_url: string };
export type DeployRow = {
  source: string;
  thumbnail_url?: string;
  character_id: string;
  outfit_id: string;
  outfit_code: string;
  expression_id: string;
  expression_name: string;
  expression_code: string;
  rating: string;
  auto_path: string | null;
  path: string | null;
  edited: boolean;
  status: 'new' | 'existing' | 'unchanged' | 'no_code' | 'clash';
  url?: string;
};
export type DeployPlan = { target: string; target_name: string; public_url: string; path_format: string; rows: DeployRow[]; counts: Record<string, number>; missing: string[] };
export type DeployResult = { source: string; path: string; url: string; ok: boolean; overwrote: boolean; status: string; error?: ServerMsg | string; log_error?: ServerMsg | string };
export type DeployRun = { id: string; status: string; total: number; done: number; results: DeployResult[]; current: { source: string; path: string; status: string } | null };
export type DeployHistory = { records: (DeployResult & { at: string; target_name: string })[] };
