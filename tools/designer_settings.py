"""Designer process precedence and a complete, machine-readable replacement audit.

Machine and calibrated filament profiles belong to the destination printer. Process
settings belong to the model unless an explicit recipe or destination policy wins.
Unknown process keys are retained: the output audit exposes unsupported slicer keys.
"""
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

API_VERSION = 2
IDENTITY = {'name', 'type', 'from', 'inherits', 'version', 'setting_id',
            'print_settings_id', 'printer_settings_id', 'filament_settings_id',
            'compatible_printers', 'compatible_printers_condition',
            'compatible_prints', 'compatible_prints_condition', 'different_settings_to_system',
            'inherits_group', 'printer_model', 'printer_variant'}
NEG_AUTO = {'filament_ramming_volumetric_speed', 'filament_ramming_volumetric_speed_nc',
            'filament_tower_interface_print_temp', 'ironing_fan_speed', 'prime_tower_lift_height',
            'raft_first_layer_expansion', 'tree_support_wall_count'}
# Bambu 2.5 writes prime_tower_brim_width = -1 (auto, 677 library 3MFs); Snapmaker Orca
# range-checks it (min 0) and refuses the whole slice. ElegooSlicer accepts -1.
NEG_AUTO_PRINTER = {'u1': {'prime_tower_brim_width'}}
# Bambu legacy names the destination loaders rename to a key we must exclude on the U1.
U1_LEGACY_FILAMENT = {'wipe_tower_extruder': 'wipe_tower_filament', 'infill_extruder': 'sparse_infill_filament',
                      'solid_infill_extruder': 'solid_infill_filament', 'perimeter_extruder': 'wall_filament'}
SLICER = {'cc2': 'ElegooSlicer', 'u1': 'Snapmaker Orca'}
# Per-plate process overrides of a BambuStudio plate (<plate> in model_settings.config).
# The U1 conversion must drop the plate block (Snapmaker CLI crash, g7u7), so the selected
# plate's overrides become global process values. Value '' = follow the global setting.
PLATE_PROCESS = ('print_sequence', 'first_layer_print_sequence', 'other_layers_print_sequence',
                 'other_layers_print_sequence_nums', 'spiral_mode')
PLATE_LISTS = {'first_layer_print_sequence', 'other_layers_print_sequence'}


def plate_blocks(model_settings):
    """[(plater_id, {key: value})] of model_settings.config text, instance metadata excluded."""
    out = []
    for block in re.findall(r'<plate>.*?</plate>', model_settings or '', flags=re.S):
        body = re.sub(r'<model_instance>.*?</model_instance>', '', block, flags=re.S)
        meta = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', body))
        out.append((int(meta.get('plater_id') or len(out) + 1), meta))
    return out


def plate_process(model_settings, plates):
    """(overrides, conflicts): the per-plate process values of designer plates `plates`
    in global config form; a key whose merged plates disagree is a conflict, not set."""
    blocks = dict(plate_blocks(model_settings))
    values, conflicts = {}, set()
    for plate in plates:
        meta = blocks.get(plate) or {}
        for key in PLATE_PROCESS:
            v = meta.get(key, '')
            if v == '':
                continue
            if key in PLATE_LISTS:
                v = v.split()
            elif key == 'spiral_mode':
                v = '1' if v.lower() in ('1', 'true') else '0'
            if key in values and values[key] != v:
                conflicts.add(key)
            values.setdefault(key, v)
    if len(plates) > 1:
        # A key set on one merged plate only does not hold for the others.
        for key in list(values):
            if any(not (blocks.get(p) or {}).get(key) for p in plates):
                conflicts.add(key)
    for key in conflicts:
        values.pop(key, None)
    return values, conflicts


def read(path, plate=None):
    """Global designer process settings; with plate (designer plate number or list of
    numbers) the plate's own process overrides replace the global values."""
    if not str(path).lower().endswith('.3mf') or not os.path.isfile(path) or not zipfile.is_zipfile(path):
        return {}
    with zipfile.ZipFile(path) as z:
        if 'Metadata/project_settings.config' not in z.namelist():
            return {}
        source = json.loads(z.read('Metadata/project_settings.config'))
        if plate is not None and 'Metadata/model_settings.config' in z.namelist():
            ms = z.read('Metadata/model_settings.config').decode('utf-8', errors='replace')
            source.update(plate_process(ms, plate if isinstance(plate, (list, tuple)) else [plate])[0])
        return source


def reason(key, value, machine=(), filament=(), printer='cc2'):
    if key in IDENTITY or key.endswith('_settings_id'):
        return 'destination preset identity'
    if key in machine or key.startswith(('machine_', 'printer_', 'extruder_', 'nozzle_')) or key == 'curr_bed_type':
        return 'destination machine and bed policy'
    if key in filament or key.startswith('filament_'):
        return 'destination filament calibration and tool mapping'
    if key.endswith('_gcode') or key == 'gcode_flavor':
        return 'destination machine G-code and safety policy'
    if printer == 'u1':
        key = U1_LEGACY_FILAMENT.get(key, key)  # its loader renames these first
    if printer == 'u1' and key == 'wipe_tower_filament':
        return 'Snapmaker CLI crash: wipe_tower_filament (pnw5)'
    if printer == 'u1' and key in {'wall_filament', 'solid_infill_filament', 'sparse_infill_filament'} and str(value) == '0':
        return 'Snapmaker CLI requires filament index >= 1; Bambu auto index 0 is invalid'
    if key in NEG_AUTO_PRINTER.get(printer, ()) and str(value) == '-1':
        return 'Bambu auto value -1 out of the destination CLI range (refuses the slice); destination profile value'
    # The CC2 has one nozzle (single_extruder_multi_material=1): with ooze_prevention on and
    # a prime tower the CLI stops with exit -51 ("Ooze prevention is only supported with the
    # wipe tower when 'single_extruder_multi_material' is off"), bd_3d-printing-nbfrz.
    if (key == 'ooze_prevention' and str(value) == '1' and isinstance(machine, dict)
            and str(machine.get('single_extruder_multi_material')) == '1'):
        return 'single-nozzle machine: ooze prevention needs separate nozzles (CLI exit -51)'
    if printer == 'cc2' and key == 'support_object_skip_flush' and _on(value):
        return SKIP_FLUSH_REASON
    if key in NEG_AUTO and str(value) == '-1':
        return 'Bambu negative auto value rejected by destination CLI'
    return None


# bd_3d-printing-foavq: Bambu "skip object" flush (M624 label bitmask, Bambu firmware only).
# ElegooSlicer GCode.cpp lists the label ids only for Bambu printers (is_bbl_printers) but,
# with exclude_object on and print_sequence by layer, encodes them for every extruder of every
# layer when support_object_skip_flush is on: the empty list throws "Unknown label object id!"
# and the CLI exits -100 on the first layer. Bambu Studio 2.x P2S / H2S / A2L / X2D 3MFs carry both on.
SKIP_FLUSH_REASON = ('Bambu skip-object flush (M624 label ids, Bambu firmware only): ElegooSlicer '
                     'stops with "Unknown label object id!" (exit -100) when it is on with '
                     'exclude_object on a non-Bambu printer; off (bd_3d-printing-foavq)')


def label_crash(effective):
    """Refusal message when the effective CC2 process would hit the ElegooSlicer
    "Unknown label object id!" stop (support_object_skip_flush and exclude_object both on,
    see SKIP_FLUSH_REASON), else None."""
    if _on(effective.get('support_object_skip_flush')) and _on(effective.get('exclude_object')):
        return ('refused: support_object_skip_flush=1 with exclude_object=1 stops ElegooSlicer '
                'with "Unknown label object id!" (exit -100) on a non-Bambu printer; set '
                'support_object_skip_flush=0 or exclude_object=0 (bd_3d-printing-foavq)')
    return None


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _on(v):
    return str(_first(v)).strip().lower() in ('1', 'true')


def translate(source, printer='cc2'):
    """{bambu_key: {'to': {destination_key: value}, 'reason': None | str}} for the BambuStudio
    process keys neither destination defines (bd_3d-printing-typ94).

    Both CLIs pass unknown keys through PrintConfigDef::handle_legacy: a few are renamed,
    some not faithfully, the rest dropped without a word. Each key here is given its
    destination meaning instead; process() withholds the Bambu key so the loader cannot
    re-translate it. reason None = faithful (same algorithm, checked in both sources and a
    scratch slice); a reason = the closest destination value, reported as a replacement.
    research/2026-11-15-bambu-only-keys.md has the evidence per key."""
    s, out = source, {}

    def put(key, to, why=None):
        # A destination key the designer set explicitly wins over a translated one.
        out[key] = {'to': {k: v for k, v in to.items() if k not in s}, 'reason': why}
    for key in ('sparse_infill_anchor', 'sparse_infill_anchor_max'):
        if key in s:   # same option (Prusa infill_anchor), renamed by Bambu
            put(key, {key.replace('sparse_', '', 1): s[key]})
    if 'ironing_direction' in s:
        # Bambu: line angle = int(ironing_direction + infill_direction) % 180 (Fill.cpp).
        # Snapmaker: ironing_angle >= 0 is that absolute angle; Elegoo: offset from the
        # solid infill angle unless ironing_angle_fixed. Their loaders copy the 45 as is.
        try:
            angle = int(float(_first(s['ironing_direction'])) + float(_first(s.get('infill_direction', 45)))) % 180
            to = {'ironing_angle': str(angle)}
            if printer == 'cc2':
                to['ironing_angle_fixed'] = '1'
            put('ironing_direction', to)
        except (TypeError, ValueError):
            put('ironing_direction', {}, 'unreadable Bambu ironing direction; destination ironing angle')
    wall = s.get('top_one_wall_type')
    if wall is not None:
        if wall == 'not apply':   # both loaders read every value but 'none' as on
            put('top_one_wall_type', {'only_one_wall_top': '0'})
        elif wall == 'all top':
            put('top_one_wall_type', {'only_one_wall_top': '1'})
        else:
            put('top_one_wall_type', {'only_one_wall_top': '1'},
                f'Bambu one wall on the topmost surface only ({wall}): {SLICER[printer]} has one switch for '
                'every top surface, set on as its loader reads it')
    if 'initial_layer_flow_ratio' in s:
        ratio = s['initial_layer_flow_ratio']
        bottom = s.get('bottom_solid_infill_flow_ratio')
        if equivalent(ratio, '1'):
            put('initial_layer_flow_ratio', {})   # neutral: no first-layer scaling either way
        elif bottom is None or equivalent(bottom, '1'):
            put('initial_layer_flow_ratio', {'bottom_solid_infill_flow_ratio': ratio},
                'Bambu scales first-layer fill touching the bed; no destination key does exactly that: '
                'applied as bottom surface flow (also bottom surfaces above the bed), as its loader reads it')
        else:
            put('initial_layer_flow_ratio', {},
                'Bambu first-layer fill flow has no destination key and the designer bottom surface flow '
                'is kept: first layer at the bottom surface flow')
    if 'prime_tower_rib_wall' in s:
        put('prime_tower_rib_wall', {'wipe_tower_wall_type': 'rib' if _on(s['prime_tower_rib_wall']) else 'rectangle'})
    for bambu, dest in (('prime_tower_rib_width', 'wipe_tower_rib_width'),
                        ('prime_tower_extra_rib_length', 'wipe_tower_extra_rib_length'),
                        ('prime_tower_fillet_wall', 'wipe_tower_fillet_wall'),
                        ('prime_tower_max_speed', 'wipe_tower_max_purge_speed'),
                        ('enable_support_ironing', 'support_ironing')):
        if bambu in s:   # the Orca forks carry these Bambu options under the wipe_tower/support names
            put(bambu, {dest: s[bambu]})
    if 'skirt_per_object' in s:
        # Bambu: one skirt per object in by-object printing only; one skirt otherwise.
        per = _on(s['skirt_per_object']) and str(_first(s.get('print_sequence', ''))) == 'by object'
        put('skirt_per_object', {'skirt_type': 'perobject' if per else 'combined'})
    return out


def process(source, machine=(), filament=(), printer='cc2'):
    """Designer keys the destination keeps, with Bambu-only keys replaced by their
    destination meaning (translate)."""
    mapped = translate(source, printer)
    out = {k: v for k, v in source.items()
           if k not in mapped and reason(k, v, machine, filament, printer) is None}
    for entry in mapped.values():
        out.update(entry['to'])
    return out


def withheld(source, printer='cc2'):
    """Bambu keys process() replaced: drop them from any merged destination process too, or
    its loader re-translates them after (a later JSON position wins)."""
    return set(translate(source, printer))


# The destination loaders' own renames of Bambu keys we leave to them (same rule as
# BambuStudio's own loader): key -> function(value) -> {destination key: value}.
_WALL_ORDER = {'inner wall/outer wall/infill': 'inner wall/outer wall',
               'infill/inner wall/outer wall': 'inner wall/outer wall',
               'outer wall/inner wall/infill': 'outer wall/inner wall',
               'infill/outer wall/inner wall': 'outer wall/inner wall',
               'inner-outer-inner wall/infill': 'inner-outer-inner wall'}
LOADER = {
    'both': {
        'wall_infill_order': lambda v: {'wall_sequence': _WALL_ORDER.get(v, v)},
        'rotate_solid_infill_direction': lambda v: {'solid_infill_rotate_template': '0,90' if _on(v) else '0'},
    },
    'cc2': {
        'wall_filament': lambda v: {'outer_wall_filament_id': '0' if str(v) == '1' else str(v)},
        'sparse_infill_filament': lambda v: {'sparse_infill_filament_id': '0' if str(v) == '1' else str(v)},
        'solid_infill_filament': lambda v: {'internal_solid_filament_id': '0' if str(v) == '1' else str(v)},
    },
}
# Bambu-only keys with no destination meaning, by family (decided per family, not per key;
# typ94 library scan of 6641 BambuStudio 3MFs). Checked in order; the first match wins.
FAMILIES = [
    (r'process_notes|thumbnail_size|thumbnails_.*|bbl_use_printhost|print_host|printhost_.*|'
     r'flashforge_serial_number|use_3mf|bambu_filament_.*|blender_material_.*|pellet_modded_printer|'
     r'unprintable_filament_types|compatible_.*_expression_group|impact_strength_z',
     'metadata or print-host setting: no toolpath effect'),
    (r'ams_.*|default_ams_type|master_extruder_id|physical_extruder_map|print_extruder_id|print_extruder_variant|'
     r'default_nozzle_volume_type|grab_length|long_retractions?_when_(ec|cut)|retraction_distances?_when_(ec|cut)|'
     r'enable_filament_dynamic_map|has_filament_switcher|hotend_(heating|cooling)_rate.*|group_algo_with_time|'
     r'prime_volume_mode|flush_multiplier_fast|flush_volumes_chan_multipliers.*|(min|max)_temperature.*_when_ec|'
     r'handle_hotend_as_extruder|multi_nozzle_diameter_mode|enable_pre_heating|pre_start_fan_time|'
     r'bed_temperature_formula|volumetric_speed_coefficients|support_object_skip_flush|number_of_giga_printheads|'
     r'auto_toolchange_command|support_multi_filament|fins_extrude_safe_temp|bed_temperature_difference',
     'Bambu multi-nozzle, AMS or tool-change hardware control: the destination tool changes and bed '
     'temperature come from its own machine and filament profiles'),
    (r'enable_wrapping_detection|wrapping_.*|fan_direction|cooling_filter_enabled|support_cooling_filter|'
     r'auto_disable_filter_on_overheat|activate_air_filtration.*|bed_heat_soak_area|farthest_point_timelapse|'
     r'print_in_clockwise|aux_fan_.*|sync_auxiliary_fan_to_second_fan|(additional|optional)_.*fan.*|'
     r'close_(additional|optional)_fan_first_x_layers|first_x_layer_(optional_)?fan_speed|fan_p\d_.*|'
     r'fan_speed_(after|before)_x_layers|.*_(BRASS|HS)|enable_power_loss_recovery|default_wipe_tower_pos',
     'Bambu printer hardware or firmware feature (clumping detection, filter, auxiliary fans, loop '
     'direction, timelapse): the destination printer has no such control'),
    (r'enable_circle_compensation|circle_compensation_.*|counter_(coef|limit)_.*|hole_(coef|limit)_.*|'
     r'diameter_limit|apply_scarf_seam_on_circles',
     'Bambu circle (hole) compensation: no destination equivalent, holes print at model size'),
    (r'enable_height_slowdown|slowdown_(start|end)_.*', 'Bambu slow down by height: no destination equivalent'),
    (r'smooth_coefficient|smooth_speed_discontinuity_area|z_direction_outwall_speed_continuous|vertical_shell_speed|'
     r'overhang_totally_speed|override_process_overhang_speed|travel_short_distance_acceleration|'
     r'role_base_wipe_speed|overhang_speed_classic',
     'Bambu speed smoothing / per-role speed extension: destination speeds and caps apply'),
    (r'cooling_slowdown_logic|cooling_perimeter_transition_distance|overhang_threshold_participating_cooling|'
     r'no_slow_down_for_cooling_on_outwalls|first_x_layer_part_fan_speed',
     'Bambu cooling logic extension: destination cooling (filament profile) applies'),
    (r'locked_.*_infill_pattern|infill_rotate_step|infill_instead_top_bottom_surfaces|embedding_wall_into_infill|'
     r'sub_top_surface_pattern|conformal_.*|sparse_infill_lattice_angle_\d|initial_layer_infill_line_width|'
     r'internal_bridge_support_thickness|enable_infill_filament_override|infill_filament_use_base_.*|'
     r'periodic_modifier.*|modifier_ignore_infill',
     'Bambu-only infill feature: no destination equivalent, its default infill applies'),
    (r'seam_slope_gap|seam_placement_away_from_overhangs|override_filament_scarf_seam_setting',
     'Bambu seam extension: destination seam and scarf settings apply'),
    (r'top_area_threshold', 'Bambu top area threshold uses another formula than the destination one-wall '
     'threshold (min_width_top_surface): destination value applies'),
    (r'apply_top_surface_compensation|detect_floating_vertical_shell|top_z_overrides_xy_distance|'
     r'enable_order_independent_overlap_carving|avoid_crossing_wall_includes_support|monotonic_travel_into_wall|'
     r'reduce_infill_retraction_mode|support_fast_purge_mode',
     'Bambu-only shell, travel or support option: no destination equivalent'),
    (r'support_ironing_(direction|inset|speed)|.*support_ring.*',
     'Bambu support ironing / support ring extension: no destination equivalent'),
    (r'prime_tower_.*', 'Bambu prime tower extension: destination wipe tower settings apply'),
    (r'enable_mixed_color_sublayer|mixed_.*|dithering_.*|local_z_.*',
     'mixed-colour / dithering feature of another slicer: no destination equivalent'),
]


def unsupported_reason(key, printer='cc2'):
    """Why a designer key absent from the destination output has no destination value."""
    for pattern, why in FAMILIES:
        if re.fullmatch(pattern, key):
            return f'{why} ({SLICER.get(printer, printer)} does not define {key})'
    return (f'unknown to {SLICER.get(printer, printer)}: its loader drops keys outside its config '
            'definitions; no verified equivalent')


def support_keys(paths):
    return {k for path in paths for k in read(path)
            if k.startswith(('support_', 'tree_support_')) or
            k in {'enable_support', 'independent_support_layer_height'}}


def equivalent(a, b):
    """Same setting value. A list against a string compares element-wise too: the G-code
    CONFIG_BLOCK writes a list comma-joined (first_layer_print_sequence 2,1), some ';'."""
    def norm(v):
        if isinstance(v, list):
            return ';'.join(norm(x) for x in v)
        s = str(v).strip()
        try:
            return f'{float(s):g}'
        except ValueError:
            return s
    if norm(a) == norm(b):
        return True
    if isinstance(a, list) != isinstance(b, list):
        listed, text = (a, b) if isinstance(a, list) else (b, a)
        if isinstance(text, str):
            return norm(listed) == norm(re.split(r'[,;]', text))
    return False


def config(path):
    out = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        active = False
        for line in f:
            if 'CONFIG_BLOCK_START' in line:
                active = True
            elif 'CONFIG_BLOCK_END' in line:
                active = False
            elif active:
                m = re.match(r';\s*(\w+)\s*=\s*(.*)', line)
                if m:
                    out[m[1]] = m[2].strip()
    return out


def audit(source, effective, reasons=None, machine=(), filament=(), printer='cc2'):
    """One row per designer key, including keys the destination does not serialize."""
    rows = []
    mapped = translate(source, printer)
    loader = dict(LOADER['both'], **LOADER.get(printer, {}))
    for k, v in sorted(source.items()):
        used = effective.get(k)
        why = (reasons or {}).get(k) or reason(k, v, machine, filament, printer)
        same = k in effective and equivalent(v, used)
        if not same and k not in effective and (k in mapped or k in loader) and not (reasons or {}).get(k):
            rows.append(_mapped_row(k, v, mapped.get(k), loader.get(k), effective, reasons or {}, printer))
            continue
        rows.append({'key': k, 'designer_value': v, 'our_value': used,
                     'status': 'survives' if same else 'replaced-with-reason',
                     'reason': None if same else why or
                     ('destination slicer normalization' if k in effective else unsupported_reason(k, printer))})
    return rows


def _mapped_row(key, value, entry, rule, effective, reasons, printer):
    """Audit row of a Bambu-only key given a destination meaning (translate, or the
    destination loader's own rename): 'mapped' only when the output holds that meaning."""
    by_loader = entry is None
    to = rule(value) if by_loader else entry['to']
    got = {k: effective.get(k) for k in to}
    row = {'key': key, 'designer_value': value, 'our_key': sorted(to), 'our_value': got or None,
           'mapping': f'{SLICER.get(printer, printer)} loader rename (same rule as BambuStudio)' if by_loader
           else 'designer_settings.translate'}
    wrong = sorted(k for k in to if k not in effective or not equivalent(to[k], effective[k]))
    if wrong:
        lock = next((reasons[k] for k in wrong if reasons.get(k)), None)
        row.update(status='replaced-with-reason', reason=lock or (
            'mapped to ' + ', '.join(f'{k}={to[k]}' for k in wrong) + ' but the output has ' +
            ', '.join(f'{k}={effective.get(k)}' for k in wrong)))
    elif not by_loader and entry['reason']:
        row.update(status='replaced-with-reason', reason=entry['reason'])
    else:
        row.update(status='mapped', reason=None)
        if not to:
            row['mapping'] += ': neutral designer value, no destination key needed'
    return row


def scoped(path):
    """Object, modifier, plate and layer settings; separate from global config."""
    values = {}
    if not str(path).lower().endswith('.3mf') or not zipfile.is_zipfile(path):
        return values
    with zipfile.ZipFile(path) as z:
        for member in ('Metadata/model_settings.config', 'Metadata/layer_config_ranges.xml'):
            if member not in z.namelist():
                continue
            root = ET.fromstring(z.read(member))
            def visit(node, scope):
                tag = node.tag.split('}')[-1]
                if tag in ('object', 'part', 'plate', 'range'):
                    ident = node.get('id') or node.get('min_z', '') + ':' + node.get('max_z', '')
                    if tag == 'plate':
                        ident = next((child.get('value', '') for child in node
                                      if child.get('key') == 'plater_id'), ident)
                    scope += '/' + tag + ':' + ident
                key = node.get('key') or node.get('opt_key')
                if key:
                    # Name, mesh accounting and thumbnails are metadata, not settings.
                    if key not in {'name', 'face_count', 'matrix', 'source_file', 'source_object_id',
                                   'source_volume_id', 'source_offset_x', 'source_offset_y', 'source_offset_z'}:
                        values[(scope, key)] = node.get('value', node.text or '')
                for child in node:
                    visit(child, scope)
            visit(root, member)
        for member in z.namelist():
            if 'layer_height' in member or 'custom_gcode' in member:
                values[(member, 'content')] = z.read(member).decode('utf-8', errors='replace')
    return values


def read_replacements(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        for _, line in zip(range(100), f):
            if line.startswith('; designer_replacements = '):
                return json.loads(line.partition(' = ')[2])
    return []


def _model_settings(path):
    if not str(path).lower().endswith('.3mf') or not os.path.isfile(path) or not zipfile.is_zipfile(path):
        return ''
    with zipfile.ZipFile(path) as z:
        if 'Metadata/model_settings.config' not in z.namelist():
            return ''
        return z.read('Metadata/model_settings.config').decode('utf-8', errors='replace')


def cc2_plates(model, plate=0):
    """The designer plates whose per-plate process values a CC2 slice of `model` makes global:
    the sliced plate (--plate N or a one-plate source), else every plate (merged: a value
    only where all plates agree, plate_process). ElegooSlicer honours the plate block itself,
    but derived keys (skirt_per_object -> skirt_type) are global, bd_3d-printing-zoj6a."""
    return sliced_plates(model, plate or None) or [p for p, _ in plate_blocks(_model_settings(model))] or None


def plate_conflicts(model, plates):
    """Per-plate process keys the merged designer plates disagree on (left at the global value)."""
    if not plates or len(plates) < 2:
        return set()
    return plate_process(_model_settings(model), plates)[1]


def sliced_plates(model, plate=None):
    """The designer plate numbers a slice of `model` uses: the only plate of a one-plate
    source, else `plate` (a number, 'plate_N' or a list for merged plates); None = unknown."""
    ids = [p for p, _ in plate_blocks(_model_settings(model))]
    if len(ids) == 1:
        return ids
    if isinstance(plate, str):
        m = re.fullmatch(r'(?:plate_)?(\d+)', plate)
        plate = int(m.group(1)) if m else None
    if not ids or not plate:
        return None
    return list(plate) if isinstance(plate, (list, tuple)) else [int(plate)]


def _paint_states(code):
    """Leaf states (filament numbers, 0 = unpainted) of one TriangleSelector paint string:
    hex read from the end, nibbles LSB first; 2 bits split, then split side + children, or
    a leaf state (< 3 in 2 bits, else 11 + 4-bit groups of state - 3)."""
    bits = []
    for ch in reversed(code):
        v = int(ch, 16)
        bits += [(v >> i) & 1 for i in range(4)]
    pos, states = [0], set()

    def take(n):
        if pos[0] + n > len(bits):
            raise ValueError('paint code ends early')
        v = sum(bits[pos[0] + i] << i for i in range(n))
        pos[0] += n
        return v

    def node():
        split = take(2)
        if split:
            take(2)
            for _ in range(split + 1):
                node()
            return
        s = take(2)
        if s == 3:
            while True:
                g = take(4)
                s += g
                if g != 15:
                    break
        states.add(s)
    node()
    return states


def plate_filaments(prepared):
    """1-based filaments the objects of a prepared (one-plate) 3MF print with: part extruder,
    else its object's, paint states, height-range extruders."""
    used = set()
    if not str(prepared).lower().endswith('.3mf') or not zipfile.is_zipfile(prepared):
        return used
    with zipfile.ZipFile(prepared) as z:
        names = z.namelist()
        ms = z.read('Metadata/model_settings.config').decode('utf-8', 'replace') \
            if 'Metadata/model_settings.config' in names else ''
        for body in re.findall(r'<object id="\d+">(.*?)</object>', ms, flags=re.S):
            own = re.search(r'<metadata key="extruder" value="(\d+)"', re.sub(r'<part .*?</part>', '', body, flags=re.S))
            default = int(own.group(1)) if own else 1
            parts = re.findall(r'<part [^>]*subtype="(\w+)"[^>]*>(.*?)</part>', body, flags=re.S)
            for subtype, part in parts or [('normal_part', '')]:
                if subtype != 'normal_part':
                    continue
                e = re.search(r'<metadata key="extruder" value="(\d+)"', part)
                used.add(int(e.group(1)) if e else default)
        codes = set()
        for n in names:
            if n.endswith('.model'):
                codes.update(re.findall(r'paint_color="([0-9A-Fa-f]+)"', z.read(n).decode('utf-8', 'replace')))
        for code in codes:
            used.update(s for s in _paint_states(code) if s > 0)
        if 'Metadata/layer_config_ranges.xml' in names:
            used.update(int(x) for x in re.findall(r'<option opt_key="extruder">(\d+)</option>',
                                                    z.read('Metadata/layer_config_ranges.xml').decode('utf-8', 'replace')))
    return used


def plate_tools(prepared, gcode, effective):
    """(filaments the prepared plate's objects and supports print with, filaments the G-code
    prints; both 1-based): the evidence for a per-plate filament map on a one-head-per-filament
    printer (G-code filament N = tool T(N-1))."""
    used = plate_filaments(prepared)
    if str(effective.get('enable_support', '0')) in ('1', 'true'):
        for key in ('support_filament', 'support_interface_filament'):
            try:
                if int(str(effective.get(key, '0')).split(',')[0]) > 0:
                    used.add(int(str(effective[key]).split(',')[0]))
            except ValueError:
                pass
    printed = set()
    with open(gcode, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = re.match(r'; filament used \[mm\] = (.*)', line)
            if m:
                printed = {i + 1 for i, x in enumerate(m.group(1).split(',')) if float(x or 0) > 0}
                break
    return used, printed


def _plate_row(scope, key, value, plates, effective, reasons, tools):
    """Audit row of one <plate> key of a U1 slice (the conversion removes the plate block)."""
    number = int(re.search(r'/plate:(\d+)', scope).group(1))
    row = {'key': key, 'scope': scope, 'designer_value': value, 'our_value': None,
           'evidence': 'prepared 3MF input and the G-code CONFIG_BLOCK / filament used line'}

    def done(status, why=None, **more):
        row.update(more, status=status, reason=why)
        return row
    if plates is None:
        return done('replaced-with-reason', 'Bambu plate block removed (Snapmaker CLI crash, g7u7); the sliced '
                    'designer plate is unknown, so its per-plate values were not applied')
    if number not in plates:
        return done('replaced-with-reason', f'designer plate {number} not in this slice (plate '
                    f'{",".join(map(str, plates))})')
    if key in PLATE_PROCESS:
        if value == '':
            return done('mapped', None, mapping='empty plate value = the global setting')
        want, conflicts = plate_process(f'<plate><metadata key="plater_id" value="{number}"/>'
                                        f'<metadata key="{key}" value="{value}"/></plate>', [number])
        if len(plates) > 1:
            return done('replaced-with-reason', 'merged designer plates: their per-plate values are applied only '
                        'where every merged plate agrees (global value otherwise)', our_value=effective.get(key))
        expect = want.get(key)
        got = effective.get(key)
        ok = got is not None and equivalent(expect, [x.strip() for x in got.split(',')] if isinstance(expect, list)
                                            else got)
        if ok:
            return done('mapped', None, our_key=[key], our_value=got,
                        mapping='per-plate value applied as the global process value (plate block removed, g7u7)')
        return done('replaced-with-reason', reasons.get(key) or f'per-plate {key} {value} not in the output '
                    f'(output {got})', our_key=[key], our_value=got)
    if key in ('filament_maps', 'filament_map_mode', 'filament_volume_maps', 'filament_nozzle_maps'):
        used, printed = tools
        evidence = (f'plate filaments {sorted(used)} -> G-code tools ' +
                    ', '.join(f'T{t - 1}' for t in sorted(printed)))
        if not printed or not printed <= used:
            return done('replaced-with-reason', f'G-code prints filaments {sorted(printed)}, the plate objects '
                        f'use {sorted(used)}: tool mapping not proven', evidence=evidence)
        if key == 'filament_volume_maps':
            flows = value.split()
            high = sorted(i + 1 for i, x in enumerate(flows) if x != '0' and i + 1 in used)
            if high:
                return done('replaced-with-reason', 'U1 heads are standard-flow nozzles; designer high-flow '
                            f'nozzle for filament(s) {high} not available', evidence=evidence)
        return done('mapped', None, evidence=evidence, our_value='filament N -> U1 tool T(N-1)',
                    mapping='Bambu filament-to-nozzle grouping (dual-nozzle printers) has no U1 meaning: '
                            'the U1 prints each filament with its own head')
    if key in ('bed_type', 'curr_bed_type'):
        return done('replaced-with-reason', 'destination machine and bed policy')
    return done('replaced-with-reason', 'Bambu plate UI metadata (name, lock, thumbnails, object list): no '
                'slicing effect; plate block removed (Snapmaker CLI crash, g7u7)')


def report(path, sources, reasons=None, machine=(), filament=(), printer='cc2', prepared=None, plate=None):
    """Write PATH.designer.json and the G-code header line. plate = the designer plate (or
    plates) of the slice: its per-plate process values are read as global designer values
    (the U1 copy has them as global values, the CC2 G-code CONFIG_BLOCK writes the plate's)."""
    rows = []
    effective = config(path)
    for model in sources:
        rows += [dict(row, model=str(model), scope='global') for row in
                 audit(read(model, sliced_plates(model, plate)), effective, reasons,
                       machine, filament, printer)]
    for model, target in zip(sources, prepared or sources):
        before, after = scoped(model), scoped(target)
        tools = None
        for (scope, key), value in sorted(before.items()):
            used = after.get((scope, key))
            same = used is not None and equivalent(value, used)
            why = reason(key, value, machine, filament, printer)
            if not same and printer == 'u1' and '/plate:' in scope and used is None:
                if tools is None:
                    tools = plate_tools(target, path, effective)
                rows.append(dict(_plate_row(scope, key, value, sliced_plates(model, plate), effective, reasons or {},
                                            tools), model=str(model)))
                continue
            elif not same and key.endswith(('_speed', '_acceleration', '_jerk')):
                why = 'destination scoped motion/noise policy or explicit object cap'
            rows.append({'key': key, 'scope': scope, 'model': str(model),
                         'designer_value': value, 'our_value': used,
                         'status': 'survives' if same else 'replaced-with-reason',
                         'evidence': 'prepared 3MF input; per-object output not serialized in global config',
                         'reason': None if same else why or
                         'object/plate selection, tool mapping or explicit object/layer recipe policy'})
    replacements = [row for row in rows if row['status'] == 'replaced-with-reason']
    if printer == 'cc2':
        # M600 removal happens after slicing and is intentionally not inferred
        # from the unchanged custom-G-code XML in the prepared input archive.
        for row in rows:
            if 'custom_gcode' in row['scope'] and re.search(r'\bM600\b', str(row['designer_value'])):
                with open(path, encoding='utf-8', errors='replace') as f:
                    kept_pause = any(re.match(r'\s*M600\b', line) for line in f)
                if not kept_pause:
                    row.update(status='replaced-with-reason', our_value=None,
                               reason='CC2 safety: M600 removed because firmware hangs on it',
                               evidence='final G-code has no executable M600')
                    if row not in replacements:
                        replacements.append(row)
    result = {'schema_version': 1, 'printer': printer, 'settings': rows,
              'designer_replacements': replacements}
    result['checks'] = [{'check': 'designer_settings', 'designer_replacements': replacements}]
    with open(path + '.designer.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    with open(path, encoding='utf-8', newline='') as f:
        lines = [line for line in f if not line.startswith('; designer_replacements = ')]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('; designer_replacements = ' + json.dumps(replacements, separators=(',', ':')) + '\n')
        f.writelines(lines)
    return result
