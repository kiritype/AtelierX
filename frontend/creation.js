/**
 * Image creation is a separate route, while retaining the established Core
 * production-plan contract and the same in-memory draft semantics.
 */
import {mount as mountProduction} from "./production.js";

export function mount(container, ctx) {
  return mountProduction(container, {...ctx, mode: "creation"});
}
