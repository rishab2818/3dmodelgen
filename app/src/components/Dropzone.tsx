/**
 * Image dropzone. Supports drag-drop AND the Tauri native picker.
 *
 * For the Tauri picker, the returned paths are absolute filesystem paths — fed directly
 * to the backend's POST /jobs (which expects absolute Paths). For browser drag-drop we
 * read the dropped file via FileReader, but in Tauri there's no path on browser drops
 * either, so we fall back to the picker when dragged-File has no path.
 */
import { useCallback, useState } from "react";
import { openImageDialog } from "@/lib/tauri-files";

type Props = {
  onSelected: (paths: string[]) => void;
  disabled?: boolean;
};

export function Dropzone({ onSelected, disabled }: Props): JSX.Element {
  const [over, setOver] = useState(false);

  const pick = useCallback(async () => {
    const paths = await openImageDialog();
    if (paths.length > 0) onSelected(paths);
  }, [onSelected]);

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        // Tauri exposes paths via plugin-dialog only; HTML drag-drop in WebView
        // doesn't carry filesystem paths. Open the picker after a hint drop.
        void pick();
      }}
      className={[
        "rounded-2xl border-2 border-dashed transition-colors",
        "px-8 py-12 text-center cursor-pointer select-none",
        over ? "border-accent bg-panel/80" : "border-border bg-panel/40",
        disabled ? "opacity-50 pointer-events-none" : "hover:border-accent",
      ].join(" ")}
      onClick={() => void pick()}
    >
      <div className="text-lg font-medium">Drop an image to generate a 3D model</div>
      <div className="text-sm text-muted mt-1">
        PNG / JPG / WebP &middot; click to pick from disk
      </div>
    </div>
  );
}
