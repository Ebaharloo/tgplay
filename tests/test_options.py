#!/usr/bin/env python3
"""test_options - THE shared options model; nothing may get lost between UIs.

The field inventory is locked: the model's field specs must cover exactly the
keys tp/setup remembers and tp/cli parses, and every conversion must behave
byte-identically to the old hand-written code (which the test_setup suite
still asserts).
Run: .venv/bin/python tests/test_options.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import options  # noqa: E402


def test_default_opts_is_legacy_shape():
    o = options.PlaybackOptions.defaults().to_opts()
    # exactly the tp/cli.parse base dict, plus the new start/end rows
    assert set(o) == {'a', 'skip', 'skip_toggle', 'e', 'f', 'cut', 'start',
                      'end', 'next', 'nowait', 'sync'}, o
    assert o == {'a': False, 'skip': False, 'skip_toggle': False, 'e': None,
                 'f': None, 'cut': None, 'start': None, 'end': None,
                 'next': False, 'nowait': False, 'sync': 'auto'}, o
    print('PASS default opts legacy shape')


def test_normalization():
    po = options.PlaybackOptions({'skip': 'names', 'next': 0.45, 'cut': '30'},
                                 ['--volume', '80', '--fullscreen'])
    assert po.skip == 'names' and po.skip_mode == 'names'
    assert options.PlaybackOptions({'skip': 'garbage'}).to_opts()['skip'] is False
    # an explicit 'off' is a real choice now (it used to collapse into False,
    # the legacy "unset" value that still means 'all' at play time)
    assert options.PlaybackOptions({'skip': 'off'}).to_opts()['skip'] == 'off'
    assert po.next == 0.45                       # explicit fraction kept
    assert options.PlaybackOptions({'next': True}).to_opts()['next'] == 0.60
    assert options.PlaybackOptions({'next': 'x'}).to_opts()['next'] is False
    assert po.cut == 30 and po.fullscreen is True
    assert po.extras == ['--volume', '80']       # fullscreen separated
    po.set_skip('off'); po.set_fullscreen(False); po.set_cut(None)
    assert po.skip == 'off' and po.fullscreen is False and po.cut is None
    po.set_next(False); po.set_next(True)
    assert po.next == options.DEFAULT_NEXT == 0.60
    print('PASS value normalization')


def test_saved_shape_and_merge_matches_setup():
    import tempfile
    from tp import setup
    p = os.path.join(tempfile.mkdtemp(prefix='tgplay-opt-'), 'ui.json')
    opts = {'skip': 'names', 'skip_toggle': True, 'next': 0.6, 'nowait': True,
            'cut': 30, 'f': '1080P [x265]', 'sync': 'auto', 'audio': 'sub'}
    mpv = ['--fullscreen', '--volume', '80']
    po = options.PlaybackOptions(opts, mpv)
    mine = po.saved_shape()
    # identical to what tp/setup.save persists (same json contract)
    assert set(mine) == {'skip', 'skip_toggle', 'next', 'nowait', 'cut',
                         'fullscreen', 'extra', 'quality', 'audio',
                         'sync'}, mine
    # merge equals tp.setup.apply on both fill and override cases
    saved = setup.load(p) if False else {
        'skip': 'all', 'quality': 'x265', 'next': 0.6, 'nowait': False,
        'cut': 10, 'fullscreen': True, 'extra': '--volume 90', 'audio': 'dub',
        'sync': 'auto'}
    o1, m1 = setup.apply({'skip': False, 'skip_toggle': False, 'next': False,
                          'nowait': False, 'cut': None, 'f': None, 'sync': '',
                          }, [], saved)
    po2 = options.PlaybackOptions({'skip': None, 'skip_toggle': False,
                                   'next': False, 'nowait': False,
                                   'cut': None, 'f': None, 'sync': ''})
    po2.merge_saved(saved)
    o1_full = {**options.PlaybackOptions.defaults().to_opts(), **o1}
    assert po2.to_opts() == o1_full, (po2.to_opts(), o1_full)
    assert po2.mpv() == m1, (po2.mpv(), m1)
    o2, m2 = setup.apply({'skip': 'auto', 'cut': 5, 'f': '720'},
                         ['--x'], saved)
    po3 = options.PlaybackOptions({'skip': 'auto', 'cut': 5, 'f': '720'},
                                  ['--x'])
    po3.merge_saved(saved)
    o2_full = {**options.PlaybackOptions.defaults().to_opts(), **o2}
    assert po3.to_opts() == o2_full and po3.mpv() == m2, (po3.to_opts(), o2_full)
    print('PASS saved-shape + merge == setup.apply')


def test_field_inventory_locked():
    """The render spec covers EVERY legacy key - no option can be dropped."""
    keys_quality = {f['k'] for f in options.form_fields(groups=['720p'])}
    keys_plain = {f['k'] for f in options.form_fields()}
    keys_axp = {f['k'] for f in options.form_fields(
        groups=['nero (dub)'], audio=True)}
    keys_tui = {f['k'] for f in options.form_fields(show_eps=True)}
    # setup with quality/extra rows + audio (axp) + skip form keys
    assert {'quality', 'skip', 'toggle', 'next', 'nowait', 'cut', 'sync',
            'full', 'extra'} <= keys_quality, keys_quality
    assert {'skip', 'toggle', 'next', 'nowait', 'cut', 'sync', 'full',
            'extra'} <= keys_plain, keys_plain
    assert 'audio' in keys_axp and 'quality' in keys_axp, keys_axp
    assert 'eps' in keys_tui, keys_tui
    assert 'audio' not in keys_plain and 'quality' not in keys_plain

    # a full form session round-trips every value without loss
    opts = {'skip': 'names', 'skip_toggle': True, 'next': 0.45,
            'nowait': True, 'cut': 12, 'f': 'nero  (dub+sub)', 'a': False,
            'e': None, 'sync': 'off'}
    mpv = ['--sub-delay', '2', '--fullscreen']
    fields = options.form_fields(groups=['nero  (dub+sub)', 'nero  (sub)'],
                                 audio=True, show_eps=True, opts=opts, mpv=mpv)    # simulate NO edits: legacy semantics preserved (and 'next' improved -
    # its exact CLI fraction 0.45 is kept when the checkbox is untouched,
    # instead of the old reset to 0.60)
    o, m = options.form_result(fields, opts, mpv)
    legacy = options.PlaybackOptions(opts, mpv).to_opts()
    assert o['skip'] == legacy['skip'] and o['cut'] == legacy['cut']
    assert o['skip_toggle'] == legacy['skip_toggle']
    assert o['nowait'] == legacy['nowait'] and o['sync'] == legacy['sync'] == 'off'
    assert o['a'] is True and o['e'] is None, o          # eps row default
    assert o['next'] == 0.45, o                          # fraction preserved
    assert m == mpv, m                                   # mpv untouched
    # a real edit (checked -> unchecked) resets next properly
    fields_e = options.form_fields(groups=['nero  (dub+sub)'], audio=True,
                                   opts=opts, mpv=mpv)
    for f in fields_e:
        if f['k'] == 'next':
            f['val'] = not f['val']
    oe, _ = options.form_result(fields_e, opts, mpv)
    assert oe['next'] is False, oe
    # construction state per apply (like the Qt flow): a form built with
    # 'next' off, then checked by the user -> the 0.60 default
    oe2_src = {k: v for k, v in opts.items() if k != 'next'} | {'next': False}
    fields2 = options.form_fields(groups=['nero  (dub+sub)'], audio=True,
                                  opts=oe2_src, mpv=mpv)
    for f in fields2:
        if f['k'] == 'next':
            f['val'] = True
    oe2, _ = options.form_result(fields2, opts, mpv)
    assert oe2['next'] == options.DEFAULT_NEXT == 0.60, oe2
    # without the eps row (Qt window): identity except 'next', whose exact
    # fraction is now PRESERVED when the checkbox is untouched (was lost by
    # the old hand-written forms - a strict improvement, nothing lost)
    fields_qt = options.form_fields(groups=['nero  (dub+sub)'], audio=True,
                                    opts=opts, mpv=mpv)
    oq, mq = options.form_result(fields_qt, opts, mpv)
    legacy = {**legacy, 'audio': 'dub'}     # the Audio row writes its default
    assert oq == legacy, (oq, legacy)
    assert mq == mpv, mq
    # and every edit is applied via form_result
    for f in fields:
        if f['kind'] == 'flag':
            f['val'] = not f['val']
        elif f['kind'] == 'choice':
            f['i'] = (f['i'] + 1) % len(f['choices'])
        elif f['k'] == 'cut':
            f['val'] = '77'
        elif f['k'] == 'eps':
            f['val'] = '2-5'
    o, m = options.form_result(fields, opts, mpv)
    assert o['cut'] == 77 and o['a'] is False and o['e'] == '2-5', o
    assert o['skip_toggle'] is False and o['next'] is False, o
    assert o['skip'] in ('off', 'all', 'names', 'auto')
    assert o['f'] in ('nero  (sub)', 'nero  (dub+sub)'), o
    assert '--sub-delay' in m and '2' in m, m            # untouched extras stay
    print('PASS field inventory locked + full round-trip')


def test_start_end_positions():
    """Start at / Finish at: mm:ss == seconds, blank clears, --end wins."""
    from tp.player import Player
    po = options.PlaybackOptions({'start': '1:30', 'end': '90'})
    assert po.start == po.end == 90
    assert options.PlaybackOptions({'start': '1:02:03'}).start == 3723
    assert options.PlaybackOptions({'start': '62'}).start == 62
    assert options.PlaybackOptions({'start': 62}).start == 62
    assert options.PlaybackOptions({'start': '', 'end': '  '}).to_opts() \
        .get('start') is None
    assert options.PlaybackOptions({'start': '', 'end': '  '}).end is None
    assert options.PlaybackOptions({'start': 'nope'}).start is None
    # absolute --end replaces the relative cut --end (never both)
    p = Player()
    cmd = p.command('u', start=10, cut=30, end=900)
    assert '--start=10' in cmd and '--end=900' in cmd, cmd
    assert '--end=-30' not in cmd, cmd
    assert sum(f.startswith('--end') for f in cmd) == 1, cmd
    # an explicit --end in the extra flags is the only --end
    cmd = p.command('u', cut=30, end=99, extra=['--end=-5'])
    assert cmd.count('--end=-5') == 1, cmd
    assert not [f for f in cmd if f.startswith('--end') and f != '--end=-5'], cmd
    # form round-trip: fields carry seconds, edits parse, blank clears
    fields = options.form_fields(opts={'start': '1:30', 'end': 120})
    by = {f['k']: f for f in fields}
    ks = [f['k'] for f in fields]
    assert by['start']['kind'] == 'text' and by['start']['val'] == '90'
    assert by['end']['val'] == '120'
    assert ks.index('start') < ks.index('cut') and ks.index('end') < ks.index('cut')
    by['start']['val'] = '2:00'
    by['end']['val'] = ' '
    o, _ = options.form_result(fields, {'start': None, 'end': None})
    assert o['start'] == 120 and o['end'] is None, o
    print('PASS start/end positions')


def main():
    test_default_opts_is_legacy_shape()
    test_normalization()
    test_saved_shape_and_merge_matches_setup()
    test_field_inventory_locked()
    test_start_end_positions()
    print('OPTIONS OK')


if __name__ == '__main__':
    main()
