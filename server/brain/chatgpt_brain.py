"""ChatGPT plan Responses transport, reusing Rocky's personality/history pipeline."""
import base64
import json
import threading
import openai
from . import config, personality
from .chatgpt_auth import ChatGPTError, RESOURCE
from .thinking import RobotBrain, TOOLS, Interrupted, _SENTENCE_END, visual_parts
from .web_access import manager as web, intent, spoken_text


def response_input(history):
    """Translate existing chat history without server-side conversation storage."""
    result = []
    for message in history:
        role = message['role']
        if role == 'tool':
            result.append({'type':'function_call_output','call_id':message['tool_call_id'],
                           'output':message['content']})
            continue
        content = message.get('content')
        if isinstance(content, str):
            if content:
                result.append({'role':role,'content':content})
        elif isinstance(content, list):
            parts = []
            for part in content:
                if part['type'] == 'text': parts.append({'type':'input_text','text':part['text']})
                elif part['type'] == 'image_url':
                    parts.append({'type':'input_image','image_url':part['image_url']['url']})
            if parts: result.append({'role':role,'content':parts})
        for call in message.get('tool_calls',[]):
            item = {'type':'function_call','call_id':call['id'],
                    'name':call['function']['name'],'arguments':call['function']['arguments']}
            if call.get('namespace'): item['namespace'] = call['namespace']
            result.append(item)
    return result


def request_error(code):
    if code in ('subscription_sharing_usage_limit_exceeded','rate_limit_exceeded'):
        return 'ChatGPT usage limit reached. Check Manage ChatGPT usage or try again later.'
    if code == 'subscription_sharing_usage_unavailable':
        return 'ChatGPT plan use is unavailable. Check your ChatGPT app permissions and sign in again.'
    if code in ('invalid_api_key','invalid_token','token_expired'):
        return 'ChatGPT login expired. Choose Continue with ChatGPT again.'
    return 'ChatGPT could not finish that reply. Try again.'


class ChatGPTBrain(RobotBrain):
    def __init__(self, auth, actions=None, client_factory=None, on_status=None):
        # Keep API-key/provider behavior untouched in the original RobotBrain.
        self.virtual_body = True
        self.auth = auth
        self.actions = actions or {}
        self.history = []
        self.emotion = 'neutral'
        self._inflight = None
        self._account_key = None
        self.client_factory = client_factory or openai.OpenAI
        self.on_status = on_status or (lambda text: None)

    def reply(self, question, jpeg=None, on_emotion=None, cancelled=None, camera_wanted=False):
        try:
            selected = self.auth.selected()
            key = selected['key'] if selected else None
            if key != self._account_key:
                self.history.clear()
                self._account_key = key
            yield from super().reply(question, jpeg, on_emotion, cancelled, camera_wanted)
        except ChatGPTError as exc:
            self.abandon()
            self.emotion = 'sad'
            if on_emotion: on_emotion('sad')
            self.on_status(str(exc))
            yield str(exc)

    def probe_web(self):
        """Explicit on-demand integration probe; never called at startup."""
        if not web.enabled: return 'Web Access is disabled; no probe was made.'
        selected=self.auth.selected()
        key=selected['key'] if selected else None
        try:
            model=self.auth.model(key); connection=('chatgpt',key,model)
            with self.client_factory(api_key=self.auth.token(key),base_url=RESOURCE,max_retries=0,timeout=30) as client:
                response=client.responses.create(model=model,tools=[{'type':'web_search'}],tool_choice={'type':'web_search'},input='Search for the official OpenAI Responses web search documentation; return its title.',store=False)
            output=getattr(response,'output',[])
            succeeded=getattr(response,'status',None)=='completed' and web.collect(output)
            web.mark(connection,'supported' if succeeded else 'error','' if succeeded else 'Probe returned no completed web search.')
        except openai.APIStatusError as exc:
            web.mark(locals().get('connection'), 'unsupported' if exc.status_code in (400,403,422) else 'error',f'Probe rejected (HTTP {exc.status_code}); hosted search is unavailable for this connection/model.')
        except Exception:
            web.mark(locals().get('connection'),'error','Probe could not complete. Sign in and check connectivity.')
        return web.status()

    def _converse(self, on_emotion, cancelled):
        limit = config.REPLY_MAX_SENTENCES
        for _ in range(5):
            if cancelled.is_set(): raise Interrupted()
            token = self.auth.token(self._account_key)
            model = self.auth.model(self._account_key)
            connection=('chatgpt',self._account_key,model)
            needs_web=intent(getattr(self,'_question',''))=='search' and not getattr(self,'_web_done',False)
            tools = [{'type':'namespace','name':'rocky',
                      'description':'Companion webcam, screen, weather, explicit textual memory and session-label abilities.',
                      'tools':[{'type':'function', **tool['function'], 'strict':False} for tool in self.available_tools()]}] if self.actions else []
            hosted=web.hosted_tools(connection) if needs_web else []
            if needs_web and not hosted:
                yield web.unavailable()
                return
            tools.extend(hosted)
            web_items=[]
            request_options={'tool_choice':{'type':'web_search'},'include':['web_search_call.action.sources'],'max_tool_calls':1} if hosted else {}
            buf = ''
            raw = []
            calls = []
            tag_decided = False
            spoken = 0
            completed = False
            # Always drain the terminal event; do not call a partial stream success.
            # The short spoken sentence limit does not cancel the HTTP response.
            try:
                with self.client_factory(api_key=token, base_url=RESOURCE, max_retries=0,
                                         timeout=45) as client:
                    with client.responses.create(model=model,
                        instructions=personality.system_prompt(virtual=getattr(self, 'virtual_body', False)),
                        input=response_input(self._request_history()), tools=tools, store=False, stream=True, **request_options) as stream:
                        for event in stream:
                            if cancelled.is_set(): raise Interrupted()
                            if event.type == 'response.output_text.delta':
                                raw.append(event.delta)
                                if hosted: continue  # Verify search before speaking any current claims.
                                if spoken >= limit: continue
                                buf += event.delta
                                if not tag_decided:
                                    buf, tag_decided = self._take_emotion_tag(buf, final=False)
                                    if not tag_decided: continue
                                    if on_emotion: on_emotion(self.emotion)
                                parts = _SENTENCE_END.split(buf)
                                for sentence in parts[:-1]:
                                    if sentence.strip() and spoken < limit:
                                        spoken += 1; yield sentence.strip()
                                buf = parts[-1] if spoken < limit else ''
                            elif event.type == 'response.output_item.done' and event.item.type == 'function_call':
                                calls.append(event.item)
                            elif event.type == 'response.output_item.done' and event.item.type in ('web_search_call','message'):
                                web_items.append(event.item)
                            elif event.type == 'response.failed':
                                error = event.response.error
                                raise ChatGPTError(request_error(error.code if error else None))
                            elif event.type in ('response.incomplete','error'):
                                raise ChatGPTError(request_error(getattr(event,'code',None)))
                            elif event.type == 'response.completed':
                                completed = True
                                web_items.extend(getattr(event.response,'output',[]) if hasattr(event,'response') else [])
                if not completed:
                    raise ChatGPTError('ChatGPT connection ended before the reply finished. Try again.')
            except openai.AuthenticationError as exc:
                if hosted: web.mark(connection,'error','ChatGPT login expired; hosted search did not complete.')
                raise ChatGPTError('ChatGPT login expired. Choose Continue with ChatGPT again.') from exc
            except openai.APIStatusError as exc:
                if hosted:
                    web.mark(connection,'unsupported' if exc.status_code in (400,403,422) else 'error',f'Hosted web search request rejected (HTTP {exc.status_code}).')
                    self.on_status(web.status())
                    yield web.unavailable()
                    return
                body = exc.body if isinstance(exc.body,dict) else {}
                detail = body.get('error',body)
                code = detail.get('code') if isinstance(detail,dict) else None
                if exc.status_code == 429: code = code or 'rate_limit_exceeded'
                raise ChatGPTError(request_error(code)) from exc
            except openai.APIConnectionError as exc:
                if hosted:
                    web.mark(connection,'error','Hosted web search connection failed.')
                    yield web.unavailable()
                    return
                raise ChatGPTError('Cannot reach ChatGPT. Check your internet connection and try again.') from exc
            except ChatGPTError:
                if hosted: web.mark(connection,'error','Hosted search did not finish; current information was not verified.')
                raise
            if hosted:
                answer=''.join(raw)
                if not web.enabled or not web.collect(web_items,answer):
                    web.mark(connection,'error','No completed web search was returned; current information was not verified.')
                    yield web.unavailable()
                    return
                self._web_done=True
                web.mark(connection,'supported')
                self.on_status(web.status())
                buf,tag_decided=self._take_emotion_tag(spoken_text(answer),final=True)
                if on_emotion: on_emotion(self.emotion)
                for sentence in _SENTENCE_END.split(buf)[:limit]:
                    if sentence.strip(): yield sentence.strip()
                buf=''; spoken=limit
            if not tag_decided:
                buf, _ = self._take_emotion_tag(buf, final=True)
                if on_emotion and (buf.strip() or not calls): on_emotion(self.emotion)
            if buf.strip() and spoken < limit: yield buf.strip()
            if calls:
                assistant = {'role':'assistant','content':''.join(raw),'tool_calls':[]}
                for call in calls:
                    entry = {'id':call.call_id,'type':'function',
                             'function':{'name':call.name,'arguments':call.arguments}}
                    if getattr(call,'namespace',None): entry['namespace'] = call.namespace
                    assistant['tool_calls'].append(entry)
                self.history.append(assistant)
                for call in calls:
                    if cancelled.is_set(): raise Interrupted()
                    try:
                        args = json.loads(call.arguments or '{}')
                        if not isinstance(args,dict): raise ValueError()
                        action = self.actions.get(call.name.rsplit('.',1)[-1])
                        from .screen import screen
                        if call.name.rsplit('.',1)[-1] == 'look' and getattr(screen.local, 'requested', False):
                            raise ValueError('Use desktop tool for desktop questions.')
                        if call.name.rsplit('.',1)[-1] == 'look_at_screen':
                            self._strip_images()
                        text, image = action(args) if action else ('Unknown desktop ability.', None)
                    except Exception:
                        text, image = 'Could not perform that desktop ability.', None
                    self.history.append({'role':'tool','tool_call_id':call.call_id,'content':text,
                        '_private_memory':call.name.rsplit('.',1)[-1] in ('recall_memory','list_people','label_visible_person')})
                    if image:
                        self.history.append({'role':'user','content':visual_parts(text,image)})
                continue
            if not ''.join(raw).strip(): yield 'Words did not come. Ask again, human.'
            return
        yield 'Too many things at once. Ask again, human.'
