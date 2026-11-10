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

export default function GenerationResolution({ service, value }: { service: string; value: Settings }) {
  return <span className="generation-resolution">
    {t(service === 'comfyui' && value.upscale ? 'gen.base_resolution' : 'gen.resolution')} {' '}
    {service === 'comfyui' ? <ComfySize value={value} /> : service === 'novelai' ? <NovelAISize value={value} /> : service === 'pixai' ? <PixAISize value={value} /> : '—'}
  </span>;
}
