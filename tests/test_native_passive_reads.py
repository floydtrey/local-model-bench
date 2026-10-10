"""Native passive queue and storage observation regressions, without API extras."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from localbench.queue_gui.core import QueueState,save_state,load_state,read_state_snapshot
from localbench.database_v2.publication_read import PublicationReader
from localbench.database_v2.store import DatabaseError,connect,wal_runtime_safe

class PassiveReadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.path=self.root/'queue.json'
    def test_running_and_pending_action_are_observed_without_recovery(self):
        state=QueueState(); state.add_models(['fixture:model']); state.start(); state.start_next(); state.request_pause()
        save_state(self.path,state); before=self.path.read_bytes(); stamp=self.path.stat().st_mtime_ns
        snapshot=read_state_snapshot(self.path)
        self.assertEqual(snapshot['native']['status'],'Running')
        self.assertEqual(snapshot['native']['pending_action'],'pause')
        self.assertEqual(snapshot['content_sha256'],sha256(before).hexdigest())
        self.assertEqual(self.path.read_bytes(),before); self.assertEqual(self.path.stat().st_mtime_ns,stamp)
        self.assertEqual(load_state(self.path).items[0].status,'Interrupted')
    def test_legacy_observation_preserves_original_hash_and_snapshots_defaults(self):
        state=QueueState(); state.add_models(['fixture:old'])
        settings=asdict(state.settings)
        for key in ('benchmark','through','allow_host_execution'): settings.pop(key)
        items=[{k:v for k,v in asdict(state.items[0]).items() if k!='settings'}]
        data=json.dumps({'version':1,'settings':settings,'items':items,'status':'Idle','pending_action':None}).encode()
        self.path.write_bytes(data)
        observed=read_state_snapshot(self.path)
        self.assertEqual(observed['native_schema_version'],1); self.assertEqual(observed['native']['version'],2)
        self.assertEqual(observed['native']['items'][0]['settings']['benchmark'],'roles')
        self.assertEqual(self.path.read_bytes(),data)
    def test_missing_invalid_and_oversized_never_create_or_replace(self):
        with self.assertRaises(FileNotFoundError): read_state_snapshot(self.path)
        self.assertFalse(self.path.exists())
        for data in (b'{bad',b'x'*20):
            self.path.write_bytes(data)
            with self.assertRaises(ValueError): read_state_snapshot(self.path,maximum_bytes=10)
            self.assertEqual(self.path.read_bytes(),data)
        self.assertEqual(list(self.root.iterdir()),[self.path])
    def test_reader_requires_default_patched_gate_and_query_only_connection(self):
        if not wal_runtime_safe():
            with self.assertRaises(DatabaseError): PublicationReader(None,self.root/'missing-artifacts')
            self.assertFalse((self.root/'missing-artifacts').exists()); return
        con=connect(self.root/'authored.sqlite'); self.addCleanup(con.close)
        with self.assertRaises(DatabaseError): PublicationReader(con,self.root/'missing-artifacts')
        self.assertFalse((self.root/'missing-artifacts').exists())
        con.execute('PRAGMA query_only=ON')
        reader=PublicationReader(con,self.root/'missing-artifacts')
        self.assertEqual(reader.events(),[]); self.assertEqual(reader.event_high_water(),0)
        self.assertEqual(reader.projection()['published_attempts'],0)
        self.assertFalse((self.root/'missing-artifacts').exists())
    def test_passive_reader_exports_no_publication_effects(self):
        for name in ('commit','prepare','artifact','schedule','started','deliver','record_review','recover','export'):
            self.assertFalse(hasattr(PublicationReader,name),name)
