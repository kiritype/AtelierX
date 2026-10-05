import ImageBoard from '../components/image/ImageBoard';
import ImageGallery from '../components/image/ImageGallery';
import ImageGenerate from '../components/image/ImageGenerate';
import ImageLab from '../components/image/ImageLab';
import ImageLora from '../components/image/ImageLora';
import ImageLibrary from '../components/image/ImageLibrary';
import ImageQueue from '../components/image/ImageQueue';
import ImageTools from '../components/image/ImageTools';
import { t } from '../i18n';
import type { ImageView } from '../types';

// Image module screens (decision 0018). Views not ported yet say what is coming.
export default function ImageScreen({
  workId,
  view,
  openView,
  openImage,
  openItem,
  characterId,
  outfitId,
}: {
  workId: string;
  view: ImageView;
  openView: (view: ImageView) => void;
  openImage: (view: ImageView, characterId?: string, outfitId?: string) => void;
  openItem: (path: string) => void;
  characterId?: string;
  outfitId?: string;
}) {
  const content = () => {
  if (view === 'library') return <ImageLibrary workId={workId} />;
  if (view === 'board') return <ImageBoard workId={workId} openGenerate={() => openImage('generate')} openGallery={(c, o) => openImage('gallery', c, o)} />;
  if (view === 'generate') return <ImageGenerate workId={workId} characterId={characterId} outfitId={outfitId} openQueue={() => openView('queue')} openItem={openItem} />;
  if (view === 'queue') return <ImageQueue />;
  if (view === 'gallery') return <ImageGallery workId={workId} characterId={characterId} outfitId={outfitId} openLab={() => openView('lab')} openTools={() => openView('tools')} />;
  if (view === 'lab') return <ImageLab workId={workId} />;
  if (view === 'tools') return <ImageTools openLab={() => openView('lab')} />;
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
      {(['board', 'generate', 'gallery', 'lora', 'lab'] as ImageView[]).map((step) => <button key={step} className={view === step ? 'primary' : 'ghost'} onClick={() => openView(step)}>{t(`flow.${step}`)}</button>)}
    </nav>
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{content()}</div>
  </div>;
}
