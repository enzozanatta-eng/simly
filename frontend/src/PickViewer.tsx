import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  type ArrowSpec, AxisGizmo, forceArrow, setView, supportPlate, type ViewName,
} from "./sceneKit";
import type { PartInfo } from "./types";

export const ROLE_COLORS = {
  none: new THREE.Color("#d5dae3"),
  hover: new THREE.Color("#ffd43b"),
  fixed: new THREE.Color("#5c677d"),
  load: new THREE.Color("#f783ac"),
  activeLoad: new THREE.Color("#e64980"),
};

interface Props {
  part: PartInfo;
  /** colour of each face id, decided by the parent from its roles */
  colorOf: (faceId: number) => THREE.Color;
  onPick: (faceId: number) => void;
  onHover: (faceId: number | null) => void;
  arrows: ArrowSpec[];
  supports: { at: [number, number, number]; normal: [number, number, number] }[];
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  mesh: THREE.Mesh;
  markers: THREE.Group;
  center: THREE.Vector3;
  radius: number;
}

const VIEWS: [ViewName, string][] = [
  ["iso", "Iso"], ["front", "Front"], ["top", "Top"], ["right", "Right"], ["back", "Back"], ["bottom", "Bottom"],
];

/** Large 3D view of an uploaded part: hover shows a face, click picks it. */
export function PickViewer({ part, colorOf, onPick, onHover, arrows, supports }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const st = useRef<SceneState | null>(null);
  const hoverRef = useRef<number | null>(null);
  const cb = useRef({ colorOf, onPick, onHover });
  cb.current = { colorOf, onPick, onHover };
  const faceOfTri = part.display.face_of_triangle;

  function paint() {
    const s = st.current;
    if (!s) return;
    const colors = s.mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = colors.array as Float32Array;
    for (let t = 0; t < faceOfTri.length; t++) {
      const f = faceOfTri[t];
      const c = f === hoverRef.current ? ROLE_COLORS.hover : cb.current.colorOf(f);
      for (let k = 0; k < 3; k++) arr.set([c.r, c.g, c.b], (3 * t + k) * 3);
    }
    colors.needsUpdate = true;
  }

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.autoClear = false;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f4f6fa");
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(1, -1.5, 2);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    // non-indexed geometry so every triangle can take its own face colour
    const { positions, indices } = part.display;
    const pos = new Float32Array(indices.length * 3);
    indices.forEach((v, i) => pos.set(positions.slice(3 * v, 3 * v + 3), 3 * i));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(pos.length), 3));
    geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.75, flatShading: true,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
    }));
    scene.add(mesh);
    // feature edges make the faces readable
    scene.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 30),
      new THREE.LineBasicMaterial({ color: 0x1c2230, transparent: true, opacity: 0.55 }),
    ));
    const markers = new THREE.Group();
    scene.add(markers);

    geometry.computeBoundingSphere();
    const { center, radius } = geometry.boundingSphere!;
    st.current = { renderer, scene, camera, controls, mesh, markers, center, radius };
    paint();
    setView(camera, controls, center, radius, "iso");

    const resize = () => {
      renderer.setSize(el.clientWidth, el.clientHeight);
      camera.aspect = el.clientWidth / Math.max(el.clientHeight, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const faceAt = (ev: PointerEvent): number | null => {
      const r = renderer.domElement.getBoundingClientRect();
      pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObject(mesh)[0];
      return hit?.faceIndex != null ? faceOfTri[hit.faceIndex] : null;
    };
    let down: { x: number; y: number } | null = null;
    const canvas = renderer.domElement;
    const onMove = (ev: PointerEvent) => {
      if (down) return; // orbiting
      const f = faceAt(ev);
      if (f !== hoverRef.current) {
        hoverRef.current = f;
        canvas.style.cursor = f === null ? "grab" : "pointer";
        cb.current.onHover(f);
        paint();
      }
    };
    const onDown = (ev: PointerEvent) => { down = { x: ev.clientX, y: ev.clientY }; };
    const onUp = (ev: PointerEvent) => {
      if (down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 5) {
        const f = faceAt(ev);
        if (f !== null) cb.current.onPick(f);
      }
      down = null;
    };
    const onLeave = () => {
      hoverRef.current = null;
      cb.current.onHover(null);
      paint();
    };
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", onLeave);

    const gizmo = new AxisGizmo();
    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.clear();
      renderer.render(scene, camera);
      gizmo.render(renderer, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      controls.dispose();
      geometry.dispose();
      renderer.dispose();
      el.removeChild(canvas);
      st.current = null;
    };
    // rebuilt only for a new part; colours and markers update separately
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [part]);

  useEffect(paint, [colorOf]);

  // support plates and force arrows previewed on the part
  useEffect(() => {
    const s = st.current;
    if (!s) return;
    s.markers.clear();
    const len = 0.45 * s.radius;
    for (const sp of supports) s.markers.add(supportPlate(sp.at, sp.normal, 0.35 * s.radius));
    for (const a of arrows) s.markers.add(forceArrow(a, len));
  }, [arrows, supports, part]);

  const view = (v: ViewName) => {
    const s = st.current;
    if (s) setView(s.camera, s.controls, s.center, s.radius, v);
  };

  return (
    <div className="viewer-shell">
      <div className="viewer" ref={host} />
      <div className="views">
        {VIEWS.map(([v, label]) => <button key={v} onClick={() => view(v)}>{label}</button>)}
      </div>
    </div>
  );
}
