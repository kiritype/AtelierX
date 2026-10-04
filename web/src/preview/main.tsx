// Runs inside the sandboxed preview frame: turns JSX source into a component and renders it with the given props.
import * as React from 'react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { transform } from 'sucrase';
import type { FromFrame, GlobalStub, ToFrame } from './protocol';

const root = createRoot(document.getElementById('root')!);

function send(message: FromFrame) {
  parent.postMessage(message, '*');
}

function stub(spec: GlobalStub, id: number) {
  const kind = spec.stub ?? 'log';
  return (...args: unknown[]) => {
    send({ type: 'call', id, name: spec.name, args: JSON.parse(JSON.stringify(args ?? null)) });
    if (kind === 'random') return Math.random();
    if (kind.startsWith('return:')) {
      try {
        return JSON.parse(kind.slice('return:'.length));
      } catch {
        return kind.slice('return:'.length);
      }
    }
    return undefined;
  };
}

function lineOf(error: unknown): number | null {
  const match = /<anonymous>:(\d+):\d+/.exec(String((error as Error)?.stack ?? ''));
  // new Function adds two header lines before the body.
  return match ? Math.max(1, Number(match[1]) - 2) : null;
}

class Boundary extends React.Component<{ id: number; children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    send({ type: 'error', id: this.props.id, message: error.message, line: lineOf(error) });
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function render(message: ToFrame) {
  document.body.className = message.theme;
  try {
    const js = transform(message.code, { transforms: ['jsx'], jsxRuntime: 'classic', production: true }).code;
    const hooks = message.hooks.filter((h) => typeof (React as Record<string, unknown>)[h] === 'function');
    const names = ['React', ...hooks, ...message.globals.map((g) => g.name)];
    const values = [React, ...hooks.map((h) => (React as Record<string, unknown>)[h]), ...message.globals.map((g) => stub(g, message.id))];
    const factory = new Function(...names, `${js}\nreturn typeof ${message.name} === 'function' ? ${message.name} : null;`);
    const component = factory(...values) as React.ComponentType<unknown> | null;
    if (!component) {
      send({ type: 'error', id: message.id, message: `function ${message.name}(props) was not found.`, line: null });
      root.render(null);
      return;
    }
    const props = message.props && typeof message.props === 'object' ? message.props : {};
    // Render synchronously so the app hears back right away; render errors are reported by the boundary first.
    flushSync(() =>
      root.render(
        <Boundary key={message.id} id={message.id}>
          {React.createElement(component, props as object)}
        </Boundary>,
      ),
    );
    send({ type: 'rendered', id: message.id });
  } catch (error) {
    const syntax = /\((\d+):(\d+)\)/.exec(String((error as Error).message));
    send({ type: 'error', id: message.id, message: (error as Error).message, line: syntax ? Number(syntax[1]) : lineOf(error) });
    root.render(null);
  }
}

window.addEventListener('message', (event) => {
  if (event.source !== parent) return;
  const message = event.data as ToFrame;
  if (message?.type === 'render') render(message);
});

// Measure the content, not the frame: scrollHeight never drops below the frame's own height.
new ResizeObserver(() => send({ type: 'size', height: Math.ceil(document.body.getBoundingClientRect().height) })).observe(document.body);
send({ type: 'ready' });
