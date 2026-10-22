#!/usr/bin/env python3
"""Read scale (mm) and camera angle from a phone photo that shows a photo-measure card (PM-1 or PM-2) and/or cube.

Kit (PM-1 card 100 x 100 mm with ArUco DICT_4X4_50 ids 0-3, cube 30 mm with ids
10-15, PM-2 240 mm C-shaped card with ids 20-26 whose marker corners come from its spec JSON,
pm2_marker_spec.json next to this script). Every visible marker of a card is used (one marker already gives a
homography, 2+ recommended; markers hidden by the object being measured are skipped). When both cards are
visible, PM-2 is the measuring plane ("card" in the output) and PM-1 goes to "other_card".

  python tools/photo_measure.py PHOTO.jpg [--measure x1,y1,x2,y2 ...] [--calib K.json | --focal-px F | --focal-35mm F]
                                [--focal-auto] [--rect-ppm 10] [--rect-margin 30] [--no-files]
                                [--spec PM2_SPEC.json] [--marker-positions MEASURED.json] [--board-scale 0.997]

Printed cards shrink (PLA ~0.3%): --marker-positions loads calipered marker positions that replace the CAD ones,
JSON {"markers": {"20": {"corners": [[x, y] TL, TR, BR, BL]} | {"centre": [x, y], "size": s}, ...}} in card mm
(ids not listed keep CAD values); --board-scale multiplies all card coordinates (e.g. 0.997 for 0.3% shrink).

Writes next to the photo: PHOTO_rectified.png (top-down view of the card plane, RECT_PPM px per mm, 10 mm grid,
origin = card bottom-left corner, so a distance in that image is px / RECT_PPM mm, valid ON the card plane only),
PHOTO_measure.json, and prints a short text summary.

Card frame: x right, y up (text "PM-1 100mm" at the top), z out of the printed face; origin bottom-left corner.
Camera frame (OpenCV): x right, y down, z forward. Tilt angles are of the card relative to a head-on view
(card x = image right, card y = image up), applied yaw, then roll, then pitch in the card's own axes:
pitch > 0 = top edge farther from the camera (the usual photo of a card on a table), roll > 0 = right edge
farther, yaw > 0 = card turned counter-clockwise in the picture.

Intrinsics: --calib (JSON {"K": 3x3, "dist": [...]}, or OpenCV YAML camera_matrix / distortion_coefficients),
else --focal-px, else --focal-35mm, else the photo's EXIF FocalLengthIn35mmFilm, else a 26 mm-equivalent guess
(typical phone main camera); principal point = image centre, no distortion. --focal-auto uses the focal length
estimated from the card homography instead (needs a clearly tilted card, > ~20 deg). The scale on the card plane
(homography) does not depend on the intrinsics; the tilt angles and the cube pose do.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

DICT = cv2.aruco.DICT_4X4_50
CARD_MM = 100.0
CARD_MARKER = 20.0
CARD_MARKERS = {0: (13.5, 13.5), 1: (86.5, 13.5), 2: (86.5, 86.5), 3: (13.5, 86.5)}   # centre, mm
PM2_SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pm2_marker_spec.json")
CUBE_MM = 30.0
CUBE_MARKER = 20.0
CUBE_FACES = {  # id: (outward normal, marker right U, marker up V), cube frame origin = cube centre
    10: ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    11: ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    12: ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    13: ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
    14: ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    15: ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
}
FULL_FRAME_DIAG = 43.267  # mm, 36 x 24 sensor diagonal
DEFAULT_F35 = 26.0
R_HEADON = np.diag([1.0, -1.0, -1.0])  # card frame -> camera frame for a head-on, upright view


def card_corners(mid):
    """Object points (4, 3) in the card frame, ArUco corner order TL, TR, BR, BL of the marker image."""
    cx, cy = CARD_MARKERS[mid]
    h = CARD_MARKER / 2
    return np.array([[cx - h, cy + h, 0], [cx + h, cy + h, 0], [cx + h, cy - h, 0], [cx - h, cy - h, 0]], float)


def pm1_board():
    return {"name": "PM-1", "size_mm": CARD_MM, "centre_mm": [CARD_MM / 2, CARD_MM / 2],
            "corners": {i: card_corners(i) for i in CARD_MARKERS}}


def corners_from_entry(e, default_size):
    if "corners" in e:
        c = np.array(e["corners"], float).reshape(4, 2)
    else:
        (cx, cy), h = e["centre"], float(e.get("size", default_size)) / 2
        c = np.array([[cx - h, cy + h], [cx + h, cy + h], [cx + h, cy - h], [cx - h, cy - h]], float)
    return np.column_stack([c, np.zeros(4)])


def load_spec_board(path):
    """PM-2 (or any planar layout) from a spec JSON: {"name", "size_mm", "centre_mm", "marker_mm", "markers":
    {id: {"corners": [[x, y] x 4 in ArUco order TL, TR, BR, BL]} | {"centre": [x, y]}}}."""
    with open(path, encoding="utf-8") as fh:
        j = json.load(fh)
    size = float(j["size_mm"])
    return {"name": j.get("name", os.path.basename(path)), "size_mm": size,
            "centre_mm": list(j.get("centre_mm", [size / 2, size / 2])), "spec": os.path.abspath(path),
            "corners": {int(k): corners_from_entry(v, j.get("marker_mm", 0)) for k, v in j["markers"].items()}}


def apply_measured(boards, path, scale):
    """Replace CAD marker corners by calipered ones (path) and/or scale every card coordinate."""
    if path:
        with open(path, encoding="utf-8") as fh:
            j = json.load(fh)
        for k, e in j.get("markers", j).items():
            for b in boards:
                if int(k) in b["corners"]:
                    size = float(np.linalg.norm(b["corners"][int(k)][0] - b["corners"][int(k)][1]))
                    b["corners"][int(k)] = corners_from_entry(e, size)
                    b["measured_positions"] = os.path.abspath(path)
    if scale and scale != 1.0:
        for b in boards:
            b["corners"] = {k: v * scale for k, v in b["corners"].items()}
            b["centre_mm"] = [c * scale for c in b["centre_mm"]]
            b["size_mm"] *= scale
            b["board_scale"] = scale
    return boards


def cube_corners(mid):
    n, U, V = (np.array(a, float) for a in CUBE_FACES[mid])
    c = n * CUBE_MM / 2
    h = CUBE_MARKER / 2
    return np.array([c - U * h + V * h, c + U * h + V * h, c + U * h - V * h, c - U * h - V * h])


def detect(gray):
    d = cv2.aruco.getPredefinedDictionary(DICT)
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = max(3, int(min(gray.shape) / 600))
    corners, ids, _ = cv2.aruco.ArucoDetector(d, p).detectMarkers(gray)
    out = {}
    if ids is not None:
        for c, i in zip(corners, ids.ravel()):
            out.setdefault(int(i), c.reshape(4, 2).astype(np.float64))
    return out


def exif_f35(path):
    try:
        from PIL import Image
        ex = Image.open(path).getexif()
        sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
        v = sub.get(0xA405) or ex.get(0xA405)
        return float(v) if v else None
    except Exception:
        return None


def load_calib(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            j = json.load(fh)
        K = np.array(j.get("K") or j["camera_matrix"], float).reshape(3, 3)
        dist = np.array(j.get("dist") or j.get("distortion_coefficients") or [], float).ravel()
        return K, dist, j.get("size")
    fs = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
    K = fs.getNode("camera_matrix").mat()
    dist = fs.getNode("distortion_coefficients").mat()
    return K, (dist.ravel() if dist is not None else np.zeros(0)), None


def focal_from_homography(H, cx, cy):
    """Focal length (px) from a plane->image homography, square pixels, known principal point (Zhang)."""
    Hn = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], float) @ H
    h1, h2 = Hn[:, 0], Hn[:, 1]
    a = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    if np.dot(a, a) < 1e-30:
        return None
    w = -np.dot(a, b) / np.dot(a, a)  # a / f^2 + b = 0
    return float(1 / math.sqrt(w)) if w > 0 else None


def euler_zyx(R):
    """R = Rz(yaw) @ Ry(roll) @ Rx(pitch); degrees (pitch, roll, yaw)."""
    roll = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    pitch = math.atan2(R[2, 1], R[2, 2])
    yaw = math.atan2(R[1, 0], R[0, 0])
    return tuple(round(math.degrees(v), 2) for v in (pitch, roll, yaw))


def rms(obj, img, rvec, tvec, K, dist):
    p, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
    return float(np.sqrt(np.mean(np.sum((p.reshape(-1, 2) - img) ** 2, 1))))


def solve_pose(obj, img, K, dist, planar):
    if planar:
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE)
    else:
        ok, rvec, tvec = False, None, None
        best = None
        for k in range(0, len(obj), 4):  # seed from each single marker (IPPE square), keep the best fit to all
            ok1, rv, tv = cv2.solvePnP(obj[k:k + 4] - obj[k:k + 4].mean(0), img[k:k + 4], K, dist, flags=cv2.SOLVEPNP_IPPE)
            if not ok1:
                continue
            tv = tv - cv2.Rodrigues(rv)[0] @ obj[k:k + 4].mean(0).reshape(3, 1)
            e = rms(obj, img, rv, tv, K, dist)
            if best is None or e < best[0]:
                best = (e, rv, tv)
        if best:
            ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, best[1].copy(), best[2].copy(), True, cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(obj, img, K, dist, rvec, tvec)
    return rvec, tvec


def card_to_px(H, pts):
    p = cv2.perspectiveTransform(np.asarray(pts, float).reshape(-1, 1, 2), H)
    return p.reshape(-1, 2)


def rectify(img, Himg2card, ppm, margin, path, size_mm=CARD_MM):
    lo, hi = -margin, size_mm + margin
    n = int(round((hi - lo) * ppm))
    S = np.array([[ppm, 0, -lo * ppm], [0, -ppm, hi * ppm], [0, 0, 1]], float)  # mm -> rectified px (y up)
    out = cv2.warpPerspective(img, S @ Himg2card, (n, n), flags=cv2.INTER_LINEAR, borderValue=(40, 40, 40))
    over = out.copy()
    for v in np.arange(math.ceil(lo / 10) * 10, hi + 1e-9, 10):
        a = int(round((v - lo) * ppm))
        col = (0, 0, 255) if abs(v) < 1e-9 else (255, 160, 0)
        cv2.line(over, (a, 0), (a, n - 1), col, 1)
        cv2.line(over, (0, n - 1 - a), (n - 1, n - 1 - a), col, 1)
        cv2.putText(over, f"{v:.0f}", (a + 2, n - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
        cv2.putText(over, f"{v:.0f}", (2, n - 1 - a - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
    out = cv2.addWeighted(over, 0.45, out, 0.55, 0)
    cv2.putText(out, f"card plane, {ppm:g} px/mm, grid 10 mm, origin = card bottom-left", (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    cv2.imwrite(path, out)
    return {"path": path, "px_per_mm": ppm, "origin_mm": [lo, lo], "size_px": n}


def plane_board(board, found, K, dist, src, focal_auto):
    """Homography + planar pose of one card from all of its visible markers.
    Returns (result dict, (R, t) or None, H image -> card mm, K, intrinsics source)."""
    ids = [i for i in sorted(board["corners"]) if i in found]
    img_pts = np.vstack([found[i] for i in ids])
    obj_pts = np.vstack([board["corners"][i] for i in ids])
    und = cv2.undistortPoints(img_pts.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2) if dist.size and np.any(dist) else img_pts
    Hc2i, _ = cv2.findHomography(obj_pts[:, :2], und, 0)
    Hi2c = np.linalg.inv(Hc2i)
    f_h = focal_from_homography(Hc2i, K[0, 2], K[1, 2])
    if focal_auto and f_h:
        K = K.copy()
        K[0, 0] = K[1, 1] = f_h
        src = f"estimated from the {board['name']} homography (--focal-auto)"
    c = np.array(board["centre_mm"], float)
    e = 0.5
    p = card_to_px(Hc2i, [c, c + [e, 0], c + [0, e]])
    jx, jy = (p[1] - p[0]) / e, (p[2] - p[0]) / e
    side = [float(np.mean([np.linalg.norm(found[i][k] - found[i][(k + 1) % 4]) for k in range(4)]))
            / float(np.mean([np.linalg.norm(board["corners"][i][k] - board["corners"][i][(k + 1) % 4]) for k in range(4)]))
            for i in ids]
    Hfit = card_to_px(Hc2i, obj_pts[:, :2])
    out = {
        "layout": board["name"],
        "ids": ids,
        "px_per_mm_centre": round(float(math.sqrt(abs(np.linalg.det(np.stack([jx, jy], 1))))), 4),
        "px_per_mm_x_axis": round(float(np.linalg.norm(jx)), 4),
        "px_per_mm_y_axis": round(float(np.linalg.norm(jy)), 4),
        "px_per_mm_per_marker": {str(i): round(v, 4) for i, v in zip(ids, side)},
        "homography_rms_px": round(float(np.sqrt(np.mean(np.sum((Hfit - und) ** 2, 1)))), 3),
        "H_image_to_card_mm": np.round(Hi2c / Hi2c[2, 2], 9).tolist(),
        "focal_from_card_px": round(f_h, 1) if f_h else None,
    }
    for k in ("spec", "measured_positions", "board_scale"):
        if k in board:
            out[k] = board[k]
    missing = [i for i in sorted(board["corners"]) if i not in found]
    if missing and board["name"] != "PM-1":
        out["hidden_ids"] = missing
    if len(ids) < 2:
        out["warning"] = "only one card marker: scale and tilt are rough"
    pose_rt = None
    pose = solve_pose(obj_pts, img_pts, K, dist, planar=True)
    if pose:
        rvec, tvec = pose
        R = cv2.Rodrigues(rvec)[0]
        pose_rt = (R, tvec.reshape(3))
        n_cam = R @ np.array([0, 0, 1.0])
        ctr = R @ np.array([c[0], c[1], 0]) + tvec.reshape(3)
        to_cam = -ctr / np.linalg.norm(ctr)
        pitch, roll, yaw = euler_zyx(R_HEADON.T @ R)
        pitch = -pitch  # Rx(+) brings the top edge towards the camera; report "top away" as positive
        out["pose"] = {
            "tilt_vs_optical_axis_deg": round(math.degrees(math.acos(max(-1, min(1, -n_cam[2])))), 2),
            "view_angle_at_centre_deg": round(math.degrees(math.acos(max(-1, min(1, float(n_cam @ to_cam))))), 2),
            "pitch_deg": pitch, "roll_deg": roll, "yaw_deg": yaw,
            "centre_cam_mm": np.round(ctr, 1).tolist(),
            "distance_mm": round(float(np.linalg.norm(ctr)), 1),
            "reproj_rms_px": round(rms(obj_pts, img_pts, rvec, tvec, K, dist), 3),
        }
    return out, pose_rt, Hi2c, K, src


def analyse(path, measures=(), calib=None, focal_px=None, focal_35=None, focal_auto=False, rect_ppm=10.0,
            rect_margin=30.0, write_files=True, spec=PM2_SPEC, marker_positions=None, board_scale=None):
    img = cv2.imread(path, cv2.IMREAD_COLOR)  # applies the EXIF orientation
    if img is None:
        raise SystemExit(f"cannot read {path}")
    Hh, Ww = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found = detect(gray)
    res = {"photo": os.path.abspath(path), "size_px": [Ww, Hh], "markers": sorted(found)}

    # intrinsics
    dist = np.zeros(5)
    if calib:
        K, dist, size = load_calib(calib)
        if size and (size[0], size[1]) != (Ww, Hh):
            s = Ww / size[0]
            K = K.copy()
            K[:2] *= s
        src = f"calib {calib}"
    else:
        diag = math.hypot(Ww, Hh)
        if focal_px:
            f, src = float(focal_px), "--focal-px"
        elif focal_35:
            f, src = focal_35 * diag / FULL_FRAME_DIAG, f"--focal-35mm {focal_35}"
        else:
            e = exif_f35(path)
            f35 = e or DEFAULT_F35
            f = f35 * diag / FULL_FRAME_DIAG
            src = f"EXIF FocalLengthIn35mmFilm {e:g} mm" if e else f"guess: {DEFAULT_F35:g} mm-equivalent phone lens"
        K = np.array([[f, 0, (Ww - 1) / 2], [0, f, (Hh - 1) / 2], [0, 0, 1]], float)

    boards = [pm1_board()]
    if spec and os.path.exists(spec):
        boards.append(load_spec_board(spec))
    apply_measured(boards, marker_positions, board_scale)
    seen = [b for b in boards if any(i in found for i in b["corners"])]
    seen.sort(key=lambda b: b["name"] != "PM-2")  # PM-2 first: the bigger plane measures
    card_pose = None
    for bi, board in enumerate(seen):
        out, pose, Hi2c, K, src = plane_board(board, found, K, dist, src, focal_auto and not calib and bi == 0)
        if bi:
            res["other_card"] = out
            continue
        res["card"] = out
        card_pose = pose
        res["measurements"] = []
        for m in measures:
            x1, y1, x2, y2 = (float(v) for v in m.split(","))
            q = np.array([[x1, y1], [x2, y2]], float)
            if dist.size and np.any(dist):
                q = cv2.undistortPoints(q.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)
            mm = card_to_px(Hi2c, q)
            res["measurements"].append({"px": [x1, y1, x2, y2], "mm_points": np.round(mm, 3).tolist(),
                                        "distance_mm": round(float(np.linalg.norm(mm[1] - mm[0])), 3)})
        if write_files:
            stem = os.path.splitext(path)[0]
            res["rectified"] = rectify(img, Hi2c, rect_ppm, rect_margin, stem + "_rectified.png", board["size_mm"])

    cube_ids = [i for i in CUBE_FACES if i in found]
    if cube_ids:
        img_pts = np.vstack([found[i] for i in cube_ids])
        obj_pts = np.vstack([cube_corners(i) for i in cube_ids])
        pose = solve_pose(obj_pts, img_pts, K, dist, planar=False)
        if pose:
            rvec, tvec = pose
            R = cv2.Rodrigues(rvec)[0]
            t = tvec.reshape(3)
            cube = {"ids": cube_ids, "centre_cam_mm": np.round(t, 1).tolist(),
                    "distance_mm": round(float(np.linalg.norm(t)), 1),
                    "rvec": np.round(rvec.ravel(), 5).tolist(), "R_cube_to_cam": np.round(R, 5).tolist(),
                    "reproj_rms_px": round(rms(obj_pts, img_pts, rvec, tvec, K, dist), 3)}
            if card_pose:
                Rc, tc = card_pose
                Rcc = Rc.T @ R
                cube["centre_card_mm"] = np.round(Rc.T @ (t - tc), 2).tolist()
                cube["R_cube_to_card"] = np.round(Rcc, 5).tolist()
                up = Rcc.T @ np.array([0, 0, 1.0])  # card normal in cube frame: which face is up
                cube["face_up_id"] = max(CUBE_FACES, key=lambda k: float(np.dot(CUBE_FACES[k][0], up)))
                cube["yaw_on_card_deg"] = round(math.degrees(math.atan2(Rcc[1, 0], Rcc[0, 0])), 2)
            if len(cube_ids) == 1:
                cube["warning"] = "one cube face only: pose from a single marker, less accurate"
            res["cube"] = cube

    res["intrinsics"] = {"source": src, "fx": round(float(K[0, 0]), 1), "fy": round(float(K[1, 1]), 1),
                         "cx": round(float(K[0, 2]), 1), "cy": round(float(K[1, 2]), 1),
                         "dist": np.round(dist, 6).tolist()}
    if write_files:
        jp = os.path.splitext(path)[0] + "_measure.json"
        with open(jp, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
        res["json"] = jp
    return res


def summary(r):
    L = [f"markers: {r['markers'] or 'none'}"]
    c = r.get("card")
    if c:
        L.append(f"{c['layout']} card ids {c['ids']}: {c['px_per_mm_centre']:.3f} px/mm at the card centre "
                 f"(x {c['px_per_mm_x_axis']:.3f}, y {c['px_per_mm_y_axis']:.3f}), homography rms {c['homography_rms_px']} px")
        p = c.get("pose")
        if p:
            L.append(f"card tilt {p['tilt_vs_optical_axis_deg']} deg vs optical axis (view angle {p['view_angle_at_centre_deg']}), "
                     f"pitch {p['pitch_deg']}, roll {p['roll_deg']}, yaw {p['yaw_deg']} deg, distance {p['distance_mm']} mm")
        for m in r.get("measurements", []):
            L.append(f"measure {m['px']} -> {m['distance_mm']:.2f} mm on the card plane")
        if c.get("hidden_ids"):
            L.append(f"{c['layout']} markers not seen (covered or out of frame): {c['hidden_ids']}")
        if r.get("rectified"):
            L.append(f"rectified: {r['rectified']['path']} ({r['rectified']['px_per_mm']:g} px/mm, origin card bottom-left)")
    elif r["markers"]:
        L.append("no card marker (PM-1 ids 0-3, PM-2 ids 20-26) found: no plane scale")
    k = r.get("cube")
    if k:
        s = f"cube ids {k['ids']}: centre {k['centre_cam_mm']} mm in camera frame, distance {k['distance_mm']} mm"
        if "centre_card_mm" in k:
            s += f"; on card at {k['centre_card_mm']} mm, face up {k['face_up_id']}, yaw {k['yaw_on_card_deg']} deg"
        L.append(s)
    i = r["intrinsics"]
    L.append(f"intrinsics: f {i['fx']} px ({i['source']})")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("photo")
    ap.add_argument("--measure", action="append", default=[], metavar="x1,y1,x2,y2")
    ap.add_argument("--calib")
    ap.add_argument("--focal-px", type=float)
    ap.add_argument("--focal-35mm", type=float)
    ap.add_argument("--focal-auto", action="store_true")
    ap.add_argument("--rect-ppm", type=float, default=10.0)
    ap.add_argument("--rect-margin", type=float, default=30.0)
    ap.add_argument("--no-files", action="store_true")
    ap.add_argument("--spec", default=PM2_SPEC, help="PM-2 layout spec JSON (marker corners in card mm)")
    ap.add_argument("--marker-positions", help="calipered marker positions JSON that replace the CAD ones")
    ap.add_argument("--board-scale", type=float, help="scale all card coordinates (0.997 = 0.3%% shrink)")
    ap.add_argument("--json", action="store_true", help="print the JSON instead of the text summary")
    a = ap.parse_args(argv)
    r = analyse(a.photo, a.measure, a.calib, a.focal_px, a.focal_35mm, a.focal_auto, a.rect_ppm, a.rect_margin,
                not a.no_files, a.spec, a.marker_positions, a.board_scale)
    print(json.dumps(r, indent=2) if a.json else summary(r))
    return 0 if r["markers"] else 2


if __name__ == "__main__":
    sys.exit(main())
