import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useInternalNode,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import { useToast } from './Toasts';

type Person = { id: string; name: string; path?: string; source: 'reserved' | 'character' | 'extra'; note?: string; char?: boolean };
type Relation = { from: string; to: string; kind?: string; calls?: string; note?: string };
type Fact = { subject: string; key: string; value: string };
type Doc = {
  people: { id: string; name?: string; note?: string }[];
  relations: Relation[];
  facts: Fact[];
  layout: Record<string, { x: number; y: number }>;
  view: Person[];
};

export default function RelationsTab({ workId, openItem }: { workId: string; openItem: (path: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  const start = async (url: string, message: string, selectedLlm?: LlmOverride) => {
    try {
      await post(url, selectedLlm ? { llm: selectedLlm } : {});
      toast({ text: message });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  };
  const query = useQuery<Doc>({ queryKey: ['relations', workId], queryFn: () => get(`/api/works/${workId}/relations`) });
  const [doc, setDoc] = useState<Doc | null>(null);
  const [mode, setMode] = useState<'graph' | 'table'>('graph');
  const [filter, setFilter] = useState('');
  const [focus, setFocus] = useState<string | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    if (query.data && !dirty.current) setDoc(query.data);
  }, [query.data]);

  // Save shortly after the last change; the server returns the refreshed view.
  useEffect(() => {
    if (!doc || !dirty.current) return;
    const timer = setTimeout(async () => {
      const saved = await put(`/api/works/${workId}/relations`, doc);
      dirty.current = false;
      qc.setQueryData(['relations', workId], saved);
      qc.invalidateQueries({ queryKey: ['check', workId] });
    }, 600);
    return () => clearTimeout(timer);
  }, [doc, workId, qc]);

  if (!doc) return null;
  const change = (next: Partial<Doc>) => {
    dirty.current = true;
    setDoc({ ...doc, ...next });
  };
  const characterIds = new Set(doc.view.filter((p) => p.source === 'character').map((p) => p.id));
  const nameOf = (id: string) => doc.view.find((p) => p.id === id)?.name ?? id;
  const shownRelations = doc.relations.map((r, n) => ({ r, n })).filter(({ r }) => !filter || r.from === filter || r.to === filter);
  const shownFacts = doc.facts.map((f, n) => ({ f, n })).filter(({ f }) => !filter || f.subject === filter);

  return (
    <div className="relations">
      <div className="row pad" style={{ paddingBottom: 0 }}>
        <div className="seg">
          <button className={mode === 'graph' ? 'on' : ''} onClick={() => setMode('graph')}>
            {t('relations.graph')}
          </button>
          <button className={mode === 'table' ? 'on' : ''} onClick={() => setMode('table')}>
            {t('relations.table')}
          </button>
        </div>
        {mode === 'table' && (
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">{t('relations.everyone')}</option>
            {doc.view.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <span className="faint relations-note grow" style={{ textAlign: 'right' }} title={t('relations.note')}>{t('relations.note')}</span>
        <RunLlmSelector task="consistency" value={llm} onChange={setLlm} />
        <button onClick={() => start(`/api/works/${workId}/relations/extract`, t('relations.extract_started'), llm)}>{t('relations.extract')}</button>
        <button onClick={() => start(`/api/works/${workId}/consistency`, t('consistency.started'), llm)}>{t('consistency.run')}</button>
      </div>
      {mode === 'graph' ? (
        <Graph doc={doc} focus={focus} setFocus={setFocus} change={change} nameOf={nameOf} openItem={openItem} />
      ) : (
        <div className="pad col" style={{ overflow: 'auto' }}>
          <div className="section-title">{t('relations.people')}</div>
          <table className="plain">
            <tbody>
              {doc.view
                .filter((p) => p.source !== 'extra')
                .map((p) => (
                  <tr key={p.id}>
                    <td className="mono">{p.id}</td>
                    <td>
                      {p.path ? (
                        <a href="#" onClick={(e) => (e.preventDefault(), openItem(p.path!))}>
                          {p.name}
                        </a>
                      ) : (
                        p.name
                      )}
                      {p.char && <span className="chip" style={{ marginLeft: 6 }}>{'{{char}}'}</span>}
                    </td>
                    <td className="faint">{t(`relations.source.${p.source}`)}</td>
                    <td />
                  </tr>
                ))}
              {doc.people.map((p, n) =>
                characterIds.has(p.id) ? null : (
                <tr key={n}>
                  <td>
                    <input className="mono" style={{ width: 70 }} value={p.id} placeholder="N01" onChange={(e) => change({ people: replace(doc.people, n, { ...p, id: e.target.value }) })} />
                  </td>
                  <td>
                    <input value={p.name ?? ''} placeholder={t('relations.name')} onChange={(e) => change({ people: replace(doc.people, n, { ...p, name: e.target.value }) })} />
                  </td>
                  <td>
                    <input value={p.note ?? ''} placeholder={t('relations.memo')} onChange={(e) => change({ people: replace(doc.people, n, { ...p, note: e.target.value }) })} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => change({ people: doc.people.filter((_, i) => i !== n) })}>
                      ×
                    </button>
                  </td>
                </tr>
                ),
              )}
            </tbody>
          </table>
          <div>
            <button onClick={() => change({ people: [...doc.people, { id: nextExtraId(doc), name: '' }] })}>{t('relations.add_person')}</button>
          </div>

          <div className="section-title">{t('relations.relations')}</div>
          <table className="plain">
            <thead>
              <tr className="faint">
                <td>{t('relations.from')}</td>
                <td />
                <td>{t('relations.to')}</td>
                <td>{t('relations.kind')}</td>
                <td>{t('relations.calls')}</td>
                <td>{t('relations.memo')}</td>
                <td />
              </tr>
            </thead>
            <tbody>
              {shownRelations.map(({ r, n }) => (
                <tr key={n}>
                  <td>
                    <PersonSelect people={doc.view} value={r.from} onChange={(v) => change({ relations: replace(doc.relations, n, { ...r, from: v }) })} />
                  </td>
                  <td>→</td>
                  <td>
                    <PersonSelect people={doc.view} value={r.to} onChange={(v) => change({ relations: replace(doc.relations, n, { ...r, to: v }) })} />
                  </td>
                  <td>
                    <input value={r.kind ?? ''} onChange={(e) => change({ relations: replace(doc.relations, n, { ...r, kind: e.target.value }) })} />
                  </td>
                  <td>
                    <input value={r.calls ?? ''} onChange={(e) => change({ relations: replace(doc.relations, n, { ...r, calls: e.target.value }) })} />
                  </td>
                  <td>
                    <input value={r.note ?? ''} onChange={(e) => change({ relations: replace(doc.relations, n, { ...r, note: e.target.value }) })} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => change({ relations: doc.relations.filter((_, i) => i !== n) })}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <button
              onClick={() =>
                change({ relations: [...doc.relations, { from: filter || doc.view[1]?.id || '{{user}}', to: '{{user}}', kind: '', calls: '' }] })
              }
            >
              {t('relations.add_relation')}
            </button>
          </div>

          <div className="section-title">{t('relations.facts')}</div>
          <table className="plain">
            <tbody>
              {shownFacts.map(({ f, n }) => (
                <tr key={n}>
                  <td>
                    <PersonSelect people={doc.view} value={f.subject} onChange={(v) => change({ facts: replace(doc.facts, n, { ...f, subject: v }) })} />
                  </td>
                  <td>
                    <input value={f.key} placeholder={t('relations.fact_key')} onChange={(e) => change({ facts: replace(doc.facts, n, { ...f, key: e.target.value }) })} />
                  </td>
                  <td>
                    <input value={f.value} placeholder={t('relations.fact_value')} onChange={(e) => change({ facts: replace(doc.facts, n, { ...f, value: e.target.value }) })} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => change({ facts: doc.facts.filter((_, i) => i !== n) })}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <button onClick={() => change({ facts: [...doc.facts, { subject: filter || doc.view[1]?.id || '{{user}}', key: '', value: '' }] })}>
              {t('relations.add_fact')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function replace<T>(list: T[], index: number, value: T): T[] {
  return list.map((x, i) => (i === index ? value : x));
}

function nextExtraId(doc: Doc) {
  const used = new Set(doc.view.map((p) => p.id).concat(doc.people.map((p) => p.id)));
  for (let n = 1; ; n++) {
    const id = `N${String(n).padStart(2, '0')}`;
    if (!used.has(id)) return id;
  }
}

function PersonSelect({ people, value, onChange }: { people: Person[]; value: string; onChange: (v: string) => void }) {
  const known = people.some((p) => p.id === value);
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {!known && <option value={value}>{value} ?</option>}
      {people.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

type PersonData = { person: Person; facts: Fact[]; focus: boolean };

function PersonNode({ data }: NodeProps<Node<PersonData>>) {
  const { person, focus } = data;
  return (
    <div className={`person-node ${person.source}${focus ? ' focus' : ''}`}>
      <Handle type="target" position={Position.Top} className="hidden-handle" />
      <Handle type="source" position={Position.Top} className="hidden-handle" />
      <strong>{person.name}</strong>
      {person.source !== 'reserved' && <div className="faint">{person.id}</div>}
    </div>
  );
}

const nodeTypes = { person: PersonNode };

// Where the line from a node's center towards (dx, dy) leaves the node's box.
function boxExit(w: number, h: number, dx: number, dy: number) {
  const scale = Math.min(w / 2 / Math.abs(dx || 1e-6), h / 2 / Math.abs(dy || 1e-6));
  return { x: dx * scale, y: dy * scale };
}

type RelationData = { label: string; bend: number; dim: boolean };

// Center-to-center curve. A pair of opposite relations bends to opposite sides, so the two arrows stay apart.
function RelationEdge({ id, source, target, markerEnd, data }: EdgeProps<Edge<RelationData>>) {
  const a = useInternalNode(source);
  const b = useInternalNode(target);
  if (!a || !b) return null;
  const aw = a.measured.width ?? 80, ah = a.measured.height ?? 40, bw = b.measured.width ?? 80, bh = b.measured.height ?? 40;
  const ac = { x: a.internals.positionAbsolute.x + aw / 2, y: a.internals.positionAbsolute.y + ah / 2 };
  const bc = { x: b.internals.positionAbsolute.x + bw / 2, y: b.internals.positionAbsolute.y + bh / 2 };
  const dx = bc.x - ac.x, dy = bc.y - ac.y;
  const length = Math.hypot(dx, dy) || 1;
  const bend = data?.bend ?? 0;
  const control = { x: (ac.x + bc.x) / 2 - (dy / length) * bend, y: (ac.y + bc.y) / 2 + (dx / length) * bend };
  const startOff = boxExit(aw + 6, ah + 6, control.x - ac.x, control.y - ac.y);
  const endOff = boxExit(bw + 10, bh + 10, control.x - bc.x, control.y - bc.y);
  const start = { x: ac.x + startOff.x, y: ac.y + startOff.y };
  const end = { x: bc.x + endOff.x, y: bc.y + endOff.y };
  const label = { x: 0.25 * start.x + 0.5 * control.x + 0.25 * end.x, y: 0.25 * start.y + 0.5 * control.y + 0.25 * end.y };
  const opacity = data?.dim ? 0.15 : 1;
  return (
    <>
      <BaseEdge id={id} path={`M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`} markerEnd={markerEnd} style={{ opacity }} />
      {data?.label && (
        <EdgeLabelRenderer>
          <div className="edge-label" style={{ transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)`, opacity }}>
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { relation: RelationEdge };

function Graph({
  doc,
  focus,
  setFocus,
  change,
  nameOf,
  openItem,
}: {
  doc: Doc;
  focus: string | null;
  setFocus: (id: string | null) => void;
  change: (next: Partial<Doc>) => void;
  nameOf: (id: string) => string;
  openItem: (path: string) => void;
}) {
  const [positions, setPositions] = useState(doc.layout);
  useEffect(() => setPositions(doc.layout), [doc.layout]);

  const nodes: Node<PersonData>[] = useMemo(() => {
    const radius = Math.max(160, doc.view.length * 40);
    return doc.view.map((person, n) => {
      const angle = (2 * Math.PI * n) / doc.view.length - Math.PI / 2;
      return {
        id: person.id,
        type: 'person',
        position: positions[person.id] ?? { x: radius + radius * Math.cos(angle), y: radius + radius * Math.sin(angle) },
        data: { person, facts: doc.facts.filter((f) => f.subject === person.id), focus: focus === person.id },
      };
    });
  }, [doc.view, doc.facts, positions, focus]);

  const edges: Edge<RelationData>[] = useMemo(
    () =>
      doc.relations
        .filter((r) => doc.view.some((p) => p.id === r.from) && doc.view.some((p) => p.id === r.to))
        .map((r, n) => {
          const paired = doc.relations.some((o) => o.from === r.to && o.to === r.from);
          return {
            id: `e${n}`,
            type: 'relation',
            source: r.from,
            target: r.to,
            markerEnd: { type: MarkerType.ArrowClosed },
            data: {
              label: [r.kind, r.calls && `"${r.calls}"`].filter(Boolean).join(' · '),
              bend: paired ? 40 : 0,
              dim: !!focus && r.from !== focus && r.to !== focus,
            },
          };
        }),
    [doc.relations, doc.view, focus],
  );

  const person = doc.view.find((p) => p.id === focus);
  const prefersDark = typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches;

  return (
    <div className="graph-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode={prefersDark ? 'dark' : 'light'}
        fitView
        nodesConnectable={false}
        onNodeClick={(_, node) => setFocus(focus === node.id ? null : node.id)}
        onPaneClick={() => setFocus(null)}
        onNodesChange={(changes) => {
          const moved = changes.filter((c) => c.type === 'position' && c.position);
          if (!moved.length) return;
          setPositions((all) => {
            const next = { ...all };
            for (const c of moved) if (c.type === 'position' && c.position) next[c.id] = c.position;
            return next;
          });
        }}
        onNodeDragStop={(_, node) => change({ layout: { ...doc.layout, ...positions, [node.id]: node.position } })}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
      {person && (
        <div className="graph-detail">
          <strong>{person.name}</strong> <span className="faint">{person.source === 'reserved' ? '' : person.id}</span>
          {doc.facts
            .filter((f) => f.subject === person.id)
            .map((f, n) => (
              <div key={n}>
                {f.key} <span className="faint">·</span> {f.value}
              </div>
            ))}
          {doc.relations
            .filter((r) => r.from === person.id)
            .map((r, n) => (
              <div key={n} className="faint">
                → {nameOf(r.to)}: {r.kind} {r.calls && `"${r.calls}"`}
              </div>
            ))}
          {person.path && (
            <button style={{ marginTop: 6 }} onClick={() => openItem(person.path!)}>
              {t('relations.open_item')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
