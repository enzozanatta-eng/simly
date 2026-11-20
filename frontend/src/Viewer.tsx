import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { turbo } from "./colormap";
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
}

/** Interactive 3D view of the part coloured by von Mises stress. */
export function Viewer({ display, exaggeration }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<SceneState | null>(null);

  // one renderer for the lifetime of the component
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f4f6fa");
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(1, -1.5, 2);
    scene.add(sun);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    camera.up.set(0, 0, 1); // the model is z-up
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    state.current = { renderer, scene, camera, controls };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
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
    geometry.setAttribute(
      "position", new THREE.Float32BufferAttribute(display.positions.slice(), 3),
    );
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
    s.markers = buildMarkers(display);
    s.scene.add(s.markers);

    // frame the part
    geometry.computeBoundingSphere();
    const { center, radius } = geometry.boundingSphere!;
    s.controls.target.copy(center);
    s.camera.position.copy(center).add(new THREE.Vector3(1.2, -2.5, 1.5).multiplyScalar(radius));
    s.camera.near = radius / 100;
    s.camera.far = radius * 100;
    s.camera.updateProjectionMatrix();
  }, [display]);

  // deformed shape: move vertices along the displacement field
  useEffect(() => {
    const part = state.current?.part;
    if (!part) return;
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

    // load arrows ride with their loaded faces
    display.loads.forEach((ld, i) => {
      const arrow = state.current?.markers?.getObjectByName(`load${i}`);
      const [dx, dy, dz] = ld.displacement;
      arrow?.position.set(scale * dx, scale * dy, scale * dz);
    });
  }, [display, exaggeration]);

  return <div className="viewer" ref={host} />;
}

/** Arrows for the loads, translucent walls for the supports. */
function buildMarkers(d: Display): THREE.Group {
  const group = new THREE.Group();
  const len = 0.18 * d.size;
  d.loads.forEach((ld, i) => {
    const dir = new THREE.Vector3(...ld.direction).normalize();
    const tip = new THREE.Vector3(...ld.centre);
    // a pull starts at the face and points away; a push points at the face from outside
    const start = ld.pulling ? tip : tip.clone().addScaledVector(dir, -len);
    const arrow = new THREE.Group();
    arrow.name = `load${i}`;
    arrow.add(new THREE.ArrowHelper(dir, start, len, 0xd6336c, 0.3 * len, 0.15 * len));
    group.add(arrow);
  });
  for (const fx of d.fixed) {
    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(0.3 * d.size, 0.3 * d.size),
      new THREE.MeshBasicMaterial({ color: 0x495057, transparent: true, opacity: 0.3,
        side: THREE.DoubleSide, depthWrite: false }),
    );
    const normal = new THREE.Vector3(...fx.normal).normalize();
    wall.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    wall.position.set(...(fx.centre as [number, number, number]));
    wall.position.addScaledVector(normal, 0.002 * d.size);
    group.add(wall);
  }
  return group;
}
