// Pure helpers of the test-set screens (#50): the opening of a run and the rows of two runs side by side.

export type RunTurn = { input: string; reply: string; error?: string | null };
export type RunLike = { set: { inputs: string[] }; turns: RunTurn[] };
export type CompareRow = { index: number; inputs: string[]; left?: RunTurn; right?: RunTurn };

// The start situation a run opens with, or null without one. A start the set names but that cannot be read throws:
// running without it would record answers to a different conversation as if nothing were wrong.
export async function startText(load: (path: string) => Promise<{ body: string }>, path: string | null, user: string) {
  if (!path) return null;
  const body = await load(path).then(
    (file) => file.body,
    () => null,
  );
  if (body == null) throw new Error(`start not readable: ${path}`);
  return body.trim().replaceAll('{{user}}', user) || null;
}

// Rows by turn order, not by input text: a set may send the same input more than once ("계속", "계속").
// When the set changed between the runs, a row shows both inputs.
export function compareRows(left: RunLike, right: RunLike): CompareRow[] {
  const n = Math.max(left.set.inputs.length, right.set.inputs.length, left.turns.length, right.turns.length);
  return Array.from({ length: n }, (_, index) => {
    const inputs = [left.set.inputs[index] ?? left.turns[index]?.input, right.set.inputs[index] ?? right.turns[index]?.input];
    return { index, inputs: [...new Set(inputs.filter((x): x is string => x != null))], left: left.turns[index], right: right.turns[index] };
  });
}
