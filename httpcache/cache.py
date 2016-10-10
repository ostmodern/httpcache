# -*- coding: utf-8 -*-
"""
cache.py
~~~~~~~~

Contains the primary cache structure used in http-cache.
"""
from datetime import datetime

from .backends import RecentOrderedDict
from .utils import (
    build_date_header, expires_from_cache_control, parse_date_header,
    url_contains_query)


# RFC 2616 specifies that we can cache 200 OK, 203 Non Authoritative,
# 206 Partial Content, 300 Multiple Choices, 301 Moved Permanently and
# 410 Gone responses. We don't cache 206s at the moment because we
# don't handle Range and Content-Range headers.
CACHEABLE_RCS = (200, 203, 300, 301, 410)

# Cacheable verbs.
CACHEABLE_VERBS = ('GET', 'HEAD', 'OPTIONS')

# Some verbs MUST invalidate the resource in the cache, according to RFC 2616.
# If we send one of these, or any verb we don't recognise, invalidate the
# cache entry for that URL. As it happens, these are also the cacheable
# verbs. That works out well for us.
NON_INVALIDATING_VERBS = CACHEABLE_VERBS


class HTTPCache(object):
    """
    The HTTP Cache object. Manages caching of responses according to RFC 2616,
    adding necessary headers to HTTP request objects, and returning cached
    responses based on server responses.

    This object is not expected to be used by most users. It is exposed as part
    of the public API for users who feel the need for more control. This API
    may change in a minor version increase. Be warned.

    :param capacity: (Optional) The maximum capacity of the HTTP cache.
    """
    def __init__(self, capacity=50, cache=None):
        #: The maximum capacity of the HTTP cache. When this many cache entries
        #: end up in the cache, the oldest entries are removed.
        self.capacity = capacity

        if cache is None:
            cache = RecentOrderedDict()
        self._cache = cache

    def store(self, response):
        """
        Takes an HTTP response object and stores it in the cache according to
        RFC 2616. Returns a boolean value indicating whether the response was
        cached or not.

        :param response: Requests :class:`Response <Response>` object to cache.
        """

        # Define an internal utility function.
        def date_header_or_default(header_name, default, response):
            try:
                date_header = response.headers[header_name]
            except KeyError:
                value = default
            else:
                value = parse_date_header(date_header)
            return value

        if response.status_code not in CACHEABLE_RCS:
            return False

        if response.request.method not in CACHEABLE_VERBS:
            return False

        url = response.url
        now = datetime.utcnow()

        # Get the value of the 'Date' header, if it exists. If it doesn't, just
        # use now.
        creation = date_header_or_default('Date', now, response)

        # Get the value of the 'Cache-Control' header, if it exists.
        cc = response.headers.get('Cache-Control', None)
        if cc is not None:
            expiry = expires_from_cache_control(cc, now)

            # If the above returns None, we are explicitly instructed not to
            # cache this.
            if expiry is None:
                return False

        # Get the value of the 'Expires' header, if it exists, and if we don't
        # have anything from the 'Cache-Control' header.
        if cc is None:
            expiry = date_header_or_default('Expires', None, response)

        # If the expiry date is earlier or the same as the Date header, don't
        # cache the response at all.
        if expiry is not None and expiry <= creation:
            return False

        # Get content lanugage header
        cl = response.headers.get('Content-Language', None)

        # If there's a query portion of the url and it's a GET, don't cache
        # this unless explicitly instructed to.
        if expiry is None and response.request.method == 'GET':
            if url_contains_query(url):
                return False

        key = '{},{}'.format(url, cl)
        self._cache.set(url, {
            'response': response,
            'creation': creation,
            'expiry': expiry})

        self.__reduce_cache_count()

        return True

    def handle_304(self, response):
        """
        Given a 304 response, retrieves the cached entry. This unconditionally
        returns the cached entry, so it can be used when the 'intelligent'
        behaviour of retrieve() is not desired.

        Returns None if there is no entry in the cache.

        :param response: The 304 response to find the cached entry for.
            Should be a Requests :class:`Response <Response>`.
        """
        cached_response = self._cache.get(response.url, {})
        return cached_response.get('response')

    def retrieve(self, request):
        """
        Retrieves a cached response if possible.

        If there is a response that can be unconditionally returned (e.g. one
        that had a Cache-Control header set), that response is returned. If
        there is one that can be conditionally returned (if a 304 is returned),
        applies an If-Modified-Since header to the request and returns None.

        :param request:
            The Requests :class:`PreparedRequest <PreparedRequest>` object.
        """
        return_response = None
        url = request.url

        al = request.headers.get('Accept-Language', None)
        al = al.strip(', *')
        key = '{},{}'.format(url, al)

        cached_response = self._cache.get(key)
        if not cached_response:
            return

        if request.method not in NON_INVALIDATING_VERBS:
            self._cache.delete(url)
            return None

        if cached_response['expiry'] is None:
            # We have no explicit expiry time, so we weren't instructed to
            # cache. Add an 'If-Modified-Since' header.
            creation = cached_response['creation']
            header = build_date_header(creation)
            request.headers['If-Modified-Since'] = header
        else:
            # We have an explicit expiry time. If we're earlier than the expiry
            # time, return the response.
            now = datetime.utcnow()
            if now <= cached_response['expiry']:
                return_response = cached_response['response']
            else:
                self._cache.delete(url)

        return return_response

    def __reduce_cache_count(self):
        """
        Drops the number of entries in the cache to the capacity of the cache.

        Walks the backing RecentOrderedDict in order from oldest to youngest.
        Deletes cache entries that are either invalid or being speculatively
        cached until the number of cache entries drops to the capacity. If this
        leaves the cache above capacity, begins deleting the least-used cache
        entries that are still valid until the cache has space.
        """
        try:
            if len(self._cache) <= self.capacity:
                return
        except TypeError:
            # memcached does not like to return everything
            return

        to_delete = len(self._cache) - self.capacity
        keys = list(self._cache.keys())

        for key in keys:
            if self._cache.get(key, {}).get('expiry') is None:
                self._cache.delete(key)
                to_delete -= 1

            if to_delete == 0:
                return

        keys = list(self._cache.keys())

        for i in range(to_delete):
            self._cache.delete(keys[i])
        return
