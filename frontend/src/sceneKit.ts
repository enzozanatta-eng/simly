/**
 * Shared three.js pieces for both viewers: an XYZ axis gizmo drawn in a corner,
 * text labels, preset camera views and load arrows.
 */
import * as THREE from "three";
import { ArcballControls } from "three/examples/jsm/controls/ArcballControls.js";

export const AXIS_COLORS = { x: "#e03131", y: "#2f9e44", z: "#1c7ed6" };

/** A text label that always faces the camera. */
export function labelSprite(text: string, color: string, height: number, bold = true): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const font = `${bold ? "700 " : ""}56px Inter, system-ui, sans-serif`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + 28;
  canvas.width = w;
  canvas.height = 80;
  ctx.font = font;
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  ctx.beginPath();
  ctx.roundRect(0, 4, w, 72, 16);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, 14, 42);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }),
  );
  sprite.scale.set((height * w) / 80, height, 1);
  sprite.renderOrder = 10;
  return sprite;
}

/**
 * XYZ triad in the bottom-left corner, as in NX: it turns with the camera, and
 * clicking an axis looks along it (click again for the opposite side); the
 * centre ball goes back to the isometric view.
 */
export class AxisGizmo {
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1.75, 1.75, 1.75, -1.75, 0.1, 10);
  private pickables: THREE.Object3D[] = [];
  private ray = new THREE.Raycaster();
  readonly size = 130;

  constructor() {
    const axes: [THREE.Vector3, string, string][] = [
      [new THREE.Vector3(1, 0, 0), AXIS_COLORS.x, "X"],
      [new THREE.Vector3(0, 1, 0), AXIS_COLORS.y, "Y"],
      [new THREE.Vector3(0, 0, 1), AXIS_COLORS.z, "Z"],
    ];
    const tag = (o: THREE.Object3D, view: string) => {
      o.userData.view = view;
      o.traverse((c) => { c.userData.view = view; });
      this.pickables.push(o);
      return o;
    };
    for (const [dir, color, name] of axes) {
      const arrow = new THREE.ArrowHelper(dir, new THREE.Vector3(), 1.05, color, 0.32, 0.2);
      this.scene.add(tag(arrow, `+${name.toLowerCase()}`));
      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(0.06, 0.06, 0.8, 10),
        new THREE.MeshBasicMaterial({ color }),
      );
      shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      shaft.position.copy(dir.clone().multiplyScalar(0.4));
      this.scene.add(tag(shaft, `+${name.toLowerCase()}`));
      const label = labelSprite(name, color, 0.55);
      label.position.copy(dir.clone().multiplyScalar(1.42));
      this.scene.add(tag(label, `+${name.toLowerCase()}`));
      // small ball on the negative side: click to look from there
      const back = new THREE.Mesh(
        new THREE.SphereGeometry(0.13, 16, 12),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.45 }),
      );
      back.position.copy(dir.clone().multiplyScalar(-0.9));
      this.scene.add(tag(back, `-${name.toLowerCase()}`));
    }
    const centre = new THREE.Mesh(
      new THREE.SphereGeometry(0.17, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0x495057 }),
    );
    this.scene.add(tag(centre, "iso"));
  }

  private rect(el: HTMLCanvasElement) {
    return { x: 8, y: el.clientHeight - this.size - 8, w: this.size, h: this.size };
  }

  render(renderer: THREE.WebGLRenderer, main: THREE.Camera) {
    const el = renderer.domElement;
    this.camera.position.set(0, 0, 4).applyQuaternion(main.quaternion);
    this.camera.quaternion.copy(main.quaternion);
    this.camera.updateMatrixWorld();
    renderer.clearDepth();
    renderer.setScissorTest(true);
    renderer.setViewport(8, 8, this.size, this.size);
    renderer.setScissor(8, 8, this.size, this.size);
    renderer.render(this.scene, this.camera);
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, el.clientWidth, el.clientHeight);
  }

  /** The view under a click (canvas pixel coordinates), or null outside the triad. */
  pick(el: HTMLCanvasElement, x: number, y: number): string | null {
    const r = this.rect(el);
    if (x < r.x || x > r.x + r.w || y < r.y || y > r.y + r.h) return null;
    const ndc = new THREE.Vector2(((x - r.x) / r.w) * 2 - 1, -((y - r.y) / r.h) * 2 + 1);
    this.ray.setFromCamera(ndc, this.camera);
    const hit = this.ray.intersectObjects(this.pickables, true)[0];
    return hit ? (hit.object.userData.view as string) : "";
  }

  contains(el: HTMLCanvasElement, x: number, y: number): boolean {
    const r = this.rect(el);
    return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
  }
}

export type ViewName = "iso" | "+x" | "-x" | "+y" | "-y" | "+z" | "-z";

const VIEW_DIRS: Record<ViewName, [number, number, number]> = {
  iso: [1, -1.6, 1.1], "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0],
  "+z": [0, 0, 1], "-z": [0, 0, -1],
};

export const opposite = (v: ViewName): ViewName =>
  v === "iso" ? "iso" : (`${v[0] === "+" ? "-" : "+"}${v[1]}` as ViewName);

/** CAD-style navigation: free rotation, pan, zoom towards the cursor, double-click to focus. */
export function cadControls(camera: THREE.PerspectiveCamera, el: HTMLElement, scene: THREE.Scene) {
  const controls = new ArcballControls(camera, el, scene);
  controls.setGizmosVisible(false);
  controls.cursorZoom = true;
  controls.enableAnimations = true;
  controls.adjustNearFar = true;
  // NX-like: middle button rotates, shift + middle pans (left rotates, right pans too)
  controls.unsetMouseAction(1);
  controls.unsetMouseAction(1, "SHIFT");
  controls.setMouseAction("ROTATE", 1);
  controls.setMouseAction("PAN", 1, "SHIFT");
  return controls;
}

/** Point the camera at the centre from a named direction. */
export function setView(
  camera: THREE.PerspectiveCamera, controls: ArcballControls,
  center: THREE.Vector3, radius: number, view: ViewName,
) {
  const dir = new THREE.Vector3(...VIEW_DIRS[view]).normalize();
  const dist = (radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 0.95;
  const vertical = Math.abs(dir.z) > 0.99;
  camera.up.set(0, vertical ? (dir.z > 0 ? 1 : -1) : 0, vertical ? 0 : 1);
  camera.position.copy(center).addScaledVector(dir, dist);
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  // ArcballControls has a public target, missing from its type declarations
  (controls as unknown as { target: THREE.Vector3 }).target.copy(center);
  controls.setCamera(camera);
}

export interface ArrowSpec {
  /** point of application on the surface */
  at: [number, number, number];
  /** unit direction of the force */
  dir: [number, number, number];
  /** outward normal of the loaded surface, to place the arrow outside the part */
  normal: [number, number, number];
  label: string;
  color?: string;
  /** a moment: double-headed arrow along its axis (right-hand rule) */
  moment?: boolean;
}

/** Force arrow drawn outside the part: its tip touches the face when it pushes, its tail when it pulls. */
export function forceArrow(a: ArrowSpec, length: number): THREE.Group {
  const g = new THREE.Group();
  const dir = new THREE.Vector3(...a.dir).normalize();
  const at = new THREE.Vector3(...a.at);
  const normal = new THREE.Vector3(...a.normal).normalize();
  const pulling = a.moment ? true : dir.dot(normal) > 0.2;
  const start = pulling ? at : at.clone().addScaledVector(dir, -length);
  const color = a.color ?? (a.moment ? "#7048e8" : "#d6336c");
  const arrow = new THREE.ArrowHelper(dir, start, length, color, 0.28 * length, 0.16 * length);
  if (a.moment) {
    // second head just behind the first: the usual double-arrow symbol for a moment
    g.add(new THREE.ArrowHelper(dir, start, 0.82 * length, color, 0.28 * length, 0.16 * length));
  }
  (arrow.line.material as THREE.LineBasicMaterial).linewidth = 2;
  g.add(arrow);
  // a thicker shaft so it reads at any zoom
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.025 * length, 0.025 * length, 0.72 * length, 12),
    new THREE.MeshBasicMaterial({ color }),
  );
  shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  shaft.position.copy(start).addScaledVector(dir, 0.36 * length);
  g.add(shaft);
  const tail = pulling ? at.clone().addScaledVector(dir, length * 1.12) : start.clone().addScaledVector(dir, -0.12 * length);
  const label = labelSprite(a.label, color, 0.2 * length);
  label.position.copy(tail);
  g.add(label);
  return g;
}

/**
 * Support symbol: a translucent plate on a face, a ball on an edge or point;
 * labelled with the held directions when it is not fully fixed.
 */
export function supportPlate(
  at: [number, number, number], normal: [number, number, number], size: number,
  entity = "face", dofs: number[] = [1, 2, 3],
): THREE.Object3D {
  const g = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: 0x343a40, transparent: true, opacity: 0.3,
    side: THREE.DoubleSide, depthWrite: false });
  if (entity === "face") {
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mat);
    const n = new THREE.Vector3(...normal).normalize();
    plate.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    plate.position.set(...at).addScaledVector(n, 0.004 * size);
    g.add(plate);
  } else {
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.06 * size, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0x343a40 }));
    ball.position.set(...at);
    g.add(ball);
  }
  if (dofs.length < 3) {
    const label = labelSprite(`holds ${dofs.map((d) => "XYZ"[d - 1]).join("")}`, "#343a40", 0.12 * size * 2);
    label.position.set(...at);
    label.position.z += 0.2 * size;
    g.add(label);
  }
  return g;
}

/** Describe a direction in words, e.g. "−Z" or "(0.71, 0, −0.71)". */
export function directionName(d: number[]): string {
  const names = ["X", "Y", "Z"];
  for (let i = 0; i < 3; i++) {
    if (Math.abs(Math.abs(d[i]) - 1) < 1e-3) return `${d[i] > 0 ? "+" : "−"}${names[i]}`;
  }
  return `(${d.map((v) => (Math.abs(v) < 5e-3 ? "0" : v.toFixed(2))).join(", ")})`;
}

/**
 * Clicks on the triad change the view; clicking the same axis twice flips to
 * the opposite side. Returns a cleanup function.
 */
export function bindGizmo(
  canvas: HTMLCanvasElement, gizmo: AxisGizmo, apply: (v: ViewName) => void,
): () => void {
  let last: ViewName | null = null;
  let down: { x: number; y: number } | null = null;
  const local = (ev: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };
  const onDown = (ev: PointerEvent) => { down = local(ev); };
  const onUp = (ev: PointerEvent) => {
    const p = local(ev);
    if (!down || Math.hypot(p.x - down.x, p.y - down.y) > 5) return;
    const hit = gizmo.pick(canvas, p.x, p.y);
    if (!hit) return;
    let view = hit as ViewName;
    if (view !== "iso" && view === last) view = opposite(view);
    last = view;
    apply(view);
  };
  const onMove = (ev: PointerEvent) => {
    const p = local(ev);
    if (gizmo.contains(canvas, p.x, p.y)) canvas.style.cursor = "pointer";
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointermove", onMove);
  return () => {
    canvas.removeEventListener("pointerdown", onDown);
    canvas.removeEventListener("pointerup", onUp);
    canvas.removeEventListener("pointermove", onMove);
  };
}
