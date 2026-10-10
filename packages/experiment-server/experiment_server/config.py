"""Explicit model and full-state schema, independent of world YAML or case names."""
import copy
import math
from pathlib import Path
from .storage import atomic, read, sha, valid_name

AU = 149597870700.
YEAR = 31557600.
ENERGY_UNIT = 1.98847e30 * (AU / YEAR) ** 2
PARTICLE_KEYS = ['x', 'y', 'z', 'vx', 'vy', 'vz', 'm', 'r']


def finite_tree(value):
    if isinstance(value, dict):
        for v in value.values(): finite_tree(v)
    elif isinstance(value, list):
        for v in value: finite_tree(v)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
        raise ValueError('配置不能包含NaN或Infinity。')


def validate(config):
    c = copy.deepcopy(config)
    finite_tree(c)
    allowed = {'schema_version', 'model', 'units', 'initial_state', 'body_names', 'diagnostics', 'integration', 'provenance', 'label'}
    if set(c) - allowed:
        raise ValueError(f'未知配置字段：{sorted(set(c) - allowed)}')
    if c.get('schema_version') != 1 or c.get('units') != ['yr', 'AU', 'Msun']:
        raise ValueError('要求schema_version=1和units=[yr,AU,Msun]。')
    if c.get('model') not in ['coupled_ctl', 'point_mass']:
        raise ValueError('model须为coupled_ctl或point_mass。')
    state = c['initial_state']; particles = state['particles']; names = c['body_names']
    if not isinstance(particles, list) or len(particles) < 2 or len(names) != len(particles) or len(names) != len(set(names)):
        raise ValueError('至少两颗粒子，每颗须有唯一body_name。')
    for name in names: valid_name(name)
    if state['epoch_yr'] < 0 or state['G'] <= 0:
        raise ValueError('epoch须非负，G须正。')
    for p in particles:
        if set(p) != set(PARTICLE_KEYS) or p['m'] <= 0 or p['r'] < 0:
            raise ValueError('粒子必须有x/y/z/vx/vy/vz/m/r，正质量及非负半径。')
    diag = c.setdefault('diagnostics', {})
    if set(diag) - {'star', 'host', 'moons', 'heat_body', 'pairs', 'primary'}:
        raise ValueError('未知diagnostics字段。')
    for key in ['star', 'host', 'heat_body', 'primary']:
        if key in diag and (not isinstance(diag[key], int) or not 0 <= diag[key] < len(particles)):
            raise ValueError(f'无效diagnostics.{key}索引。')
    for pair in diag.get('pairs', []):
        if len(pair) != 2 or pair[0] == pair[1] or any(not isinstance(i, int) or not 0 <= i < len(particles) for i in pair):
            raise ValueError('pairs必须是两个不同粒子的合法索引。')
    integration = c.setdefault('integration', {})
    if set(integration) - {'eps_rel', 'eps_abs', 'interval_yr', 'checkpoint_yr'}:
        raise ValueError('未知integration字段。')
    for key, default in [('eps_rel', 1e-11), ('eps_abs', 1e-14), ('interval_yr', 2.), ('checkpoint_yr', 1000.)]:
        integration.setdefault(key, default)
        if integration[key] <= 0:
            raise ValueError('积分精度和输出／保存间隔须为正数。')
    if integration['checkpoint_yr'] < integration['interval_yr'] or not math.isclose(integration['checkpoint_yr'] / integration['interval_yr'], round(integration['checkpoint_yr'] / integration['interval_yr'])):
        raise ValueError('checkpoint_yr须为interval_yr的正整数倍。')
    if c['model'] == 'coupled_ctl':
        if len(particles) < 5 or diag.get('star') != 0 or diag.get('host') != 1 or diag.get('moons') != [2, 3, 4]:
            raise ValueError('coupled_ctl结构：索引0恒星，1母星，2/3/4自转卫星；其它粒子为保守外行星。')
        if diag.get('heat_body', 2) not in [2, 3, 4]:
            raise ValueError('coupled_ctl heat_body须为2/3/4。')
        spin = state['spin_state16']; s = state['settings']
        if len(spin) != 16 or any(sum(v * v for v in spin[i:i+3]) == 0 for i in [0, 3, 6, 9]) or any(v < 0 for v in spin[12:]):
            raise ValueError('coupled_ctl须有12维非零spin和4维非负累计热。')
        for key in ['radii_au', 'k2', 'k2tau_yr', 'inertias', 'j2_array']:
            if len(s[key]) < 5:
                raise ValueError(f'coupled_ctl缺少至少5项settings.{key}。')
        if any(s['inertias'][i] <= 0 for i in [1, 2, 3, 4]):
            raise ValueError('四个自转体的惯性矩须为正。')
        if any(v < 0 for key in ['radii_au', 'k2', 'k2tau_yr'] for v in s[key]):
            raise ValueError('半径／Love数／时滞不可为负。')
        if s.get('all_permanent_figures') or s.get('multisource_nacrea'):
            raise ValueError('此验证后端仅支持原pairedCTL/J2-spin，不支持额外形状／多源。')
        if not math.isclose(state['G'], 39.476926421373, rel_tol=1e-12):
            raise ValueError('coupled_ctl固定kernel G与初态G不一致。')
        for i in [1, 2, 3, 4]:
            if s['radii_au'][i] <= 0 or not math.isclose(s['radii_au'][i], particles[i]['r'], rel_tol=1e-12, abs_tol=1e-16):
                raise ValueError('粒子半径与CTL物性半径不一致。')
        diag.setdefault('heat_body',2)
    elif state.get('spin_state16') or state.get('settings'):
        raise ValueError('point_mass不接受spin/tidal settings，避免静默忽略物性。')
    return c


def import_portable(state, names=None, pairs=None):
    n = len(state['particles'])
    names = names or ['star_ignis', 'planet_aegis', 'satellite_nacrea', 'satellite_cadence', 'satellite_vigil'] + [f'planet_{i}' for i in range(5, n)]
    return validate({'schema_version': 1, 'model': 'coupled_ctl', 'units': ['yr', 'AU', 'Msun'],
                     'initial_state': copy.deepcopy(state), 'body_names': names,
                     'diagnostics': {'star': 0, 'host': 1, 'moons': [2, 3, 4], 'heat_body': 2, 'pairs': pairs or [[3, 4]]},
                     'provenance': {'imported_portable_full_state': True}})


def read_config(path: Path):
    return validate(read(path))
