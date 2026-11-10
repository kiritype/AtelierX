import { t } from '../../i18n';
import { useCatalog } from './GenSettings';
import { useNovelAIInfo } from './NovelAISettings';
import { usePixAIInfo } from './PixAISettings';

type Settings = Record<string, unknown>;

function pixelSize({ width, height }: Settings) {
  return typeof width === 'number' && width > 0 && typeof height === 'number' && height > 0 ? `${width} × ${height}` : '—';
}

function ComfySize({ value }: { value: Settings }) {
  const catalog = useCatalog();
  return pixelSize({ width: value.width ?? catalog.data?.defaults.width, height: value.height ?? catalog.data?.defaults.height });
}

function NovelAISize({ value }: { value: Settings }) {
  const info = useNovelAIInfo();
  return pixelSize({ ...info.data?.defaults, ...value });
}

function PixAISize({ value }: { value: Settings }) {
  const info = usePixAIInfo();
  const { aspect_ratio: ratio, size } = { ...info.data?.defaults, ...value };
  return typeof ratio === 'string' && typeof size === 'string' ? `${ratio} · ${size}` : '—';
}

type OutputSize = { outputWidth?: number; outputHeight?: number };

function positiveSize(width: unknown, height: unknown): OutputSize {
  return typeof width === 'number' && Number.isFinite(width) && width > 0
    && typeof height === 'number' && Number.isFinite(height) && height > 0
    ? { outputWidth: width, outputHeight: height }
    : {};
}

function aspectSize(value: unknown): OutputSize {
  if (typeof value !== 'string') return {};
  const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  if (!match) return {};
  return positiveSize(Number(match[1]), Number(match[2]));
}

/** Render a child with the actual dimensions (or aspect ratio) for the active service. */
export function ShotResolution({ service, value, children }: {
  service: string;
  value: Settings;
  children: (size: OutputSize) => React.ReactNode;
}) {
  if (service === 'comfyui') return <ComfyShotSize value={value}>{children}</ComfyShotSize>;
  if (service === 'novelai') return <NovelAIShotSize value={value}>{children}</NovelAIShotSize>;
  if (service === 'pixai') return <PixAIShotSize value={value}>{children}</PixAIShotSize>;
  return <>{children({})}</>;
}

function ComfyShotSize({ value, children }: { value: Settings; children: (size: OutputSize) => React.ReactNode }) {
  const catalog = useCatalog();
  const family = value.family === 'sdxl' ? 'sdxl' : 'anima';
  const fallback = family === 'sdxl' ? { width: 1024, height: 1024 } : { width: 1536, height: 1536 };
  return <>{children(positiveSize(value.width ?? catalog.data?.defaults.width ?? fallback.width,
    value.height ?? catalog.data?.defaults.height ?? fallback.height))}</>;
}

function NovelAIShotSize({ value, children }: { value: Settings; children: (size: OutputSize) => React.ReactNode }) {
  const info = useNovelAIInfo();
  return <>{children(positiveSize(value.width ?? info.data?.defaults.width, value.height ?? info.data?.defaults.height))}</>;
}

function PixAIShotSize({ value, children }: { value: Settings; children: (size: OutputSize) => React.ReactNode }) {
  const info = usePixAIInfo();
  return <>{children(aspectSize(value.aspect_ratio ?? info.data?.defaults.aspect_ratio))}</>;
}

export default function GenerationResolution({ service, value }: { service: string; value: Settings }) {
  return <span className="generation-resolution">
    {t(service === 'comfyui' && value.upscale ? 'gen.base_resolution' : 'gen.resolution')} {' '}
    {service === 'comfyui' ? <ComfySize value={value} /> : service === 'novelai' ? <NovelAISize value={value} /> : service === 'pixai' ? <PixAISize value={value} /> : '—'}
  </span>;
}
