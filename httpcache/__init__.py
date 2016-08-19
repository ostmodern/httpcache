# -*- coding: utf-8 -*-
"""
__init__.py
~~~~~~~~~~~

Defines the public API to the httpcache module.
"""
from .adapter import CachingHTTPAdapter
from .cache import HTTPCache


__version__ = '0.1.4'


__all__ = [HTTPCache, CachingHTTPAdapter]
