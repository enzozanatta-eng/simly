"""Build small STL/STEP test parts with Gmsh's OpenCASCADE kernel."""

from pathlib import Path


def make_part(path: Path, shape: str = "box") -> Path:
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        if shape == "box":  # 1000 x 50 x 80 mm beam
            occ.addBox(0, 0, 0, 1000, 50, 80)
        elif shape == "bracket":  # L bracket with a hole in the vertical leg
            base = occ.addBox(0, 0, 0, 80, 40, 6)
            leg = occ.addBox(0, 0, 0, 6, 40, 60)
            occ.fuse([(3, base)], [(3, leg)])
            hole = occ.addCylinder(-1, 20, 40, 8, 0, 0, 5)
            occ.cut(occ.getEntities(3), [(3, hole)])
        elif shape == "shaft":  # round bar, diameter 20 mm, length 200 mm along x
            occ.addCylinder(0, 0, 0, 200, 0, 0, 10)
        occ.synchronize()
        if path.suffix == ".stl":
            gmsh.option.setNumber("Mesh.MeshSizeMax", 10)
            gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path
