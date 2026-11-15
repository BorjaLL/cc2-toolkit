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


def read(path):
    if not str(path).lower().endswith('.3mf') or not os.path.isfile(path) or not zipfile.is_zipfile(path):
        return {}
    with zipfile.ZipFile(path) as z:
        if 'Metadata/project_settings.config' not in z.namelist():
            return {}
        return json.loads(z.read('Metadata/project_settings.config'))


def reason(key, value, machine=(), filament=(), printer='cc2'):
    if key in IDENTITY or key.endswith('_settings_id'):
        return 'destination preset identity'
    if key in machine or key.startswith(('machine_', 'printer_', 'extruder_', 'nozzle_')) or key == 'curr_bed_type':
        return 'destination machine and bed policy'
    if key in filament or key.startswith('filament_'):
        return 'destination filament calibration and tool mapping'
    if key.endswith('_gcode') or key == 'gcode_flavor':
        return 'destination machine G-code and safety policy'
    if printer == 'u1' and key == 'wipe_tower_filament':
        return 'Snapmaker CLI crash: wipe_tower_filament (pnw5)'
    if printer == 'u1' and key in {'wall_filament', 'solid_infill_filament', 'sparse_infill_filament'} and str(value) == '0':
        return 'Snapmaker CLI requires filament index >= 1; Bambu auto index 0 is invalid'
    if key in NEG_AUTO and str(value) == '-1':
        return 'Bambu negative auto value rejected by destination CLI'
    return None


def process(source, machine=(), filament=(), printer='cc2'):
    return {k: v for k, v in source.items() if reason(k, v, machine, filament, printer) is None}


def support_keys(paths):
    return {k for path in paths for k in read(path)
            if k.startswith(('support_', 'tree_support_')) or
            k in {'enable_support', 'independent_support_layer_height'}}


def equivalent(a, b):
    def norm(v):
        if isinstance(v, list):
            return ';'.join(norm(x) for x in v)
        s = str(v).strip()
        try:
            return f'{float(s):g}'
        except ValueError:
            return s
    return norm(a) == norm(b)


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
    for k, v in sorted(source.items()):
        used = effective.get(k)
        why = (reasons or {}).get(k) or reason(k, v, machine, filament, printer)
        same = k in effective and equivalent(v, used)
        rows.append({'key': k, 'designer_value': v, 'our_value': used,
                     'status': 'survives' if same else 'replaced-with-reason',
                     'reason': None if same else why or
                     ('destination slicer normalization' if k in effective else
                      'not serialized by destination slicer; preservation unverified')})
    return rows


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


def report(path, sources, reasons=None, machine=(), filament=(), printer='cc2', prepared=None):
    rows = []
    effective = config(path)
    for model in sources:
        rows += [dict(row, model=str(model), scope='global') for row in
                 audit(read(model), effective, reasons, machine, filament, printer)]
    for model, target in zip(sources, prepared or sources):
        before, after = scoped(model), scoped(target)
        for (scope, key), value in sorted(before.items()):
            used = after.get((scope, key))
            same = used is not None and equivalent(value, used)
            why = reason(key, value, machine, filament, printer)
            if not same and printer == 'u1' and '/plate:' in scope and used is None:
                why = 'Bambu plate metadata removed to avoid Snapmaker CLI crash; per-plate mapping unverified'
            elif not same and key.endswith(('_speed', '_acceleration', '_jerk')):
                why = 'destination scoped motion/noise policy or explicit object cap'
            rows.append({'key': key, 'scope': scope, 'model': str(model),
                         'designer_value': value, 'our_value': used,
                         'status': 'survives' if same else 'replaced-with-reason',
                         'evidence': 'prepared 3MF input; per-object output not serialized in global config',
                         'reason': None if same else why or
                         'object/plate selection, tool mapping or explicit object/layer recipe policy'})
    replacements = [row for row in rows if row['status'] != 'survives']
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
