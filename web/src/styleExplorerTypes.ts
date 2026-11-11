import type { ServerMessage } from './api';

export type ExplorerRules = {
  artist_min: number;
  artist_max: number;
  artist_low: number;
  artist_high: number;
  artist_step: number;
  lora_min: number;
  lora_max: number;
  lora_low: number;
  lora_high: number;
  lora_step: number;
};
export type ExplorerSelectionRules = Pick<ExplorerRules, 'artist_min' | 'artist_max' | 'lora_min' | 'lora_max'>;
export type ExplorerArtist = {
  name: string;
  mode: 'always' | 'candidate' | 'exclude';
};
export type ExplorerWeight =
  | { mode: 'fixed'; value?: number }
  | { mode: 'random'; low?: number; high?: number; step?: number; include_high?: boolean };
export type ExplorerMaterial = {
  kind: 'tag' | 'lora';
  name: string;
  id?: string;
  role?: 'style' | 'character' | 'other';
  mode?: 'always' | 'candidate' | 'exclude';
  weight: ExplorerWeight;
  trigger_words?: string;
};
export type ExplorerConfig = {
  request_id: string;
  name: string;
  service: string;
  family: string;
  positive: string;
  negative: string;
  seed: number;
  settings: Record<string, unknown>;
  models?: string[];
  artists?: ExplorerArtist[];
  materials?: ExplorerMaterial[];
  rules: ExplorerSelectionRules & Partial<ExplorerRules>;
  budget: number;
};
export type ExplorerCandidate = {
  id: string;
  index: number;
  positive: string;
  negative: string;
  settings: Record<string, unknown>;
  artists: { name: string; weight: number }[];
  materials?: (Omit<ExplorerMaterial, 'weight'> & { weight: number })[];
  seed: number;
  status: string;
  job_id?: string;
  image_url?: string | null;
  image_missing?: boolean;
  path?: string | null;
  error?: unknown;
  elo: number;
  matches: number;
  wins: number;
  draws: number;
  rejected: number;
  preset_id?: string;
};
export type ExplorerPair = { id: string; a: string; b: string };
export type ExplorerVote = {
  id: string;
  pair_id: string;
  a: string;
  b: string;
  result: ExplorerResult;
  created_at: string;
};
export type ExplorerResult = 'a' | 'b' | 'tie' | 'neither' | 'skip';
export type ExplorerSummary = {
  id: string;
  name: string;
  service: string;
  family: string;
  created_at: string;
  budget: number;
  used: number;
  candidate_count: number;
  vote_count: number;
  revision: number;
};
export type ExplorerSession = ExplorerSummary & {
  config: Omit<ExplorerConfig, 'request_id'>;
  candidates: ExplorerCandidate[];
  pair: ExplorerPair | null;
  votes: ExplorerVote[];
  ranking: ExplorerCandidate[];
};
export type ExplorerCapabilities = {
  services: {
    id: string;
    name: string;
    enabled: boolean;
    families: { id: string; name: string; enabled: boolean; reason?: string | ServerMessage }[];
  }[];
  max_batch: number;
  max_budget: number;
  defaults: { count: number; budget: number } & Partial<ExplorerRules>;
};
