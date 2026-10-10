"""
Empirical AI Telemetry & Benchmark Test
Tests real LLM performance (space-bunny / 9router) under GravityGuard supervision.
Measures:
- Latency (ms)
- Prompt & Completion tokens
- PreToolUse decisions (ALLOW / DENY)
- Stop Hook enforcement (Does it catch missing CHANGELOG?)
- Model self-correction (How easily does it resolve the doc obligation?)
- Final Stop clearance
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path
import httpx

ROUTER_URL = os.environ.get("ROUTER_URL", "http://127.0.0.1:20128/v1/chat/completions")
API_KEY = os.environ.get("ROUTER_API_KEY", "")
MODEL = os.environ.get("ROUTER_MODEL", "cmc/stealth/space-bunny-alpha")

SANDBOX_DIR = Path(__file__).resolve().parent.parent / "tests" / "sandbox"
GG_VALIDATOR = Path(__file__).resolve().parent.parent / "engine" / "gravity-validator.py"

telemetry = {
    "model": MODEL,
    "steps": [],
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_time_seconds": 0.0,
    "stop_blocked": False,
    "stop_resolved": False,
}

def call_model(messages, system_prompt=None):
    payload_messages = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(messages)
    
    t0 = time.time()
    resp = httpx.post(
        ROUTER_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": MODEL, "messages": payload_messages, "temperature": 0.2},
        timeout=30.0
    )
    dt = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    p_tok = usage.get("prompt_tokens", 0)
    c_tok = usage.get("completion_tokens", 0)
    telemetry["total_prompt_tokens"] += p_tok
    telemetry["total_completion_tokens"] += c_tok
    telemetry["total_time_seconds"] += dt
    content = data["choices"][0]["message"]["content"]
    return content, p_tok, c_tok, dt

def run_gg_pre_tool(tool_name, target_file, new_content, old_content=""):
    payload = {
        "conversationId": "benchmark-test-conv-001",
        "workspacePaths": [str(SANDBOX_DIR)],
        "toolCall": {
            "name": tool_name,
            "args": {
                "TargetFile": str(target_file),
                "CodeContent": new_content
            }
        }
    }
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(GG_VALIDATOR)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(SANDBOX_DIR)
    )
    dt = time.time() - t0
    decision = "unknown"
    reason = proc.stderr or proc.stdout
    try:
        out_json = json.loads(proc.stdout)
        decision = out_json.get("decision", "unknown")
        reason = out_json.get("reason", reason)
    except Exception:
        pass
    return decision, reason, dt

def run_gg_stop():
    payload = {
        "conversationId": "benchmark-test-conv-001",
        "workspacePaths": [str(SANDBOX_DIR)],
        "terminationReason": "agent_stop"
    }
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(GG_VALIDATOR), "--stop"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(SANDBOX_DIR)
    )
    dt = time.time() - t0
    decision = "unknown"
    reason = proc.stderr or proc.stdout
    try:
        out_json = json.loads(proc.stdout)
        decision = out_json.get("decision", "unknown")
        reason = out_json.get("reason", reason)
    except Exception:
        pass
    return decision, reason, dt

def main():
    print(f"=== Starting Empirical Telemetry Test with Model: {MODEL} ===")
    
    # Step 1: Request code implementation
    calc_path = SANDBOX_DIR / "src" / "calculator.py"
    current_calc = calc_path.read_text(encoding="utf-8")
    
    prompt_code = (
        f"Here is current src/calculator.py:\n```python\n{current_calc}\n```\n"
        "Please add a function `divide(a: float, b: float) -> float`. "
        "If b == 0, raise ValueError('Division by zero'). "
        "Return ONLY the updated python file content inside ```python ```."
    )
    
    print("\n[Step 1] Requesting code implementation from AI...")
    content_code, p_tok, c_tok, dt = call_model([{"role": "user", "content": prompt_code}])
    print(f"  AI generated code in {dt:.2f}s | Tokens: {p_tok} prompt, {c_tok} completion")
    
    # Extract code
    new_code = content_code
    if "```python" in content_code:
        new_code = content_code.split("```python")[1].split("```")[0].strip()
    elif "```" in content_code:
        new_code = content_code.split("```")[1].split("```")[0].strip()
    
    # Evaluate with GravityGuard PreToolUse
    print("  Testing PreToolUse hook on src/calculator.py...")
    decision, reason, gg_dt = run_gg_pre_tool("write_to_file", calc_path, new_code, current_calc)
    print(f"  GravityGuard Decision: {decision.upper()} in {gg_dt*1000:.1f}ms (Reason: {reason})")
    
    if decision == "allow":
        calc_path.write_text(new_code, encoding="utf-8")
        print("  File written to disk.")
    
    telemetry["steps"].append({
        "step": "write_code",
        "tokens": {"prompt": p_tok, "completion": c_tok},
        "ai_latency_sec": dt,
        "gg_decision": decision,
        "gg_latency_ms": gg_dt * 1000
    })

    # Step 2: Request unit test
    test_path = SANDBOX_DIR / "tests" / "test_calculator.py"
    current_test = test_path.read_text(encoding="utf-8")
    prompt_test = (
        f"Here is current tests/test_calculator.py:\n```python\n{current_test}\n```\n"
        "Add a unit test `test_divide` testing normal division and `assertRaises(ValueError)` when dividing by zero. "
        "Return ONLY the updated python test file content inside ```python ```."
    )
    print("\n[Step 2] Requesting unit test from AI...")
    content_test, p_tok, c_tok, dt = call_model([{"role": "user", "content": prompt_test}])
    print(f"  AI generated test in {dt:.2f}s | Tokens: {p_tok} prompt, {c_tok} completion")
    
    new_test = content_test
    if "```python" in content_test:
        new_test = content_test.split("```python")[1].split("```")[0].strip()
    elif "```" in content_test:
        new_test = content_test.split("```")[1].split("```")[0].strip()

    print("  Testing PreToolUse hook on tests/test_calculator.py...")
    decision, reason, gg_dt = run_gg_pre_tool("write_to_file", test_path, new_test, current_test)
    print(f"  GravityGuard Decision: {decision.upper()} in {gg_dt*1000:.1f}ms")
    if decision == "allow":
        test_path.write_text(new_test, encoding="utf-8")
        print("  Test file written to disk.")

    telemetry["steps"].append({
        "step": "write_test",
        "tokens": {"prompt": p_tok, "completion": c_tok},
        "ai_latency_sec": dt,
        "gg_decision": decision,
        "gg_latency_ms": gg_dt * 1000
    })

    # Step 3: Trigger STOP hook WITHOUT updating CHANGELOG
    print("\n[Step 3] AI tries to EXIT / STOP session (without updating CHANGELOG)...")
    stop_dec, stop_reason, stop_dt = run_gg_stop()
    print(f"  GravityGuard Stop Hook Result: {stop_dec.upper()} in {stop_dt*1000:.1f}ms")
    print(f"  Stop Hook Feedback to AI: \"{stop_reason}\"")
    
    if stop_dec == "continue":
        telemetry["stop_blocked"] = True
        print("  --> CONFIRMED: GravityGuard successfully caught the missing CHANGELOG and blocked exit!")
    else:
        print("  --> WARNING: Stop was not blocked!")

    # Step 4: Give the stop feedback back to the AI model
    print("\n[Step 4] Giving GravityGuard's feedback to the AI and asking for resolution...")
    prompt_fix = (
        f"GravityGuard blocked your session termination with the following reason:\n'{stop_reason}'\n\n"
        "Here is the current CHANGELOG.md:\n```markdown\n"
        + (SANDBOX_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        + "\n```\n"
        "Please provide the updated CHANGELOG.md content adding the new `divide` function under [Unreleased] Added. "
        "Return ONLY the updated markdown inside ```markdown ```."
    )
    content_cl, p_tok, c_tok, dt = call_model([{"role": "user", "content": prompt_fix}])
    print(f"  AI responded in {dt:.2f}s | Tokens: {p_tok} prompt, {c_tok} completion")
    
    new_cl = content_cl
    if "```markdown" in content_cl:
        new_cl = content_cl.split("```markdown")[1].split("```")[0].strip()
    elif "```" in content_cl:
        new_cl = content_cl.split("```")[1].split("```")[0].strip()

    cl_path = SANDBOX_DIR / "CHANGELOG.md"
    current_cl = cl_path.read_text(encoding="utf-8")
    decision, reason, gg_dt = run_gg_pre_tool("write_to_file", cl_path, new_cl, current_cl)
    print(f"  GravityGuard CHANGELOG write decision: {decision.upper()} in {gg_dt*1000:.1f}ms")
    if decision == "allow":
        cl_path.write_text(new_cl, encoding="utf-8")
        print("  CHANGELOG.md physically updated on disk.")

    # Step 5: Test STOP hook AGAIN
    print("\n[Step 5] AI calls STOP hook again after updating CHANGELOG...")
    final_dec, final_reason, final_dt = run_gg_stop()
    print(f"  GravityGuard Stop Hook Result: {final_dec.upper()} in {final_dt*1000:.1f}ms")
    if final_dec == "allow":
        telemetry["stop_resolved"] = True
        print("  --> SUCCESS: GravityGuard verified physical SHA-256 disk change and ALLOWED exit!")
    else:
        print(f"  --> Still blocked: {final_reason}")

    print("\n" + "="*50)
    print("=== TELEMETRY SUMMARY REPORT ===")
    print(f"Model Tested: {telemetry['model']}")
    print(f"Total Prompt Tokens: {telemetry['total_prompt_tokens']}")
    print(f"Total Completion Tokens: {telemetry['total_completion_tokens']}")
    print(f"Total AI Time: {telemetry['total_time_seconds']:.2f}s")
    print(f"Stop Hook Caught Omission: {'YES' if telemetry['stop_blocked'] else 'NO'}")
    print(f"Obligation Cleared After Doc Write: {'YES' if telemetry['stop_resolved'] else 'NO'}")
    print("="*50)

    # Save report
    out_file = Path(r"C:\Users\Halil Emre\.gemini\antigravity\scratch\benchmark_report.json")
    out_file.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
    print(f"Detailed JSON report saved to: {out_file}")

if __name__ == "__main__":
    main()
