"""Optional Camoufox/Firefox renderer for permitted Raus listing requests only."""
import os,subprocess,sys,time
from urllib.parse import urlsplit


def render_listing(url,http,deadline,launch=None):
    from scripts.qualify_restored_branch import AGENT,origin,public
    from scripts.generic_event_scraper import is_bot_challenge
    diagnostic=dict(engine='camoufox',url=url,navigations=0,requests=0,blocked_requests=0,max_requests=20,outcome='not_attempted')
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='rausgegangen.de' or p.path!='/en/berlin/eventsbydate/' or p.fragment or p.username or p.password:
        diagnostic['outcome']='source_not_allowlisted';return None,diagnostic
    policy=http.robots.get(origin(url))
    if policy is None or not policy.can_fetch(AGENT,url):
        diagnostic['outcome']='robots_denied_or_unknown';return None,diagnostic
    if time.monotonic()+180>deadline:
        diagnostic['outcome']='deadline';return None,diagnostic
    try:
        if launch is None:
            # Install/fetch lazily, after permission, never in response to a
            # denied robots policy. Suppress downloader output/signed URLs.
            from camoufox.sync_api import Camoufox
            subprocess.run([sys.executable,'-m','camoufox','fetch'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120,check=True)
            launch=Camoufox
        options=dict(headless=True,humanize=False,os='linux',geoip=False)
        # Reuse only the managed session transport, never a circumvention proxy.
        proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        if proxy:options['proxy']={'server':proxy}
        with launch(**options) as browser:
            context=browser.new_context(locale='en-GB',timezone_id='Europe/Berlin',ignore_https_errors=False)
            page=context.new_page()
            def route_request(route,request):
                q=urlsplit(request.url)
                denied=(diagnostic['requests']>=20 or time.monotonic()+5>deadline or request.method!='GET' or
                        q.scheme!='https' or q.hostname!='rausgegangen.de' or
                        request.resource_type in ('image','media','font') or
                        any(part in q.path.split('/') for part in ('login','report','captcha','checkout')) or
                        not public(request.url) or not policy.can_fetch(AGENT,request.url))
                if denied:diagnostic['blocked_requests']+=1;route.abort();return
                diagnostic['requests']+=1;route.continue_()
            page.route('**/*',route_request)
            diagnostic['navigations']=1
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            if response is None or response.status>=400:
                diagnostic.update(outcome='browser_http_failure',http_status=response.status if response else None);return None,diagnostic
            # No clicks, login, CAPTCHA interaction, script injection or solver.
            html=page.content()
            if is_bot_challenge(html):diagnostic['outcome']='challenge';return None,diagnostic
            page.wait_for_timeout(1500)
            html=page.content();final=page.url
            q=urlsplit(final)
            if q.scheme!='https' or q.hostname!='rausgegangen.de' or q.path!='/en/berlin/eventsbydate/' or not policy.can_fetch(AGENT,final):
                diagnostic['outcome']='destination_rejected';return None,diagnostic
            if len(html.encode())>1_500_000 or is_bot_challenge(html):
                diagnostic['outcome']='oversize_or_challenge';return None,diagnostic
            diagnostic.update(outcome='received',http_status=response.status,response_bytes=len(html.encode()))
            return (final,html),diagnostic
    except ImportError:
        diagnostic['outcome']='camoufox_not_installed'
    except subprocess.TimeoutExpired:
        diagnostic['outcome']='camoufox_install_timeout'
    except subprocess.CalledProcessError:
        diagnostic['outcome']='camoufox_install_failed'
    except Exception as exc:
        # Browser exceptions can echo proxy URLs; persist the type only.
        diagnostic.update(outcome='camoufox_failed',error_type=type(exc).__name__)
    return None,diagnostic
