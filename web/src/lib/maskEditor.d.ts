// Brush mask editor (plain DOM, see maskEditor.js).
export type MaskEditor = {
  element: HTMLElement;
  isDirty: () => boolean;
  save: () => Promise<void>;
  setStatus: (text: string) => void;
  maskCanvas: HTMLCanvasElement;
  onPaint: (listener: () => void) => void;
};
export function createMaskEditor(options: {
  imageUrl: string;
  maskUrl?: string | null;
  width: number;
  height: number;
  onSave: (blob: Blob) => Promise<void>;
  onChange?: () => void;
  color?: [number, number, number];
  background?: 'checker' | 'white' | 'black';
  preview?: boolean;
}): MaskEditor;
