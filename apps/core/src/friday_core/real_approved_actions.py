"""Deterministic Jarvis actions, approval-bound local execution and room adapters.

Planning never executes. Approval is a separate authenticated server operation;
API callers cannot enable execution or register arbitrary commands/devices.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hmac
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import time
from typing import Callable
from threading import RLock
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


SITES = {'youtube':'https://www.youtube.com','whatsapp':'https://web.whatsapp.com','gmail':'https://mail.google.com',
         'google':'https://www.google.com','github':'https://github.com','maps':'https://maps.google.com',
         'calendar':'https://calendar.google.com','drive':'https://drive.google.com'}
ALIASES = {'vs code':'code','visual studio code':'code','chrome':'chrome','spotify':'spotify','terminal':'terminal'}


@dataclass
class ActionPlan:
    id: str
    kind: str
    target: str
    payload: dict
    status: str
    created_at: float
    expires_at: float
    result: str = ''


class LocalActionEngine:
    def __init__(self, state_dir: str | Path, control_token: str = '', enabled: bool = False,
                 apps: dict[str,list[str]] | None = None, contacts: dict[str,str] | None = None,
                 clock: Callable = time.time, runner: Callable = subprocess.run) -> None:
        self.directory = Path(state_dir)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.control_token,self.enabled = control_token,enabled
        self.apps,self.contacts,self.clock,self.runner = apps or {},contacts or {},clock,runner
        self._lock = RLock()
        self.pending: dict[str,ActionPlan] = {}
        self.devices: dict[str,dict] = {}
        self.device_runner: Callable | None = None

    @staticmethod
    def discover_apps() -> dict[str,list[str]]:
        """Discover a small known set of launchers; never parse a user's shell text."""
        names = {'code':'code','chrome':'google-chrome','chromium':'chromium','spotify':'spotify','terminal':'gnome-terminal'}
        apps = {name:[path] for name,executable in names.items() if (path := shutil.which(executable))}
        if platform.system()=='Darwin':
            for directory in (Path('/Applications'),Path('/System/Applications')):
                for path in directory.glob('*.app'):
                    apps[path.stem.lower()] = ['open','-a',str(path)]
            for alias,app in {'code':'visual studio code','chrome':'google chrome','terminal':'terminal'}.items():
                if app in apps:
                    apps[alias] = apps[app]
        return apps

    def system_status(self) -> dict:
        usage = shutil.disk_usage(self.directory)
        status = {'platform':platform.system(),'disk_total_bytes':usage.total,'disk_free_bytes':usage.free,
                  'disk_used_percent':100*usage.used/usage.total,'observed_at':self.clock()}
        try:
            status['load_average'] = list(os.getloadavg())
        except (AttributeError,OSError):
            status['load_average'] = None
        mem = Path('/proc/meminfo')
        if mem.exists():
            entries = {line.split(':')[0]:int(line.split()[1])*1024 for line in mem.read_text().splitlines()}
            total,available = entries.get('MemTotal',0),entries.get('MemAvailable',0)
            status['memory_total_bytes'] = total
            status['memory_used_percent'] = 100*(total-available)/total if total else None
        else:
            status['memory_used_percent'] = None
        uptime = Path('/proc/uptime')
        status['uptime_seconds'] = float(uptime.read_text().split()[0]) if uptime.exists() else None
        status['battery_percent'] = None
        for battery in Path('/sys/class/power_supply').glob('BAT*/capacity'):
            status['battery_percent'] = int(battery.read_text())
            break
        return status

    def _plan(self, kind: str, target: str, payload: dict, requires_approval: bool = True) -> ActionPlan:
        now = self.clock()
        self.pending = {key:value for key,value in self.pending.items() if value.expires_at>now and value.status=='pending'}
        if len(self.pending)>=256:
            raise ValueError('too many pending actions')
        plan = ActionPlan(secrets.token_hex(16),kind,target,payload,'pending' if requires_approval else 'ready',now,now+300)
        if requires_approval:
            self.pending[plan.id] = plan
        return plan

    def parse(self, query: str) -> dict | None:
        command = re.sub(r'^\s*(?:(?:hey|hi)\s+)?(?:jarvis|friday)\b[,\s]*','',query,flags=re.I).strip(' .!?')
        lowered = command.lower()
        now = datetime.fromtimestamp(self.clock()).astimezone()
        if re.fullmatch(r'(?:what(?:\x27s| is)? (?:the )?)?(?:time|date)(?: is it| today)?',lowered):
            return {'text':now.isoformat(timespec='seconds'),'source':'local','agent':'FRIDAY'}
        if lowered in {'system status','system vitals'}:
            status = self.system_status()
            return {'text':json.dumps(status),'source':'local','system':status}
        if lowered in {'check whatsapp','whatsapp'}:
            plan = self._plan('open_url','whatsapp',{'url':SITES['whatsapp']},False)
            return {'text':'Ready to open WhatsApp in your browser.','source':'local','action':asdict(plan)}
        if lowered in {'mail brief','check mail','read emails','inbox summary','unread emails'}:
            path = self.directory/'mail_cache.txt'
            if not path.exists():
                return {'text':'No mail cache is connected. No inbox counts are available.','source':'local','agent':'FRIDAY'}
            content = path.read_text(encoding='utf-8',errors='replace')[:6000].strip()
            return {'text':content or 'The connected mail cache is empty.','source':'local','agent':'FRIDAY',
                    'observed_at':path.stat().st_mtime,'cached':True}
        match = re.fullmatch(r'(?:send|message)(?: on)? whatsapp to (.+?)(?: saying (.+))?',command,re.I)
        if match:
            contact,message = match[1].strip(),match[2] or ''
            number = self.contacts.get(contact.lower())
            url = 'https://wa.me/'+re.sub(r'\D','',number) if number else SITES['whatsapp']+'/send'
            url += '?'+urlencode({'text':message})
            plan = self._plan('compose_message',contact,{'url':url,'message':message,'recipient_resolved':bool(number)},False)
            return {'text':'Message draft prepared; nothing has been sent.','source':'local','action':asdict(plan)}
        match = re.fullmatch(r'(?:play|search|find|open) (.+?) (?:on|in) youtube',command,re.I)
        if match:
            plan = self._plan('open_url','youtube',{'url':SITES['youtube']+'/results?'+urlencode({'search_query':match[1]})},False)
        elif (match := re.fullmatch(r'(?:search|google)(?: for)? (.+)',command,re.I)):
            plan = self._plan('open_url','google',{'url':SITES['google']+'/search?'+urlencode({'q':match[1]})},False)
        elif (match := re.fullmatch(r'(?:please )?(?:open|launch|start) (.+)',command,re.I)):
            name = match[1].lower().strip()
            if name in SITES:
                plan = self._plan('open_url',name,{'url':SITES[name]},False)
            else:
                target = ALIASES.get(name,name)
                if target not in self.apps:
                    return {'text':f'Application {name} is not in the administrator allowlist.','source':'local','agent':'FRIDAY'}
                plan = self._plan('launch_app',target,{})
        elif lowered in {'volume up','volume down','mute','mute volume','louder','quieter'}:
            target = 'mute' if 'mute' in lowered else 'up' if lowered in {'volume up','louder'} else 'down'
            plan = self._plan('volume',target,{})
        elif (match := re.fullmatch(r'turn (on|off) (?:the )?(.+)',lowered)):
            device = match[2]
            if device not in self.devices:
                return {'text':f'Device {device} is not configured. No control request was sent.','source':'local'}
            plan = self._plan('room_device',device,{'state':match[1]})
        else:
            return None
        return {'text':'Ready to open in your browser.' if plan.status=='ready' else 'Action prepared; explicit approval required.',
                'source':'local','agent':'FRIDAY','action':asdict(plan)}

    def execute(self, identifier: str, token: str) -> dict:
        with self._lock:
            return self._execute(identifier,token)

    def _execute(self, identifier: str, token: str) -> dict:
        if not self.enabled or not self.control_token or not hmac.compare_digest(token,self.control_token):
            raise PermissionError('Local execution is disabled or authorization failed')
        plan = self.pending.get(identifier)
        if not plan or plan.status!='pending' or self.clock()>plan.expires_at:
            raise ValueError('Action is missing, expired or already consumed')
        # Claim before execution so repeat approvals cannot launch twice.
        plan.status = 'executing'
        try:
            if plan.kind=='launch_app':
                argv = self.apps.get(plan.target)
                if not argv or not isinstance(argv,list) or not all(isinstance(v,str) for v in argv):
                    raise ValueError('invalid administrator application configuration')
                result = self.runner(argv,capture_output=True,timeout=10,check=False)
                if result.returncode:
                    raise RuntimeError('application launcher failed')
            elif plan.kind=='volume':
                if platform.system()=='Darwin':
                    scripts = {'up':'set volume output volume ((output volume of (get volume settings)) + 15)',
                               'down':'set volume output volume ((output volume of (get volume settings)) - 15)',
                               'mute':'set volume with output muted'}
                    argv = ['osascript','-e',scripts[plan.target]]
                elif shutil.which('pactl'):
                    argv = ['pactl','set-sink-mute','@DEFAULT_SINK@','1'] if plan.target=='mute' else ['pactl','set-sink-volume','@DEFAULT_SINK@','+15%' if plan.target=='up' else '-15%']
                else:
                    raise RuntimeError('No supported local audio controller')
                if self.runner(argv,capture_output=True,timeout=10,check=False).returncode:
                    raise RuntimeError('audio controller failed')
            elif plan.kind=='room_device' and self.device_runner:
                self.device_runner(self.devices[plan.target],plan.payload['state'])
            else:
                raise ValueError('No configured executor for this action')
            plan.status,plan.result = 'completed','Execution acknowledged by configured adapter.'
        except Exception as error:
            plan.status,plan.result = 'failed',type(error).__name__
        with (self.directory/'action_audit.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(asdict(plan))+'\n')
        return asdict(plan)


class HomeAssistantRoomAdapter:
    """Configured HA services also cover BroadLink IR remotes; never guess codes."""

    def __init__(self, base_url: str, token: str, transport: Callable = urlopen) -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('invalid administrator Home Assistant URL')
        self.base_url,self.token,self.transport = base_url.rstrip('/'),token,transport

    def __call__(self, device: dict, state: str) -> None:
        config = device.get(state)
        if not config or state not in {'on','off'}:
            raise ValueError('device action not configured')
        domain,service = config['service'].split('.')
        if not re.fullmatch(r'[a-z_]+',domain) or not re.fullmatch(r'[a-z_]+',service):
            raise ValueError('invalid service')
        request = Request(self.base_url+'/api/services/'+domain+'/'+service,
            data=json.dumps(config['data']).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        with self.transport(request,timeout=10) as response:
            if not 200<=response.status<300:
                raise RuntimeError('device service rejected request')
