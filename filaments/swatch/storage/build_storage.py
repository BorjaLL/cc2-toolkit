"""Parametric swatch storage. Deliverables stay here; slicing work stays in TEMP."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import shutil
import tempfile

import numpy as np
import trimesh
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(x, y, z, dx, dy, dz):
    m = trimesh.creation.box((dx, dy, dz))
    m.apply_translation((x + dx/2, y + dy/2, z + dz/2))
    return m


def prism_yz(points, x, width):
    m = trimesh.creation.extrude_polygon(Polygon(points), width)
    m.vertices = m.vertices[:, [2, 0, 1]]
    m.apply_translation((x, 0, 0))
    return m


def rounded(w, d, radius, z, height):
    p = box(radius, radius, w-radius, d-radius).buffer(radius, quad_segs=12)
    m = trimesh.creation.extrude_polygon(p, height)
    m.apply_translation((0, 0, z))
    return m


def foot(cx, cy):
    # Gridfinity base: 0.8 chamfer, 1.8 straight, 2.15 upper chamfer.
    # Corresponding rounded squares: 35.6 / 37.2 / 37.2 / 41.5 mm.
    rings = []
    for z, size, r in [(0, 35.6, .8), (.8, 37.2, 1.6),
                       (2.6, 37.2, 1.6), (4.75, 41.5, 3.75)]:
        ring = []
        for sx, sy, start in [(1, 1, 0), (-1, 1, 90),
                               (-1, -1, 180), (1, -1, 270)]:
            for a in np.linspace(start, start+90, 13):
                ring.append((cx+sx*(size/2-r)+r*math.cos(math.radians(a)),
                             cy+sy*(size/2-r)+r*math.sin(math.radians(a)), z))
        rings.append(ring)
    n = len(rings[0])
    verts = np.array(rings).reshape(-1, 3)
    faces = []
    for j in range(3):
        for i in range(n):
            a, b = j*n+i, j*n+(i+1) % n
            faces.extend([(a, b, b+n), (a, b+n, a+n)])
    for i in range(1, n-1):
        faces.extend([(0, i+1, i), (3*n, 3*n+i, 3*n+i+1)])
    m = trimesh.Trimesh(verts, faces, process=True)
    m.fix_normals()
    assert m.is_volume
    return m


def groove(y, floor, top, width, theta, x, length, chamfer=.6):
    half = width / (2*math.cos(theta))
    zs = [floor, top-.8, top+.02]
    cs = [y+(z-floor)*math.tan(theta) for z in zs]
    points = [(cs[0]-half, zs[0]), (cs[0]+half, zs[0]),
              (cs[1]+half, zs[1]), (cs[2]+half+chamfer, zs[2]),
              (cs[2]-half-chamfer, zs[2]), (cs[1]-half, zs[1])]
    return prism_yz(points, x, length)


def build(spec, count, grid_y, clearance, angle, wall_height=14., section=False):
    cw, ch, ct = [spec[k] for k in ('width_mm', 'height_mm', 'thickness_mm')]
    slot = round(spec['edge_thickness_mm'] + clearance, 4)
    theta = math.radians(0 if grid_y else angle)
    visible = max(17., spec['label_strip']['depth_from_edge_mm']+.5)
    pitch = round(slot+1., 4) if grid_y else math.ceil((visible*math.sin(theta)+ct*math.cos(theta)+.5)*5)/5
    wall = 2.25 if grid_y else 2.4
    front = wall+1+slot/(2*math.cos(theta))
    if grid_y:
        w, d, floor, top = 83.5, 83.5, 5.75, 21.
        if cw+2 > w-2*wall:
            raise ValueError('Card needs more than two Gridfinity cells along X')
        count = min(22, math.floor((d-2*(wall+2)-slot)/pitch)+1)
        front = (d-(count-1)*pitch)/2
        base = [foot(20.75+42*i, 20.75+42*j) for i in range(2) for j in range(2)]
        base.append(rounded(w, d, 3.75, 4.75, 1.))
    else:
        w = cw+2+2*wall
        projection = ch*math.sin(theta)+ct*math.cos(theta)
        d = 18. if section else math.ceil((front+(count-1)*pitch+projection+wall+1)*5)/5
        floor, top = 1., wall_height
        base = [rounded(w, d, 3., 0, floor)]
    if max(w, d) > 246:
        raise ValueError('Holder exceeds 246 mm design limit')
    # Account for the full lateral play, not just the centered card position.
    rail = (w-cw)/2+(4.0 if grid_y else 3.0)
    inner_length = w-2*wall
    lateral_play = inner_length-cw
    rib_length = rail-wall
    worst_engagement = rib_length-lateral_play
    assert worst_engagement >= (2.5 if grid_y else 2.0)-1e-9
    outer = rounded(w, d, 3.75 if grid_y else 3., floor, top-floor)
    end_wall = 1.6
    cavity = block(rail, end_wall, floor, w-2*rail, d-2*end_wall, top-floor+1)
    shell = trimesh.boolean.difference([outer, cavity], engine='manifold')
    cutters = [groove(front+i*pitch, floor, top, slot, theta, wall, w-2*wall, .2 if grid_y else .6)
               for i in range(count)]
    # The fit section is open at its cut end, as a real end section of A.
    if section:
        cutters.append(block(rail, end_wall, floor, w-2*rail, d, top-floor+1))
    if not grid_y:
        finger = trimesh.creation.extrude_polygon(Polygon([
            (w/2-14, top+1), (w/2+14, top+1),
            (w/2+8, floor+3), (w/2-8, floor+3)]), wall+.2)
        finger.vertices = finger.vertices[:, [0, 2, 1]]
        finger.invert()
        finger.apply_translation((0, -.1, 0))
        cutters.append(finger)
    shell = trimesh.boolean.difference([shell, *cutters], engine='manifold')
    mesh = trimesh.boolean.union([*base, shell], engine='manifold')
    info = dict(capacity=count, dimensions_mm=[w, d, top], floor_z_mm=floor,
                floor_thickness_mm=1., slot_width_mm=slot, slot_pitch_mm=pitch,
                edge_thickness_mm=spec['edge_thickness_mm'], clearance_mm=clearance,
                rib_width_mm=pitch-slot if grid_y else None,
                angle_from_vertical_deg=0 if grid_y else angle,
                visible_face_strip_from_above_mm=None if grid_y else (pitch-ct*math.cos(theta))/math.sin(theta),
                label_strip_required_mm=visible, inner_length_mm=inner_length,
                lateral_play_mm=lateral_play, rib_length_mm=rib_length,
                centered_side_engagement_mm=rail-(w-cw)/2,
                worst_case_side_engagement_mm=worst_engagement,
                minimum_side_engagement_mm=2.5 if grid_y else 2.0,
                first_slot_y_mm=front, rail_inner_x_mm=rail,
                chamfer_horizontal_mm=.6, chamfer_height_mm=.8,
                grid=[2, 2] if grid_y else None,
                height_units=3 if grid_y else None, magnets=False, stacking_lip=False)
    if grid_y:
        # A 0.6 mm flare would erase the 1 mm rib tips. Use a 0.2 mm flare.
        info['chamfer_horizontal_mm'] = .2
    info['loaded_height_mm'] = floor+ch*math.cos(theta)+ct*math.sin(theta)
    info['loaded_rear_y_mm'] = front+(count-1)*pitch+ch*math.sin(theta)+ct/(2*math.cos(theta))
    if not section:
        assert info['loaded_rear_y_mm'] <= d-1
    if grid_y:
        info['base_profile'] = dict(grid_pitch_mm=42, profile_height_mm=4.75,
            z_levels_mm=[0, .8, 2.6, 4.75], square_widths_mm=[35.6, 37.2, 37.2, 41.5],
            corner_radii_mm=[.8, 1.6, 1.6, 3.75], magnets=False)
    return mesh, info


def coupon(spec, angle, clearance, wall_height):
    mesh, info = build(spec, 1, 0, clearance, angle, wall_height, section=True)
    info['purpose'] = 'Full-width one-slot end section of Box A; real seating and lean test'
    return mesh, info


def positioned_card(card, spec, info, i):
    c = card.copy()
    v = c.vertices.copy()-card.bounds[0]
    theta = math.radians(info['angle_from_vertical_deg'])
    s, co = math.sin(theta), math.cos(theta)
    u = v[:, 2]-spec['thickness_mm']/2
    lift = spec['thickness_mm']/2*s
    c.vertices = np.column_stack((
        v[:, 0]+(info['dimensions_mm'][0]-spec['width_mm'])/2,
        info['first_slot_y_mm']+i*info['slot_pitch_mm']+v[:, 1]*s-u*co+lift*math.tan(theta),
        info['floor_z_mm']+v[:, 1]*co+u*s+lift))
    return c


def raster(triangles, colors, camera, size=(660, 420)):
    """Orthographic depth-buffer render; avoids painter-sort triangle artifacts."""
    camera = np.asarray(camera, dtype=float)
    camera /= np.linalg.norm(camera)
    right = np.cross([0, 0, 1], camera)
    if np.linalg.norm(right) < .01:
        right = np.array([1., 0., 0.])
    right /= np.linalg.norm(right)
    up = np.cross(camera, right)
    projected = triangles @ np.array([right, up, camera]).T
    lo = projected[:, :, :2].min(axis=(0, 1))
    hi = projected[:, :, :2].max(axis=(0, 1))
    scale = min((size[0]-40)/(hi[0]-lo[0]), (size[1]-30)/(hi[1]-lo[1]))
    projected[:, :, :2] = (projected[:, :, :2]-(lo+hi)/2)*scale
    projected[:, :, 0] += size[0]/2
    projected[:, :, 1] = size[1]/2-projected[:, :, 1]
    pixels = np.full((size[1], size[0], 3), 246, dtype=np.uint8)
    depth = np.full((size[1], size[0]), -np.inf)
    for tri, color in zip(projected, colors):
        x0, y0 = np.maximum(np.floor(tri[:, :2].min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(tri[:, :2].max(axis=0)).astype(int), np.array(size)-1)
        a, b, c = tri
        den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den) < 1e-8 or x1 < x0 or y1 < y0:
            continue
        xx, yy = np.meshgrid(np.arange(x0, x1+1)+.5, np.arange(y0, y1+1)+.5)
        u = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        v = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        z = u*a[2]+v*b[2]+(1-u-v)*c[2]
        region = depth[y0:y1+1, x0:x1+1]
        mask = (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7) & (z > region)
        region[mask] = z[mask]
        pixels[y0:y1+1, x0:x1+1][mask] = color
    from PIL import Image
    return Image.fromarray(pixels)


def preview(items, spec, out):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (2040, 1110), '#f6f6f6')
    draw = ImageDraw.Draw(image)
    fontpath = Path('C:/Windows/Fonts/arial.ttf')
    def font(size):
        return ImageFont.truetype(str(fontpath), size) if fontpath.exists() else ImageFont.load_default()
    angle = items['box_a'][1]['angle_from_vertical_deg']
    draw.text((30, 18), 'SWATCH STORAGE', font=font(32), fill='#24374a')
    draw.text((30, 62), 'Box A: %g degree lean  |  Bin B: vertical index  |  Full-width fit test' % angle,
              font=font(20), fill='#536779')
    palette = ['#62a3bd', '#d9ac5c', '#8bb896', '#b48dab', '#d8826e', '#8194bc']
    from PIL.ImageColor import getrgb
    for col, (name, (mesh, info)) in enumerate(items.items()):
        x = 20+col*680
        title = ('GRIDFINITY 2x%d / %d CARDS' % (info['grid'][1], info['capacity'])
                 if name == 'bin_b' else ('BOX A / %d CARDS' if name == 'box_a'
                                         else 'COUPON / %d SLOTS') % info['capacity'])
        draw.text((x, 110), title, font=font(24), fill='#24374a')
        draw.text((x, 146), '%.1f x %.1f x %.1f mm' % tuple(info['dimensions_mm']), font=font(19), fill='#536779')
        light = np.array([-.3, -.5, .8])
        shades = .78+.22*np.clip(mesh.face_normals@light, -1, 1)
        colors = np.array([np.array([161, 182, 201])*v for v in shades]).astype(np.uint8)
        triangles = mesh.triangles.copy()
        image.paste(raster(triangles, colors, [1, -1.4, 1.2]), (x, 180))
        label = 'Loaded: overhead labels' if name == 'box_a' else 'Vertical index: flip cards to read'
        if name != 'coupon':
            theta = math.radians(info['angle_from_vertical_deg'])
            for i in range(info['capacity']):
                xx = (info['dimensions_mm'][0]-spec['width_mm'])/2
                yy = info['first_slot_y_mm']+i*info['slot_pitch_mm']
                zz = info['floor_z_mm']+.5
                pts = np.array([[xx, yy, zz], [xx+spec['width_mm'], yy, zz],
                    [xx+spec['width_mm'], yy+spec['height_mm']*math.sin(theta), zz+spec['height_mm']*math.cos(theta)],
                    [xx, yy+spec['height_mm']*math.sin(theta), zz+spec['height_mm']*math.cos(theta)]])
                band = pts.copy()
                band[:2] += [0, (spec['height_mm']-spec['label_strip']['depth_from_edge_mm'])*math.sin(theta),
                              (spec['height_mm']-spec['label_strip']['depth_from_edge_mm'])*math.cos(theta)]
                band[:, 1] -= .05
                band[:, 2] += .05
                triangles = np.concatenate([triangles, pts[[[0,1,2],[0,2,3]]], band[[[0,1,2],[0,2,3]]]])
                colors = np.concatenate([colors, [getrgb(palette[i%6])]*2, [getrgb('#f3e3b9')]*2])
            camera = [0, 0, 1] if name == 'box_a' else [1, -1.4, 1.2]
        else:
            camera = [1, -.05, .2]
            label = 'One full-width %.1f mm slot; same lean as Box A' % info['slot_width_mm']
        draw.text((x, 610), label, font=font(18), fill='#24374a')
        image.paste(raster(triangles, colors, camera), (x, 650))
    draw.text((30, 1080), 'Cards shown as envelopes. Actual card STL used for collision checks. Print the coupon first.', font=font(18), fill='#536779')
    image.save(out/'preview.png')


def validate_gcode(path, info):
    text = path.read_text(encoding='utf-8', errors='replace')
    def field(key):
        hit = re.search(r'^;\s*'+re.escape(key)+r'\s*=\s*(.+)$', text, re.M)
        if not hit:
            raise ValueError('Missing G-code field: '+key)
        return hit.group(1).strip()
    time = field('estimated printing time (normal mode)')
    seconds = sum(float(n)*{'d':86400,'h':3600,'m':60,'s':1}[u]
                  for n, u in re.findall(r'(\d+(?:\.\d+)?)\s*([dhms])', time))
    report = dict(time=time, seconds=seconds, grams=float(field('total filament used [g]')),
                  m600_count=len(re.findall(r'^\s*M600\b', text, re.M)),
                  support_toolpath_sections=len(re.findall(r'^;TYPE:Support', text, re.M)),
                  gcode_sha256=digest(path))
    for key, expected in [('enable_support', '0'), ('ironing_type', 'no_ironing'),
                           ('default_acceleration', '3000'), ('outer_wall_acceleration', '2000'),
                           ('top_surface_acceleration', '1500'), ('outer_wall_speed', '120'),
                           ('layer_height', '0.2'), ('wall_loops', '2'),
                           ('top_shell_layers', '3'), ('bottom_shell_layers', '3')]:
        report[key] = field(key)
        assert report[key].replace(' ', '_') == expected, (key, report[key], expected)
    # Actual extrusion bounds after the slicer's LAYER_CHANGE marker, omitting
    # machine start/purge paths. Track modal coordinates and both E modes.
    xyz = {'X':0., 'Y':0., 'Z':0.}
    e, relative_e, printing = 0., False, False
    points = []
    tools = set()
    for raw in text.splitlines():
        if raw.startswith(';LAYER_CHANGE'):
            printing = True
        line = raw.split(';', 1)[0].strip()
        if re.fullmatch(r'T\d+', line):
            tools.add(line)
        if line == 'M83': relative_e = True
        if line == 'M82': relative_e = False
        vals = {k:float(v) for k,v in re.findall(r'([XYZE])(-?(?:\d+(?:\.\d*)?|\.\d+))', line)}
        if printing and re.match(r'^G[23]\s', line) and 'E' in vals:
            raise ValueError('Extruding arc requires a curved-path bounds check')
        if line.startswith('G92'):
            if 'E' in vals: e = vals['E']
            continue
        if not re.match(r'^G[01]\s', line):
            continue
        old = dict(xyz)
        xyz.update({k:v for k,v in vals.items() if k in xyz})
        extrusion = vals.get('E', 0) if relative_e else vals.get('E', e)-e
        if 'E' in vals: e = vals['E']
        if printing and extrusion > 0 and ('X' in vals or 'Y' in vals):
            points.extend([list(old.values()), list(xyz.values())])
    assert points, 'No object extrusion paths found'
    bounds = np.array([np.min(points, axis=0), np.max(points, axis=0)])
    report['extrusion_bounds_xyz_mm'] = bounds.tolist()
    report['extrusion_fits_256_bed'] = bool(np.all(bounds[0,:2] >= .3) and np.all(bounds[1,:2] <= 255.7))
    report['tools'] = sorted(tools)
    report['sliced_height_matches_mesh'] = bool(abs(bounds[1,2]-info['dimensions_mm'][2]) < .05)
    assert report['m600_count'] == 0 and report['extrusion_fits_256_bed']
    assert report['support_toolpath_sections'] == 0
    assert report['sliced_height_matches_mesh']
    assert tools <= {'T0'}
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--count', type=int, default=12)
    ap.add_argument('--clearance', type=float, default=.8)
    ap.add_argument('--wall-height', type=float, default=14.)
    ap.add_argument('--angle', type=float, default=30.)
    ap.add_argument('--dims', type=Path, default=ROOT.parent/'card_dims.json')
    ap.add_argument('--out', type=Path, default=ROOT)
    ap.add_argument('--slice', action='store_true')
    a = ap.parse_args()
    out = a.out.resolve()
    if not out.is_relative_to(ROOT):
        ap.error('--out must stay within filaments/swatch/storage')
    if not (1 <= a.count and .2 <= a.clearance <= 1 and 20 <= a.angle <= 40 and 10 <= a.wall_height <= 24):
        ap.error('Require count >= 1, clearance 0.2..1, angle 20..40 degrees, wall height 10..24 mm')
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(a.dims.read_text())
    assert spec['label_edge'] == 'top' and spec['label_strip']['edge'] == 'top'
    items = {'box_a':build(spec, a.count, 0, a.clearance, a.angle, a.wall_height),
             'bin_b':build(spec, 0, 2, a.clearance, a.angle, a.wall_height),
             'coupon':coupon(spec, a.angle, a.clearance, a.wall_height)}
    report = dict(card_dimensions=spec, dims_sha256=digest(a.dims),
                  generator_sha256=digest(Path(__file__)),
                  physical_print_tested=False, models={})
    cardpath = ROOT.parent/'cards/elegoo-pla-emoji/card.stl'
    card = trimesh.load(cardpath, force='mesh')
    check_real = np.allclose(card.extents, [spec['width_mm'], spec['height_mm'], spec['thickness_mm']], atol=.001)
    report['source_card_sha256'] = digest(cardpath)
    for name, (mesh, info) in items.items():
        assert mesh.is_volume and len(mesh.split()) == 1, name
        assert np.allclose(mesh.extents, info['dimensions_mm'], atol=.001)
        info['watertight'] = mesh.is_watertight
        info['connected_components'] = len(mesh.split())
        info['volume_mm3'] = float(mesh.volume)
        info['mesh_fits_bed'] = bool(max(mesh.extents[:2]) <= 246)
        info['real_card_collision_checked'] = bool(check_real)
        if check_real:
            cards = [positioned_card(card, spec, info, i) for i in range(info['capacity'])]
            collision = [float(trimesh.boolean.intersection([mesh, c], engine='manifold').volume) for c in cards]
            assert max(collision) < .01, (name, collision)
            info['card_holder_intersection_mm3'] = collision
            extreme_collisions = {}
            for side, shift in [('left', -info['lateral_play_mm']/2),
                                ('right', info['lateral_play_mm']/2)]:
                shifted = []
                for c in cards:
                    c = c.copy()
                    c.apply_translation((shift, 0, 0))
                    shifted.append(float(trimesh.boolean.intersection([mesh, c], engine='manifold').volume))
                assert max(shifted) < .01, (name, side, shifted)
                extreme_collisions[side] = shifted
            info['lateral_extreme_card_holder_intersection_mm3'] = extreme_collisions
            pair = float(trimesh.boolean.intersection(cards[:2], engine='manifold').volume) if len(cards)>1 else 0.
            assert pair < .01
            info['adjacent_cards_intersection_mm3'] = pair
        if name != 'bin_b':
            assert info['visible_face_strip_from_above_mm'] >= info['label_strip_required_mm']
        centered = mesh.copy()
        centered.apply_translation((128-mesh.extents[0]/2, 128-mesh.extents[1]/2, 0))
        stem = {'box_a':f'CC2_SwatchBoxA_{a.count}cards',
                'bin_b':f"CC2_SwatchBinB_2x2_{info['capacity']}cards",
                'coupon':'CC2_SwatchFitTest'}[name]
        path = out/(stem+'.stl')
        info['stl'] = path.name
        centered.export(path)
        info['stl_sha256'] = digest(path)
        if a.slice:
            dest = Path(tempfile.mkdtemp(prefix='swatch-storage-'+name+'-'))
            cmd = [sys.executable, '-B', str(REPO/'tools/slice_cc2.py'),
                   str(path), '--filament', 'pla', '--no-iron', '--no-brim', '--no-arrange',
                   '--proc', 'enable_support=0', '--proc', 'top_shell_layers=3',
                   '--proc', 'top_shell_thickness=0.6', '--out', str(dest)]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
            (dest/(name+'_slice_console.txt')).write_text(result.stdout+result.stderr, encoding='utf-8')
            assert re.search(r'^exit 0\b', result.stdout, re.M), result.stdout+result.stderr
            gcodes = list(dest.glob('*.gcode'))
            assert len(gcodes) == 1, gcodes
            final_gcode = out/(stem+'.gcode')
            shutil.copy2(gcodes[0], final_gcode)
            info['gcode'] = final_gcode.name
            info['slicing_command'] = cmd
            info['slicer'] = validate_gcode(final_gcode, info)
            if name == 'coupon':
                assert info['slicer']['seconds'] < 1200, 'Fit test must be under 20 minutes'
        report['models'][name] = info
        print(name, json.dumps(info), flush=True)
    preview(items, spec, out)
    report['preview_sha256'] = digest(out/'preview.png')
    (out/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

