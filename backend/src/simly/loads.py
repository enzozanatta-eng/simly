"""Turning supports and loads on faces, edges and points into nodal quantities.

Quadratic elements need *consistent* nodal loads, not equal shares:

* 6-node triangle under a uniform traction: corners 0, each mid-side node A/3.
* 3-node line under a uniform line load: ends L/6, middle node 4L/6.

A moment is applied as forces f_i = w_i (theta x r_i) about the weighted
centroid, the distribution a rigid twist would produce. Solving
J theta = M, with J = sum w_i (|r_i|^2 I - r_i r_i^T), makes the resultant
moment exactly M and the resultant force exactly zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import Mesh


class LoadError(ValueError):
    pass


@dataclass
class Weighted:
    """Nodes of a selection with their consistent weights (area or length)."""

    nodes: np.ndarray
    weights: np.ndarray
    points: np.ndarray

    @property
    def total(self) -> float:
        return float(self.weights.sum())

    @property
    def centre(self) -> np.ndarray:
        return self.weights @ self.points / self.total


def face_weights(mesh: Mesh, name: str) -> Weighted:
    tris = mesh.faces[name]
    p = mesh.nodes
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    w = np.zeros(len(p))
    for col in (3, 4, 5):
        np.add.at(w, tris[:, col], area / 3)
    nodes = np.unique(tris)
    return Weighted(nodes, w[nodes], p[nodes])


def edge_weights(mesh: Mesh, name: str) -> Weighted:
    lines = mesh.edges[name]
    p = mesh.nodes
    length = np.linalg.norm(p[lines[:, 1]] - p[lines[:, 0]], axis=1)
    w = np.zeros(len(p))
    np.add.at(w, lines[:, 0], length / 6)
    np.add.at(w, lines[:, 1], length / 6)
    np.add.at(w, lines[:, 2], 4 * length / 6)
    nodes = np.unique(lines)
    return Weighted(nodes, w[nodes], p[nodes])


def point_node(mesh: Mesh, point) -> int:
    """Nearest boundary node to a point, so a point load sits on the surface."""
    skin = np.unique(mesh.skin)
    d = np.linalg.norm(mesh.nodes[skin] - np.asarray(point, float), axis=1)
    return int(skin[np.argmin(d)])


def distribute_force(n_nodes: int, sel: Weighted, force) -> np.ndarray:
    out = np.zeros((n_nodes, 3))
    out[sel.nodes] = np.outer(sel.weights / sel.total, np.asarray(force, float))
    return out


def pressure_forces(mesh: Mesh, name: str, pressure: float) -> np.ndarray:
    """Pressure pushing into the face, following each triangle's own normal
    (so it is right on curved faces too). Triangles are stored outward-facing."""
    tris = mesh.faces[name]
    p = mesh.nodes
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    area_vec = 0.5 * np.cross(b - a, c - a)  # area x outward normal
    out = np.zeros_like(p)
    for col in (3, 4, 5):
        np.add.at(out, tris[:, col], -pressure * area_vec / 3)
    return out


def moment_forces(n_nodes: int, sel: Weighted, moment) -> np.ndarray:
    m = np.asarray(moment, float)
    r = sel.points - sel.centre
    w = sel.weights
    inertia = (np.einsum("i,ij,ij->", w, r, r) * np.eye(3)
               - np.einsum("i,ij,ik->jk", w, r, r))
    m_hat = m / np.linalg.norm(m)
    if m_hat @ inertia @ m_hat < 1e-9 * np.trace(inertia):
        raise LoadError("This moment twists about a straight edge, which cannot carry it; "
                        "apply it to a face instead.")
    theta = np.linalg.solve(inertia + 1e-12 * np.trace(inertia) * np.eye(3), m)
    out = np.zeros((n_nodes, 3))
    out[sel.nodes] = w[:, None] * np.cross(theta, r)
    return out


@dataclass
class Mark:
    """What the viewer draws for a support or a load."""

    kind: str  # "support", "force", "moment"
    nodes: np.ndarray
    centre: np.ndarray
    normal: np.ndarray | None
    vector: np.ndarray | None = None
    dofs: tuple[int, ...] = (1, 2, 3)
    entity: str = "face"


def face_normal(mesh: Mesh, name: str) -> np.ndarray:
    tris = mesh.faces[name]
    p = mesh.nodes
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    n = np.cross(b - a, c - a).sum(axis=0)
    return n / (np.linalg.norm(n) or 1.0)
