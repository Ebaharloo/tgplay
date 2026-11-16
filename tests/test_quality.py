#!/usr/bin/env python3
"""test_quality - own test model for quality-from-filename (tp.quality)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import quality  # noqa: E402


def test_quality():
    assert quality.parse_quality('x 480p y') == '480p'
    assert quality.parse_quality('x 1080P y') == '1080p'
    assert quality.parse_quality('movie 4K') == '2160p'
    assert quality.parse_quality('no tag here') is None
    assert quality.parse_quality('x480pts') is None          # 'p' glued to letters is not a tag
    names = ['BTTH - S5 E213 [Eng-Sub] 480p @S.mkv',
             'BTTH - S5 E213 [Eng-Sub] 1080p @S.mkv',
             'BTTH - S5 E213 [Eng-Sub] 4K @S.mkv']
    qs, byq = quality.group(names)
    assert qs == ['480p', '1080p', '2160p'], qs
    assert len(byq['1080p']) == 1 and byq['1080p'][0].endswith('1080p @S.mkv')
    # a single quality is not a group (caller keeps the flat list)
    assert quality.group(['a 720p.mkv', 'b 720p.mkv']) == ([], {})
    # an untagged file is offered in every quality group
    qs, byq = quality.group(['e 480p.mkv', 'e 1080p.mkv', 'e no-tag.mkv'])
    assert qs == ['480p', '1080p'] and all('e no-tag.mkv' in v for v in byq.values())


def main():
    test_quality()
    print('QUALITY OK')


if __name__ == '__main__':
    main()
