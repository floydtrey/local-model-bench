"""C1 deterministic transport fixtures. No real principals, models or controls."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import contextlib
import socket
import threading
import time
import urllib.request
import unittest
from unittest.mock import Mock, patch

HAS_API=importlib.util.find_spec('fastapi') is not None
if os.environ.get('LOCALBENCH_REQUIRE_API')=='1' and not HAS_API:
    raise RuntimeError('Qualified API environment is required')
if HAS_API:
    from localbench.api import create_app
    from localbench.api.dto import SourceIdentity, Event, Cursor, Observation
    from localbench.api.ports import NativeReadPort
    from localbench.api.testing import FixturePrincipal, create_fixture_app
    from localbench.database_v2.publication_read import PublicationReader

def request(app,path,*,headers=None,method='GET',query='',body=b''):
    async def run():
        output=[]; sent=False; done=asyncio.Event()
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
               'method':method,'scheme':'http','path':path,'raw_path':path.encode(),
               'query_string':query.encode(),'root_path':'','client':('127.0.0.1',1),
               'server':('127.0.0.1',8000),'headers':[(k.lower().encode(),v.encode()) for k,v in
               {'host':'127.0.0.1:8000',**(headers or {})}.items()]}
        async def receive():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':body,'more_body':False}
            await done.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            output.append(message)
            if message['type']=='http.response.body' and not message.get('more_body',False): done.set()
        await asyncio.wait_for(app(scope,receive,send),5)
        status=next(x['status'] for x in output if x['type']=='http.response.start')
        payload=b''.join(x.get('body',b'') for x in output if x['type']=='http.response.body')
        return status,payload
    return asyncio.run(run())

@unittest.skipUnless(HAS_API,'Optional API dependencies absent from base CLI environment')
class APIFixtures(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,10,tzinfo=timezone.utc)
        self.source=SourceIdentity(source_id='authored-fixture',generation='fixture-generation',mode='fixture')
        self.port=Mock(); self.port.source=self.source
        self.actor=FixturePrincipal('fixture-owner','benchmark-api-fixture',
            frozenset({'results.read','events.read','health.read','queue.read'}),self.now+timedelta(seconds=30))
    def app(self,validator=None):
        return create_fixture_app(read_port=self.port,validator=validator or (lambda request:self.actor),clock=lambda:self.now)
    def test_default_deny_stops_before_every_reader(self):
        app=create_app(read_port=self.port)
        for path in ('/health','/publications','/queue','/events/cases','/streams/cases'):
            status,_=request(app,'/api/v1'+path,headers={'X-Owner':'true','Authorization':'Bearer fixture'})
            self.assertEqual(status,401)
        self.assertEqual(self.port.mock_calls,[])
    def test_liveness_contains_only_transport_fact(self):
        status,payload=request(create_app(read_port=self.port),'/api/v1/liveness')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(payload),{'schema_version':'benchmark-api:v1','transport_alive':True})
        self.assertEqual(self.port.mock_calls,[])
    def test_uvicorn_ephemeral_loopback_lifespan_and_native_sse(self):
        import uvicorn
        marks=[]
        @contextlib.asynccontextmanager
        async def lifespan(app):
            marks.append('started')
            yield
            marks.append('stopped')
        self.port.events.return_value=([{'sequence':1,'id':'authored-event','attempt_id':'attempt',
            'revision':1,'stage':'capture','result_id':None}],False,1)
        app=self.app(); app.router.lifespan_context=lifespan
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(16)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=sock.getsockname()[1],
            loop='asyncio',http='h11',proxy_headers=False,lifespan='on',access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+10
            while not server.started and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(server.started)
            prefix=f'http://127.0.0.1:{sock.getsockname()[1]}'
            with urllib.request.urlopen(prefix+'/api/v1/liveness',timeout=3) as response:
                self.assertEqual(json.load(response),{'schema_version':'benchmark-api:v1','transport_alive':True})
            with urllib.request.urlopen(prefix+'/api/v1/streams/cases',timeout=3) as response:
                body=response.read()
                self.assertTrue(response.headers['content-type'].startswith('text/event-stream'))
                self.assertIn(b'authored-event',body)
        finally:
            server.should_exit=True; thread.join(10); sock.close()
        self.assertFalse(thread.is_alive()); self.assertEqual(marks,['started','stopped'])
    def test_wrong_audience_expired_and_forged_denied(self):
        for actor in (None, {'subject':'fixture-owner'},FixturePrincipal('owner','kc',self.actor.grants,self.actor.expires_at),
                      FixturePrincipal('owner',self.actor.audience,self.actor.grants,self.now)):
            app=create_fixture_app(read_port=self.port,validator=lambda request:actor,clock=lambda:self.now)
            self.assertEqual(request(app,'/api/v1/publications')[0],401)
        self.assertEqual(self.port.mock_calls,[])
    def test_missing_grants_do_not_read(self):
        self.actor=FixturePrincipal('viewer','benchmark-api-fixture',frozenset({'health.read'}),self.actor.expires_at)
        for path in ('/publications','/queue','/events/cases','/streams/cases'):
            self.assertEqual(request(self.app(),'/api/v1'+path)[0],403)
        self.assertEqual(self.port.mock_calls,[])
    def test_no_mutation_login_or_fixture_actor_routes(self):
        app=self.app()
        self.assertEqual(request(app,'/api/v1/publications',method='POST')[0],405)
        for path in ('/login','/api/v1/actor','/api/v1/token','/api/v1/queue/start','/api/v1/artifacts','/docs'):
            self.assertEqual(request(app,path)[0],404)
        self.assertEqual(self.port.mock_calls,[])
    def test_host_and_get_body_rejected(self):
        app=self.app()
        self.assertEqual(request(app,'/api/v1/publications',headers={'host':'attacker.example'})[0],400)
        self.assertEqual(request(app,'/api/v1/publications',headers={'content-length':'1'},body=b'x')[0],400)
        self.assertEqual(self.port.mock_calls,[])
    def test_unknown_query_and_invalid_fixture_fields_fail_closed(self):
        self.assertEqual(request(self.app(),'/api/v1/publications',query='path=private')[0],400)
        for actor in (FixturePrincipal('owner',self.actor.audience,'results.read',self.actor.expires_at),
                      FixturePrincipal('owner',self.actor.audience,self.actor.grants,'tomorrow')):
            app=create_fixture_app(read_port=self.port,validator=lambda request:actor,clock=lambda:self.now)
            self.assertEqual(request(app,'/api/v1/publications')[0],401)
        self.assertEqual(self.port.mock_calls,[])
    def test_fixture_injection_cannot_advertise_installed_source(self):
        self.port.source=SourceIdentity(source_id='development',generation='one',mode='development')
        with self.assertRaises(ValueError): self.app()
        self.assertEqual(self.port.mock_calls,[])
    def test_consumer_timeout_denial_missing_and_invalid_are_unknown(self):
        for exception,coverage in ((TimeoutError,'timeout'),(PermissionError,'denied'),(ValueError,'invalid')):
            self.port.health.side_effect=exception('unsafe private path')
            status,payload=request(self.app(),'/api/v1/health')
            self.assertEqual(status,200)
            data=json.loads(payload); db=next(x for x in data['observations'] if x['scope']=='database_reads')
            self.assertEqual(db['status'],'unknown'); self.assertEqual(db['coverage'],'unknown')
            self.assertEqual(db['coverage_reason'],coverage)
            self.assertNotIn('unsafe private path',payload.decode()); self.assertIsNone(data['aggregate_status'])
        self.port.health.side_effect=None; self.port.health.return_value={'schema_version':10,'sqlite_version':'3.53.4'}
        status,payload=request(self.app(),'/api/v1/health')
        self.assertTrue(all(x['status']=='unknown' and x['expires_at'] is None for x in json.loads(payload)['observations']))
    def test_strict_identity_event_and_cursor_units(self):
        from pydantic import ValidationError
        for fields in ({'sequence':True},{'sequence':-1},{'result_id':'fake'}):
            value={'sequence':1,'id':'publication','attempt_id':'a','revision':1,'stage':'capture','result_id':None,**fields}
            with self.assertRaises(ValidationError): Event(**value)
        with self.assertRaises(ValidationError): SourceIdentity(**{**self.source.model_dump(),'extra':True})
        with self.assertRaises(ValidationError): Cursor(source_id='s',generation='g',sequence='1',event_id='x')

@unittest.skipUnless(HAS_API,'Optional API dependencies absent')
class NativeAPIFixtures(unittest.TestCase):
    def setUp(self):
        from test_case_publication_revisions import PublicationRevisionTests
        from localbench.database_v2.store import wal_runtime_safe
        if not wal_runtime_safe(): self.skipTest('API operational reader requires patched runtime')
        self.native=PublicationRevisionTests(); self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.run=self.native.root/'authored-capture'; self.key=self.native.register(self.run)
        self.publication_id=self.native.capture(self.run,self.key)
        uri=(self.native.root/'cases.sqlite3').resolve().as_uri()+'?mode=ro'
        self.read=sqlite3.connect(uri,uri=True,check_same_thread=False,isolation_level=None,timeout=.25)
        self.addCleanup(self.read.close)
        self.read.execute('PRAGMA query_only=ON')
        self.source=SourceIdentity(source_id='authored-native',generation='fixture-native',mode='fixture')
        self.reader=PublicationReader(self.read,self.native.pub.root)
        self.port=NativeReadPort(self.reader,self.source)
        self.now=datetime(2026,10,10,tzinfo=timezone.utc)
        self.actor=FixturePrincipal('fixture','benchmark-api-fixture',frozenset({'results.read','events.read','health.read','queue.read'}),self.now+timedelta(seconds=10))
        self.app=create_fixture_app(read_port=self.port,validator=lambda request:self.actor,clock=lambda:self.now)
    def test_pending_capture_then_late_assessment_same_population(self):
        status,body=request(self.app,'/api/v1/publications'); data=json.loads(body)
        self.assertEqual(status,200); self.assertEqual(data['native'],self.native.pub.projection())
        self.assertEqual(data['native']['rows'][0]['assessment_state'],'pending')
        for name in ('score','maximum_score','assessed_outcome'): self.assertIsNone(data['native']['rows'][0][name])
        cursor=data['cursor']; binding=data['bindings'][0]
        self.native.assessed(self.run,self.key)
        status,body=request(self.app,'/api/v1/publications'); later=json.loads(body)
        self.assertEqual(later['native'],self.native.pub.projection())
        self.assertEqual(later['native']['published_attempts'],1); self.assertEqual(later['native']['committed_results'],1)
        self.assertEqual(later['bindings'][0]['attempt_id'],binding['attempt_id'])
        events=json.loads(request(self.app,'/api/v1/events/cases',query='after='+cursor)[1])['events']
        self.assertEqual([x['stage'] for x in events],['assessed']); self.assertIsNotNone(events[0]['result_id'])
        self.assertEqual(self.native.db.execute('SELECT count(*) FROM attempts').fetchone()[0],1)
    def test_read_only_passivity_and_no_writer_methods(self):
        before=self.native.db.total_changes
        self.assertFalse(hasattr(self.reader,'commit')); self.assertFalse(hasattr(self.reader,'recover'))
        with patch('localbench.database_v2.store.migrate',side_effect=AssertionError('GET migrated')):
            for path in ('/publications','/events/cases','/health'):
                self.assertEqual(request(self.app,'/api/v1'+path)[0],200)
        self.assertEqual(self.native.db.total_changes,before)
        self.assertEqual(self.read.total_changes,0); self.assertFalse(self.read.in_transaction)
        with self.assertRaises(sqlite3.OperationalError): self.read.execute('DELETE FROM case_publication_events')
    def test_sse_uses_native_stable_ids_and_validates_before_headers(self):
        status,body=request(self.app,'/api/v1/streams/cases')
        self.assertEqual(status,200); self.assertIn(b'event: case_publication',body)
        payload=json.loads(next(line[6:] for line in body.splitlines() if line.startswith(b'data: ')))
        self.assertEqual(payload['id'],self.publication_id); self.assertIsNone(payload['result_id'])
        self.assertEqual(request(self.app,'/api/v1/streams/cases',headers={'Last-Event-ID':'invalid'})[0],409)
    def test_cursor_wrong_source_generation_and_future_reset(self):
        from localbench.api.app import _encode
        for token in (_encode(self.source,9,'absent'),_encode(SourceIdentity(source_id='other',generation='fixture-native',mode='fixture'),1,self.publication_id),
                      _encode(SourceIdentity(source_id='authored-native',generation='restored',mode='fixture'),1,self.publication_id)):
            self.assertEqual(request(self.app,'/api/v1/events/cases',query='after='+token)[0],409)
    def test_same_sequence_with_changed_history_anchor_resets(self):
        from localbench.api.app import _encode
        token=_encode(self.source,1,'different-restored-event')
        self.assertEqual(request(self.app,'/api/v1/events/cases',query='after='+token)[0],409)
    def test_verified_producer_failure_is_separate_from_unknown_consumer_coverage(self):
        with patch('localbench.api.ports.wal_runtime_safe',return_value=False):
            status,body=request(self.app,'/api/v1/health')
        db=next(x for x in json.loads(body)['observations'] if x['scope']=='database_reads')
        self.assertEqual(status,200); self.assertEqual(db['producer_outcome'],'failed')
        self.assertEqual(db['coverage'],'unknown'); self.assertIsNotNone(db['observed_at'])
    def test_missing_and_tampered_evidence_keep_native_unknown_semantics(self):
        relative=self.native.db.execute('SELECT relative_path FROM artifacts LIMIT 1').fetchone()[0]
        (self.native.pub.root/relative).write_bytes(b'authored tampering')
        status,body=request(self.app,'/api/v1/publications')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['native'],self.native.pub.projection())
        self.assertEqual(json.loads(body)['native']['rows'][0]['publication_integrity'],'evidence_unavailable')
    def test_queue_snapshot_does_not_recover_running_item(self):
        from localbench.queue_gui.core import QueueState,save_state,load_state
        state=QueueState(); state.add_models(['authored:fixture']); state.start(); state.start_next()
        path=self.native.root/'queue.json'; save_state(path,state)
        self.port.queue_path=path; before=path.read_bytes()
        status,body=request(self.app,'/api/v1/queue'); data=json.loads(body)
        self.assertEqual(status,200); self.assertEqual(data['native']['status'],'Running')
        self.assertEqual(data['native']['items'][0]['status'],'Running')
        self.assertEqual(data['custody'],'unknown'); self.assertIsNone(data['owner_observed_at'])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(load_state(path).items[0].status,'Interrupted')
    def test_health_does_not_verify_evidence_project_or_recover(self):
        with patch.object(self.reader,'projection',side_effect=AssertionError('health projected')), \
             patch.object(self.reader,'_verify',side_effect=AssertionError('health hashed')):
            self.assertEqual(request(self.app,'/api/v1/health')[0],200)
    def test_stream_revalidates_authority_after_admission(self):
        seen=[]
        def validator(request):
            seen.append(True)
            return self.actor if len(seen)<=2 else None
        app=create_fixture_app(read_port=self.port,validator=validator,clock=lambda:self.now)
        status,body=request(app,'/api/v1/streams/cases')
        self.assertEqual(status,200); self.assertNotIn(b'data:',body)
        self.assertGreater(len(seen),2)
