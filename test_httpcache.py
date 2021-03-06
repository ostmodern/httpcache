# -*- coding: utf-8 -*-
"""
test-httpcache.py
~~~~~~~~~~~~~~~~~

Test cases for httpcache.
"""
from datetime import datetime, timedelta

import httpcache
from httpcache.backends import RecentOrderedDict
import mockcache
import pytest
import requests

mc = mockcache.Client(["127.0.0.1:11211"])


@pytest.mark.parametrize("cache", [
    RecentOrderedDict(), None, mc
])
class TestHTTPCache(object):
    """
    Assorted tests of the HTTPCache object.
    """

    def test_can_store_responses(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse()
        cache = httpcache.HTTPCache(cache=cache)

        rc = cache.store(resp, req)
        assert rc

    def test_store_responses_correctly(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse()
        cache = httpcache.HTTPCache()

        cache.store(resp, req)
        key = cache.make_key(resp.url, '')
        assert cache._cache.get(key)

    def test_dont_store_non_200_responses(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(status_code=403)
        cache = httpcache.HTTPCache()

        rc = cache.store(resp, req)
        assert not rc

    def test_can_retrieve_responses(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse()
        cache = httpcache.HTTPCache()

        cache.store(resp, req)
        cached_resp = cache.handle_304(resp, req)

        assert resp is cached_resp

    def test_can_extract_creation_date_from_response_RFC_1123(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(
            headers={'Date': 'Sun, 06 Nov 1994 08:49:37 GMT'})
        cache = httpcache.HTTPCache()
        dt = datetime(1994, 11, 6, 8, 49, 37)

        cache.store(resp, req)
        key = cache.make_key(req.url, '')
        assert cache._cache[key]['creation'] == dt

    def test_can_extract_creation_date_from_response_RFC_850(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(
            headers={'Date': 'Sunday, 06-Nov-94 08:49:37 GMT'})
        cache = httpcache.HTTPCache()
        dt = datetime(1994, 11, 6, 8, 49, 37)

        cache.store(resp, req)
        key = cache.make_key(resp.url, '')
        assert cache._cache[key]['creation'] == dt

    def test_can_add_if_modified_since_header(self, cache):
        date = 'Sun, 06 Nov 1994 08:49:37 GMT'
        resp = MockRequestsResponse(headers={'Date': date})
        cache = httpcache.HTTPCache()
        initial_req = MockRequestsPreparedRequest()
        req = MockRequestsPreparedRequest()

        cache.store(resp, initial_req)
        cache.retrieve(req)

        assert req.headers['If-Modified-Since'] == date

    def test_we_respect_the_expires_header(self, cache):
        resp = MockRequestsResponse(headers={
            'Date': 'Sun, 06 Nov 1994 08:49:37 GMT',
            'Expires': 'Sun, 06 Nov 2034 08:49:37 GMT'})
        cache = httpcache.HTTPCache()
        req = MockRequestsPreparedRequest()

        cache.store(resp, req)
        cached_resp = cache.retrieve(req)

        assert cached_resp is resp

    def test_expires_headers_invalidate(self, cache):
        req = MockRequestsPreparedRequest()
        resp1 = MockRequestsResponse(headers={
            'Date': 'Sun, 06 Nov 1994 08:49:37 GMT',
            'Expires': 'Sun, 06 Nov 1994 08:49:37 GMT'})
        resp2 = MockRequestsResponse(headers={
            'Date': 'Sun, 06 Nov 1994 08:49:37 GMT',
            'Expires': 'Sun, 06 Nov 1994 08:00:00 GMT'})
        cache = httpcache.HTTPCache()

        assert not cache.store(resp1, req)
        assert not cache.store(resp2, req)

    def test_expiry_of_expires(self, cache):
        resp = MockRequestsResponse(headers={
            'Date': 'Sun, 06 Nov 1994 08:49:37 GMT',
            'Expires': 'Sun, 04 Nov 2012 08:49:37 GMT'})
        cache = httpcache.HTTPCache()
        req = MockRequestsPreparedRequest()
        earlier = timedelta(seconds=-60)
        much_earlier = timedelta(days=-1)

        key = cache.make_key(resp.url, '')
        cache._cache[key] = {
            'response': resp,
            'creation': datetime.utcnow() + much_earlier,
            'expiry': datetime.utcnow() + earlier}

        cached_resp = cache.retrieve(req)

        assert cached_resp is None
        assert len(cache._cache) == 0

    def test_we_respect_cache_control_max_age(self, cache):
        resp = MockRequestsResponse(headers={'Cache-Control': 'max-age=3600'})
        cache = httpcache.HTTPCache()
        req = MockRequestsPreparedRequest()
        assert cache.store(resp, req)

        cached_resp = cache.retrieve(req)
        assert cached_resp is resp

    def test_we_respect_no_cache(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(headers={'Cache-Control': 'no-cache'})
        cache = httpcache.HTTPCache()

        assert not cache.store(resp, req)

    def test_we_respect_no_store(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(headers={'Cache-Control': 'no-store'})
        cache = httpcache.HTTPCache()

        assert not cache.store(resp, req)

    def test_we_respect_max_age_zero(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(headers={'Cache-Control': 'max-age=0'})
        cache = httpcache.HTTPCache()

        assert not cache.store(resp, req)

    def test_cache_is_correctly_ordered(self, cache):
        resp1 = MockRequestsResponse()
        resp2 = MockRequestsResponse()
        resp2.url += 'abc'
        resp3 = MockRequestsResponse()
        resp3.url += 'def'
        cache = httpcache.HTTPCache()
        req = MockRequestsPreparedRequest()

        cache.store(resp1, req)
        cache.store(resp2, req)
        cache.store(resp3, req)
        cache.store(resp2, req)

        cachelist = list(cache._cache.items())
        assert cachelist[0][1]['response'] is resp1
        assert cachelist[1][1]['response'] is resp3
        assert cachelist[2][1]['response'] is resp2

        cache.handle_304(req, req)

        cachelist = list(cache._cache.items())
        assert cachelist[0][1]['response'] is resp3
        assert cachelist[1][1]['response'] is resp2
        assert cachelist[2][1]['response'] is resp1

    def test_do_not_cache_query_strings(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse()
        resp.url += '?a=b'
        cache = httpcache.HTTPCache()

        assert not cache.store(resp, req)

    def test_cache_query_string_if_explicitly_asked(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse(headers={'Cache-Control': 'max-age=3600'})
        resp.url += '?a=b'
        req.url = resp.url
        cache = httpcache.HTTPCache()

        assert cache.store(resp, req)

        cached_resp = cache.handle_304(resp, req)
        assert cached_resp is resp

    def test_we_dont_cache_some_methods(self, cache):
        req = MockRequestsPreparedRequest()
        resp = MockRequestsResponse()
        cache = httpcache.HTTPCache()

        methods = ('POST', 'PUT', 'DELETE', 'CONNECT', 'PATCH')

        for method in methods:
            resp.request.method = method
            assert not cache.store(resp, req)

    def test_we_invalidate_for_some_methods(self, cache):
        resp = MockRequestsResponse()
        cache = httpcache.HTTPCache()
        req = MockRequestsPreparedRequest()

        methods = ('POST', 'PUT', 'DELETE', 'CONNECT', 'PATCH')

        for method in methods:
            assert cache.store(resp, req)
            req.method = method
            assert cache.retrieve(req) is None
            assert len(cache._cache) == 0

    def test_cache_has_fixed_capacity(self, cache):
        req = MockRequestsPreparedRequest()
        cache = httpcache.HTTPCache(capacity=5)

        for i in range(10):
            resp = MockRequestsResponse()
            resp.url += str(i)
            assert cache.store(resp, req)

        assert len(cache._cache) == 5

    def test_cache_preferentially_deletes_speculative_caching(self, cache):
        req = MockRequestsPreparedRequest()
        cache = httpcache.HTTPCache(capacity=5)

        for i in range(4):
            resp = MockRequestsResponse(
                headers={'Cache-Control': 'max-age=3600'})
            resp.url += str(i)
            assert cache.store(resp, req)

        test_resp = MockRequestsResponse()
        test_resp.url += 'other'
        assert cache.store(test_resp, req)

        resp = MockRequestsResponse(
            headers={'Cache-Control': 'max-age=3600'})
        assert cache.store(resp, req)

        assert len(cache._cache) == 5
        assert test_resp not in [
            cache._cache[key] for key in list(cache._cache.keys())]

    def test_cache_will_delete_expiry_caches_if_necessary(self, cache):
        req = MockRequestsPreparedRequest()
        cache = httpcache.HTTPCache(capacity=5)
        test_resp = MockRequestsResponse(
            headers={'Cache-Control': 'max-age=3600'})
        assert cache.store(test_resp, req)

        for i in range(5):
            resp = MockRequestsResponse(
                headers={'Cache-Control': 'max-age=3600'})
            resp.url += str(i)
            assert cache.store(resp, req)

        assert len(cache._cache) == 5
        assert test_resp not in [
            cache._cache[key] for key in list(cache._cache.keys())]


class TestCachingHTTPAdapter(object):
    """
    Tests for the caching HTTP adapter.
    """
    def test_we_respect_304(self):
        s = requests.Session()
        s.mount('http://', httpcache.CachingHTTPAdapter())

        r1 = s.get('http://httpbin.org/cache')
        r2 = s.get('http://httpbin.org/cache')

        assert r1 is r2

    def test_we_respect_cache_control(self):
        s = requests.Session()
        s.mount('http://', httpcache.CachingHTTPAdapter())

        r1 = s.get('http://httpbin.org/response-headers',
                   params={'Cache-Control': 'max-age=3600'})
        r2 = s.get('http://httpbin.org/response-headers',
                   params={'Cache-Control': 'max-age=3600'})

        assert r1 is r2

    def test_we_respect_expires(self):
        s = requests.Session()
        s.mount('http://', httpcache.CachingHTTPAdapter())

        r1 = s.get('http://httpbin.org/response-headers',
                   params={'Expires': 'Sun, 06 Nov 2034 08:49:37 GMT'})
        r2 = s.get('http://httpbin.org/response-headers',
                   params={'Expires': 'Sun, 06 Nov 2034 08:49:37 GMT'})

        assert r1 is r2

    def test_we_respect_cache_control_2(self):
        s = requests.Session()
        s.mount('http://', httpcache.CachingHTTPAdapter())

        r1 = s.get('http://httpbin.org/response-headers',
                   params={'Cache-Control': 'no-cache'})
        r2 = s.get('http://httpbin.org/response-headers',
                   params={'Cache-Control': 'no-cache'})

        assert r1 is not r2


class MockRequestsResponse(object):
    """
    A specially-designed Mock object that emulates the behaviour of the
    post-v1.0.0 Requests Response object. For use with testing HTTPCache.
    """
    def __init__(self,
                 status_code=200,
                 headers=None,
                 body='',
                 url='http://www.test.com/'):
        self.status_code = status_code
        if not headers:
            headers = {}
        self.headers = headers
        self.body = body
        self.url = url
        self.request = MockRequestsPreparedRequest(url=self.url)


class MockRequestsPreparedRequest(object):
    """
    A specially-designed Mock object that emulates the behaviour of the
    post-v1.0.0 Requests PreparedRequest object. For use with testing
    HTTPCache.
    """
    def __init__(self,
                 method='GET',
                 headers=None,
                 body='',
                 url='http://www.test.com/'):
        self.method = method
        if not headers:
            headers = {}
        self.headers = headers
        self.body = body
        self.url = url
