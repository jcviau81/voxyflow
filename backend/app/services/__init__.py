# Services package
#
# Core services:
#   claude_service     — Claude API calls (Fast + Deep layers), personality-infused
#   analyzer_service   — Card detection from conversation + agent routing
#
# Personality layer:
#   personality_service — Loads SOUL/USER/IDENTITY, builds system prompts
#   memory_service      — Reads/writes ~/.openclaw/workspace/ memory files
#
# Agent layer:
#   agent_personas     — Agent type definitions and persona prompts
#   agent_router       — Smart routing of cards to specialized agents
#
# NOTE: tts_service was removed — TTS is now 100% client-side (browser speechSynthesis)
