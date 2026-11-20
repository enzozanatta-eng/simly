import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PartInfo } from "./types";

export const ROLE_COLORS = {
  none: new THREE.Color("#c9ced6"),
  hover: new THREE.Color("#ffd43b"),
  fixed: new THREE.Color("#495057"),
  load: new THREE.Color("#e64980"),
  activeLoad: new THREE.Color("#c2255c"),
};

interface Props {
  part: PartInfo;
  /** colour of each face id, decided by the parent from its roles */
  colorOf: (faceId: number) => THREE.Color;
  onPick: (faceId: number) => void;
}

/** 3D view of an uploaded part where faces are picked with the mouse. */
export function PickViewer({ part, colorOf, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const hoverRef = useRef<number | null>(null);
  const colorOfRef = useRef(colorOf);
  const onPickRef = useRef(onPick);
  colorOfRef.current = colorOf;
  onPickRef.current = onPick;

  const faceOfTri = part.display.face_of_triangle;

  function paint() {
    const mesh = meshRef.current;
    if (!mesh) return;
    const colors = mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = colors.array as Float32Array;
    for (let t = 0; t < faceOfTri.length; t++) {
      const f = faceOfTri[t];
      const c = f === hoverRef.current ? ROLE_COLORS.hover : colorOfRef.current(f);
      for (let k = 0; k < 3; k++) arr.set([c.r, c.g, c.b], (3 * t + k) * 3);
    }
    colors.needsUpdate = true;
  }

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f4f6fa");
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(1, -1.5, 2);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    camera.up.set(0, 0, 1);
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
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.7, flatShading: true }),
    );
    scene.add(mesh);
    meshRef.current = mesh;
    paint();

    geometry.computeBoundingSphere();
    const { center, radius } = geometry.boundingSphere!;
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(1.5, -2.6, 1.7).multiplyScalar(radius));
    camera.near = radius / 100;
    camera.far = radius * 100;

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
    const onMove = (ev: PointerEvent) => {
      const f = faceAt(ev);
      if (f !== hoverRef.current) {
        hoverRef.current = f;
        paint();
      }
    };
    const onDown = (ev: PointerEvent) => { down = { x: ev.clientX, y: ev.clientY }; };
    const onUp = (ev: PointerEvent) => {
      // a click, not the end of an orbit drag
      if (down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 5) {
        const f = faceAt(ev);
        if (f !== null) onPickRef.current(f);
      }
      down = null;
    };
    const canvas = renderer.domElement;
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);

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
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      controls.dispose();
      geometry.dispose();
      renderer.dispose();
      el.removeChild(canvas);
      meshRef.current = null;
    };
    // the scene is rebuilt only for a new part; colours update through paint()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [part]);

  useEffect(paint, [colorOf]);

  return <div className="viewer" ref={host} />;
}
