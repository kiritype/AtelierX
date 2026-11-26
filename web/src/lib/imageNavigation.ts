import type { ImageView } from '../types';

// One navigation model for the Image menu and its sidebar (#242).
export const imageNavigation: { group: string; views: ImageView[] }[] = [
  { group: 'prepare', views: ['library', 'presets', 'models'] },
  { group: 'make', views: ['single', 'reference', 'generate', 'board'] },
  { group: 'refine', views: ['gallery', 'tools', 'info'] },
  { group: 'experiment', views: ['lab', 'lora'] },
  { group: 'manage', views: ['queue'] },
];

export const imageFlow: ImageView[] = ['single', 'reference', 'generate', 'board', 'gallery', 'tools', 'queue'];

export const globalImageViews = ['single', 'explorer', 'presets', 'queue'] as const;
export type GlobalToolsView = (typeof globalImageViews)[number] | 'settings';
