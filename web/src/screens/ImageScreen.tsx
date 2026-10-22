import ImageBoard from '../components/image/ImageBoard';
import ImageGallery from '../components/image/ImageGallery';
import ImageGenerate from '../components/image/ImageGenerate';
import ImageSingle from '../components/image/ImageSingle';
import ImageExperiments from '../components/image/StyleExplorer';
import ImageLora from '../components/image/ImageLora';
import ImageLibrary from '../components/image/ImageLibrary';
import ImageQueue from '../components/image/ImageQueue';
import ImageTools from '../components/image/ImageTools';
import ImageInfoViewer from '../components/image/ImageInfoViewer';
import PresetExplorer from '../components/image/PresetExplorer';
import ModelsScreen from '../components/image/ModelsScreen';
import { t } from '../i18n';
import type { ImageView } from '../types';
import { imageFlow } from '../lib/imageNavigation';

// Image module screens (decision 0018). Views not ported yet say what is coming.
export default function ImageScreen({
  active = true,
  workId,
  view,
  openView,
  openImage,
  openItem,
  openSettings,
  characterId,
  outfitId,
}: {
  active?: boolean;
  workId: string;
  view: ImageView;
  openView: (view: ImageView) => void;
  openImage: (view: ImageView, characterId?: string, outfitId?: string) => void;
  openItem: (path: string) => void;
  openSettings?: (section?: 'image' | 'install') => void;
  characterId?: string;
  outfitId?: string;
}) {
  const content = () => {
  if (view === 'single') return <ImageSingle workId={workId} openView={openView} />;
  if (view === 'library') return <ImageLibrary workId={workId} />;
  if (view === 'models') return <ModelsScreen openSettings={openSettings} />;
  if (view === 'presets') return <PresetExplorer workId={workId} openGenerate={() => openView('generate')} />;
  if (view === 'board') return <ImageBoard workId={workId} openGenerate={() => openImage('generate')} openGallery={(c, o) => openImage('gallery', c, o)} />;
  if (view === 'generate') return <ImageGenerate workId={workId} characterId={characterId} outfitId={outfitId} openQueue={() => openView('queue')} openItem={openItem} openSettings={openSettings} />;
  if (view === 'queue') return <ImageQueue />;
  if (view === 'gallery') return <ImageGallery workId={workId} characterId={characterId} outfitId={outfitId} openLab={() => openView('lab')} openTools={() => openView('tools')} />;
  if (view === 'lab') return <ImageExperiments workId={workId} active={active} openPresets={() => openView('presets')} />;
  if (view === 'tools') return <ImageTools active={active} openLab={() => openView('lab')} openSettings={openSettings} />;
  if (view === 'info') return <ImageInfoViewer active={active} />;
  if (view === 'lora') return <ImageLora workId={workId} initialCharacterId={characterId} initialOutfitId={outfitId} openLab={() => openView('lab')} />;
  return (
    <div className="pad col" style={{ maxWidth: 720 }}>
      <h3>{t(`image_menu.${view}`)}</h3>
      <p className="faint">{t(`image_menu.${view}_about`)}</p>
      <p className="faint">{t('image_menu.coming')}</p>
    </div>
  );
  };
  return <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <nav className="row image-flow" aria-label={t('flow.navigation')}>
      {characterId && <strong>{characterId}{outfitId ? ` · ${outfitId}` : ''}</strong>}
      {imageFlow.map((step) => <button key={step} className={view === step ? 'primary' : 'ghost'} onClick={() => openView(step)}>{t(`image_menu.${step}`)}</button>)}
    </nav>
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{content()}</div>
  </div>;
}
