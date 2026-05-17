/**
 * R3F viewer that loads a .glb from the backend's static-files mount.
 *
 * Preserves camera state across model swaps (Suspense fallback inside the canvas so
 * the canvas itself doesn't remount on URL change).
 */
import { Suspense, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, useGLTF, Environment, Center } from "@react-three/drei";
import { backendUrl } from "@/lib/api";

type Props = { jobId: string | null; glbRelPath: string | null };

function Model({ url }: { url: string }): JSX.Element {
  const gltf = useGLTF(url);
  return (
    <Center>
      <primitive object={gltf.scene} />
    </Center>
  );
}

export function ModelViewer({ jobId, glbRelPath }: Props): JSX.Element {
  const url = useMemo(() => {
    if (!jobId || !glbRelPath) return null;
    // The backend writes export paths relative to repo root (e.g. "exports/<id>/model.glb").
    // The /exports/<id>/<file> route serves them.
    const file = glbRelPath.split(/[\\/]/).pop() ?? "model.glb";
    return `${backendUrl()}/exports/${jobId}/${file}`;
  }, [jobId, glbRelPath]);

  return (
    <div className="aspect-[16/10] w-full rounded-xl border border-border bg-panel overflow-hidden">
      <Canvas camera={{ position: [2, 1.6, 2.4], fov: 40 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[3, 5, 2]} intensity={1.1} />
        <Suspense fallback={null}>
          {url ? <Model url={url} /> : null}
          <Environment preset="studio" />
        </Suspense>
        <OrbitControls makeDefault enableDamping />
      </Canvas>
    </div>
  );
}
