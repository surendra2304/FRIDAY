"""Operational wiring for source-derived capabilities across FRIDAY agents."""
from __future__ import annotations

from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from .real_approved_actions import LocalActionEngine, HomeAssistantRoomAdapter
from .real_business_routines import BusinessRoutineEngine

ROOT = Path(__file__).resolve().parents[5]


def load(name: str, relative: str):
    key = 'friday_capability_'+name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key,ROOT/relative)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


class AgentCapabilityRuntime:
    def __init__(self, cross) -> None:
        self.cross = cross
        self.state = Path(cross._state_dir)/'capabilities'
        self.state.mkdir(parents=True,exist_ok=True)
        from Stratex.real_market_service import MarketDataService
        from Stratex.real_trading_discipline import TradingDisciplineEngine, TradeJournal
        self.market = MarketDataService()
        self.discipline = TradingDisciplineEngine()
        self.journal = TradeJournal(self.state/'trades.jsonl')
        self.investigation_module = load('investigation','IntelX/intelx/services/real_grounded_investigation.py')
        catalog = load('robin_catalog','IntelX/intelx/services/real_robin_config.py')
        self.pipeline = self.investigation_module.InvestigationPipeline(
            self.investigation_module.InvestigationStore(self.state/'investigations'),
            engines=tuple(self.investigation_module.SearchEngine(name,url) for name,url in catalog.DEFAULT_SEARCH_ENGINES))
        self.business = load('business','Cortex/apps/api/src/cortex_api/real_business_operations.py').BusinessOperationsEngine()
        self.voice_module = load('voice','VyralX/app/agents/real_voice_interaction.py')
        self.voice_sessions: dict[str,tuple[float,object]] = {}
        self.chat_sessions: dict[str,dict] = {}
        self.actions = LocalActionEngine(self.state,os.environ.get('FRIDAY_CONTROL_TOKEN') or os.environ.get('FRIDAY_LOCAL_ACTION_TOKEN',''),
            os.environ.get('FRIDAY_LOCAL_EXECUTION')=='1',
            apps=json.loads(os.environ['FRIDAY_ALLOWED_APPS']) if os.environ.get('FRIDAY_ALLOWED_APPS') else LocalActionEngine.discover_apps(),
            contacts=json.loads(os.environ.get('FRIDAY_CONTACTS','{}')))
        devices = json.loads(os.environ.get('FRIDAY_ROOM_DEVICES','{}'))
        if devices and os.environ.get('HOME_ASSISTANT_URL') and os.environ.get('HOME_ASSISTANT_TOKEN'):
            self.actions.devices = devices
            self.actions.device_runner = HomeAssistantRoomAdapter(os.environ['HOME_ASSISTANT_URL'],os.environ['HOME_ASSISTANT_TOKEN'])
        self.network_research = os.environ.get('FRIDAY_RESEARCH_NETWORK')=='1'
        self.models = load('research_models','IntelX/intelx/services/real_research_models.py').ResearchModelRegistry.from_environment()
        if os.environ.get('FRIDAY_RESEARCH_MODEL'):
            self.pipeline.model = self.models.resolve(os.environ['FRIDAY_RESEARCH_MODEL'])
        if os.environ.get('FRIDAY_SEARCH_ENGINES'):
            configured = json.loads(os.environ['FRIDAY_SEARCH_ENGINES'])
            if not isinstance(configured,list) or not 1<=len(configured)<=32:
                raise ValueError('FRIDAY_SEARCH_ENGINES requires 1..32 configured engines')
            self.pipeline.engines = tuple(self.investigation_module.SearchEngine(**entry) for entry in configured)
            from urllib.parse import urlsplit
            self.pipeline.engine_hosts = {urlsplit(e.template).hostname for e in self.pipeline.engines}

        self.routines = BusinessRoutineEngine(self.state/'routines',self.run_business_skill)
        self.sources: dict[str,dict] = {}
        source_file = self.state/'sources.json'
        if source_file.exists():
            self.sources = json.loads(source_file.read_text())

    def local(self, command: str) -> dict | None:
        result = self.actions.parse(command)
        if result:
            return result
        if re.search(r'\b(stock|market|nifty|sensex|crypto|bitcoin|buy or sell)\b',command,re.I):
            from Stratex.real_market_service import WATCHLIST
            aliases = {'nifty':'^NSEI','sensex':'^BSESN','bitcoin':'BTC-USD','crypto':'BTC-USD'}
            symbol = next((value for key,value in aliases.items() if re.search(r'\b'+key+r'\b',command,re.I)),None)
            if symbol is None:
                symbol = next((ticker for ticker,name in WATCHLIST.items() if name.lower() in command.lower() or re.search(r'(?<!\w)'+re.escape(ticker.replace('.NS',''))+r'(?!\w)',command,re.I)),None)
            try:
                watchlist = self.market.watchlist([symbol] if symbol else None)
                return {'text':watchlist['briefing'],'source':'local','agent':'Stratex','watchlist':watchlist}
            except (ValueError,RuntimeError) as error:
                return {'text':str(error),'source':'local','agent':'Stratex','status':'unavailable'}
        return None

    def respond(self, query: str) -> dict:
        local = self.local(query)
        return local if local else self.cross.assistant_reply(query)

    def investigate(self, query: str, **options) -> dict:
        if not self.network_research:
            raise PermissionError('Network investigation is disabled. Configure Tor and FRIDAY_RESEARCH_NETWORK=1 on the server.')
        result = self.pipeline.investigate(query,**options)
        if result['status']=='ok':
            evidence = self.cross.research_threats(result.get('pages',[]),per_host_limit=50)
            result['intel_report_id'] = evidence['report']['report_id']
            result['memory_id'] = evidence['memory_id']
        result.pop('pages',None)
        return result

    def new_chat(self) -> str:
        now = time.monotonic()
        self.chat_sessions = {key:value for key,value in self.chat_sessions.items() if now-value['at']<1800}
        if len(self.chat_sessions)>=128:
            raise ValueError('chat session capacity reached')
        from .real_hybrid_assistant import HybridAssistantEngine, GroqChatProvider
        key = os.environ.get('GROQ_API_KEY','').strip()
        identifier = uuid.uuid4().hex
        payload = {}
        def local(query):
            result = self.local(query)
            if result:
                payload.update({k:v for k,v in result.items() if k!='text'})
                return result['text']
            return None
        self.chat_sessions[identifier] = {'at':now,'payload':payload,
            'brain':HybridAssistantEngine(['llama-3.3-70b-versatile','llama-3.1-8b-instant'] if key else [],
                                         GroqChatProvider(key) if key else None,local,history_turns=3)}
        return identifier

    def chat(self, identifier: str, query: str) -> dict:
        item = self.chat_sessions.get(identifier)
        if not item or time.monotonic()-item['at']>1800:
            self.chat_sessions.pop(identifier,None)
            raise ValueError('chat session missing or expired')
        item['at'] = time.monotonic()
        item['payload'].clear()
        return {**asdict(item['brain'].respond(query)),**item['payload']}

    def voice_session(self) -> str:
        now = time.monotonic()
        self.voice_sessions = {key:item for key,item in self.voice_sessions.items() if now-item[0]<900}
        if len(self.voice_sessions)>=64:
            raise ValueError('voice session capacity reached')
        identifier = uuid.uuid4().hex
        self.voice_sessions[identifier] = (now,self.voice_module.VoiceInteractionEngine(self.respond))
        return identifier

    def voice(self, identifier: str):
        item = self.voice_sessions.get(identifier)
        if not item or time.monotonic()-item[0]>900:
            self.voice_sessions.pop(identifier,None)
            raise ValueError('voice session missing or expired')
        self.voice_sessions[identifier] = (time.monotonic(),item[1])
        return item[1]

    def run_business_skill(self, kind: str, sources: dict, parameters: dict) -> dict:
        parameters = dict(parameters)
        if kind=='lead_review':
            parameters.setdefault('now',time.time())
            records = [row for data in sources.values() for row in data]
            return self.business.review_leads(records,**parameters)
        if kind=='ad_report':
            if parameters.get('date')=='yesterday':
                from datetime import datetime, timedelta
                from zoneinfo import ZoneInfo
                parameters['date'] = str(datetime.now(ZoneInfo(parameters['reporting_timezone'])).date()-timedelta(days=1))
            rows = [row for data in sources.values() for row in data]
            return self.business.ad_report(rows,**parameters)
        if kind=='weekly_sweep':
            return self.business.weekly_sweep(**parameters)
        raise ValueError('unknown business skill')

    def validate_skill(self, name: str) -> dict:
        skill = self.routines.skills[name]
        now = time.time()
        sources = {}
        for source in skill['sources']:
            item = self.sources[source]
            if item.get('error') or now-item['updated_at']>86400 or item['updated_at']>now:
                raise ValueError('source unavailable or stale: '+source)
            sources[source] = item['data']
        result = self.run_business_skill(skill['kind'],sources,skill['parameters'])
        skill['validated'] = True
        self.routines.save()
        return {'skill':name,'validated':True,'preview':result}

    def save_source(self, identifier: str, data, updated_at: float) -> None:
        if not re.fullmatch(r'[\w.-]{1,80}',identifier):
            raise ValueError('invalid source ID')
        self.sources[identifier] = {'updated_at':updated_at,'data':data}
        path = self.state/'sources.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.sources))
        temporary.replace(path)

    def tick(self, now: float | None = None) -> list[dict]:
        return self.routines.tick(time.time() if now is None else now,lambda key:self.sources[key])

    def diagnostics(self) -> dict:
        return {'local_execution':self.actions.enabled,'configured_apps':list(self.actions.apps),
                'configured_devices':list(self.actions.devices),'research_network':self.network_research,
                'research_transport':'SOCKS5 remote DNS','groq_configured':bool(os.environ.get('GROQ_API_KEY')),
                'elevenlabs_configured':bool(os.environ.get('ELEVENLABS_API_KEY')),
                'voice_sessions':len(self.voice_sessions),'routines':len(self.routines.routines),
                'pending_actions':len(self.actions.pending)}
