# GravityGuard — duyuru taslakları

Hepsi elle paylaşılmak üzere hazırlandı (hesabın adına dışarıya yayın yapılmadı).

## Show HN
**Başlık:** Show HN: GravityGuard – hooks that stop AI coding agents from deleting tests or leaking keys

**Metin:**
I kept seeing coding agents "fix" a failing test by adding `@pytest.mark.skip`, swallow errors with `except: pass`, or paste an API key into a file. A rule in a prompt is a wish, so I built a PreToolUse hook that evaluates the diff before the write happens and refuses it.

- Pure in-memory evaluation, ~0.1 ms avg, Python stdlib only, no LLM in the loop
- Rules: secret leaks (OpenAI/Anthropic/Gemini/Slack/GitHub/private keys), test deletion/skipping, silent exceptions, layer-boundary imports, god-files
- Works with Claude Code (settings.json hook) and Antigravity IDE
- GPL-3.0, 300+ tests

Demo and 2-minute setup: https://github.com/halilogia/GravityGuard

Happy to hear which rules you'd want that I'm missing.

## Reddit (r/ClaudeAI, r/LocalLLaMA)
**Başlık:** My Claude Code agent started skipping failing tests, so I wrote a hook that blocks it

Aynı gövde; r/LocalLLaMA için "no LLM in the loop, runs locally" vurgusunu öne al. Kural: her subreddit'in kendi tanıtım kuralını önce oku.

## Awesome listeleri (PR satırı)
- awesome-claude-code: `[GravityGuard](https://github.com/halilogia/GravityGuard) - Deterministic PreToolUse/Stop hooks that block leaked secrets, silenced tests and silent exceptions.`
- awesome-mcp-servers / awesome-ai-agents: aynı satır, ilgili kategoriye (Security / Guardrails).

## Ivan'a (XERJ) hatırlatma — bir hafta sonra
Hi Ivan, GravityGuard v1.4.18 is now out with a Claude Code quick start in the README. If the Corpus Hub entry is live, I'd love a link. Thanks!
