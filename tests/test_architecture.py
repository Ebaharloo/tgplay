#!/usr/bin/env python3
"""test_architecture - the repo's object rules, ENFORCED.

Any AI (or human) changing this repo must keep these green. If a rule here
blocks your change, the change needs a refactor into the feature/tracking
object pattern - not a bypass.

Rules:
1. No per-source literals in feature logic: `== 'axp'`-style comparisons only
   in the two registries and the link-routing table.
2. Consumers never build clients directly: gui_all constructs no SimklAccount.
3. The tp/features REGISTRY covers every feature module in the package.
4. tp/tracking exists with its own REGISTRY; no direct simkl_client imports
   outside tp/tracking (consumers go through the registry).
5. tp/web is gone: nothing imports it.
6. Every feature module ships its test file.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

TP = os.path.join(ROOT, 'tp')


def _pyfiles(base):
    out = []
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.join(dirpath, f))
    return out


LITERAL_OK = {
    os.path.join(TP, 'features', '__init__.py'),
    os.path.join(TP, 'tracking', '__init__.py'),
    os.path.join(ROOT, 'tp', 'cli_all.py'),
    os.path.join(TP, 'cli_all.py'),
}
_SRC_RE = re.compile(r"==\s*'(axp|agp|tg|tgp|zoro)'\b")


def test_no_src_literals_in_feature_logic():
    hits = []
    for path in _pyfiles(TP):
        if any(os.path.samefile(path, ok) for ok in LITERAL_OK if os.path.exists(ok)):
            continue
        src = open(path, encoding='utf-8').read()
        for line in src.splitlines():
            if _SRC_RE.search(line) and 'route' not in line.lower():
                hits.append(f'{os.path.relpath(path, ROOT)}: {line.strip()[:90]}')
    assert not hits, ('per-source literals outside the registries/routing:\n'
                      + '\n'.join(hits[:10]))


def test_gui_never_builds_simkl_clients_directly():
    gui = open(os.path.join(TP, 'gui_all.py'), encoding='utf-8').read()
    assert 'SimklAccount(' not in gui, (
        'gui_all must call tracking features, not construct SimklAccount')


def test_features_registry_covers_every_feature_module():
    import tp.features as feat
    pkg_dir = os.path.join(TP, 'features')
    modules = {f[:-3] for f in os.listdir(pkg_dir)
               if f.endswith('.py') and f != '__init__.py'}
    missing = modules - set(feat.REGISTRY)
    assert not missing, f'registry misses feature modules: {missing}'


def test_tracking_package_has_its_registry():
    import tp.tracking as trk
    assert hasattr(trk, 'REGISTRY') and trk.REGISTRY, 'tp/tracking REGISTRY'
    pkg_dir = os.path.join(TP, 'tracking')
    sync_mods = {f[:-3] for f in os.listdir(pkg_dir)
                 if f.endswith('.py') and f not in ('__init__.py',)} - {
        'simkl_client', 'anilist_client', 'local_store', 'wiki'}
    missing = sync_mods - set(trk.REGISTRY)
    assert not missing, f'tracking registry misses feature modules: {missing}'


def test_tp_web_is_gone():
    for path in _pyfiles(TP):
        src = open(path, encoding='utf-8').read()
        assert 'from .web' not in src and 'import tp.web' not in src and \
            'from tp.web' not in src, f'{path} still imports tp/web'


def test_every_feature_module_has_a_test():
    for pkg in ('features', 'tracking'):
        pkg_dir = os.path.join(TP, pkg)
        for f in os.listdir(pkg_dir):
            if not f.endswith('.py') or f == '__init__.py':
                continue
            test = os.path.join(HERE, f'test_{pkg}_{f[:-3]}.py')
            assert os.path.exists(test), f'missing test for {pkg}/{f}: {test}'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
