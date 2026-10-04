"""Mounting orientation: remap IMU axes before tilt filtering.

Triki is often worn or rested flat (horizontal). These remaps rotate the
sensor frame so pitch/roll match how the user holds the cap. Applied to
accel and gyro the same way. Signs and axis choices remain a
reference-hypothesis — not HOM-27 measured.
"""

from __future__ import annotations

from dataclasses import dataclass

Tuple3 = tuple[int, int, int]
FloatTuple3 = tuple[float, float, float]
Matrix3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True, slots=True)
class MountingOrientation:
    """One mounting frame: 3×3 rotation applied as v' = R @ v."""

    id: str
    label_pl: str
    description_pl: str
    matrix: Matrix3


def _mat(
    r00: float,
    r01: float,
    r02: float,
    r10: float,
    r11: float,
    r12: float,
    r20: float,
    r21: float,
    r22: float,
) -> Matrix3:
    return (
        (r00, r01, r02),
        (r10, r11, r12),
        (r20, r21, r22),
    )


# Right-handed remaps. Horizontal keeps gravity on −Z when the cap lies flat.
# Vertical steering rest, measured on CAP001: gravity is on sensor −Y
# (about −2064 counts). That pose becomes control −Z, so pitch and roll
# are zero while the wheel is centered. Twist in the wheel plane stays roll.
_ORIENTATIONS: dict[str, MountingOrientation] = {
    "horizontal": MountingOrientation(
        id="horizontal",
        label_pl="Poziomo",
        description_pl="Nakładka leży płasko (domyślnie). Bez zmiany osi.",
        matrix=_mat(1, 0, 0, 0, 1, 0, 0, 0, 1),
    ),
    "yaw_90": MountingOrientation(
        id="yaw_90",
        label_pl="Poziomo · obrót 90°",
        description_pl="Płasko, obrót 90° wokół pionu (yaw).",
        matrix=_mat(0, 1, 0, -1, 0, 0, 0, 0, 1),
    ),
    "yaw_180": MountingOrientation(
        id="yaw_180",
        label_pl="Poziomo · obrót 180°",
        description_pl="Płasko, obrót 180° — przód/tył i lewo/prawo zamienione.",
        matrix=_mat(-1, 0, 0, 0, -1, 0, 0, 0, 1),
    ),
    "yaw_270": MountingOrientation(
        id="yaw_270",
        label_pl="Poziomo · obrót 270°",
        description_pl="Płasko, obrót 270° wokół pionu (yaw).",
        matrix=_mat(0, -1, 0, 1, 0, 0, 0, 0, 1),
    ),
    "vertical": MountingOrientation(
        id="vertical",
        label_pl="Pionowo",
        description_pl="Kierownica pionowo. Grawitacja na −Y czujnika jest pozycją zerową.",
        matrix=_mat(0, 0, -1, -1, 0, 0, 0, 1, 0),
    ),
    "vertical_180": MountingOrientation(
        id="vertical_180",
        label_pl="Pionowo · obrót 180°",
        description_pl="Kierownica pionowo, dodatkowo obrót 180° wokół pionu.",
        matrix=_mat(0, 0, 1, 1, 0, 0, 0, 1, 0),
    ),
}

DEFAULT_ORIENTATION = "horizontal"
ORIENTATION_IDS = tuple(_ORIENTATIONS.keys())

# CLI / settings aliases → canonical id
_ALIASES = {
    "horizontal": "horizontal",
    "poziomo": "horizontal",
    "0": "horizontal",
    "yaw_90": "yaw_90",
    "90": "yaw_90",
    "yaw_180": "yaw_180",
    "180": "yaw_180",
    "yaw_270": "yaw_270",
    "270": "yaw_270",
    "vertical": "vertical",
    "pionowo": "vertical",
    "vertical_180": "vertical_180",
    "pionowo_180": "vertical_180",
}


def parse_orientation(name: str) -> str:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return _ALIASES[key]
    except KeyError as exc:
        known = ", ".join(ORIENTATION_IDS)
        raise ValueError(f"unknown orientation {name!r}; choose one of: {known}") from exc


def get_orientation(name: str) -> MountingOrientation:
    return _ORIENTATIONS[parse_orientation(name)]


def orientation_choices() -> tuple[MountingOrientation, ...]:
    return tuple(_ORIENTATIONS[oid] for oid in ORIENTATION_IDS)


def orientation_labels_pl() -> dict[str, str]:
    return {oid: _ORIENTATIONS[oid].label_pl for oid in ORIENTATION_IDS}


def remap_vector(vector: Tuple3 | FloatTuple3, orientation: str | MountingOrientation) -> FloatTuple3:
    """Apply mounting rotation: v' = R @ v. Accel and gyro use the same R."""
    matrix = orientation.matrix if isinstance(orientation, MountingOrientation) else get_orientation(orientation).matrix
    x, y, z = (float(vector[0]), float(vector[1]), float(vector[2]))
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    )


def unmap_vector(vector: Tuple3 | FloatTuple3, orientation: str | MountingOrientation) -> FloatTuple3:
    """Inverse mounting rotation: v = Rᵀ @ v' (R is orthonormal)."""
    matrix = orientation.matrix if isinstance(orientation, MountingOrientation) else get_orientation(orientation).matrix
    x, y, z = (float(vector[0]), float(vector[1]), float(vector[2]))
    return (
        matrix[0][0] * x + matrix[1][0] * y + matrix[2][0] * z,
        matrix[0][1] * x + matrix[1][1] * y + matrix[2][1] * z,
        matrix[0][2] * x + matrix[1][2] * y + matrix[2][2] * z,
    )


def remap_counts(counts: Tuple3, orientation: str | MountingOrientation) -> Tuple3:
    x, y, z = remap_vector(counts, orientation)
    return (int(round(x)), int(round(y)), int(round(z)))


def unmap_counts(counts: Tuple3, orientation: str | MountingOrientation) -> Tuple3:
    x, y, z = unmap_vector(counts, orientation)
    return (int(round(x)), int(round(y)), int(round(z)))
