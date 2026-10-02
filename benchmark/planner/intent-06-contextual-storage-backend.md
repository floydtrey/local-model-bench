# Planner Intent 06 — contextual storage backend for an always-aware assistant

I am designing an always-aware AI assistant. The long-term assistant will receive input from many sources and decide whether the user needs to be interrupted, whether it should take an authorized action, and what historical or real-time information it should retrieve before making that decision.

The larger project may eventually involve Home Assistant, cameras, Alexa Echo devices, phones, smart-home devices, remote Toyota vehicle controls, custom computer programs, smart glasses, facial recognition, schedules, alarms, weather, HVAC data, and other sensors or services. I may eventually want a VR or smart-glasses dashboard. I may also evaluate different reasoning models later.

Examples of future assistant behavior include:
- An alarm wakes the assistant. It may need to determine whether anything requires action, whether it is cold outside, whether systems are nominal, where the user is, what is on the schedule, whether to start the coffee pot, or whether the car should be started.
- A camera observes that the user's keys are on the kitchen counter. That information should be easy to retrieve later, while still allowing the current location to change when another observation shows that the keys moved.
- Historical HVAC data may show that an air conditioner maintained a 16-degree temperature difference three months ago but only an 11-degree difference today. The storage/retrieval system should make it practical for deterministic software or the assistant to connect those observations and identify a potentially degrading system.
- Smart glasses may eventually identify a person and retrieve the person's name and relevant past information.

These examples describe the larger system and why the storage component matters. They are not separate features to build in this task.

## Current bounded objective

Design and build the backend storage component that can support this future assistant.

The current task is the storage system only. Do not design or build:
- Home Assistant integration;
- device connection points or device-specific adapters;
- camera processing;
- facial recognition;
- Alexa, phone, Toyota, smart-glasses, or VR interfaces;
- dashboards or user interfaces;
- the assistant's interruption/decision engine;
- a reasoning-model selection system.

Those systems may use this storage component later, but they are outside the current scope.

## Required storage behavior

The storage component must support both recent/temporal information and durable long-term information.

It must be able to preserve historical observations while also making the current known state easy to retrieve. A newer observation may change the current state without destroying the older observation that established the previous state.

It must support information arriving from many future sources without requiring the core storage design to be rebuilt for every new device or integration.

Stored information must retain enough source and time context to distinguish observations from different sources and different times.

The system must support relationships between information so relevant historical observations can be connected. This should support cases such as:
- retrieving the latest known location of an object while preserving its movement history;
- comparing current measurements with older measurements;
- retrieving related historical information about an entity, device, place, or observation.

Retrieval must work for assistants with both small and large context windows. The storage system should not require dumping an entire history into the model. It should make it possible to retrieve a bounded amount of the most relevant information while retaining access to exact underlying records when needed.

Where deterministic storage, indexing, current-state maintenance, relationship tracking, filtering, or retrieval can do the work reliably, prefer that over requiring the AI model to remember, infer, or reconstruct it from conversation history.

The component should be testable on the current local development system and should follow the existing General Intent preference for the simplest proven path and minimal unnecessary infrastructure.

## Implementation freedom

No storage engine or database technology is preselected for this fixture. Choosing the implementation approach is part of the bounded engineering work. The choice should be justified by the requirements above and should not create unrelated infrastructure.

The implementation should begin with the backend and a testable storage/retrieval interface. A graphical interface is not part of this task.

## Acceptance direction

The completed component should be demonstrably capable of:
- recording timestamped observations from multiple generic sources;
- preserving observation history;
- updating and retrieving current known state without deleting history;
- associating related information for later retrieval;
- querying historical observations by entity/source/time;
- retrieving enough related history to support a simple trend comparison such as the HVAC example;
- returning bounded relevant context rather than an unfiltered full history;
- exposing exact stored records when requested;
- adding a new generic source without redesigning the storage core;
- running locally with automated tests for the required behaviors.

The plan should stay focused on this storage component. The larger assistant examples are provided so the storage design preserves the right long-term direction, not so the current work expands into building those other systems.
