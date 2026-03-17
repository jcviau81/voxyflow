# Services package
#
# Core services:
#   claude_service     — Claude API calls (Haiku + Opus), personality-infused
#   chat_service       — Conversation management and persistence
#   tts_service        — Text-to-speech
#   analyzer_service   — Card detection from conversation + agent routing
#
# Personality layer (NEW):
#   personality_service — Loads SOUL/USER/IDENTITY, builds system prompts
#   memory_service      — Reads/writes ~/.openclaw/workspace/ memory files
#
# Agent layer (NEW):
#   agent_personas     — Agent type definitions and persona prompts
#   agent_router       — Smart routing of cards to specialized agents
