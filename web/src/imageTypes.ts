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

export type ReviewHistoryEntry = { at: string; path: string; from: string; to: string; source?: string };
