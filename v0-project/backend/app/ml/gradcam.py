"""Phase 3 — real Grad-CAM explainability for the trained EfficientNet-B0.

Computes a gradient-weighted class-activation map against the actual Phase 2
checkpoint (``efficientnet_b0_dr.pt``) via manual forward/backward hooks on the
last convolutional block (``features[-1]`` in the torchvision implementation).
No placeholder/canned visualizations: the heatmap reflects the gradients of the
model's own decision.

Two classifier variants are supported, matching Phase 2's ``classifier.py``:
  * 5-class head (``out_features == 5``): target = the predicted class score.
  * ordinal-regression head (``out_features == 1``): there is no discrete class,
    so the raw scalar output is used as the backprop target. The heatmap then
    means "regions driving the severity score upward", NOT "regions driving
    class N" — this semantic difference is intentional and documented.

Every failure path (OOM, hook mismatch, corrupt checkpoint) returns ``None`` so
the rest of the pipeline (structured findings + text report) proceeds and the
UI shows "Heatmap unavailable" rather than blocking the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import settings
from .preprocessing import preprocess_image, preprocess_image_display

logger = logging.getLogger("netrascan.gradcam")

# CAM overlay blend factor (higher = more heatmap, less fundus underneath).
OVERLAY_ALPHA = 0.45

# Regional-analysis tuning (Fix 2 — regions are computed from the real CAM).
REGION_THRESHOLD_PCT = 0.80  # keep the top 20% of activation values
MIN_CLUSTER_AREA_FRAC = 0.004  # <0.4% of the image = noise, not a hotspot
MAX_REPORTED_CLUSTERS = 4
MACULA_OD_DIAMETERS = 2.0  # the fovea sits ~2 disc diameters temporal to the disc


@dataclass
class GradcamResult:
    path: Optional[str]  # saved PNG path, or None when computation failed
    cam: Optional[np.ndarray]  # normalized 2-D CAM at input resolution (for region notes)


@dataclass
class OpticDisc:
    x: float
    y: float
    radius: float


@dataclass
class RegionAnalysis:
    """What the thresholded Grad-CAM actually shows (Fix 2)."""

    cluster_count: int
    used_optic_disc: bool  # false = positions are image-relative, not anatomical
    disc: Optional[dict]  # {"x","y","radius"} when detected
    clusters: list[dict]  # {x, y, area_frac, activation_share, zone, overlaps}
    description: str
    macula_attention: bool  # one or more clusters sit in the macular zone
    exudates_near_macula: int  # hard-exudate boxes whose centre is in the macular zone
    spread_evenly: bool  # true only when the thresholded map really has no clusters


def _load_classifier_model():
    """Reuse the checkpoint loader so Grad-CAM sees the exact same model class
    and weights as /analyze."""
    from .classifier import DRClassifier

    clf = DRClassifier().load()
    return clf._model, clf.ordinal


def generate_gradcam(
    image_path: Path,
    predicted_class: Optional[int],
    out_path: Path,
    size: int = 380,
    model=None,
    ordinal: bool = False,
    device: str = "cpu",
) -> GradcamResult:
    """Compute and save the Grad-CAM overlay for a single fundus image.

    ``model`` may be passed in to reuse an already-loaded instance (the
    registry keeps one resident); when None the checkpoint is loaded once.
    """
    if model is None:
        model, ordinal = _load_classifier_model()

    import cv2
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    tensor = preprocess_image(image, size=size)  # CHW, normalized — what the model sees
    display = preprocess_image_display(image, size=size)  # HWC uint8 — overlay base

    try:
        x = torch.from_numpy(tensor).unsqueeze(0).to(device)
        x.requires_grad_(True)

        activations: dict = {}
        gradients: dict = {}

        def fwd_hook(_mod, _inp, out):
            activations["a"] = out

        def bwd_hook(_mod, _ginp, gout):
            gradients["g"] = gout[0]

        target = model.features[-1]
        fwd_handle = target.register_forward_hook(fwd_hook)
        bwd_handle = target.register_full_backward_hook(bwd_hook)

        logits = model(x)

        if ordinal:
            # Single scalar head: backprop from the severity score itself.
            score = logits[0, 0]
        elif predicted_class is not None:
            score = logits[0, predicted_class]
        else:
            score = logits[0, int(torch.argmax(logits[0]))]

        model.zero_grad()
        score.backward()
        fwd_handle.remove()
        bwd_handle.remove()

        act = activations["a"].detach()
        grad = gradients["g"].detach()
        weights = grad.mean(dim=(2, 3), keepdim=True)  # alpha_c
        cam = torch.relu((weights * act).sum(dim=1))  # (1, H, W)
        cam = cam.squeeze(0).cpu().numpy().astype(np.float32)
        cam = cam - cam.min()
        denom = cam.max()
        cam = cam / denom if denom > 1e-8 else cam

        cam = cv2.resize(cam, (size, size), interpolation=cv2.INTER_LINEAR)

        heat = cv2.applyColorMap((cam * 255).astype(np.uint8), cv2.COLORMAP_JET)  # BGR
        base = cv2.cvtColor(display, cv2.COLOR_RGB2BGR)
        overlay = cv2.addWeighted(base, 1.0 - OVERLAY_ALPHA, heat, OVERLAY_ALPHA, 0)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(out_path), overlay)
        if not ok:
            logger.warning("Grad-CAM: cv2.imwrite returned False for %s", out_path)
            return GradcamResult(path=None, cam=cam)

        logger.info("Grad-CAM saved -> %s (class %s, ordinal=%s)", out_path, predicted_class, ordinal)
        return GradcamResult(path=str(out_path), cam=cam)

    except Exception as exc:  # noqa: BLE001 — OOM/hook mismatch must not block the report
        logger.warning("Grad-CAM failed for %s: %s", image_path, exc)
        return GradcamResult(path=None, cam=None)
    finally:
        try:
            fwd_handle.remove()
        except Exception:
            pass
        try:
            bwd_handle.remove()
        except Exception:
            pass


def _load_display_image(path: Path, size: int) -> Optional[np.ndarray]:
    """Best-effort load of the display image the model actually saw (matches the
    CAM coordinate frame). Returns None when the image cannot be read."""
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        return preprocess_image_display(img, size=size)
    except Exception as exc:  # noqa: BLE001 — region analysis is never fatal
        logger.warning("Could not load display image for region analysis: %s", exc)
        return None


def detect_optic_disc(display: np.ndarray, size: int) -> Optional[OpticDisc]:
    """Best-effort optic-disc localization on the preprocessed fundus image.

    The optic disc is the largest bright, roughly circular structure in a fundus
    photo. We threshold the brightness, keep length-scale-plausible connected
    components, and score candidates by circularity·solidity·brightness. A
    Hough-circle pass backs this up. Returns None (positions then fall back to
    image-relative terms) rather than guessing.
    """
    try:
        import cv2

        gray = cv2.cvtColor(display, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
        hi = float(np.percentile(blur, 93))
        _, binm = cv2.threshold(blur, max(hi, 1), 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        binm = cv2.morphologyEx(binm, cv2.MORPH_CLOSE, kernel)

        n, _labels, stats, centroids = cv2.connectedComponentsWithStats(binm, 8)
        area_min = 0.015 * size * size
        area_max = 0.25 * size * size
        candidates: list[tuple[float, float, float, float]] = []
        for i in range(1, n):
            area = float(stats[i, cv2.CC_STAT_AREA])
            w = float(stats[i, cv2.CC_STAT_WIDTH])
            h = float(stats[i, cv2.CC_STAT_HEIGHT])
            if area < area_min or area > area_max:
                continue
            cx, cy = centroids[i]
            circ = 4.0 * np.pi * area / max(w * h, 1.0)
            solidity = area / max(w * h, 1.0)
            cx_i, cy_i = int(round(cx)), int(round(cy))
            if 0 <= cx_i < size and 0 <= cy_i < size:
                brightness = float(blur[cy_i, cx_i]) / 255.0
            else:
                brightness = 0.0
            candidates.append((cx, cy, np.sqrt(area / np.pi), circ * solidity * (0.5 + brightness)))
        if candidates:
            best = max(candidates, key=lambda c: c[3])
            cx, cy, radius, _ = best
            return OpticDisc(x=cx, y=cy, radius=radius)

        # Hough fallback — accept the largest bright circle found.
        circles = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=size * 0.55,
            param1=120,
            param2=24,
            minRadius=int(size * 0.05),
            maxRadius=int(size * 0.28),
        )
        if circles is not None:
            circle = circles[0][0]
            return OpticDisc(x=float(circle[0]), y=float(circle[1]), radius=float(circle[2]))
    except Exception as exc:  # noqa: BLE001 — never fatal
        logger.warning("Optic-disc detection failed: %s", exc)
    return None


def _map_boxes_to_cam(
    lesion_boxes: Optional[dict[str, list[list[float]]]],
    original_size: tuple[int, int],
    size: int,
) -> dict[str, list[list[float]]]:
    """Map normalized (0..1) detection boxes into the CAM 380x380 frame.

    The detector sees the raw upload; the classifier/Grad-CAM sees a
    center-cropped square resized to ``size``. Boxes landing fully outside the
    crop are dropped, partial boxes are clamped back into the frame.
    """
    if not lesion_boxes:
        return {}
    w, h = original_size
    side = float(min(w, h))
    scale = size / side
    offset_x = (w - side) / 2.0
    offset_y = (h - side) / 2.0
    out: dict[str, list[list[float]]] = {}
    for ltype, boxes in lesion_boxes.items():
        mapped: list[list[float]] = []
        for b in boxes:
            x1 = (b[0] * w - offset_x) * scale
            y1 = (b[1] * h - offset_y) * scale
            x2 = (b[2] * w - offset_x) * scale
            y2 = (b[3] * h - offset_y) * scale
            if x2 < 0 or y2 < 0 or x1 > size or y1 > size:
                continue
            mapped.append([max(x1, 0.0), max(y1, 0.0), min(x2, float(size)), min(y2, float(size))])
        if mapped:
            out[ltype] = mapped
    return out


def _zone_for_cluster(
    cx: float,
    cy: float,
    disc: Optional[OpticDisc],
    size: int,
) -> tuple[str, bool]:
    """Coarse anatomical position of a cluster, using the optic disc as the
    reference (Fix 2). Returns (zone_label, is_macula)."""
    if disc is None:
        # Image-relative fallback when no anatomical reference is available.
        half = size / 2.0
        v = "upper" if cy < half else "lower"
        hpart = "left" if cx < half else "right"
        band = _radial_band(cx, cy, size)
        return f"{v}-{hpart} region of the image ({band})", False

    vx = cx - disc.x
    vy = cy - disc.y
    dist = float(np.hypot(vx, vy))
    r = disc.radius

    if dist <= 1.15 * r:
        return "surrounding the optic disc", False

    # The disc sits nasally in the photograph; without an eye line recorded we
    # infer laterality from where the disc appears (documented in the README).
    # Disc left of centre -> right eye (OD), temporal retina toward +x.
    temporal_sign = 1.0 if disc.x < size / 2.0 else -1.0
    mx = disc.x + temporal_sign * MACULA_OD_DIAMETERS * r
    my = disc.y
    if np.hypot(cx - mx, cy - my) <= 1.30 * r:
        return "macular region", True

    vertical = ""
    if vy <= -0.75 * r:
        vertical = "supero-"
    elif vy >= 0.75 * r:
        vertical = "infero-"

    horizontal = ""
    if vx * temporal_sign > 0.5 * r:
        horizontal = "temporal"
    elif vx * -temporal_sign > 0.5 * r:
        horizontal = "nasal"

    band = _radial_band(cx, cy, size)
    if vertical and horizontal:
        zone = f"{vertical}{horizontal} {band} retina"
    elif vertical:
        zone = f"{vertical.strip('-')} {band} retina"
    elif horizontal:
        zone = f"{horizontal} {band} retina"
    else:
        zone = f"{band} retina"
    return zone, False


def _radial_band(cx: float, cy: float, size: int) -> str:
    dist = np.hypot(cx - size / 2.0, cy - size / 2.0)
    frac = dist / (size / 2.0)
    if frac < 0.42:
        return "central"
    if frac < 0.75:
        return "mid-field"
    return "peripheral"


def analyze_heatmap_regions(
    cam: np.ndarray,
    *,
    image_path: Optional[Path] = None,
    display: Optional[np.ndarray] = None,
    lesion_boxes: Optional[dict[str, list[list[float]]]] = None,
    size: int = 380,
    threshold_pct: float = REGION_THRESHOLD_PCT,
) -> RegionAnalysis:
    """Characterize what the Grad-CAM heatmap actually shows (Fix 2).

    Thresholds the top of the activation map, finds connected hotspots, and for
    each hotspot computes a coarse anatomical position relative to the detected
    optic disc. Also reports whether any hotpot sits in the macular zone and
    whether detected lesion boxes overlap the hotspots. The "spread evenly"
    fallback is used ONLY when the thresholded map genuinely has no clusters.
    """
    empty = RegionAnalysis(
        cluster_count=0,
        used_optic_disc=False,
        disc=None,
        clusters=[],
        description="spread across the image, with no single concentrated region",
        macula_attention=False,
        exudates_near_macula=0,
        spread_evenly=True,
    )
    if cam is None or cam.size == 0:
        return empty

    if display is None:
        display = _load_display_image(image_path, size) if image_path is not None else None

    disc = detect_optic_disc(display, size) if display is not None else None

    # Hard-exudate boxes in the macular zone (needs disc + boxes).
    exudates_near_macula = 0
    if disc is not None and lesion_boxes:
        mapped = _map_boxes_to_cam(lesion_boxes, _image_size(image_path), size)
        for b in mapped.get("hard_exudate", []):
            cxm = (b[0] + b[2]) / 2.0
            cym = (b[1] + b[3]) / 2.0
            temporal_sign = 1.0 if disc.x < size / 2.0 else -1.0
            mx = disc.x + temporal_sign * MACULA_OD_DIAMETERS * disc.radius
            my = disc.y
            if np.hypot(cxm - mx, cym - my) <= 1.30 * disc.radius:
                exudates_near_macula += 1

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        logger.warning("cv2 unavailable for region analysis: %s", exc)
        return empty

    try:
        h, w = cam.shape
        thr = float(np.percentile(cam, threshold_pct * 100.0))
        binary = (cam >= thr).astype(np.uint8)
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
        min_area = MIN_CLUSTER_AREA_FRAC * size * size

        regions: list[dict] = []
        for i in range(1, n):
            area = float(stats[i, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            cx, cy = float(centroids[i][0]), float(centroids[i][1])
            mass = float(cam[labels == i].sum())
            zone, is_macula = _zone_for_cluster(cx, cy, disc, size)
            regions.append(
                {
                    "x": round(cx, 1),
                    "y": round(cy, 1),
                    "area_frac": round(area / (size * size), 4),
                    "activation_share": round(mass, 4),
                    "zone": zone,
                    "macula": is_macula,
                    "overlaps": [],
                }
            )

        if not regions:
            empty.used_optic_disc = disc is not None
            if disc is not None:
                empty.disc = {"x": round(disc.x, 1), "y": round(disc.y, 1), "radius": round(disc.radius, 1)}
            empty.exudates_near_macula = exudates_near_macula
            return empty

        total_mass = sum(r["activation_share"] for r in regions)
        for r in regions:
            r["activation_share"] = round(r["activation_share"] / total_mass, 3)

        regions.sort(key=lambda r: -r["activation_share"])

        # Overlap clause — which lesion types sit inside a hotspot.
        if lesion_boxes and disc is not None:
            mapped = _map_boxes_to_cam(lesion_boxes, _image_size(image_path), size)
            for r in regions:
                rradius = np.sqrt(r["area_frac"] * size * size / np.pi) * 1.6
                for ltype, boxes in mapped.items():
                    hit = False
                    for b in boxes:
                        cxm = (b[0] + b[2]) / 2.0
                        cym = (b[1] + b[3]) / 2.0
                        if np.hypot(cxm - r["x"], cym - r["y"]) <= rradius:
                            hit = True
                            break
                    if hit:
                        r["overlaps"].append(ltype)
                r["overlaps"] = list(dict.fromkeys(r["overlaps"]))

        top = regions[:MAX_REPORTED_CLUSTERS]
        zone_parts = [r["zone"] for r in top]
        if len(zone_parts) == 1:
            sentence = f"concentrated in 1 region: the {zone_parts[0]}"
        else:
            listed = ", ".join(f"the {z}" for z in zone_parts[:-1])
            sentence = (
                f"concentrated in {len(top)} regions: {listed} and {zone_parts[-1]}"
            )
        if len(regions) > len(top):
            sentence += f" (plus {len(regions) - len(top)} smaller areas)"
        overlap_types = sorted({t for r in top for t in r["overlaps"]})
        if overlap_types:
            noun = "clusters"
            sentence += f" — overlapping the detected {', '.join(overlap_types).replace('_', ' ')} {noun}"

        macula_attention = any(r["macula"] for r in regions)
        return RegionAnalysis(
            cluster_count=len(regions),
            used_optic_disc=disc is not None,
            disc=(
                {"x": round(disc.x, 1), "y": round(disc.y, 1), "radius": round(disc.radius, 1)}
                if disc is not None
                else None
            ),
            clusters=top,
            description=sentence,
            macula_attention=macula_attention,
            exudates_near_macula=exudates_near_macula,
            spread_evenly=False,
        )
    except Exception as exc:  # noqa: BLE001 — never fatal
        logger.warning("Region analysis failed: %s", exc)
        return empty


def _image_size(image_path: Optional[Path]) -> tuple[int, int]:
    if image_path is None or not image_path.exists():
        return (380, 380)
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            return img.size
    except Exception:
        return (380, 380)


# Kept as a compatibility shim used nowhere in the codebase: the report now uses
# analyze_heatmap_regions(). Removed from the imports in reports.py.
def region_notes_from_cam(cam: Optional[np.ndarray]) -> Optional[str]:
    """Legacy coarse quadrant text — superseded by ``analyze_heatmap_regions``."""
    if cam is None or cam.size == 0:
        return None
    return analyze_heatmap_regions(cam).description if cam.max() > 0 else None


def report_dir() -> Path:
    return settings.upload_dir / "reports"