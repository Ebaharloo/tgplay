"""tp - tg_playlist service package.

Each concern lives in one small class with an explicit interface so it can be
tested, reused and tuned independently. The agp/tg/tgp scripts are the CLIs
over this. See ../ARCHITECTURE.md.
"""
__all__ = ['log', 'config', 'http', 'chapters', 'episodes',
           'sources', 'cache', 'proxy', 'providers',
           'metadata', 'skip', 'prefetch', 'player', 'playlist', 'cli']