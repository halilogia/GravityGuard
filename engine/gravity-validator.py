#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravityGuard — Lightweight Deterministic Airbag & Architecture Guard.
Zero external dependencies. Sub-10ms in-memory fast path.

This file serves as the official CLI entrypoint for Antigravity hooks (hooks.json).
The implementation is modularized under the `gravityguard_engine` package.
"""
from __future__ import annotations

import os
import sys

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

# Re-export public API symbols for backwards compatibility
from gravityguard_engine import __version__  # noqa: F401
from gravityguard_engine.project_context import (  # noqa: F401
    DEFAULT_COMPLEXITY_THRESHOLDS,
    _COMPLEXITY_THRESHOLD_FLOORS,
    extract_project_info,
    harden_streams_to_utf8,
    is_doc_governed_target,
    load_gravityguard_config,
    resolve_complexity_thresholds,
    resolve_project_root,
    should_enforce_doc_obligations,
)
from gravityguard_engine.audit import (  # noqa: F401
    _resolve_log_dir,
    log_event,
)
from gravityguard_engine.diffing import (  # noqa: F401
    extract_diff_and_projected,
    get_diff_analysis,
    get_projected_and_old_content,
)
from gravityguard_engine.security_rules import (  # noqa: F401
    PLACEHOLDER_KEYWORDS,
    _PEM_BODY_RE,
    check_escape_hatch_tampering,
    check_g0_secret_leak,
    check_g1_silent_exception,
    check_g2_test_integrity,
    is_elided_pem_fixture,
    is_placeholder,
    redact_token,
)
from gravityguard_engine.architecture_rules import (  # noqa: F401
    COHESIVE_MODULE_PATTERNS,
    _get_base_name,
    _has_declared_cohesion_marker,
    _is_exempt_class_ast,
    analyze_python_srp,
    analyze_python_srp_regex_fallback,
    check_arch_file_growth,
    check_g3_compiler_bypass,
    check_g4_import_matrix,
    check_oe_spike,
    is_cohesive_module_by_filename,
    is_py_cohesive_monolith,
    is_ts_cohesive_monolith,
    record_and_check_cumulative_growth,
)
from gravityguard_engine.diagnostics import (  # noqa: F401
    _CREATE_NO_WINDOW,
    _hidden_console_kwargs,
    read_recent_diagnostics,
    trigger_background_validation,
)
from gravityguard_engine.test_evidence import (  # noqa: F401
    DEFAULT_EXEMPT_PATTERNS,
    _TEST_FILE_PATTERNS,
    check_t1_missing_test,
    check_t2_observable_assertion,
    check_t3_symbol_to_test_link,
    evaluate_test_evidence,
    is_exempt_from_test_evidence,
    project_has_test_infrastructure,
    resolve_candidate_test_file,
)
from gravityguard_engine.governance import (  # noqa: F401
    clear_doc_obligations,
    clear_governance_state,
    clear_test_evidence_state,
    get_governance_file_path,
    get_session_stop_retries,
    get_test_evidence_file_path,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
    increment_session_stop_retries,
    load_governance_state,
    load_test_evidence_state,
    reconcile_obligations_on_disk,
    record_pending_doc_obligation,
    record_pending_test_evidence,
    reset_session_stop_retries,
    resolve_pending_doc_obligations,
    resolve_pending_test_evidence,
    save_governance_state,
    save_test_evidence_state,
)
from gravityguard_engine.dispatcher import (  # noqa: F401
    run_cli,
    validate_gravityguard,
)

# Compatibility alias for private function
_harden_streams_to_utf8 = harden_streams_to_utf8

# Stream hardening on import
_harden_streams_to_utf8()

if __name__ == "__main__":
    run_cli()
