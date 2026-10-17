import pytest
from scripts.tinyfish_client import TinyFishClient, public_url

class Response:
    def __init__(self,payload=None,status=200): self.payload,self.status_code=payload,status
    def json(self):
        if isinstance(self.payload,Exception): raise self.payload
        return self.payload

class Transport:
    def __init__(self,response): self.response,self.calls=response,[]
    def post(self,url,**kw): self.calls.append(('post',url,kw)); return self.response
    def get(self,url,**kw): self.calls.append(('get',url,kw)); return self.response

def client(monkeypatch,response,**kw):
    monkeypatch.setenv('TINYFISH_API_KEY','fixture-secret')
    t=Transport(response)
    return TinyFishClient(t,sleep=lambda _:None,validator=lambda u:public_url(u,resolve=False),**kw),t

def test_fetch_contract_partial_and_redirect(monkeypatch):
    a,b='https://a.example/event','https://b.example/event'
    c,t=client(monkeypatch,Response({'results':[{'url':a,'final_url':a+'/final','format':'html','text':'<p>Grüße</p>'},{'url':b,'format':'html','text':'bad'}],'errors':[{'url':b,'error':'quota'}]}))
    out=c.fetch([a,b]); assert list(out)==[a] and out[a]['final_url'].endswith('/final')
    method,url,kw=t.calls[0]
    assert (method,url)==('post','https://api.fetch.tinyfish.ai')
    assert kw['headers']=={'X-API-Key':'fixture-secret'} and not kw['allow_redirects']
    assert kw['json']=={'urls':[a,b],'format':'html','links':True,'ttl':0,'per_url_timeout_ms':45000}
    assert c.fetch_urls==2

def test_search_contract_candidates_only(monkeypatch):
    c,t=client(monkeypatch,Response({'results':[{'url':'https://a.example/event','snippet':'Free Available'}, {'url':'http://127.0.0.1/x'}]}))
    assert c.search('Grüße & Straße Berlin')==['https://a.example/event']
    method,url,kw=t.calls[0]
    assert method=='get' and url=='https://api.search.tinyfish.ai'
    assert kw['params']=={'query':'Grüße & Straße Berlin','location':'DE','language':'de'}
    assert c.search_queries==1

@pytest.mark.parametrize('status',[401,402,403,429])
def test_auth_and_rate_failure_closes_client(monkeypatch,status,capsys):
    c,t=client(monkeypatch,Response({},status))
    assert not c.fetch(['https://a.example/x'])
    assert not c.search('title') and len(t.calls)==1
    assert 'fixture-secret' not in capsys.readouterr().out

def test_malformed_budgets_batch_and_missing_key(monkeypatch):
    c,t=client(monkeypatch,Response(ValueError('fixture-secret')),max_fetch=2,max_search=1)
    for _ in range(5): c.fetch(['https://a.example/x']); c.search('x')
    assert (c.fetch_urls,c.search_queries,len(t.calls))==(2,1,3)
    with pytest.raises(ValueError): c.fetch(['https://a.example/x']*11)
    monkeypatch.delenv('TINYFISH_API_KEY')
    empty=TinyFishClient(t)
    assert not empty.fetch(['https://a.example/x']) and not empty.search('x')
    assert empty.diagnostic=='tinyfish_skipped_no_key' and len(t.calls)==3

@pytest.mark.parametrize('url',['http://localhost/','https://127.0.0.1/x','http://169.254.169.254/','file:///tmp/x','https://u:p@a.example/x','https://a.example/?ticket_token=x'])
def test_private_or_secret_urls_rejected(url): assert not public_url(url,resolve=False)

def test_private_final_url_and_markdown_rejected(monkeypatch):
    a='https://a.example/x'
    for item in [dict(url=a,final_url='http://127.0.0.1/',format='html',text='x'),dict(url=a,format='markdown',text='x')]:
        c,t=client(monkeypatch,Response({'results':[item],'errors':[]})); assert not c.fetch([a])

def test_throttle_applies_between_search_and_fetch(monkeypatch):
    monkeypatch.setenv('TINYFISH_API_KEY','fixture-secret')
    sleeps=[];transport=Transport(Response({'results':[],'errors':[]}))
    c=TinyFishClient(transport,sleep=sleeps.append,clock=lambda:1,validator=lambda _:True)
    c.search('show Berlin');c.fetch(['https://a.example/show'])
    assert sleeps==[1]

@pytest.mark.parametrize('payload',[[],{'results':'bad'},{'results':None},{'errors':17}])
def test_malformed_payload_types_fail_closed(monkeypatch,payload):
    c,t=client(monkeypatch,Response(payload))
    assert c.fetch(['https://a.example/show'])=={}
    assert c.diagnostic=='tinyfish_failed'

def test_live_fetch_timeout_and_402_diagnostics_are_safe(monkeypatch):
    c,t=client(monkeypatch,Response({'error':{'code':'INSUFFICIENT_CREDITS','message':'secret must not be logged'}},402))
    assert not c.fetch(['https://a.example/show?tracking=value'])
    assert t.calls[0][2]['timeout']==(8,150)
    assert c.disabled and c.diagnostic=='tinyfish_allowance_exhausted'
    assert not c.search('x')
    report=str(c.diagnostics)
    assert 'fixture-secret' not in report and 'tracking' not in report
    assert c.diagnostics[0]['http_status']==402

def test_run_deadline_reserves_full_fetch_timeout(monkeypatch):
    c,t=client(monkeypatch,Response({'results':[],'errors':[]}),deadline=100,clock=lambda:0)
    assert not c.fetch(['https://a.example/show']) and c.fetch_urls==0 and not t.calls

def test_documented_per_url_errors_have_whitelisted_diagnostics(monkeypatch):
    payload={'results':[], 'errors':[{'url':'https://a.example/show?x=private','error':'target_http_error','status':403},{'url':'https://b.example/show','error':'bot_blocked'},{'url':'https://b.example/show','error':'text-with-private-token'}]}
    c,t=client(monkeypatch,Response(payload))
    assert not c.fetch(['https://a.example/show'])
    assert c.diagnostics[0]['schema_valid']
    assert c.diagnostics[0]['error_codes']==['bot_blocked','target_http_error','unrecognized_error']
    assert 'private' not in str(c.diagnostics)
