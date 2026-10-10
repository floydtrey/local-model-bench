"""Versioned transport envelopes; native rows and scores retain their own schemas."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

API_VERSION = 'benchmark-api:v1'

class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False, frozen=True)

class SourceIdentity(StrictModel):
    source_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')
    generation: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')
    mode: Literal['development', 'fixture']
    software_commit: str | None = Field(default=None, pattern=r'^[0-9a-f]{40}$')
    deployment_commit: None = None

class Observation(StrictModel):
    scope: Literal['api_transport', 'database_reads', 'queue_owner', 'model_runtime', 'resources']
    status: Literal['healthy', 'degraded', 'unavailable', 'unknown']
    coverage: Literal['observed', 'unknown']
    coverage_reason: Literal['observed', 'not_checked', 'missing', 'denied', 'expired', 'invalid', 'timeout']
    reason_code: Literal['transport_alive', 'native_read_ready', 'freshness_policy_unset',
                         'not_observed', 'reader_missing', 'reader_denied', 'reader_timeout',
                         'reader_failed', 'observation_expired', 'observation_invalid']
    method_revision: str
    source: str
    required_for: tuple[str, ...]
    observed_at: datetime | None
    received_at: datetime
    expires_at: datetime | None
    sample_started_at: datetime | None
    sample_ended_at: datetime | None
    producer_outcome: Literal['ready', 'failed', 'not_observed'] = 'not_observed'
    values: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def truthful_coverage(self):
        if self.status != 'unknown' and (self.coverage != 'observed' or self.observed_at is None
                                        or self.expires_at is None):
            raise ValueError('A non-unknown status needs observed bounded evidence')
        if any(t is not None and (t.tzinfo is None or t.utcoffset() is None) for t in
               (self.observed_at, self.received_at, self.expires_at, self.sample_started_at, self.sample_ended_at)):
            raise ValueError('Observation times must be aware')
        if (self.sample_started_at is None) != (self.sample_ended_at is None):
            raise ValueError('Sample interval must be complete or absent')
        if self.sample_started_at is not None and self.sample_ended_at < self.sample_started_at:
            raise ValueError('Sample interval reversed')
        if self.expires_at is not None and (self.observed_at is None or self.expires_at < self.observed_at):
            raise ValueError('Expiry precedes observation')
        return self

class Cursor(StrictModel):
    version: Literal['benchmark-case-cursor:v1'] = 'benchmark-case-cursor:v1'
    scope: Literal['case_publication'] = 'case_publication'
    source_id: str
    generation: str
    sequence: int = Field(ge=0)
    event_id: str | None

class Event(StrictModel):
    sequence: int = Field(ge=1)
    id: str
    attempt_id: str
    revision: int = Field(ge=1)
    stage: Literal['capture', 'assessed']
    result_id: str | None

    @model_validator(mode='after')
    def result_binding(self):
        if (self.stage == 'capture') != (self.result_id is None):
            raise ValueError('Capture and assessed result bindings differ')
        return self

class Envelope(StrictModel):
    schema_version: Literal['benchmark-api:v1'] = API_VERSION
    boot_id: str
    source: SourceIdentity
    received_at: datetime

class LatestBinding(Event):
    publication_id: str
    trial_id: str
    case_id: str
    run_id: str
    configuration_id: str
    protocol_id: str

    @model_validator(mode='after')
    def same_publication(self):
        if self.publication_id != self.id:
            raise ValueError('Publication binding differs')
        return self

class PublicationSnapshot(Envelope):
    high_water: int = Field(ge=0)
    cursor: str
    native: dict[str, JsonValue]
    bindings: list[dict[str, JsonValue]]
    evidence_check: Literal['native_current_files'] = 'native_current_files'
    count_units: dict[str, str] = Field(default_factory=lambda: {
        'published_attempts':'canonical_attempts', 'committed_results':'assessed_publications',
        'high_water':'publication_revisions', 'native_rows':'native_rows_not_case_denominators'})

    @model_validator(mode='after')
    def native_contract(self):
        if (self.native.get('schema_version') != 'benchmark-case-publication:v2'
            or type(self.native.get('published_attempts')) is not int
            or type(self.native.get('committed_results')) is not int
            or type(self.native.get('cursor')) is not int or self.native.get('cursor') != self.high_water
            or not isinstance(self.native.get('rows'),list)
            or self.native['published_attempts'] != len(self.bindings)
            or self.native['committed_results'] != sum(b.get('result_id') is not None for b in self.bindings)):
            raise ValueError('Native publication/count/cursor mismatch')
        for binding in self.bindings:
            LatestBinding(**{**binding,'id':binding['publication_id']})
        return self

class EventPage(Envelope):
    high_water: int = Field(ge=0)
    cursor: str
    has_more: bool
    events: list[Event]
    producer_event_time: None = None

class StreamEvent(Envelope):
    cursor: str
    event: Event
    producer_event_time: None = None

class QueueSnapshot(Envelope):
    native_schema_version: int
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    native: dict[str, JsonValue]
    custody: Literal['unknown'] = 'unknown'
    owner_observed_at: None = None

class Health(Envelope):
    observations: list[Observation]
    aggregate_status: None = None
    freshness_policy: Literal['unaccepted'] = 'unaccepted'
