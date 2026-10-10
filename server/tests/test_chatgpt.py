"""Sign-in tests use a locally generated RSA key and fake OAuth/Responses services."""
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from urllib.parse import parse_qs, urlsplit, urlencode
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from brain.chatgpt_auth import (AuthManager, CredentialStore, ChatGPTError, ISSUER,
                                RESOURCE, PLAN_SCOPE, validate_callback, protect)
from brain.chatgpt_brain import ChatGPTBrain, response_input

class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        cls.jwk.update(kid='test-key', use='sig')
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client_id = 'oaiapp_test123'
        self.subject = 'test-account'
        self.nonce = None
        self.sent = []
        self.scope = PLAN_SCOPE + ' offline_access openid profile email resource.invoke'
        self.refresh_count = 0
        self.remote_fail = False
        client = httpx.Client(transport=httpx.MockTransport(self.transport))
        store = CredentialStore(Path(self.temp.name),codec=lambda data,decrypt=False:data)
        self.auth = AuthManager(self.temp.name,http=client,store=store)
    def tearDown(self):
        self.auth.http.close(); self.temp.cleanup()
    def id_token(self, **updates):
        claims = {'iss':ISSUER,'aud':self.client_id,'sub':self.subject,
                  'email':'test@example.invalid','iat':int(time.time()),
                  'exp':int(time.time())+3600,'nonce':self.nonce}
        claims.update(updates)
        return jwt.encode(claims,self.private,algorithm='RS256',headers={'kid':'test-key'})
    def transport(self, request):
        self.sent.append(request)
        if request.url.path.endswith('openid-configuration'):
            return httpx.Response(200,json={'issuer':ISSUER,'jwks_uri':ISSUER+'/jwks',
                                           'revocation_endpoint':ISSUER+'/revoke'})
        if request.url.path == '/jwks': return httpx.Response(200,json={'keys':[self.jwk]})
        if request.url.path.endswith('/oauth/token'):
            values = parse_qs(request.content.decode())
            if values['grant_type'][0]=='refresh_token':
                self.refresh_count += 1
                return httpx.Response(200,json={'access_token':'rotated-token','refresh_token':'rotated-refresh',
                    'expires_in':3600,'token_type':'Bearer','scope':self.scope})
            self.assertEqual(values['client_id'],[self.client_id])
            self.assertNotEqual(values['client_id'],['dynamic_agent_client'])
            return httpx.Response(200,json={'id_token':self.id_token(),'access_token':'fake-access',
                'refresh_token':'fake-refresh','token_type':'Bearer','scope':self.scope,'expires_in':3600})
        if request.url.path == '/v1/models':
            self.assertEqual(request.headers['Authorization'],'Bearer fake-access')
            return httpx.Response(200,json={'models':[{'slug':'test-vision','display_name':'Test vision','visibility':'list'},
                                                    {'slug':'hidden','visibility':'hide'}]})
        if request.url.path == '/revoke': return httpx.Response(503 if self.remote_fail else 200)
        return httpx.Response(404)
    def login(self):
        attempt = self.auth.prepare_attempt(); self.nonce = attempt['nonce']
        query = urlencode({'code':'code','client_id':self.client_id,'state':attempt['state']})
        enabled = self.auth.complete_attempt(attempt,query,'http://127.0.0.1:9999/auth/callback')
        return enabled
    def test_pkce_host_and_first_registration(self):
        attempt = self.auth.prepare_attempt()
        params = parse_qs(urlsplit(self.auth.authorization_url(attempt,'http://127.0.0.1:9/auth/callback')).query)
        self.assertEqual(params['client_id'],['dynamic_agent_client'])
        self.assertEqual(params['agent_name_hint'],['Virtual Rocky'])
        import hashlib
        expected = base64.urlsafe_b64encode(hashlib.sha256(attempt['verifier'].encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['code_challenge'],[expected])
        self.assertEqual(attempt['host_id'],self.auth.prepare_attempt()['host_id'])
        self.assertNotEqual(attempt['state'],self.auth.prepare_attempt()['state'])
    def test_callback_rejects_wrong_state_missing_or_changed_client(self):
        for query, issued in [('code=x&client_id=a&state=bad',None),('code=x&state=good',None),
                              ('code=x&client_id=b&state=good','a'),('code=x&client_id=dynamic_agent_client&state=good',None),
                              ('code=x&client_id=a&state=good&state=good',None)]:
            with self.assertRaises(ChatGPTError): validate_callback(query,'good',issued)
    def test_declined_callback(self):
        with self.assertRaisesRegex(ChatGPTError,'declined'):
            validate_callback('state=good&error=access_denied','good')
    def test_verified_login_catalog_and_returning_client(self):
        self.assertTrue(self.login())
        key = self.auth.selected()['key']
        self.assertEqual(self.auth.models(True),[{'slug':'test-vision','display_name':'Test vision'}])
        self.assertEqual(self.auth.model(),'test-vision')
        attempt = self.auth.prepare_attempt(key)
        params = parse_qs(urlsplit(self.auth.authorization_url(attempt,'http://127.0.0.1:9/auth/callback')).query)
        self.assertEqual(params['client_id'],[self.client_id])
        self.assertNotIn('agent_name_hint',params)
        self.assertIn('id_token_hint',params)
        self.assertNotIn('access_token',json.dumps(self.auth.accounts()))
    def test_signature_issuer_audience_nonce_expiry_and_subject_checked(self):
        self.nonce = 'good'
        for updates in ({'iss':'https://evil.invalid'},{'aud':'wrong'},{'nonce':'wrong'},
                        {'exp':int(time.time())-10},{'sub':'someone-else'}):
            with self.assertRaises(ChatGPTError):
                self.auth.verify_identity(self.id_token(**updates),self.client_id,'good',self.subject)
        wrong = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        token = jwt.encode({'iss':ISSUER,'aud':self.client_id,'sub':self.subject,
                            'iat':int(time.time()),'exp':int(time.time())+100},wrong,algorithm='RS256',headers={'kid':'test-key'})
        with self.assertRaises(ChatGPTError): self.auth.verify_identity(token,self.client_id)
    def test_identity_without_plan_permission_cannot_infer(self):
        self.scope='openid profile email'
        self.assertFalse(self.login())
        with self.assertRaisesRegex(ChatGPTError,'not enabled'): self.auth.token()
    def test_refresh_rotates_once_and_persists(self):
        self.login()
        with self.auth.store.locked():
            state=self.auth.store.read(); state['accounts'][state['active']]['expires_at']=0; self.auth.store.write(state)
        self.assertEqual(self.auth.token(),'rotated-token')
        self.assertEqual(self.auth.token(),'rotated-token')
        self.assertEqual(self.refresh_count,1)
        state=self.auth.store.read(); self.assertEqual(state['accounts'][state['active']]['refresh_token'],'rotated-refresh')
    def test_logout_revokes_and_preserves_registration_host(self):
        self.login(); key=self.auth.selected()['key']; host=self.auth.prepare_attempt()['host_id']
        self.assertTrue(self.auth.sign_out())
        self.assertFalse(self.auth.selected()['signed_in'])
        self.assertEqual(self.auth.prepare_attempt()['host_id'],host)
        attempt=self.auth.prepare_attempt(key)
        self.assertEqual(attempt['account']['client_id'],self.client_id)
        self.assertNotIn('id_token',attempt['account'])
        with self.assertRaises(ChatGPTError): self.auth.token()
    def test_offline_logout_clears_local_secrets(self):
        self.login(); self.remote_fail=True
        self.assertFalse(self.auth.sign_out())
        self.assertNotIn('fake-access',self.auth.store.path.read_text())
    def test_two_registrations_same_email_stay_separate(self):
        self.login(); first=self.auth.selected()['key']
        self.client_id='oaiapp_other456'; self.login()
        self.assertEqual(len(self.auth.accounts()),2)
        self.auth.select_account(first)
        self.assertEqual(self.auth.selected()['key'],first)
    def test_tampered_storage_does_not_get_overwritten(self):
        self.auth.store.path.write_bytes(b'broken')
        with self.assertRaises(ChatGPTError): self.auth.accounts()
        self.assertEqual(self.auth.store.path.read_bytes(),b'broken')
    def test_loopback_signin_rejects_unsolicited_callback_and_completes(self):
        threads = []
        responses = []
        def browser(url):
            params = parse_qs(urlsplit(url).query)
            self.nonce = params['nonce'][0]
            redirect = params['redirect_uri'][0]
            def callback():
                with httpx.Client(trust_env=False) as client:
                    responses.append(client.get(redirect,params={'state':'wrong','code':'attack','client_id':self.client_id}).status_code)
                    responses.append(client.get(redirect,params={'state':params['state'][0],'code':'test-code','client_id':self.client_id}).status_code)
            thread = threading.Thread(target=callback); thread.start(); threads.append(thread)
            return True
        self.assertTrue(self.auth.sign_in(browser=browser,timeout=5))
        for thread in threads: thread.join(timeout=2)
        self.assertEqual(responses,[400,200])
        self.assertTrue(self.auth.selected()['signed_in'])

    def test_os_protected_store_roundtrip(self):
        store=CredentialStore(Path(self.temp.name)/'protected')
        with store.locked():
            state=store.read(); state['secret']='never-plaintext'; store.write(state)
            self.assertEqual(store.read()['secret'],'never-plaintext')
            if os.name=='nt': self.assertNotIn(b'never-plaintext',store.path.read_bytes())

class ResponsesTests(unittest.TestCase):
    def auth(self):
        return NS(selected=lambda:{'key':'account'},token=lambda key=None:'fake-token',model=lambda key=None:'test-model')
    def brain(self, rounds, actions=None):
        self.requests=[]; self.closed=[]
        outer=self
        class Stream:
            def __init__(self, events): self.events=events
            def __enter__(self): return self
            def __exit__(self,*args): outer.closed.append(True)
            def __iter__(self): return iter(self.events)
        class Client:
            def __init__(self, **kwargs):
                outer.assertEqual(kwargs['base_url'],RESOURCE)
                outer.assertEqual(kwargs['api_key'],'fake-token')
                self.responses=NS(create=self.create)
            def create(self, **kwargs):
                outer.requests.append(kwargs); return Stream(rounds.pop(0))
            def __enter__(self): return self
            def __exit__(self,*args): pass
        return ChatGPTBrain(self.auth(),actions=actions,client_factory=Client)
    def delta(self,text): return NS(type='response.output_text.delta',delta=text)
    def completed(self): return NS(type='response.completed')
    def test_sentence_stream_images_and_permitted_request_shape(self):
        brain=self.brain([[self.delta('[happy] Hello. '),self.delta('Camera works.'),self.completed()]])
        emotion=[]
        self.assertEqual(list(brain.reply('what do you see',b'jpeg',on_emotion=emotion.append)),['Hello.','Camera works.'])
        request=self.requests[0]
        self.assertFalse(request['store']); self.assertTrue(request['stream'])
        self.assertIn('instructions',request)
        self.assertNotIn('max_output_tokens',request)
        self.assertNotIn('temperature',request)
        self.assertNotIn('previous_response_id',request)
        self.assertTrue(any(p['type']=='input_image' for m in request['input'] for p in m.get('content',[]) if isinstance(p,dict)))
        self.assertIn('happy',emotion)
    def test_missing_terminal_event_forgets_failed_turn(self):
        brain=self.brain([[self.delta('Some text.')]])
        result=list(brain.reply('hello'))
        self.assertIn('ended before',result[-1]); self.assertEqual(brain.history,[])
    def test_usage_failure_after_sentence_limit_is_not_silently_ignored(self):
        failure=NS(type='response.failed',response=NS(error=NS(code='subscription_sharing_usage_limit_exceeded')))
        brain=self.brain([[self.delta('[neutral] One. Two. Three. Four. '),failure]])
        result=list(brain.reply('hello'))
        self.assertEqual(result[:3],['One.','Two.','Three.'])
        self.assertIn('usage limit',result[-1]); self.assertEqual(brain.history,[])
        self.assertTrue(self.closed)
    def test_tool_result_and_fresh_image_are_replayed(self):
        call=NS(type='function_call',call_id='call-1',name='look',arguments='{}',namespace='rocky')
        brain=self.brain([[NS(type='response.output_item.done',item=call),self.completed()],
                          [self.delta('[happy] I see a desk.'),self.completed()]],
                         {'look':lambda args:('Fixed webcam view.',b'fresh')})
        self.assertEqual(list(brain.reply('look')),['I see a desk.'])
        self.assertEqual(self.requests[0]['tools'][0]['type'],'namespace')
        replay=self.requests[1]['input']
        self.assertTrue(any(i.get('type')=='function_call_output' and i['call_id']=='call-1' for i in replay))
        self.assertTrue(any(i.get('namespace')=='rocky' for i in replay))
    def test_signed_out_has_actionable_message(self):
        auth=self.auth()
        def fail(*args): raise ChatGPTError('Choose Continue with ChatGPT first.')
        auth.token=fail
        brain=ChatGPTBrain(auth)
        self.assertIn('Continue with ChatGPT',list(brain.reply('hello'))[0])
        self.assertEqual(brain.history,[])
    def test_desktop_tool_image_reaches_provider_and_is_removed(self):
        call=NS(type='function_call',call_id='screen-1',name='look_at_screen',
                arguments='{"monitor":2}',namespace='rocky')
        selected=[]
        def capture(args):
            selected.append(args['monitor'])
            return 'Fresh desktop screenshot: monitor 2.', b'fresh-screen'
        brain=self.brain([[NS(type='response.output_item.done',item=call),self.completed()],
                          [self.delta('Monitor two shows an error.'),self.completed()]],
                         {'look_at_screen':capture})
        self.assertEqual(list(brain.reply('What is on monitor two?')), ['Monitor two shows an error.'])
        self.assertEqual(selected,[2])
        replay=self.requests[1]['input']
        self.assertTrue(any(p.get('type')=='input_image' for m in replay
                            for p in m.get('content',[]) if isinstance(p,dict)))
        self.assertIn('Fresh desktop screenshot',json.dumps(replay))
        self.assertNotIn('data:image',json.dumps(brain.history))
    def test_temporal_images_are_replayed_in_order_and_removed(self):
        call=NS(type='function_call',call_id='temporal-1',name='look_at_screen',arguments='{}',namespace='rocky')
        images=[{'text':'6 seconds ago','jpeg':b'past'}, {'text':'Current fresh','jpeg':b'now'}]
        brain=self.brain([[NS(type='response.output_item.done',item=call),self.completed()],
                          [self.delta('Your health visibly decreased.'),self.completed()]],
                         {'look_at_screen':lambda args:('Temporal observations',images)})
        list(brain.reply('What happened in my game?'))
        replay=self.requests[1]['input']
        parts=[p for message in replay for p in message.get('content',[]) if isinstance(p,dict)]
        self.assertEqual(sum(p.get('type')=='input_image' for p in parts),2)
        text=' '.join(p.get('text','') for p in parts)
        self.assertLess(text.index('6 seconds ago'),text.index('Current fresh'))
        self.assertNotIn('data:image',json.dumps(brain.history))
    def test_history_clears_on_account_change(self):
        brain=self.brain([[self.delta('Hello.'),self.completed()],[self.delta('Hi.'),self.completed()]])
        list(brain.reply('first account'))
        brain.auth.selected=lambda:{'key':'another'}
        list(brain.reply('second account'))
        self.assertNotIn('first account',json.dumps(self.requests[1]['input']))

if __name__=='__main__': unittest.main()
