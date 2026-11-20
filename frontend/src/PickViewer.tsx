import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { ArcballControls } from "three/examples/jsm/controls/ArcballControls.js";
import {
  type ArrowSpec, AxisGizmo, bindGizmo, cadControls, forceArrow, setView, supportPlate,
} from "./sceneKit";
import type { Entity, PartInfo, Vec3 } from "./types";

export const ROLE_COLORS = {
  none: new THREE.Color("#d5dae3"),
  hover: new THREE.Color("#ffd43b"),
  fixed: new THREE.Color("#5c677d"),
  load: new THREE.Color("#f783ac"),
  activeLoad: new THREE.Color("#e64980"),
  edge: new THREE.Color("#1c2230"),
};

export interface PickTarget {
  entity: Entity;
  id?: number;
  point?: Vec3;
}

export interface SupportMarker {
  at: Vec3;
  normal: Vec3;
  entity: Entity;
  dofs: number[];
}

interface Props {
  part: PartInfo;
  filter: Entity;
  faceColor: (id: number) => THREE.Color;
  edgeColor: (id: number) => THREE.Color | null;
  onPick: (t: PickTarget) => void;
  onHover: (t: PickTarget | null) => void;
  arrows: ArrowSpec[];
  supports: SupportMarker[];
  points: { at: Vec3; color: string }[];
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: ArcballControls;
  mesh: THREE.Mesh;
  lines: THREE.LineSegments;
  markers: THREE.Group;
  cursor: THREE.Mesh;
  center: THREE.Vector3;
  radius: number;
}

/** Large 3D view of an uploaded part: faces, edges or points are picked with the mouse. */
export function PickViewer(props: Props) {
  const { part, faceColor, edgeColor, arrows, supports, points, filter } = props;
  const host = useRef<HTMLDivElement>(null);
  const st = useRef<SceneState | null>(null);
  const hoverRef = useRef<PickTarget | null>(null);
  const cb = useRef(props);
  cb.current = props;
  const faceOfTri = part.display.face_of_triangle;
  const edgeOfSeg = part.display.edge_of_segment;

  function paint() {
    const s = st.current;
    if (!s) return;
    const hov = hoverRef.current;
    const colors = s.mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = colors.array as Float32Array;
    for (let t = 0; t < faceOfTri.length; t++) {
      const f = faceOfTri[t];
      const c = hov?.entity === "face" && hov.id === f ? ROLE_COLORS.hover : cb.current.faceColor(f);
      for (let k = 0; k < 3; k++) arr.set([c.r, c.g, c.b], (3 * t + k) * 3);
    }
    colors.needsUpdate = true;
    const lc = s.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    const la = lc.array as Float32Array;
    for (let i = 0; i < edgeOfSeg.length; i++) {
      const e = edgeOfSeg[i];
      const c = hov?.entity === "edge" && hov.id === e ? ROLE_COLORS.hover
        : cb.current.edgeColor(e) ?? ROLE_COLORS.edge;
      la.set([c.r, c.g, c.b, c.r, c.g, c.b], 6 * i);
    }
    lc.needsUpdate = true;
    const mat = s.lines.material as THREE.LineBasicMaterial;
    mat.opacity = cb.current.filter === "edge" ? 1 : 0.55;
    s.cursor.visible = hov?.entity === "point";
    if (hov?.point) s.cursor.position.set(...hov.point);
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

    // non-indexed geometry so every triangle can take its own face colour
    const { positions, indices, edge_segments } = part.display;
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

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(edge_segments, 3));
    lineGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(edge_segments.length), 3));
    const lines = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.55,
    }));
    scene.add(lines);

    const markers = new THREE.Group();
    scene.add(markers);
    geometry.computeBoundingSphere();
    const { center, radius } = geometry.boundingSphere!;
    const cursor = new THREE.Mesh(new THREE.SphereGeometry(0.018 * radius, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xffd43b, depthTest: false }));
    cursor.renderOrder = 20;
    cursor.visible = false;
    scene.add(cursor);

    const controls = cadControls(camera, renderer.domElement, scene);
    st.current = { renderer, scene, camera, controls, mesh, lines, markers, cursor, center, radius };
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

    const vertices = part.vertices.map((v) => new THREE.Vector3(...v.point));
    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const canvas = renderer.domElement;
    const gizmo = new AxisGizmo();

    const targetAt = (ev: PointerEvent): PickTarget | null => {
      const r = canvas.getBoundingClientRect();
      if (gizmo.contains(canvas, ev.clientX - r.left, ev.clientY - r.top)) return null;
      pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(pointer, camera);
      const mode = cb.current.filter;
      if (mode === "edge") {
        // pixel-ish tolerance: a fraction of the distance to the part
        ray.params.Line.threshold = camera.position.distanceTo(center) * 0.012;
        const hit = ray.intersectObject(lines)[0];
        return hit?.index != null ? { entity: "edge", id: edgeOfSeg[Math.floor(hit.index / 2)] } : null;
      }
      const hit = ray.intersectObject(mesh)[0];
      if (!hit) return null;
      if (mode === "face") return hit.faceIndex != null ? { entity: "face", id: faceOfTri[hit.faceIndex] } : null;
      // point: snap to a corner when close
      const snap = camera.position.distanceTo(center) * 0.025;
      const near = vertices.reduce<THREE.Vector3 | null>(
        (best, v) => (v.distanceTo(hit.point) < snap && (!best || v.distanceTo(hit.point) < best.distanceTo(hit.point)) ? v : best), null);
      const p = (near ?? hit.point).toArray().map((x) => Math.round(x * 1e4) / 1e4) as Vec3;
      return { entity: "point", point: p };
    };

    let down: { x: number; y: number } | null = null;
    const same = (a: PickTarget | null, b: PickTarget | null) =>
      a?.entity === b?.entity && a?.id === b?.id && a?.point?.join() === b?.point?.join();
    const onMove = (ev: PointerEvent) => {
      if (down) return; // navigating
      const t = targetAt(ev);
      if (!same(t, hoverRef.current)) {
        hoverRef.current = t;
        canvas.style.cursor = t ? "pointer" : "grab";
        cb.current.onHover(t);
        paint();
      }
    };
    const onDown = (ev: PointerEvent) => { down = { x: ev.clientX, y: ev.clientY }; };
    const onUp = (ev: PointerEvent) => {
      if (ev.button === 0 && down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 5) {
        const t = targetAt(ev);
        if (t) cb.current.onPick(t);
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
    const unbind = bindGizmo(canvas, gizmo, (v) => setView(camera, controls, center, radius, v));

    let frame = 0;
    const loop = () => {
      renderer.clear();
      renderer.render(scene, camera);
      gizmo.render(renderer, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      unbind();
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      controls.dispose();
      geometry.dispose();
      lineGeo.dispose();
      renderer.dispose();
      el.removeChild(canvas);
      st.current = null;
    };
    // rebuilt only for a new part; colours and markers update separately
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [part]);

  useEffect(paint, [faceColor, edgeColor, filter]);

  useEffect(() => {
    const s = st.current;
    if (!s) return;
    s.markers.clear();
    const len = 0.45 * s.radius;
    for (const sp of supports) s.markers.add(supportPlate(sp.at, sp.normal, 0.35 * s.radius, sp.entity, sp.dofs));
    for (const a of arrows) s.markers.add(forceArrow(a, len));
    for (const p of points) {
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.02 * s.radius, 16, 12),
        new THREE.MeshBasicMaterial({ color: p.color, depthTest: false }));
      ball.renderOrder = 15;
      ball.position.set(...p.at);
      s.markers.add(ball);
    }
  }, [arrows, supports, points, part]);

  return (
    <div className="viewer-shell">
      <div className="viewer" ref={host} />
    </div>
  );
}
