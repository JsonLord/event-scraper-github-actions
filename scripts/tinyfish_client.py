"""Optional free Fetch/Search only. No paid endpoints, cookies or URL secrets."""
from __future__ import annotations
import ipaddress
import os
import socket
import time
from urllib.parse import urlsplit, parse_qsl
import requests


def public_url(url, resolve=True):
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
            return False
        host = p.hostname.lower()
        if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')) or '.' not in host:
            return False
        if any(any(word in k.lower() for word in ('token', 'secret', 'session', 'password', 'auth', 'cookie')) for k,v in parse_qsl(p.query)):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            if not resolve:
                return True
            addresses = socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    except (ValueError, OSError):
        return False


class TinyFishClient:
    def __init__(self, transport=None, max_fetch=30, max_search=12, sleep=time.sleep, clock=time.monotonic, validator=public_url):
        self.transport = transport or requests
        from dotenv import load_dotenv
        load_dotenv(override=False)
        self.key = os.environ.get('TINYFISH_API_KEY', '')
        self.enabled = bool(self.key) and os.environ.get('TINYFISH_ENABLED', 'true').lower() == 'true'
        self.max_fetch, self.max_search = min(max_fetch, 30), min(max_search, 12)
        self.fetch_urls = self.search_queries = 0
        self.disabled = False
        self.diagnostic = 'ready' if self.enabled else 'tinyfish_skipped_no_key'
        self.sleep, self.clock, self.validator = sleep, clock, validator
        self.last_call = None

    def _call(self, method, endpoint, **kwargs):
        if self.last_call is not None:
            self.sleep(max(0, 1 - (self.clock() - self.last_call)))
        self.last_call = self.clock()
        try:
            response = getattr(self.transport, method)(endpoint, headers={'X-API-Key': self.key}, timeout=(8,12), allow_redirects=False, **kwargs)
            if response.status_code in (401,403,429):
                self.disabled = True
            if response.status_code != 200:
                self.diagnostic = 'tinyfish_http_' + str(response.status_code)
                return {}
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('object required')
            for field in ('results','errors'):
                if field in payload and not isinstance(payload[field],list):
                    raise ValueError('array required')
            self.diagnostic = 'ok'
            return payload
        except (requests.exceptions.RequestException, ValueError, TypeError):
            # Exceptions/responses may contain the key: never log their content.
            self.diagnostic = 'tinyfish_failed'
            return {}

    def fetch(self, urls):
        if len(urls) > 10:
            raise ValueError('Fetch supports at most 10 URLs')
        if not self.enabled or self.disabled or os.environ.get('TINYFISH_FETCH_ENABLED', 'true').lower() != 'true':
            return {}
        targets = [u for u in dict.fromkeys(urls) if self.validator(u)][:max(0,self.max_fetch-self.fetch_urls)]
        if not targets:
            return {}
        self.fetch_urls += len(targets)  # Failed URLs consume quota too.
        payload = self._call('post', 'https://api.fetch.tinyfish.ai', json={'urls': targets, 'format':'html', 'links':True})
        errors = {x.get('url') for x in (payload.get('errors') or []) if isinstance(x, dict)}
        out = {}
        for item in payload.get('results', []) or []:
            if not isinstance(item, dict):
                continue
            requested = item.get('url')
            final = item.get('final_url') or requested
            if requested not in targets or requested in errors or not self.validator(final):
                continue
            if item.get('format') != 'html' or not isinstance(item.get('text'), str):
                continue
            if len(item['text'].encode()) > 1_500_000:
                continue
            out[requested] = dict(url=requested, final_url=final, html=item['text'])
        return out

    def search(self, query):
        if not self.enabled or self.disabled or os.environ.get('TINYFISH_SEARCH_ENABLED', 'true').lower() != 'true' or self.search_queries >= self.max_search:
            return []
        self.search_queries += 1
        payload = self._call('get', 'https://api.search.tinyfish.ai', params={'query':query, 'location':'DE', 'language':'de'})
        return [r['url'] for r in payload.get('results', []) or [] if isinstance(r,dict) and self.validator(r.get('url',''))]
