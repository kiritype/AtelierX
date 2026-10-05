// "Resend inputs" in the test screen: send the earlier inputs again, one after another. Stopping or an error ends the
// whole run, so a stopped resend never goes on to bill the next request.
export type ReplayTurn = { stopped?: boolean; error?: string };

export async function replayInputs<T extends ReplayTurn>(
  inputs: string[],
  history: T[],
  send: (message: string, history: T[]) => Promise<T[]>,
  cancelled: () => boolean = () => false,
): Promise<{ history: T[]; sent: number }> {
  let sent = 0;
  for (const message of inputs) {
    if (cancelled()) break;
    history = await send(message, history);
    sent += 1;
    const last = history[history.length - 1];
    if (last?.stopped || last?.error || cancelled()) break;
  }
  return { history, sent };
}
