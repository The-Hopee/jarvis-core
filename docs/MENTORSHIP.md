# Project record

2026-11-04: native kernel stage requested and implemented.

The user defined the architecture and requirements: C++ Windows operations,
Python agents and a collector, JSON context sent through OpenRouter, then a
spoken response. The assistant implemented this native stage from the reviewed
Rikor source modules and wrote the build, protocol, Python bridge examples and
integration checks.

Current validated project capability is the native kernel and its Python
boundary. The user's independent Python/ML proficiency has not yet been assessed
from submitted code. Resume wording must distinguish architecture/requirements
work, assisted implementation and the user's later independent contributions.

2026-11-04: the user separated Jarvis from the mentoring curriculum. Jarvis is a
home tool implemented on request. ML study will start with a shared foundation;
the user is interested in NLP, computer vision, speech/audio and recommender
systems and will choose one or more specializations later. Do not require Jarvis
implementation as homework or treat assisted code as independent ML experience.

Stage 2 implements the Python controller, persistent IPC, OpenRouter tool calling,
Russian speech input/output, browser/Telegram commands, weather and places tools.
Live OpenRouter inference was initially deferred; version 0.4 now validates real
chat/tool calls with a separate inference key. See VALIDATION.md for current limits.

Latest user requirements and the next-session handoff are recorded in
[NEXT_SESSION.md](NEXT_SESSION.md). These supersede earlier choices of voice,
learning-by-Jarvis assignments and feature priorities.
