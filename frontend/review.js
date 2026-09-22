/** Validation-focused view. The gallery keeps result browsing and downloads. */
import {mount as mountGallery} from "./gallery.js";

export function mount(container, ctx) {
  return mountGallery(container, {...ctx, mode: "review"});
}
