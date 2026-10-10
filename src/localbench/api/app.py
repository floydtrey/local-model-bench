"""C1 optional transport: default denial and bounded passive reads only."""
import base64
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .dto import (Cursor, Event, EventPage, Health, Observation, PublicationSnapshot,
                  QueueSnapshot, SourceIdentity)
from .ports import ResetRequired
from .testing import FixturePrincipal

def _encode(source, sequence, event_id):
    cursor=Cursor(source_id=source.source_id,generation=source.generation,
                  sequence=sequence,event_id=event_id)
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip('=')

def _decode(token, source):
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,2048}',token): raise ValueError
        cursor=Cursor.model_validate_json(base64.urlsafe_b64decode(token+'='*(-len(token)%4)),strict=True)
        if cursor.source_id!=source.source_id or cursor.generation!=source.generation:
            raise ValueError
        if (cursor.sequence==0)!=(cursor.event_id is None): raise ValueError
        return cursor
    except (ValueError,ValidationError):
        raise HTTPException(409,detail='cursor_reset_required') from None

def create_app(*, read_port=None):
    """No operational identity provider, login, control, or credential bypass."""
    return _build_app(read_port=read_port,validator=None)

def _build_app(*, read_port=None, validator=None, clock=None):
    now=clock or (lambda:datetime.now(timezone.utc))
    boot_id=str(uuid4())
    source=(read_port.source if read_port is not None else
            SourceIdentity(source_id='unconfigured',generation=boot_id,mode='development'))
    if validator is not None and source.mode!='fixture':
        raise ValueError('C1 admission injection is fixture-only')
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])

    @app.middleware('http')
    async def passive_only(request,call_next):
        from starlette.responses import JSONResponse
        if request.method!='GET': return JSONResponse({'detail':'read_only_api'},status_code=405)
        allowed={'after'} if request.url.path=='/api/v1/events/cases' else set()
        if len(request.scope['query_string'])>4096 or any(k not in allowed for k in request.query_params):
            return JSONResponse({'detail':'query_fields_invalid'},status_code=400)
        length=request.headers.get('content-length','0')
        if not length.isdigit() or int(length)!=0 or 'transfer-encoding' in request.headers:
            return JSONResponse({'detail':'get_body_rejected'},status_code=400)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    def admit(request, grant):
        if validator is None: raise HTTPException(401,detail='identity_unavailable')
        try: principal=validator(request)
        except Exception: raise HTTPException(401,detail='identity_invalid') from None
        instant=now()
        if (not isinstance(principal,FixturePrincipal) or type(principal.subject) is not str or not principal.subject
            or principal.audience!='benchmark-api-fixture'
            or type(principal.expires_at) is not datetime or type(principal.grants) is not frozenset
            or any(type(grant_name) is not str for grant_name in principal.grants)
            or principal.expires_at.tzinfo is None or principal.expires_at<=instant):
            raise HTTPException(401,detail='identity_invalid')
        if grant not in principal.grants: raise HTTPException(403,detail='grant_denied')
        return principal

    def port():
        if read_port is None: raise HTTPException(503,detail='reader_unavailable')
        return read_port

    def native_read(call):
        try: return call()
        except ResetRequired: raise HTTPException(409,detail='cursor_reset_required') from None
        except Exception: raise HTTPException(503,detail='native_read_unavailable') from None

    def envelope():
        return dict(boot_id=boot_id,source=source,received_at=now())

    @app.get('/api/v1/liveness')
    async def liveness():
        return {'schema_version':'benchmark-api:v1','transport_alive':True}

    @app.get('/api/v1/health',response_model=Health)
    async def health(request:Request):
        admit(request,'health.read')
        value={}; coverage='missing'; reason='reader_missing'
        if read_port is not None:
            try: value=read_port.health(); coverage='observed'; reason='freshness_policy_unset'
            except PermissionError: coverage='denied'; reason='reader_denied'
            except TimeoutError: coverage='timeout'; reason='reader_timeout'
            except Exception: coverage='invalid'; reason='reader_failed'
        received=now()
        rows=[]
        for scope in ('api_transport','database_reads','queue_owner','model_runtime','resources'):
            observed=received if scope=='api_transport' or scope=='database_reads' and coverage=='observed' else None
            rows.append(Observation(scope=scope,status='unknown',
                coverage='unknown',
                coverage_reason='observed' if scope=='api_transport' else coverage if scope=='database_reads' else 'not_checked',
                reason_code='freshness_policy_unset' if scope=='api_transport' else reason if scope=='database_reads' else 'not_observed',
                method_revision='benchmark-api-observation:v1',source='api' if scope=='api_transport' else source.source_id,
                required_for=('results',) if scope=='database_reads' else (),observed_at=observed,
                received_at=received,expires_at=None,sample_started_at=None,sample_ended_at=None,
                producer_outcome='ready' if scope=='api_transport' else value.get('producer_outcome','not_observed') if scope=='database_reads' else 'not_observed',
                values=value if scope=='database_reads' else {}))
        return Health(**envelope(),observations=rows)

    @app.get('/api/v1/publications',response_model=PublicationSnapshot)
    async def publications(request:Request):
        admit(request,'results.read')
        native,bindings,high,anchor=native_read(port().publications)
        return PublicationSnapshot(**envelope(),native=native,bindings=bindings,high_water=high,
                                   cursor=_encode(source,high,anchor))

    @app.get('/api/v1/queue',response_model=QueueSnapshot)
    async def queue(request:Request):
        admit(request,'queue.read')
        snapshot=native_read(port().queue)
        return QueueSnapshot(**envelope(),**snapshot)

    def event_page(request,token):
        admit(request,'events.read'); admit(request,'results.read')
        cursor=_decode(token,source) if token is not None else Cursor(
            source_id=source.source_id,generation=source.generation,sequence=0,event_id=None)
        events,more,high=native_read(lambda:port().events(cursor.sequence,cursor.event_id))
        last=events[-1] if events else None
        output_cursor=_encode(source,last['sequence'],last['id']) if last else _encode(source,cursor.sequence,cursor.event_id)
        return EventPage(**envelope(),events=[Event(**e) for e in events],has_more=more,high_water=high,cursor=output_cursor)

    @app.get('/api/v1/events/cases',response_model=EventPage)
    async def events(request:Request,after:str|None=None):
        return event_page(request,after)

    async def stream_page(request:Request):
        return event_page(request,request.headers.get('last-event-id'))

    @app.get('/api/v1/streams/cases',response_class=EventSourceResponse)
    async def stream(request:Request,page:EventPage=Depends(stream_page)):
        # Admission/read failure occurs before response headers; this bounded batch
        # streams existing native revisions, never runs a subscription/controller.
        for event in page.events:
            try: admit(request,'events.read'); admit(request,'results.read')
            except HTTPException: return
            yield ServerSentEvent(event='case_publication',id=_encode(source,event.sequence,event.id),
                                  data=event.model_dump(mode='json'))

    return app
