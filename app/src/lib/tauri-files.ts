/**
 * Tauri-side file interactions. Two operations only:
 *   - openImageDialog(): native file picker for input images.
 *   - showInFolder(path): reveal an export in Explorer / Finder.
 *
 * Falls back to no-ops in a non-Tauri context so the React app boots in a plain browser
 * during component testing.
 */
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { open as openShell } from "@tauri-apps/plugin-shell";

const IMAGE_FILTERS = [
  { name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] },
];

export async function openImageDialog(): Promise<string[]> {
  try {
    const selected = await openDialog({
      multiple: true,
      filters: IMAGE_FILTERS,
    });
    if (!selected) return [];
    return Array.isArray(selected) ? selected : [selected];
  } catch {
    return [];
  }
}

export async function showInFolder(path: string): Promise<void> {
  try {
    await openShell(path);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("showInFolder failed", err);
  }
}
