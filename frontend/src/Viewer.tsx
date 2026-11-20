import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { turbo } from "./colormap";
import { AxisGizmo, directionName, forceArrow, setView, supportPlate, type ViewName } from "./sceneKit";
import type { Display } from "./types";

interface Props {
  display: Display;
  /** Deformation shown as a fraction of the part size (0 = undeformed). */
  exaggeration: number;
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  part?: THREE.Mesh;
  markers?: THREE.Group;
  arrows: THREE.Group[];
  center: THREE.Vector3;
  radius: number;
}

const VIEWS: [ViewName, string][] = [["iso", "Iso"], ["front", "Front"], ["top", "Top"], ["right", "Right"]];

const fmtN = (n: number) => (n >= 1000 ? `${Number((n / 1000).toPrecision(3))} kN` : `${Number(n.toPrecision(3))} N`);

/** Interactive 3D view of the part coloured by von Mises stress. */
export function Viewer({ display, exaggeration }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<SceneState | null>(null);

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.autoClear = false;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f4f6fa");
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.0));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(1, -1.5, 2);
    scene.add(sun);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    state.current = { renderer, scene, camera, controls, arrows: [],
      center: new THREE.Vector3(), radius: 1 };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

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
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  // rebuild the part when a new result arrives
  useEffect(() => {
    const s = state.current!;
    if (s.part) {
      s.scene.remove(s.part);
      s.part.geometry.dispose();
      (s.part.material as THREE.Material).dispose();
    }
    if (s.markers) s.scene.remove(s.markers);

    const geometry = new THREE.BufferGeometry();
    geometry.setIndex(display.indices);
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(display.positions.slice(), 3));
    const [lo, hi] = display.range;
    const colors = new Float32Array(display.von_mises.length * 3);
    display.von_mises.forEach((v, i) => colors.set(turbo((v - lo) / (hi - lo || 1)), 3 * i));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.computeVertexNormals();
    const part = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.05 }),
    );
    s.part = part;
    s.scene.add(part);

    geometry.computeBoundingSphere();
    s.center = geometry.boundingSphere!.center.clone();
    s.radius = geometry.boundingSphere!.radius;

    const markers = new THREE.Group();
    s.arrows = display.loads.map((ld) => {
      const dir = ld.direction as [number, number, number];
      const g = forceArrow({
        at: ld.centre as [number, number, number], dir,
        normal: (ld.pulling ? dir : dir.map((v) => -v)) as [number, number, number],
        label: `${fmtN(ld.magnitude_N)} ${directionName(dir)}`,
      }, 0.45 * s.radius);
      markers.add(g);
      return g;
    });
    for (const fx of display.fixed) {
      markers.add(supportPlate(fx.centre as [number, number, number],
        fx.normal as [number, number, number], 0.35 * s.radius));
    }
    s.markers = markers;
    s.scene.add(markers);
    setView(s.camera, s.controls, s.center, s.radius, "iso");
  }, [display]);

  // deformed shape: move vertices along the displacement field
  useEffect(() => {
    const s = state.current;
    const part = s?.part;
    if (!s || !part) return;
    const d = display.displacement;
    let maxDisp = 0;
    for (let i = 0; i < d.length; i += 3) maxDisp = Math.max(maxDisp, Math.hypot(d[i], d[i + 1], d[i + 2]));
    const scale = maxDisp > 0 ? (exaggeration * display.size) / maxDisp : 0;
    const pos = part.geometry.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < display.positions.length; i++) {
      (pos.array as Float32Array)[i] = display.positions[i] + scale * d[i];
    }
    pos.needsUpdate = true;
    part.geometry.computeVertexNormals();
    display.loads.forEach((ld, i) => {
      const [dx, dy, dz] = ld.displacement;
      s.arrows[i]?.position.set(scale * dx, scale * dy, scale * dz);
    });
  }, [display, exaggeration]);

  const view = (v: ViewName) => {
    const s = state.current;
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
