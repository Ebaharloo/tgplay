"""tp.episodes - the episode model, and the ONLY place the play list is built.

`play()` consumes `list[Episode]`. An `Episode` is a `(num, link)` tuple, so
the old failure mode - handing the player a list of bare link strings and
dying at `num, link = eps[i]` with "too many values to unpack" - cannot be
expressed: selection and resume go through `select()` / `resume()` here.
"""
from typing import Dict, Iterable, List, NamedTuple, Optional


class Episode(NamedTuple):
    num: int
    link: str


def parse_range(spec: Optional[str]) -> List[int]:
    """'2-5,9' -> [2, 3, 4, 5, 9] (empty on junk)."""
    out = []
    for tok in (spec or '').replace(',', ' ').split():
        if '-' in tok:
            a, b = tok.split('-', 1)
            try:
                out += list(range(int(a), int(b) + 1))
            except ValueError:
                pass
        elif tok.isdigit():
            out.append(int(tok))
    return sorted(set(out))


def select(eps: Dict[int, str], nums: Optional[Iterable[int]] = None,
           all: bool = False) -> List[Episode]:
    """Episodes by number set, or every episode when `all`."""
    ks = sorted(eps)
    if all:
        pick = ks
    elif nums is not None:
        want = set(nums)
        pick = [k for k in ks if k in want]
    else:
        pick = []
    return [Episode(k, eps[k]) for k in pick]


def resume(eps: Dict[int, str], start: int) -> List[Episode]:
    """Every episode from `start` onward (the resume prompt's choice)."""
    return [Episode(k, eps[k]) for k in sorted(eps) if k >= start]


def first_start_for(planned: List[Episode], resume_ep: int,
                    pos: int) -> Optional[int]:
    """Seconds to seek to on the first episode, only if it is the resumed one."""
    return int(pos) if planned and planned[0].num == resume_ep else None
