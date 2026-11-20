export type TemplateName = "cantilever_beam" | "plate_with_hole";
export type MeshLevel = "coarse" | "medium" | "fine";

export interface Spec {
  template: TemplateName;
  material: string;
  mesh: MeshLevel;
  load: number;
  [key: string]: string | number;
}

export interface Comparison {
  quantity: string;
  formula: string;
  hand_calc: number;
  simulation: number;
  unit: string;
  note: string;
  error_pct: number;
  status: "PASS" | "WARN" | "FAIL";
}

export interface GciQuantity {
  quantity: string;
  unit: string;
  fine: number;
  medium: number;
  coarse: number;
  observed_order: number | null;
  extrapolated: number | null;
  gci_fine_pct: number;
  behaviour: "monotonic" | "oscillatory" | "converged" | "singular";
  order_clipped: boolean;
}

export interface Display {
  positions: number[];
  indices: number[];
  displacement: number[];
  von_mises: number[];
  range: [number, number];
  loads: {
    centre: number[]; normal: number[] | null; entity: Entity; kind: "force" | "moment";
    direction: number[]; magnitude: number; displacement: number[];
  }[];
  fixed: { centre: number[]; normal: number[] | null; entity: Entity; dofs: number[]; displacement: number[] }[];
  size: number;
}

export type Entity = "face" | "edge" | "point";
export type Vec3 = [number, number, number];

export interface SupportSpec {
  entity: Entity;
  ids: number[];
  point: Vec3 | null;
  dofs: number[];
}

export interface LoadSpec {
  entity: Entity;
  ids: number[];
  point: Vec3 | null;
  kind: "force" | "moment" | "pressure";
  vector: Vec3 | null;
  pressure: number | null;
}

export interface CustomSpec {
  template: "custom_part";
  part_id: string;
  units: Units;
  supports: SupportSpec[];
  loads: LoadSpec[];
  material: string;
  mesh: MeshLevel;
}

export type Units = "mm" | "cm" | "m" | "in";

export interface PartFace {
  id: number;
  area_mm2: number;
  centroid: number[];
  normal: number[];
}

export interface PartEdge {
  id: number;
  length_mm: number;
  midpoint: number[];
  direction: number[] | null;
  faces: number[];
}

export interface PartInfo {
  part_id: string;
  units: Units;
  bbox_mm: { min: number[]; max: number[]; size: number[] };
  faces: PartFace[];
  edges: PartEdge[];
  vertices: { id: number; point: number[] }[];
  display: {
    positions: number[]; indices: number[]; face_of_triangle: number[];
    edge_segments: number[]; edge_of_segment: number[];
  };
}

export interface StudyResult {
  spec: Spec | CustomSpec;
  mesh: { nodes: number; elements: number; element_type: string };
  summary: {
    material: string;
    max_von_mises_MPa: number;
    max_von_mises_at_mm: number[];
    max_displacement_mm: number;
    applied_load_N: number;
    strength_basis: string;
    strength_MPa: number;
    safety_factor: number;
    strength_z_MPa?: number;
    safety_factor_z?: number;
    warnings: string[];
    reaction_N: number[];
    equilibrium_error_pct: number;
  };
  comparisons: Comparison[];
  note: string;
  display: Display;
  timings: { mesh_s: number; solve_s: number };
  convergence?: {
    elements: Record<MeshLevel, number>;
    refinement_ratios: number[];
    quantities: GciQuantity[];
    method: string;
  };
}

export interface Health {
  version: string;
  solver: boolean;
  mesher: boolean;
  ai_provider: string | null;
}

export interface Material {
  key: string;
  name: string;
  category: "metal" | "printing_polymer" | "engineering_polymer";
  condition: string;
  youngs_modulus: number;
  youngs_modulus_z: number | null;
  poisson_ratio: number;
  yield_strength: number | null;
  tensile_strength: number;
  tensile_strength_z: number | null;
  elongation_pct: number | null;
  density: number;
  thermal_conductivity: number | null;
  specific_heat: number | null;
  thermal_expansion: number | null;
  max_service_temp: number | null;
  resistivity: number | null;
  electrical: "conductor" | "insulator" | "not_insulating";
  source: string;
  notes: string;
}
