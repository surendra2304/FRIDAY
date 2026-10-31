"""HTTP and JSON-RPC front doors for the operational agent capabilities."""
from __future__ import annotations

from dataclasses import asdict
import base64
import binascii
import hmac
import os
from pathlib import Path
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field


class InvestigationRequest(BaseModel):
    query: str = Field(min_length=1,max_length=1000)
    preset: str = 'threat_intel'
    max_results: int = Field(default=30,ge=1,le=50)
    max_scrape: int = Field(default=10,ge=1,le=50)
    content_chars: int = Field(default=12000,ge=500,le=50000)
    threads: int = Field(default=4,ge=1,le=8)


class AssistantQuery(BaseModel):
    query: str = Field(min_length=1,max_length=4000)


class Arguments(BaseModel):
    arguments: dict[str,Any] = Field(default_factory=dict)


class WatchlistRequest(BaseModel):
    symbols: list[str] | None = Field(default=None,max_length=30)


class TranscriptRequest(BaseModel):
    text: str = Field(min_length=1,max_length=4000)
    at: float = Field(ge=0,allow_inf_nan=False)
    force: bool = True


class FrameRequest(BaseModel):
    samples: list[float] = Field(min_length=1,max_length=4096)
    at: float = Field(ge=0,allow_inf_nan=False)
    playback: bool = False


class MotionRequest(BaseModel):
    x: float = Field(ge=0,le=1,allow_inf_nan=False)
    y: float = Field(ge=0,le=1,allow_inf_nan=False)
    at: float = Field(ge=0,allow_inf_nan=False)


class AudioRequest(BaseModel):
    audio_base64: str = Field(max_length=5600000)
    media_type: str = 'audio/webm'


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1,max_length=4000)


class SourceRequest(BaseModel):
    data: list[dict] = Field(max_length=10000)
    updated_at: float = Field(allow_inf_nan=False)


def create_capability_router(cross) -> APIRouter:
    import asyncio
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        async def scheduler():
            while True:
                await asyncio.sleep(30)
                await asyncio.to_thread(cross.capability_runtime().tick)
        worker = asyncio.create_task(scheduler())
        try:
            yield
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                worker = None
    router = APIRouter(lifespan=lifespan)
    def runtime():
        return cross.capability_runtime()
    def call(operation, *args, **kwargs):
        try:
            return operation(*args,**kwargs)
        except PermissionError as error:
            raise HTTPException(403,str(error)) from error
        except (ValueError,TypeError) as error:
            raise HTTPException(422,str(error)) from error
        except (KeyError,FileNotFoundError) as error:
            raise HTTPException(404,'Requested record or required field not found') from error
        except RuntimeError as error:
            raise HTTPException(503,str(error)) from error
    def authorize(token):
        expected = os.environ.get('FRIDAY_CONTROL_TOKEN') or os.environ.get('FRIDAY_LOCAL_ACTION_TOKEN','')
        if not expected or not token or not hmac.compare_digest(token,expected):
            raise HTTPException(403,'Administrator approval token required')
    def operator(x_friday_control_token: str | None = Header(default=None),
                 x_friday_operator: str | None = Header(default=None)):
        token = x_friday_control_token or x_friday_operator
        authorize(token)
        return token

    def speech():
        from .real_capability_runtime import load
        return load('speech_bridge','VyralX/app/agents/real_speech_bridge.py').SpeechBridge(
            os.environ.get('ELEVENLABS_API_KEY',''),os.environ.get('ELEVENLABS_VOICE_ID',''))

    @router.get('/assistant',response_class=HTMLResponse)
    def assistant_ui():
        return Path(__file__).with_name('assistant_workplace.html').read_text(encoding='utf-8')

    @router.post('/api/assistant/respond')
    def respond(request: AssistantQuery):
        return call(runtime().respond,request.query)

    @router.get('/api/assistant/system')
    def system_status():
        return runtime().actions.system_status()

    @router.post('/api/assistant/sessions')
    def chat_session():
        return {'session_id':call(runtime().new_chat)}

    @router.post('/api/assistant/sessions/{identifier}')
    def chat(identifier: str, request: SpeakRequest):
        return call(runtime().chat,identifier,request.text)

    @router.delete('/api/assistant/sessions/{identifier}')
    def forget(identifier: str):
        runtime().chat_sessions.pop(identifier,None)
        return {'forgotten':True}

    @router.get('/api/assistant/capabilities')
    def capabilities():
        return {**runtime().diagnostics(),'speech':speech().capabilities()}

    @router.post('/api/assistant/actions/{identifier}/approve')
    def approve(identifier: str, approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().actions.execute,identifier,approval_token)

    @router.post('/api/trading/watchlist')
    def watchlist(request: WatchlistRequest):
        return call(runtime().market.watchlist,request.symbols)

    @router.post('/api/trading/risk-plan')
    def risk_plan(request: Arguments):
        plan = call(runtime().discipline.plan,**request.arguments)
        gate = runtime().journal.review()
        return {'plan':asdict(plan),'journal_gate':gate,'allowed':plan.allowed and gate['allowed']}

    @router.post('/api/trading/structure')
    def structure(request: Arguments):
        return call(runtime().discipline.market_structure,**request.arguments)

    @router.post('/api/trading/correlation')
    def correlation(request: Arguments):
        return call(runtime().discipline.correlation_exposure,**request.arguments)

    @router.post('/api/trading/manage-position')
    def manage_position(request: Arguments):
        return call(runtime().discipline.manage_position,**request.arguments)

    @router.post('/api/trading/journal', dependencies=[Depends(operator)])
    def journal(request: Arguments):
        return call(runtime().journal.record,**request.arguments)

    @router.get('/api/trading/journal', dependencies=[Depends(operator)])
    def journal_review():
        return {'entries':runtime().journal.entries(),'review':runtime().journal.review()}

    @router.get('/api/threat/models')
    def models():
        return {'models':runtime().models.choices(),'selected':os.environ.get('FRIDAY_RESEARCH_MODEL'),
                'fallback':'extractive evidence, lexical ranking'}

    @router.get('/api/threat/presets')
    def presets():
        return {'presets':sorted(runtime().investigation_module.PRESETS)}

    @router.post('/api/threat/investigate', dependencies=[Depends(operator)])
    def investigate(request: InvestigationRequest):
        return call(runtime().investigate,**request.model_dump())

    @router.post('/api/threat/search', dependencies=[Depends(operator)])
    def search(request: InvestigationRequest):
        if not runtime().network_research:
            raise HTTPException(403,'Network investigation disabled on server')
        return call(runtime().pipeline.search,request.query,request.threads)

    @router.get('/api/threat/investigations', dependencies=[Depends(operator)])
    def history():
        return runtime().pipeline.store.history()

    @router.get('/api/threat/investigations/{identifier}', dependencies=[Depends(operator)])
    def report(identifier: str):
        return call(runtime().pipeline.store.get,identifier)

    @router.get('/api/threat/investigations/{identifier}/export', dependencies=[Depends(operator)])
    def export(identifier: str, format: str = 'markdown'):
        result = call(runtime().pipeline.export,identifier,format)
        return Response(result,media_type='application/json' if format=='json' else 'text/markdown',
                        headers={'Content-Disposition':'attachment; filename="investigation.'+('json' if format=='json' else 'md')+'"'})

    @router.post('/api/threat/investigations/{identifier}/followup', dependencies=[Depends(operator)])
    def followup(identifier: str, request: SpeakRequest):
        return call(runtime().pipeline.followup,identifier,request.text)

    @router.get('/api/threat/transport-health', dependencies=[Depends(operator)])
    def transport_health():
        if not runtime().network_research:
            return {'status':'disabled'}
        return call(runtime().pipeline.transport.health)

    @router.post('/api/voice/sessions')
    def voice_session():
        return {'session_id':call(runtime().voice_session)}

    @router.post('/api/voice/sessions/{identifier}/transcript')
    def transcript(identifier: str, request: TranscriptRequest):
        voice = call(runtime().voice,identifier)
        return call(voice.transcript,**request.model_dump())

    @router.post('/api/voice/sessions/{identifier}/frame')
    def voice_frame(identifier: str, request: FrameRequest):
        voice = call(runtime().voice,identifier)
        return call(voice.frame,**request.model_dump())

    @router.post('/api/voice/sessions/{identifier}/motion')
    def motion(identifier: str, request: MotionRequest):
        voice = call(runtime().voice,identifier)
        return call(voice.motion_frame,**request.model_dump())

    @router.post('/api/voice/transcribe')
    def transcribe(request: AudioRequest):
        try:
            audio = base64.b64decode(request.audio_base64,validate=True)
        except binascii.Error as error:
            raise HTTPException(422,'Invalid base64 audio') from error
        return {'text':call(speech().transcribe,audio,request.media_type)}

    @router.post('/api/voice/speak')
    def speak(request: SpeakRequest):
        return Response(call(speech().synthesize,request.text),media_type='audio/mpeg')

    @router.post('/api/business/leads/review')
    def leads(request: Arguments):
        return call(runtime().business.review_leads,**request.arguments)

    @router.post('/api/business/ads/report')
    def ads(request: Arguments):
        return call(runtime().business.ad_report,**request.arguments)

    @router.post('/api/business/weekly-sweep')
    def sweep(request: Arguments):
        return call(runtime().business.weekly_sweep,**request.arguments)

    @router.post('/api/business/pilot-economics')
    def economics(request: Arguments):
        return call(runtime().business.pilot_economics,**request.arguments)

    @router.post('/api/business/opportunities/rank')
    def opportunities(request: Arguments):
        return call(runtime().business.rank_opportunities,**request.arguments)

    @router.put('/api/business/sources/{identifier}')
    def source(identifier: str, request: SourceRequest, approval_token: str = Depends(operator)):
        authorize(approval_token)
        call(runtime().save_source,identifier,request.data,request.updated_at)
        return {'id':identifier,'updated_at':request.updated_at}

    @router.post('/api/business/skills')
    def skill(request: Arguments, approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().routines.save_skill,**request.arguments)

    @router.post('/api/business/skills/{name}/validate')
    def validate_skill(name: str, approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().validate_skill,name)

    @router.post('/api/business/routines', dependencies=[Depends(operator)])
    def create_routine(request: Arguments, approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().routines.create,**request.arguments)

    @router.get('/api/business/routines', dependencies=[Depends(operator)])
    def routines():
        return [asdict(r) for r in runtime().routines.routines.values()]

    @router.post('/api/business/routines/{identifier}/pause')
    def pause(identifier: str, request: Arguments, approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().routines.pause,identifier,**request.arguments)

    @router.post('/api/business/routines/tick')
    def tick(approval_token: str = Depends(operator)):
        authorize(approval_token)
        return call(runtime().tick)

    # MCP-shaped JSON-RPC front door: discovery + strictly bounded read-only tools.
    tools = {'intelx_investigate':lambda a:runtime().investigate(**InvestigationRequest(**a).model_dump()),
             'intelx_history':lambda a:runtime().pipeline.store.history(**a),
             'intelx_followup':lambda a:runtime().pipeline.followup(**a),
             'stratex_watchlist':lambda a:runtime().market.watchlist(**a)}
    @router.post('/api/research/rpc', dependencies=[Depends(operator)])
    def rpc(body: dict):
        identifier = body.get('id')
        if body.get('jsonrpc')!='2.0' or not isinstance(body.get('method'),str):
            return {'jsonrpc':'2.0','id':identifier,'error':{'code':-32600,'message':'Invalid Request'}}
        if body['method']=='initialize':
            return {'jsonrpc':'2.0','id':identifier,'result':{'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'FRIDAY research','version':'1.0'}}}
        if body['method']=='notifications/initialized':
            return Response(status_code=204)
        if body['method']=='tools/list':
            return {'jsonrpc':'2.0','id':identifier,'result':{'tools':[{'name':name,'description':'FRIDAY read-only agent tool',
                'inputSchema':{'type':'object'}} for name in tools]}}
        if body['method']!='tools/call':
            return {'jsonrpc':'2.0','id':identifier,'error':{'code':-32601,'message':'Method not found'}}
        try:
            params = body.get('params',{})
            if not isinstance(params,dict) or params.get('name') not in tools or not isinstance(params.get('arguments',{}),dict):
                raise ValueError('Invalid tool or arguments')
            import json
            result = tools[params['name']](params.get('arguments',{}))
            return {'jsonrpc':'2.0','id':identifier,'result':{'content':[{'type':'text','text':json.dumps(result)}]}}
        except Exception as error:
            return {'jsonrpc':'2.0','id':identifier,'error':{'code':-32602,'message':type(error).__name__}}

    return router
