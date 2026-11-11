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
export type ExplorerArtist = {
  name: string;
  mode: 'always' | 'candidate' | 'exclude';
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
  artists: ExplorerArtist[];
  rules: ExplorerRules;
  budget: number;
};
export type ExplorerCandidate = {
  id: string;
  index: number;
  positive: string;
  negative: string;
  settings: Record<string, unknown>;
  artists: { name: string; weight: number }[];
  seed: number;
  status: string;
  job_id?: string;
  image_url?: string;
  image_missing?: boolean;
  path?: string;
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
  config: ExplorerConfig;
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
    families: { id: string; name: string; enabled: boolean; reason?: string }[];
  }[];
  max_batch: number;
  max_budget: number;
  defaults: { count: number; budget: number } & Partial<ExplorerRules>;
};
