// Image tools (#151): tabs grouped by what they do, and the method each runs with (this PC or a service).

export type ToolTab = 'prompt' | 'convert' | 'tag' | 'post' | 'censor' | 'alpha' | 'inpaint';
export type Method = 'local' | 'novelai';

export const TAB_GROUPS: { id: 'prompt' | 'image' | 'file'; tabs: ToolTab[] }[] = [
  { id: 'prompt', tabs: ['prompt', 'tag'] },
  { id: 'image', tabs: ['post', 'alpha', 'inpaint'] },
  { id: 'file', tabs: ['convert', 'censor'] },
];

// The server features behind each tab. Tabs not listed run in the app itself and have no method to choose.
export const TAB_FEATURES: Partial<Record<ToolTab, string[]>> = {
  tag: ['tag'],
  post: ['upscale', 'detail'],
  censor: ['detect'],
  alpha: ['alpha'],
  inpaint: ['inpaint'],
};

// The methods a tab runs with: any of its features' methods, from GET /api/image/tools/methods.
export function tabMethods(tab: ToolTab, features: Record<string, string[]> | undefined): Method[] {
  const found = new Set<string>();
  for (const feature of TAB_FEATURES[tab] ?? []) for (const method of features?.[feature] ?? []) found.add(method);
  return [...found] as Method[];
}

// The tab's method: the one chosen last if the tab still supports it, else this PC.
export function pickMethod(tab: ToolTab, features: Record<string, string[]> | undefined, remembered: Partial<Record<ToolTab, Method>>): Method {
  const supported = tabMethods(tab, features);
  const last = remembered[tab];
  return last && supported.includes(last) ? last : 'local';
}
