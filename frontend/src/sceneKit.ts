/**
 * Shared three.js pieces for both viewers: an XYZ axis gizmo drawn in a corner,
 * text labels, preset camera views and load arrows.
 */
import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

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

/** Small XYZ triad rendered in the bottom-right corner, turning with the main camera. */
export class AxisGizmo {
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1.75, 1.75, 1.75, -1.75, 0.1, 10);

  constructor() {
    const axes: [THREE.Vector3, string, string][] = [
      [new THREE.Vector3(1, 0, 0), AXIS_COLORS.x, "X"],
      [new THREE.Vector3(0, 1, 0), AXIS_COLORS.y, "Y"],
      [new THREE.Vector3(0, 0, 1), AXIS_COLORS.z, "Z"],
    ];
    for (const [dir, color, name] of axes) {
      this.scene.add(new THREE.ArrowHelper(dir, new THREE.Vector3(), 1.05, color, 0.32, 0.2));
      const shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(0.045, 0.045, 0.8, 10),
        new THREE.MeshBasicMaterial({ color }),
      );
      shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      shaft.position.copy(dir.clone().multiplyScalar(0.4));
      this.scene.add(shaft);
      const label = labelSprite(name, color, 0.55);
      label.position.copy(dir.clone().multiplyScalar(1.42));
      this.scene.add(label);
    }
  }

  render(renderer: THREE.WebGLRenderer, main: THREE.Camera, size = 130) {
    const el = renderer.domElement;
    const w = el.clientWidth;
    this.camera.position.set(0, 0, 4).applyQuaternion(main.quaternion);
    this.camera.quaternion.copy(main.quaternion);
    renderer.clearDepth();
    renderer.setScissorTest(true);
    renderer.setViewport(w - size - 6, 6, size, size);
    renderer.setScissor(w - size - 6, 6, size, size);
    renderer.render(this.scene, this.camera);
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, el.clientHeight);
  }
}

export type ViewName = "iso" | "front" | "back" | "top" | "bottom" | "right" | "left";

const VIEW_DIRS: Record<ViewName, [number, number, number]> = {
  iso: [1, -1.6, 1.1],
  front: [0, -1, 0],
  back: [0, 1, 0],
  top: [0, 0, 1],
  bottom: [0, 0, -1],
  right: [1, 0, 0],
  left: [-1, 0, 0],
};

/** Point the camera at the centre from a named direction. */
export function setView(
  camera: THREE.PerspectiveCamera, controls: OrbitControls,
  center: THREE.Vector3, radius: number, view: ViewName,
) {
  const dir = new THREE.Vector3(...VIEW_DIRS[view]).normalize();
  const dist = (radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 0.95;
  controls.target.copy(center);
  // looking straight down Z would make the up vector degenerate
  camera.up.set(0, view === "top" || view === "bottom" ? 1 : 0, view === "top" || view === "bottom" ? 0 : 1);
  camera.position.copy(center).addScaledVector(dir, dist);
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.updateProjectionMatrix();
  controls.update();
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
}

/** Force arrow drawn outside the part: its tip touches the face when it pushes, its tail when it pulls. */
export function forceArrow(a: ArrowSpec, length: number): THREE.Group {
  const g = new THREE.Group();
  const dir = new THREE.Vector3(...a.dir).normalize();
  const at = new THREE.Vector3(...a.at);
  const normal = new THREE.Vector3(...a.normal).normalize();
  const pulling = dir.dot(normal) > 0.2;
  const start = pulling ? at : at.clone().addScaledVector(dir, -length);
  const color = a.color ?? "#d6336c";
  const arrow = new THREE.ArrowHelper(dir, start, length, color, 0.28 * length, 0.16 * length);
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

/** Hatched support symbol: a translucent plate on the face. */
export function supportPlate(at: [number, number, number], normal: [number, number, number], size: number) {
  const plate = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshBasicMaterial({ color: 0x343a40, transparent: true, opacity: 0.28,
      side: THREE.DoubleSide, depthWrite: false }),
  );
  const n = new THREE.Vector3(...normal).normalize();
  plate.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
  plate.position.set(...at).addScaledVector(n, 0.004 * size);
  return plate;
}

/** Describe a direction in words, e.g. "−Z" or "(0.71, 0, −0.71)". */
export function directionName(d: number[]): string {
  const names = ["X", "Y", "Z"];
  for (let i = 0; i < 3; i++) {
    if (Math.abs(Math.abs(d[i]) - 1) < 1e-3) return `${d[i] > 0 ? "+" : "−"}${names[i]}`;
  }
  return `(${d.map((v) => (Math.abs(v) < 5e-3 ? "0" : v.toFixed(2))).join(", ")})`;
}
