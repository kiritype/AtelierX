import { lazy, Suspense, type ComponentProps } from 'react';
import { Loading } from './ui';

// CodeMirror is most of the editor's weight: read it when the first editor opens (#83).
const Editor = lazy(() => import('./CodeEditor'));

export default function CodeEditor(props: ComponentProps<typeof Editor>) {
  return (
    <Suspense fallback={<Loading />}>
      <Editor {...props} />
    </Suspense>
  );
}
