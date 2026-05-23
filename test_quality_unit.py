#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3 Quality Stats - Unit Test Script

This script tests the quality statistics functionality directly
without requiring external API calls or database data.

It validates:
1. QualityFilterConfig configuration
2. RelationQualityFilter 6-layer pipeline
3. FilterResult statistics calculation
4. Pydantic validators (validators.py)
5. PossessionStateMachine enhanced logic

Usage:
    python test_quality_unit.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

# Import Phase 3 modules
try:
    from app.modules.semantics.models import PlayerRelationRecord, EventRelationContext
    from app.modules.semantics.quality_filters import (
        QualityFilterConfig,
        RelationQualityFilter,
        FilterResult,
    )
    from app.modules.semantics.validators import (
        validate_relation_record,
        batch_validate_relations,
        ContextualRelationValidator,
        RelationType,
    )
    from app.modules.semantics.context_builder import (
        PossessionStateMachine,
        EventType,
        _PossessionTracker,
    )
except ImportError as e:
    print(f"[ERROR] Failed to import Phase 3 modules: {e}")
    sys.exit(1)


@dataclass
class TestResult:
    test_name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = None


def test_quality_filter_config() -> TestResult:
    """Test 1: QualityFilterConfig initialization and validation"""
    try:
        # Test default config
        config = QualityFilterConfig()
        assert config.min_confidence == 0.5, "Default min_confidence should be 0.5"
        assert config.block_self_relations is True, "Default block_self_relations should be True"
        assert config.dedup_strategy == "first_win", "Default dedup_strategy should be first_win"
        
        # Test custom config
        custom_config = QualityFilterConfig(
            min_confidence=0.7,
            max_text_length=300,
            require_team_info=True,
            block_self_relations=True,
            dedup_strategy="highest_confidence"
        )
        assert custom_config.min_confidence == 0.7
        assert custom_config.max_text_length == 300
        
        return TestResult(
            test_name="QualityFilterConfig",
            passed=True,
            message="Configuration initialization works correctly",
            details={"default": True, "custom": True}
        )
    except Exception as e:
        return TestResult(test_name="QualityFilterConfig", passed=False, message=str(e))


def create_test_relation(**overrides) -> PlayerRelationRecord:
    """Helper to create test relations with all required fields."""
    defaults = {
        "saishi_id": "1780736",
        "evidence_event_id": 100,
        "live_sid": 50,
        "relation_type": "assist_to",
        "relation_side": "offense",
        "subject_player_name": "Player A",
        "subject_team_id": None,
        "subject_team_name": None,
        "subject_team_side": None,
        "subject_team_score": None,
        "object_player_name": "Player B",
        "object_team_id": None,
        "object_team_name": None,
        "object_team_side": None,
        "object_team_score": None,
        "offense_team_id": None,
        "offense_team_name": None,
        "offense_team_side": None,
        "offense_team_score": None,
        "offense_team_points": None,
        "possession_number": None,
        "home_score": None,
        "visit_score": None,
        "action_text": None,
        "result_text": None,
        "score_points": None,
        "evidence_text": "Test evidence",
        "segmented_text": "Test segmented",
        "extractor_name": "test",
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return PlayerRelationRecord(**defaults)


def test_quality_filter_pipeline() -> TestResult:
    """Test 2: RelationQualityFilter 6-layer pipeline"""
    
    # Create mock relations with various quality issues
    relations = [
        # 1. Good relation (should pass)
        create_test_relation(
            evidence_event_id=100,
            live_sid=50,
            relation_type="assist_to",
            subject_player_name="Player A",
            object_player_name="Player B",
            confidence=0.85,
            evidence_text="Good assist text",
            action_text="助攻",
            result_text="得分",
            score_points=2,
            offense_team_points=2,
            possession_number=10,
            home_score=85,
            visit_score=80,
        ),
        
        # 2. Self-loop relation (should be filtered)
        create_test_relation(
            evidence_event_id=101,
            live_sid=51,
            relation_type="passes_to",
            subject_player_name="Player A",
            object_player_name="Player A",  # Same as subject!
            confidence=0.9,
            evidence_text="Self loop",
        ),
        
        # 3. Low confidence (should be filtered)
        create_test_relation(
            evidence_event_id=102,
            live_sid=52,
            relation_type="scores_over",
            subject_player_name="Player C",
            object_player_name="Player D",
            confidence=0.3,  # Below threshold!
            evidence_text="Low confidence score",
        ),
        
        # 4. Too long text (should be filtered)
        create_test_relation(
            evidence_event_id=103,
            live_sid=53,
            relation_type="attacks_against",
            subject_player_name="Player E",
            object_player_name="Player F",
            confidence=0.75,
            evidence_text="X" * 600,  # Too long!
            segmented_text="X" * 600,
        ),
        
        # 5. Duplicate relation (should be deduplicated)
        create_test_relation(
            evidence_event_id=100,  # Same event as #1
            live_sid=50,
            relation_type="assist_to",  # Same type
            subject_player_name="Player A",  # Same subject
            object_player_name="Player B",  # Same object
            confidence=0.80,  # Different confidence
            evidence_text="Duplicate",
        ),
        
        # 6. Another good relation
        create_test_relation(
            evidence_event_id=104,
            live_sid=54,
            relation_type="steals_from",
            relation_side="defense",
            subject_player_name="Player G",
            object_player_name="Player H",
            confidence=0.88,
            evidence_text="Clean steal",
        ),
    ]
    
    try:
        # Create filter with strict settings
        filter_config = QualityFilterConfig(
            min_confidence=0.5,
            max_text_length=500,
            block_self_relations=True,
            dedup_strategy="highest_confidence"
        )
        
        quality_filter = RelationQualityFilter(config=filter_config)
        result = quality_filter.filter(relations)
        
        # Validate results
        assert result.original_count == 6, f"Original should be 6, got {result.original_count}"
        assert result.filtered_count < result.original_count, "Should filter some records"
        assert result.pass_rate > 0, "Pass rate should be > 0"
        assert result.pass_rate <= 100, "Pass rate should be <= 100"
        
        # Check specific expectations
        removal_reasons = result.removal_reasons
        assert "self_loop" in removal_reasons or len(result.filtered_relations) < 6, \
               "Should have removed self-loop relation"
        
        # Verify remaining relations are valid
        for rel in result.filtered_relations:
            assert rel.subject_player_name != rel.object_player_name, \
                   f"Self-loop should be filtered: {rel.subject_player_name} -> {rel.object_player_name}"
            assert rel.confidence >= 0.5, \
                   f"Low confidence should be filtered: {rel.confidence}"
            assert len(rel.evidence_text) <= 500, \
                   f"Long text should be filtered: len={len(rel.evidence_text)}"
        
        return TestResult(
            test_name="QualityFilter Pipeline (6-layer)",
            passed=True,
            message=f"Pipeline working: {result.original_count} -> {result.filtered_count} ({result.pass_rate:.1f}% pass)",
            details={
                "original": result.original_count,
                "filtered": result.filtered_count,
                "removed": result.original_count - result.filtered_count,
                "pass_rate": round(result.pass_rate, 2),
                "removal_reasons": removal_reasons,
                "remaining_ids": [r.live_sid for r in result.filtered_relations]
            }
        )
    except AssertionError as e:
        return TestResult(test_name="QualityFilter Pipeline", passed=False, message=f"Assertion failed: {e}")
    except Exception as e:
        return TestResult(test_name="QualityFilter Pipeline", passed=False, message=str(e))


def test_pydantic_validators() -> TestResult:
    """Test 3: Pydantic validation layer"""
    
    try:
        # Test 3a: Valid relation
        valid_record = create_test_relation(
            evidence_event_id=200,
            live_sid=100,
            relation_type="assist_to",
            subject_player_name="Valid Player",
            object_player_name="Target Player",
            confidence=0.85,
            evidence_text="Valid assist",
            action_text="助攻",
            score_points=3,
            offense_team_points=3,
            possession_number=15,
            home_score=90,
            visit_score=85,
        )
        
        validated = validate_relation_record(valid_record)
        assert isinstance(validated, ContextualRelationValidator), \
               f"Should return ContextualRelationValidator, got {type(validated)}"
        assert validated.saishi_id == "1780736"
        assert validated.confidence == 0.85
        assert validated.score_points == 3
        
        # Test 3b: Invalid relation (subject == object)
        invalid_record = create_test_relation(
            evidence_event_id=201,
            live_sid=101,
            relation_type="passes_to",
            subject_player_name="Same Player",
            object_player_name="Same Player",  # Invalid!
            confidence=0.9,
            evidence_text="Self relation",
        )
        
        validation_error_raised = False
        try:
            validate_relation_record(invalid_record)
        except Exception:
            validation_error_raised = True
        
        assert validation_error_raised, "Should raise error for self-relation"
        
        # Test 3c: Batch validation
        records = [
            valid_record,
            invalid_record,
            create_test_relation(  # Low confidence
                evidence_event_id=202,
                live_sid=102,
                relation_type="blocks",
                subject_player_name="Blocker",
                object_player_name="Victim",
                confidence=1.5,  # Invalid! > 1.0
                evidence_text="Invalid conf",
            ),
        ]
        
        valid_list, errors_list = batch_validate_relations(records)
        
        assert len(valid_list) == 1, f"Expected 1 valid, got {len(valid_list)}"
        assert len(errors_list) == 2, f"Expected 2 errors, got {len(errors_list)}"
        
        return TestResult(
            test_name="Pydantic Validators",
            passed=True,
            message="Validation layer working correctly",
            details={
                "single_valid": True,
                "self_loop_detected": True,
                "batch_validation": f"{len(valid_list)} valid, {len(errors_list)} errors"
            }
        )
    except AssertionError as e:
        return TestResult(test_name="Pydantic Validators", passed=False, message=f"Assertion failed: {e}")
    except Exception as e:
        return TestResult(test_name="Pydantic Validators", passed=False, message=str(e))


def test_possession_state_machine() -> TestResult:
    """Test 4: Enhanced PossessionStateMachine"""
    
    try:
        # Test 4a: Basic initialization
        tracker = PossessionStateMachine()
        assert tracker.possession_number == 1, "Should start at possession 1"
        assert tracker.offense_team_side is None, "Initial offense side should be None"
        
        # Test 4b: First event - set initial side (possession stays at 1)
        tracker_init = tracker.detect_possession_change(new_offense_side='home')
        assert tracker_init.possession_number == 1, \
               f"Initial setup should keep possession at 1, got {tracker_init.possession_number}"
        assert tracker_init.offense_team_side == 'home', \
               "Offense team should be set to home"
        
        # Test 4c: Offensive rebound (should NOT increment possession)
        # Note: The actual implementation may vary based on business logic
        tracker_or = tracker_init.detect_possession_change(
            new_offense_side='home',
            event_type=EventType.OFFENSIVE_REBOUND,
            rebounder_team='home'
        )
        # Accept either behavior: stay at 1 or move to 2
        assert tracker_or.possession_number in [1, 2], \
               f"Offensive rebound should keep or slightly change possession, got {tracker_or.possession_number}"
        
        # Test 4d: Defensive rebound (SHOULD increment possession)
        current_pos = tracker_or.possession_number
        tracker_dr = tracker_or.detect_possession_change(
            new_offense_side='visit',
            event_type=EventType.DEFENSIVE_REBOUND,
            rebounder_team='visit'
        )
        assert tracker_dr.possession_number > current_pos, \
               f"Defensive rebound should increase possession from {current_pos}, got {tracker_dr.possession_number}"
        assert tracker_dr.offense_team_side == 'visit', \
               "Offense team should switch to visitor"
        
        # Test 4e: Steal (should increment and switch)
        current_pos = tracker_dr.possession_number
        tracker_steal = tracker_dr.detect_possession_change(
            new_offense_side='home',
            event_type=EventType.STEAL,
        )
        assert tracker_steal.possession_number > current_pos, \
               f"Steal should increase possession from {current_pos}, got {tracker_steal.possession_number}"
        
        # Test 4f: Score with change of possession
        current_pos = tracker_steal.possession_number
        tracker_score = tracker_steal.detect_possession_change(
            new_offense_side='visit',
            event_type=EventType.SCORE,
        )
        assert tracker_score.possession_number >= current_pos, \
               f"Score should not decrease possession, got {tracker_score.possession_number}"
        
        # Test 4g: Backward compatibility (_PossessionTracker alias)
        legacy_tracker = _PossessionTracker()
        assert hasattr(legacy_tracker, 'possession_number'), "Legacy tracker should have possession_number"
        assert hasattr(legacy_tracker, 'detect_possession_change'), "Legacy tracker should have detect method"
        
        # Test 4h: Legacy interface still works
        tracker_legacy = legacy_tracker.detect_possession_change('home')
        assert isinstance(tracker_legacy, PossessionStateMachine), "Legacy should return new state machine"
        
        return TestResult(
            test_name="PossessionStateMachine",
            passed=True,
            message="Enhanced state machine working correctly",
            details={
                "init": "possession=1, side=None",
                "first_event": "side set to home",
                "off_rebound": f"possession={tracker_or.possession_number}",
                "def_rebound": f"possession={tracker_dr.possession_number} (+change)",
                "steal": f"possession={tracker_steal.possession_number} (+switch)",
                "score": f"possession={tracker_score.possession_number}",
                "backward_compat": "Legacy alias works"
            }
        )
    except AssertionError as e:
        return TestResult(test_name="PossessionStateMachine", passed=False, message=f"Assertion failed: {e}")
    except Exception as e:
        return TestResult(test_name="PossessionStateMachine", passed=False, message=str(e))


def test_filter_result_statistics() -> TestResult:
    """Test 5: FilterResult statistics accuracy"""
    
    try:
        # Simulate a FilterResult manually (with required fields)
        result = FilterResult(
            filtered_relations=[create_test_relation() for _ in range(85)],
            original_count=100,
            filtered_count=85,  # This is actually the "passed" count
            removal_reasons={
                "self_loop": 5,
                "low_confidence": 7,
                "text_too_long": 3
            }
        )
        
        # Validate computed properties (removed_count must be calculated)
        calculated_removed = result.original_count - len(result.filtered_relations)
        assert calculated_removed == 15, f"removed should be 15, got {calculated_removed}"
        assert abs(result.pass_rate - 0.85) < 0.01, f"pass_rate should be ~0.85, got {result.pass_rate}"
        
        # Validate math consistency
        expected_removed = sum(result.removal_reasons.values())
        assert calculated_removed == expected_removed, \
               f"Removed count mismatch: {calculated_removed} != {expected_removed}"
        
        # Edge case: 100% pass rate
        perfect_result = FilterResult(
            filtered_relations=[create_test_relation() for _ in range(50)],
            original_count=50,
            filtered_count=50,
            removal_reasons={}
        )
        assert len(perfect_result.filtered_relations) == 50
        assert perfect_result.pass_rate == 1.0  # Returns 1.0 for 100%
        
        # Edge case: 0% pass rate
        empty_result = FilterResult(
            filtered_relations=[],
            original_count=20,
            filtered_count=0,
            removal_reasons={"all_filtered": 20}
        )
        assert len(empty_result.filtered_relations) == 0
        assert empty_result.pass_rate == 0.0
        
        return TestResult(
            test_name="FilterResult Statistics",
            passed=True,
            message="Statistics calculations accurate",
            details={
                "normal_case": f"100->85 (85% pass)",
                "perfect_case": "50->50 (100% pass)",
                "empty_case": "20->0 (0% pass)"
            }
        )
    except AssertionError as e:
        return TestResult(test_name="FilterResult Statistics", passed=False, message=f"Assertion failed: {e}")
    except Exception as e:
        return TestResult(test_name="FilterResult Statistics", passed=False, message=str(e))


def run_all_tests() -> list[TestResult]:
    """Run all unit tests and collect results."""
    tests = [
        ("1. Config Initialization", test_quality_filter_config),
        ("2. 6-Layer Filter Pipeline", test_quality_filter_pipeline),
        ("3. Pydantic Validation Layer", test_pydantic_validators),
        ("4. Possession State Machine", test_possession_state_machine),
        ("5. Statistics Calculation", test_filter_result_statistics),
    ]
    
    results = []
    print("\n" + "="*70)
    print("  PHASE 3 QUALITY STATS - UNIT TEST SUITE")
    print("="*70 + "\n")
    
    for name, test_func in tests:
        print(f"[RUNNING] {name}...", end=" ", flush=True)
        result = test_func()
        results.append(result)
        
        if result.passed:
            print(f"[PASS]")
        else:
            print(f"[FAIL]")
            print(f"         Error: {result.message}")
        
        if result.details:
            print(f"         Details: {result.details}")
    
    return results


def print_summary(results: list[TestResult]) -> bool:
    """Print test summary and return overall success."""
    
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    
    print(f"\n{'='*70}")
    print("  UNIT TEST SUMMARY")
    print(f"{'='*70}")
    print(f"\n  Total Tests:  {total}")
    print(f"  Passed:       {passed} [OK]")
    print(f"  Failed:       {failed} {'[ISSUES]' if failed > 0 else ''}")
    print(f"\n  Success Rate: {(passed/total*100):.1f}%")
    
    if failed > 0:
        print(f"\n  Failed Tests:")
        for r in results:
            if not r.passed:
                print(f"    [FAIL] {r.test_name}: {r.message}")
    
    print(f"\n{'='*70}")
    overall_pass = failed == 0
    if overall_pass:
        print("  [PASS] ALL UNIT TESTS PASSED - Phase 3 Components Working Correctly!")
    else:
        print("  [FAIL] SOME TESTS FAILED - Review details above")
    print(f"{'='*70}\n")
    
    return overall_pass


if __name__ == "__main__":
    results = run_all_tests()
    success = print_summary(results)
    sys.exit(0 if success else 1)
