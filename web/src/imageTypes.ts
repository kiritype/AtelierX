// Answers of the image API that several screens read (#159). Server message fields are ServerMsg (translate with tm).
import type { ServerMsg } from './i18n';

// A ComfyUI tool: usable, or why not (ComfyUI not reachable, or nodes missing).
export type ToolInfo = { available: boolean; reason?: 'offline' | 'nodes'; error?: ServerMsg | string };

// GET /api/image/tools/tagger
export type TaggerInfo = ToolInfo & {
  models?: string[];
  defaults?: { model: string; threshold: number; character_threshold: number };
  exclude?: string[];
};

// GET /api/image/tools/postprocess
export type PostInfo = ToolInfo & {
  prefix?: string;
  ops?: Record<string, ServerMsg>;
  upscale_models?: string[];
  rembg?: boolean;
};

// GET /api/image/tools/methods
export type ToolMethods = { methods: string[]; features: Record<string, string[]> };

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
  style_ids?: string[] | null;
  [key: string]: unknown;
};

export type ReviewHistoryEntry = { at: string; path: string; from: string; to: string; source?: string };
