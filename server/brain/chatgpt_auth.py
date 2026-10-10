"""Official ChatGPT plan OAuth flow. Tokens are never logged or stored in .env."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

import httpx
import jwt

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
RESOURCE = 'https://api.openai.com/v1'
PLAN_SCOPE = 'chatgpt.tokens.use.direct'
SCOPES = 'openid profile email offline_access resource.invoke ' + PLAN_SCOPE

class ChatGPTError(RuntimeError):
    """Safe user-facing message, with no credential or response-body contents."""


def protect(data: bytes, decrypt=False) -> bytes:
    """DPAPI binds Windows credentials to this Windows user; Unix uses mode 0600."""
    if os.name != 'nt':
        return data
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ChatGPTError('Windows could not protect or open the saved ChatGPT login.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self, directory: Path, codec=protect):
        self.directory = Path(directory)
        self.path = self.directory / 'accounts.dat'
        self.codec = codec
        self._lock = threading.RLock()

    @contextmanager
    def locked(self):
        """Serialize rotating refresh tokens, including across app processes."""
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._lock, open(self.directory / 'session.lock', 'a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b'0'); handle.flush()
                deadline = time.monotonic() + 30
                while True:
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise ChatGPTError('Another Rocky window is updating the login. Try again.')
                        time.sleep(.05)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self):
        if not self.path.exists():
            return {'host_id': 'urn:uuid:' + str(uuid.uuid4()), 'accounts': {}, 'active': None}
        try:
            data = self.codec(self.path.read_bytes(), decrypt=True)
            state = json.loads(data)
            if not isinstance(state.get('accounts'), dict) or not state.get('host_id'):
                raise ValueError()
            return state
        except ChatGPTError: raise
        except Exception as exc:
            raise ChatGPTError('Saved ChatGPT login could not be read. Keep the file and try again.') from exc

    def write(self, state):
        data = self.codec(json.dumps(state).encode('utf-8'))
        temp = self.directory / ('accounts-' + secrets.token_hex(8) + '.tmp')
        try:
            with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
                out.write(data); out.flush(); os.fsync(out.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)


def validate_callback(query, state, issued=None):
    """Never exchange an unsolicited callback or mix two client registrations."""
    values = parse_qs(query, keep_blank_values=True)
    if any(len(v) != 1 for v in values.values()):
        raise ChatGPTError('Invalid sign-in callback.')
    value = {k: v[0] for k, v in values.items()}
    if not value.get('state') or not secrets.compare_digest(value['state'], state):
        raise ChatGPTError('Sign-in callback did not match this window.')
    if value.get('error'):
        raise ChatGPTError('ChatGPT sign-in was declined. Choose Continue with ChatGPT to try again.')
    client = value.get('client_id') or issued
    if not client or client == 'dynamic_agent_client' or (issued and client != issued):
        raise ChatGPTError('ChatGPT registration was incomplete or did not match this account.')
    if not value.get('code'):
        raise ChatGPTError('ChatGPT did not return a sign-in code.')
    return value['code'], client


class AuthManager:
    def __init__(self, directory, http=None, store=None):
        self.store = store or CredentialStore(Path(directory))
        self.http = http or httpx.Client(timeout=20, follow_redirects=False)
        self._metadata = None
        with self.store.locked():
            state = self.store.read()
            self.store.write(state)  # persist host ID before first authorization

    def discovery(self):
        if self._metadata is None:
            result = self.request('GET', ISSUER + '/.well-known/openid-configuration')
            if result.get('issuer') != ISSUER:
                raise ChatGPTError('Unexpected ChatGPT sign-in issuer.')
            for field in ('jwks_uri', 'revocation_endpoint'):
                parsed = urlsplit(result.get(field, ''))
                if parsed.scheme != 'https' or parsed.netloc != 'auth.openai.com':
                    raise ChatGPTError('Unexpected ChatGPT sign-in endpoint.')
            self._metadata = result
        return self._metadata

    def request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ChatGPTError('Cannot reach ChatGPT. Check the internet connection and try again.') from exc
        if response.status_code >= 400:
            if response.status_code == 401:
                raise ChatGPTError('ChatGPT login expired. Choose Continue with ChatGPT again.')
            if response.status_code == 429:
                raise ChatGPTError('ChatGPT usage limit reached. Check Manage ChatGPT usage or try later.')
            raise ChatGPTError(f'ChatGPT could not complete this request (HTTP {response.status_code}). Try signing in again.')
        if not response.content: return {}
        try: return response.json()
        except ValueError as exc: raise ChatGPTError('ChatGPT returned an unreadable response.') from exc

    def verify_identity(self, token, client_id, nonce=None, subject=None):
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not header.get('kid'): raise ValueError()
            keys = self.request('GET', self.discovery()['jwks_uri'])['keys']
            key = next(k for k in keys if k.get('kid') == header.get('kid') and k.get('use','sig') == 'sig')
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=['RS256'],
                                issuer=ISSUER, audience=client_id,
                                options={'require': ['iss','aud','exp','iat','sub']})
            if not isinstance(claims['sub'], str) or not claims['sub']: raise ValueError()
            if nonce is not None and (not isinstance(claims.get('nonce'), str) or
                                       not secrets.compare_digest(claims['nonce'], nonce)): raise ValueError()
            if subject is not None and claims['sub'] != subject: raise ValueError()
            return claims
        except ChatGPTError: raise
        except Exception as exc:
            raise ChatGPTError('ChatGPT identity could not be verified. No login was saved.') from exc

    def accounts(self):
        with self.store.locked():
            state = self.store.read()
            return [{'key': key, 'label': record['label'], 'selected': key == state['active'],
                     'signed_in': bool(record.get('access_token')),
                     'plan_enabled': PLAN_SCOPE in record.get('scopes', [])}
                    for key, record in state['accounts'].items()]

    def selected(self):
        return next((a for a in self.accounts() if a['selected']), None)

    def prepare_attempt(self, account_key=None):
        with self.store.locked():
            state = self.store.read()
            account = state['accounts'].get(account_key) if account_key else None
            if account_key and account is None: raise ChatGPTError('Choose a saved ChatGPT account first.')
            host_id = state['host_id']
        return {'state': secrets.token_urlsafe(32), 'nonce': secrets.token_urlsafe(32),
                'verifier': secrets.token_urlsafe(64), 'host_id': host_id, 'account': account,
                'account_key': account_key}

    def authorization_url(self, attempt, redirect_uri):
        account = attempt['account']
        params = {'client_id': account['client_id'] if account else 'dynamic_agent_client',
                  'ext_agent_host_id': attempt['host_id'], 'response_type':'code',
                  'redirect_uri':redirect_uri, 'scope':SCOPES, 'resource':RESOURCE,
                  'state':attempt['state'], 'nonce':attempt['nonce'], 'code_challenge_method':'S256',
                  'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(attempt['verifier'].encode()).digest()).decode().rstrip('=')}
        if not account: params['agent_name_hint'] = 'Virtual Rocky'
        elif account.get('id_token'): params['id_token_hint'] = account['id_token']
        return AUTHORIZE + '?' + urlencode(params)

    def complete_attempt(self, attempt, query, redirect_uri):
        prior = attempt['account']
        code, client_id = validate_callback(query, attempt['state'], prior['client_id'] if prior else None)
        tokens = self.request('POST', TOKEN, data={'grant_type':'authorization_code',
            'client_id':client_id, 'code':code, 'code_verifier':attempt['verifier'],
            'redirect_uri':redirect_uri, 'resource':RESOURCE})
        identity = self.verify_identity(tokens.get('id_token',''), client_id, attempt['nonce'],
                                        prior['subject'] if prior else None)
        if not tokens.get('access_token') or str(tokens.get('token_type','')).lower() != 'bearer':
            raise ChatGPTError('ChatGPT did not return usable credentials.')
        scopes = str(tokens.get('scope','')).split()
        key = hashlib.sha256((client_id + '\0' + identity['sub']).encode()).hexdigest()
        label = str(identity.get('email') or 'ChatGPT account') + ' · ' + client_id[-6:]
        record = {'subject':identity['sub'], 'client_id':client_id, 'label':label,
                  'scopes':scopes, 'expires_at':time.time()+float(tokens.get('expires_in',3600)),
                  'id_token':tokens['id_token'], 'access_token':tokens['access_token'],
                  'refresh_token':tokens.get('refresh_token'), 'model':None, 'models':[]}
        with self.store.locked():
            state = self.store.read()
            existing = state['accounts'].get(key,{})
            record['model'], record['models'] = existing.get('model'), existing.get('models',[])
            state['accounts'][key] = record
            state['active'] = key
            self.store.write(state)
        return PLAN_SCOPE in scopes

    def sign_in(self, account_key=None, cancel=None, browser=webbrowser.open, timeout=300):
        attempt = self.prepare_attempt(account_key)
        result = {}
        class Handler(BaseHTTPRequestHandler):
            def setup(handler):
                super().setup()
                handler.connection.settimeout(2)
            def log_message(self, *args): pass  # callback contains secret code; never log it
            def do_GET(handler):
                parsed = urlsplit(handler.path)
                if parsed.path != '/auth/callback':
                    handler.send_error(404); return
                # Wrong-state requests must not end a legitimate pending login.
                values = parse_qs(parsed.query)
                offered = values.get('state',[])
                if len(offered) != 1 or not secrets.compare_digest(offered[0], attempt['state']):
                    handler.send_error(400); return
                result['query'] = parsed.query
                page = b'<html><body><h2>You can return to Virtual Rocky.</h2><p>Rocky is finishing sign-in.</p></body></html>'
                handler.send_response(200)
                handler.send_header('Content-Type','text/html; charset=utf-8')
                handler.send_header('Cache-Control','no-store')
                handler.send_header('Content-Length',str(len(page)))
                handler.end_headers(); handler.wfile.write(page)
        with HTTPServer(('127.0.0.1',0), Handler) as listener:
            listener.timeout = .25
            redirect = f'http://127.0.0.1:{listener.server_port}/auth/callback'
            if not browser(self.authorization_url(attempt,redirect)):
                raise ChatGPTError('The sign-in browser could not open. Check your default browser and try again.')
            deadline = time.monotonic() + timeout
            while not result:
                if (cancel and cancel.is_set()) or time.monotonic() > deadline:
                    raise ChatGPTError('ChatGPT sign-in was canceled or timed out. Try again.')
                listener.handle_request()
            return self.complete_attempt(attempt,result['query'],redirect)

    def select_account(self, key):
        with self.store.locked():
            state = self.store.read()
            if key not in state['accounts']: raise ChatGPTError('Unknown ChatGPT account.')
            state['active'] = key
            self.store.write(state)

    def token(self, account_key=None):
        with self.store.locked():
            state = self.store.read()
            record = state['accounts'].get(account_key or state['active'])
            if not record or not record.get('access_token'):
                raise ChatGPTError('Right-click my face and choose Continue with ChatGPT first.')
            if PLAN_SCOPE not in record.get('scopes',[]):
                raise ChatGPTError('ChatGPT plan use was not enabled. Sign in again and allow Rocky to use your plan.')
            if record.get('expires_at',0) <= time.time()+60:
                if not record.get('refresh_token'):
                    raise ChatGPTError('ChatGPT login expired. Choose Continue with ChatGPT again.')
                tokens = self.request('POST', TOKEN, data={'grant_type':'refresh_token',
                    'client_id':record['client_id'], 'refresh_token':record['refresh_token'], 'resource':RESOURCE})
                if tokens.get('id_token'):
                    self.verify_identity(tokens['id_token'],record['client_id'],subject=record['subject'])
                if not tokens.get('access_token'):
                    raise ChatGPTError('ChatGPT login needs renewal. Choose Continue with ChatGPT again.')
                record.update(access_token=tokens['access_token'],
                    refresh_token=tokens.get('refresh_token',record['refresh_token']),
                    id_token=tokens.get('id_token',record['id_token']),
                    scopes=str(tokens.get('scope',' '.join(record['scopes']))).split(),
                    expires_at=time.time()+float(tokens.get('expires_in',3600)))
                self.store.write(state)
                if PLAN_SCOPE not in record['scopes']:
                    raise ChatGPTError('ChatGPT plan access was removed. Sign in again to enable it.')
            return record['access_token']

    def models(self, refresh=False, account_key=None):
        with self.store.locked():
            account_key = account_key or self.store.read()['active']
        if refresh:
            catalog = self.request('GET',RESOURCE+'/models',headers={'Authorization':'Bearer '+self.token(account_key)})
            models = [{'slug':m['slug'],'display_name':m.get('display_name',m['slug'])}
                      for m in catalog.get('models',[]) if m.get('visibility')=='list' and m.get('slug')]
            if not models: raise ChatGPTError('No models are available for this ChatGPT account.')
            with self.store.locked():
                state = self.store.read(); record = state['accounts'][account_key]
                record['models'] = models
                if record.get('model') not in [m['slug'] for m in models]: record['model'] = models[0]['slug']
                self.store.write(state)
            return models
        with self.store.locked():
            state = self.store.read(); record = state['accounts'].get(account_key,{})
            return record.get('models',[])

    def model(self, account_key=None):
        with self.store.locked():
            state = self.store.read()
            account_key = account_key or state['active']
            record = state['accounts'].get(account_key,{})
            model = record.get('model')
        if not model:
            self.models(refresh=True, account_key=account_key)
            return self.model(account_key)
        return model

    def choose_model(self, slug):
        with self.store.locked():
            state = self.store.read(); record = state['accounts'].get(state['active'])
            if not record or slug not in [m['slug'] for m in record.get('models',[])]:
                raise ChatGPTError('Choose one of this account’s available models.')
            record['model'] = slug; self.store.write(state)

    def sign_out(self):
        confirmed = True
        with self.store.locked():
            state = self.store.read(); record = state['accounts'].get(state['active'])
            if record and record.get('refresh_token'):
                confirmed = False
                for delay in (0,.4):
                    if delay: time.sleep(delay)
                    try:
                        self.request('POST',self.discovery()['revocation_endpoint'],data={
                            'token':record['refresh_token'],'token_type_hint':'refresh_token','client_id':record['client_id']})
                        confirmed = True; break
                    except ChatGPTError: pass
            if record:
                for name in ('access_token','refresh_token','id_token','expires_at'):
                    record.pop(name,None)
                self.store.write(state)
        return confirmed
