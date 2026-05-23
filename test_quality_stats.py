#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3 Quality Stats Verification Script

This script simulates calling the /api/v1/live-text/zhiboba/relations/extract endpoint
and validates that the new quality statistics fields are returned correctly.

Usage:
    python test_quality_stats.py [--saishi_id SAISHI_ID] [--base-url URL] [--timeout SECONDS]

Examples:
    python test_quality_stats.py                          # Use default game 1780736
    python test_quality_stats.py --saishi_id 1780736      # Specific game
    python test_quality_stats.py --base-url http://localhost:8003 --timeout 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import requests
except ImportError:
    print("[ERROR] Please install requests: pip install requests")
    sys.exit(1)


@dataclass
class ValidationResult:
    """Holds validation results for each quality stat field."""
    field_name: str
    expected_type: type
    actual_value: Any = None
    is_valid: bool = False
    error_message: str = ""


@dataclass
class TestReport:
    """Complete test report with all validations."""
    saishi_id: str = ""
    api_url: str = ""
    status_code: int = 0
    response_time_seconds: float = 0.0
    processed: bool = False
    
    # Core fields
    events: int = 0
    relations_raw: int = 0
    relations_filtered: int = 0
    relations_inserted: int = 0
    backend: str = ""
    model_name: str = ""
    
    # Quality stats (Phase 3 new fields)
    quality_stats_present: bool = False
    quality_original_count: int | None = None
    quality_filtered_count: int | None = None
    quality_removed_count: int | None = None
    quality_pass_rate: float | None = None
    quality_removal_reasons: dict[str, int] = field(default_factory=dict)
    
    # Validation results
    validations: list[ValidationResult] = field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    
    # Samples
    samples_count: int = 0


def validate_response_structure(response_json: dict[str, Any]) -> list[ValidationResult]:
    """Validate the structure and types of all response fields."""
    results = []
    
    # Validate top-level required fields
    required_fields = {
        "processed": bool,
        "saishi_id": str,
        "events": int,
        "backend": str,
        "model_name": str,
        "samples": list,
    }
    
    for field_name, expected_type in required_fields.items():
        result = ValidationResult(
            field_name=field_name,
            expected_type=expected_type,
            actual_value=response_json.get(field_name),
        )
        
        if field_name not in response_json:
            result.is_valid = False
            result.error_message = f"Missing required field: {field_name}"
        elif not isinstance(response_json[field_name], expected_type):
            result.is_valid = False
            result.error_message = (
                f"Type mismatch for {field_name}: "
                f"expected {expected_type.__name__}, "
                f"got {type(response_json[field_name]).__name__}"
            )
        else:
            result.is_valid = True
        
        results.append(result)
    
    return results


def validate_quality_stats_fields(response_json: dict[str, Any]) -> tuple[bool, list[ValidationResult]]:
    """Validate the new Phase 3 quality statistics fields."""
    results = []
    has_quality_stats = "quality_stats" in response_json
    
    if not has_quality_stats:
        results.append(ValidationResult(
            field_name="quality_stats",
            expected_type=dict,
            is_valid=False,
            error_message="Missing quality_stats field (Phase 3 feature not present)"
        ))
        return False, results
    
    quality = response_json["quality_stats"]
    
    # Validate quality stats structure
    quality_fields = {
        "original_count": int,
        "filtered_count": int,
        "removed_count": int,
        "pass_rate": (int, float),
        "removal_reasons": dict,
    }
    
    for field_name, expected_types in quality_fields.items():
        result = ValidationResult(
            field_name=f"quality_stats.{field_name}",
            expected_type=expected_types if isinstance(expected_types, tuple) else expected_types,
            actual_value=quality.get(field_name),
        )
        
        if field_name not in quality:
            result.is_valid = False
            result.error_message = f"Missing quality_stats.{field_name}"
        elif not isinstance(quality[field_name], expected_types):
            result.is_valid = False
            result.error_message = (
                f"Type mismatch for quality_stats.{field_name}: "
                f"expected {expected_types}, got {type(quality[field_name]).__name__}"
            )
        else:
            result.is_valid = True
        
        results.append(result)
    
    # Additional business logic validations
    orig = quality.get("original_count", 0)
    filt = quality.get("filtered_count", 0)
    removed = quality.get("removed_count", 0)
    pass_rate = quality.get("pass_rate", 0)
    reasons = quality.get("removal_reasons", {})
    
    # Check math consistency: original - filtered == removed
    math_result = ValidationResult(
        field_name="quality_stats.math_consistency",
        expected_type=bool,
        actual_value=f"{orig} - {filt} == {removed}",
    )
    if orig - filt == removed:
        math_result.is_valid = True
    else:
        math_result.is_valid = False
        math_result.error_message = (
            f"Math inconsistency: original({orig}) - filtered({filt}) != removed({removed})"
        )
    results.append(math_result)
    
    # Check pass_rate calculation
    rate_result = ValidationResult(
        field_name="quality_stats.pass_rate_calculation",
        expected_type=float,
        actual_value=f"{pass_rate}% ≈ {(filt/orig*100) if orig > 0 else 0:.2f}%",
    )
    if orig > 0:
        expected_rate = round(filt / orig * 100, 2)
        if abs(pass_rate - expected_rate) < 0.01:  # Allow small floating point difference
            rate_result.is_valid = True
        else:
            rate_result.is_valid = False
            rate_result.error_message = (
                f"Pass rate mismatch: reported {pass_rate}%, "
                f"calculated {expected_rate}%"
            )
    else:
        rate_result.is_valid = True  # No data, can't validate
    results.append(rate_result)
    
    # Check removal_reasons sum equals removed_count
    reasons_sum = sum(reasons.values()) if isinstance(reasons, dict) else 0
    reasons_result = ValidationResult(
        field_name="quality_stats.removal_reasons_sum",
        expected_type=int,
        actual_value=f"sum(reasons)={reasons_sum} vs removed={removed}",
    )
    if reasons_sum == removed:
        reasons_result.is_valid = True
    else:
        reasons_result.is_valid = False
        reasons_result.error_message = (
            f"Removal reasons sum ({reasons_sum}) != removed count ({removed})"
        )
    results.append(reasons_result)
    
    # Check pass_rate range (should be 0-100)
    range_result = ValidationResult(
        field_name="quality_stats.pass_rate_range",
        expected_type=float,
        actual_value=pass_rate,
    )
    if 0 <= pass_rate <= 100:
        range_result.is_valid = True
    else:
        range_result.is_valid = False
        range_result.error_message = f"Pass rate out of range [0, 100]: {pass_rate}"
    results.append(range_result)
    
    return True, results


def validate_relations_consistency(response_json: dict[str, Any]) -> list[ValidationResult]:
    """Validate consistency between raw/filtered/inserted relation counts."""
    results = []
    
    raw = response_json.get("relations_raw")
    filtered = response_json.get("relations_filtered")
    inserted = response_json.get("relations_inserted")
    
    # Check that these fields exist (Phase 3 additions)
    for field in ["relations_raw", "relations_filtered"]:
        result = ValidationResult(
            field_name=field,
            expected_type=int,
            actual_value=response_json.get(field),
        )
        if field not in response_json:
            result.is_valid = False
            result.error_message = f"Missing {field} (Phase 3 field)"
        elif not isinstance(response_json[field], int):
            result.is_valid = False
            result.error_message = f"{field} should be int, got {type(response_json[field]).__name__}"
        else:
            result.is_valid = True
        results.append(result)
    
    # Validate consistency: raw >= filtered >= inserted
    if all(isinstance(v, int) for v in [raw, filtered, inserted]):
        consistency_result = ValidationResult(
            field_name="relations_consistency",
            expected_type=bool,
            actual_value=f"raw={raw} >= filtered={filtered} >= inserted={inserted}",
        )
        
        if raw >= filtered >= inserted:
            consistency_result.is_valid = True
        else:
            consistency_result.is_valid = False
            consistency_result.error_message = (
                f"Inconsistent counts: raw({raw}) < filtered({filtered}) or "
                f"filtered({filtered}) < inserted({inserted})"
            )
        results.append(consistency_result)
    
    return results


def call_extraction_api(base_url: str, saishi_id: str, timeout: int) -> tuple[int, dict[str, Any] | None, str]:
    """
    Call the extraction API endpoint.
    
    Returns:
        Tuple of (status_code, response_json_or_none, error_message)
    """
    url = f"{base_url.rstrip('/')}/api/v1/live-text/zhiboba/relations/extract"
    params = {"saishi_id": saishi_id}
    
    print(f"\n{'='*70}")
    print(f"  PHASE 3 QUALITY STATS VERIFICATION TEST")
    print(f"{'='*70}")
    print(f"\n[API CALL]")
    print(f"  URL: {url}")
    print(f"  Params: saishi_id={saishi_id}")
    print(f"  Timeout: {timeout}s")
    print(f"\n  Calling API...", end=" ", flush=True)
    
    start_time = time.time()
    try:
        response = requests.post(
            url,
            params=params,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        elapsed = time.time() - start_time
        
        print(f"[{response.status_code}] ({elapsed:.2f}s)")
        
        if response.status_code == 200:
            try:
                data = response.json()
                return response.status_code, data, ""
            except json.JSONDecodeError as e:
                return response.status_code, None, f"Invalid JSON response: {e}"
        else:
            try:
                error_data = response.json()
                return response.status_code, None, f"API Error: {error_data.get('detail', response.text)}"
            except:
                return response.status_code, None, f"HTTP {response.status_code}: {response.text[:200]}"
                
    except requests.exceptions.Timeout:
        return 0, None, f"Request timed out after {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return 0, None, f"Connection error: {e}"
    except Exception as e:
        return 0, None, f"Unexpected error: {e}"


def generate_report(status_code: int, response_data: dict[str, Any] | None, 
                    error_msg: str, elapsed: float) -> TestReport:
    """Generate comprehensive test report."""
    report = TestReport()
    report.response_time_seconds = round(elapsed, 2)
    report.status_code = status_code
    
    if error_msg or not response_data:
        print(f"\n[ERROR] {error_msg}")
        return report
    
    report.processed = response_data.get("processed", False)
    report.saishi_id = response_data.get("saishi_id", "")
    report.events = response_data.get("events", 0)
    report.relations_raw = response_data.get("relations_raw", 0)
    report.relations_filtered = response_data.get("relations_filtered", 0)
    report.relations_inserted = response_data.get("relations_inserted", 0)
    report.backend = response_data.get("backend", "")
    report.model_name = response_data.get("model_name", "")
    report.samples_count = len(response_data.get("samples", []))
    
    # Extract quality stats
    quality_data = response_data.get("quality_stats")
    if quality_data:
        report.quality_stats_present = True
        report.quality_original_count = quality_data.get("original_count")
        report.quality_filtered_count = quality_data.get("filtered_count")
        report.quality_removed_count = quality_data.get("removed_count")
        report.quality_pass_rate = quality_data.get("pass_rate")
        report.quality_removal_reasons = quality_data.get("removal_reasons", {})
    
    # Run validations
    print(f"\n[VALIDATION]")
    
    # 1. Basic structure validation
    basic_results = validate_response_structure(response_data)
    report.validations.extend(basic_results)
    
    # 2. Quality stats validation
    has_quality, quality_results = validate_quality_stats_fields(response_data)
    report.validations.extend(quality_results)
    
    # 3. Relations consistency validation
    consistency_results = validate_relations_consistency(response_data)
    report.validations.extend(consistency_results)
    
    # Count passed/failed
    for v in report.validations:
        if v.is_valid:
            report.passed_count += 1
        else:
            report.failed_count += 1
    
    return report


def print_report(report: TestReport):
    """Print formatted test report."""
    
    print(f"\n{'='*70}")
    print(f"  TEST RESULTS SUMMARY")
    print(f"{'='*70}")
    
    print(f"\n[API RESPONSE]")
    print(f"  Status Code: {report.status_code}")
    print(f"  Response Time: {report.response_time_seconds}s")
    print(f"  Processed: {'YES' if report.processed else 'NO'}")
    
    if report.processed:
        print(f"\n[EXTRACTION STATISTICS]")
        print(f"  Game ID:       {report.saishi_id}")
        print(f"  Events:        {report.events}")
        print(f"  Backend:       {report.backend}")
        print(f"  Model:         {report.model_name}")
        print(f"  Samples:       {report.samples_count}")
        
        print(f"\n[RELATION COUNTS (Phase 3 Fields)]")
        print(f"  Raw Relations:     {report.relations_raw:>5} (pre-filter)")
        print(f"  Filtered Relations: {report.relations_filtered:>5} (post-filter)")
        print(f"  Inserted to DB:    {report.relations_inserted:>5} (final)")
        
        if report.relations_raw > 0:
            filter_pct = (1 - report.relations_filtered / report.relations_raw) * 100
            print(f"  Filtering Rate:    {filter_pct:.1f}% removed")
    
    print(f"\n[QUALITY STATISTICS (Phase 3 New Feature)]")
    if report.quality_stats_present:
        print(f"  Status: {'PRESENT' if report.quality_stats_present else 'MISSING'}")
        print(f"  Original Count:   {report.quality_original_count}")
        print(f"  Filtered Count:   {report.quality_filtered_count}")
        print(f"  Removed Count:    {report.quality_removed_count}")
        print(f"  Pass Rate:        {report.quality_pass_rate}%")
        
        if report.quality_removal_reasons:
            print(f"  Removal Reasons:")
            for reason, count in sorted(report.quality_removal_reasons.items()):
                print(f"    - {reason:<25}: {count:>3}")
    else:
        print(f"  Status: MISSING (quality_stats field not found)")
        print(f"  Note: This indicates Phase 3 features are not active")
    
    print(f"\n[VALIDATION RESULTS]")
    print(f"  Total Checks:  {len(report.validations)}")
    print(f"  Passed:        {report.passed_count} ✓")
    print(f"  Failed:        {report.failed_count} ✗")
    
    if report.failed_count > 0:
        print(f"\n  Failed Checks Details:")
        for v in report.validations:
            if not v.is_valid:
                print(f"    [FAIL] {v.field_name}")
                print(f"           Expected: {v.expected_type}")
                print(f"           Actual:   {v.actual_value}")
                print(f"           Error:    {v.error_message}")
    
    # Final verdict
    print(f"\n{'='*70}")
    overall_pass = report.failed_count == 0 and report.processed and report.quality_stats_present
    if overall_pass:
        print(f"  [PASS] ALL VALIDATIONS PASSED - Phase 3 Quality Stats Working Correctly!")
    elif report.processed and report.quality_stats_present:
        print(f"  [WARN] SOME VALIDATIONS FAILED - Review details above")
    elif report.processed and not report.quality_stats_present:
        print(f"  [WARN] QUALITY STATS NOT PRESENT - Phase 3 may not be integrated")
    else:
        print(f"  [FAIL] TEST FAILED - API call unsuccessful")
    print(f"{'='*70}\n")
    
    return overall_pass


def main():
    parser = argparse.ArgumentParser(
        description="Verify Phase 3 Quality Statistics Fields in Relation Extraction API"
    )
    parser.add_argument(
        "--saishi-id",
        default="1780736",
        help="Game ID to test (default: 1780736)"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8003",
        help="Base URL of the API server (default: http://127.0.0.1:8003)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: 120)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    parser.add_argument(
        "--sync-first",
        action="store_true",
        help="Sync and tokenize data before extraction (if no data exists)"
    )
    
    args = parser.parse_args()
    
    # Optional: Sync data first if requested
    if args.sync_first:
        print(f"\n[PRE-STEP] Syncing live text data for game {args.saishi_id}...")
        sync_url = f"{args.base_url.rstrip('/')}/api/v1/live-text/zhiboba/sync"
        try:
            sync_resp = requests.post(
                sync_url,
                params={"saishi_id": args.saishi_id},
                timeout=300,  # Sync can take longer
            )
            if sync_resp.status_code == 200:
                sync_data = sync_resp.json()
                events_count = sync_data.get("events_fetched", 0)
                segmented_count = sync_data.get("events_segmented", 0)
                print(f"  Sync completed: {events_count} events fetched, {segmented_count} segmented")
            else:
                print(f"  [WARN] Sync failed: HTTP {sync_resp.status_code}")
                print(f"  Continuing with extraction anyway...")
        except Exception as e:
            print(f"  [WARN] Sync error: {e}")
            print(f"  Continuing with extraction anyway...")
    
    # Call API
    status_code, response_data, error_msg = call_extraction_api(
        base_url=args.base_url,
        saishi_id=args.saishi_id,
        timeout=args.timeout
    )
    
    # Generate report
    report = generate_report(status_code, response_data, error_msg, 0)
    report.api_url = args.base_url
    
    # Output results
    if args.json:
        # JSON output for programmatic use
        output = {
            "success": report.failed_count == 0 and report.processed,
            "status_code": report.status_code,
            "response_time_seconds": report.response_time_seconds,
            "processed": report.processed,
            "quality_stats_present": report.quality_stats_present,
            "relations": {
                "raw": report.relations_raw,
                "filtered": report.relations_filtered,
                "inserted": report.relations_inserted,
            },
            "quality_stats": {
                "original_count": report.quality_original_count,
                "filtered_count": report.quality_filtered_count,
                "removed_count": report.quality_removed_count,
                "pass_rate": report.quality_pass_rate,
                "removal_reasons": report.quality_removal_reasons,
            },
            "validations": {
                "total": len(report.validations),
                "passed": report.passed_count,
                "failed": report.failed_count,
                "details": [
                    {
                        "field": v.field_name,
                        "passed": v.is_valid,
                        "error": v.error_message
                    }
                    for v in report.validations
                ]
            }
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # Human-readable output
        overall_pass = print_report(report)
        
        # Exit code for CI/CD
        sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
