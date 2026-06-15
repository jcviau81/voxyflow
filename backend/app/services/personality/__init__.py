"""Personality package — mixins and ambient-block builders for PersonalityService.

The public entry point remains ``app.services.personality_service`` (facade).
This package holds the implementation, split by audience:

- ``loader``                — file/settings loading + caching (PersonalityLoaderMixin)
- ``context_blocks``        — chat-init + dynamic context builders (ContextBlocksMixin)
- ``delegate_instructions`` — per-provider delegate/tool instructions (DelegateInstructionsMixin)
- ``dispatcher_prompts``    — dispatcher/autonomy system prompts (DispatcherPromptsMixin)
- ``worker_prompts``        — worker/agent prompts (WorkerPromptsMixin)
- ``ambient_blocks``        — module-level ambient context blocks (pure functions)
"""
