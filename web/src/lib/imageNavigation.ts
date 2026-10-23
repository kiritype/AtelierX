import type { ImageView } from '../types';

// One navigation model for the Image menu and its sidebar (#242).
export const imageNavigation: { group: string; views: ImageView[] }[] = [
  { group: 'prepare', views: ['library', 'presets', 'models'] },
  { group: 'make', views: ['single', 'generate', 'board'] },
  { group: 'refine', views: ['gallery', 'tools', 'info'] },
  { group: 'manage', views: ['queue'] },
];

export const imageFlow: ImageView[] = ['single', 'generate', 'board', 'gallery', 'tools', 'queue'];
