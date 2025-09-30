"""Verification helpers for Season 2 results imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .results_store import Season2ResultsStore


@dataclass
class Season2ParticipantTotalMismatch:
    """Mismatch between stored and recomputed participant totals."""

    fight_code: str
    participant_id: int
    seat_index: int
    display_name: str
    recorded_total: int
    computed_total: int

    def as_dict(self) -> dict[str, object]:
        return {
            "fight_code": self.fight_code,
            "participant_id": self.participant_id,
            "seat_index": self.seat_index,
            "display_name": self.display_name,
            "recorded_total": self.recorded_total,
            "computed_total": self.computed_total,
        }


@dataclass
class Season2FightStructureIssue:
    """Structural inconsistencies detected for a fight."""

    fight_code: str
    participant_count: int
    expected_questions: int
    actual_questions: int
    expected_results: int
    actual_results: int

    def as_dict(self) -> dict[str, object]:
        return {
            "fight_code": self.fight_code,
            "participant_count": self.participant_count,
            "expected_questions": self.expected_questions,
            "actual_questions": self.actual_questions,
            "expected_results": self.expected_results,
            "actual_results": self.actual_results,
        }


@dataclass
class Season2VerificationReport:
    """Summary of consistency checks for Season 2 fights."""

    fights_checked: int = 0
    participants_checked: int = 0
    questions_checked: int = 0
    participant_total_mismatches: List[Season2ParticipantTotalMismatch] = field(default_factory=list)
    fight_structure_issues: List[Season2FightStructureIssue] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        return not self.participant_total_mismatches and not self.fight_structure_issues

    def as_dict(self) -> dict[str, object]:
        return {
            "fights_checked": self.fights_checked,
            "participants_checked": self.participants_checked,
            "questions_checked": self.questions_checked,
            "participant_total_mismatches": [
                mismatch.as_dict() for mismatch in self.participant_total_mismatches
            ],
            "fight_structure_issues": [
                issue.as_dict() for issue in self.fight_structure_issues
            ],
            "is_successful": self.is_successful,
        }


class Season2VerificationError(RuntimeError):
    """Raised when verification detects inconsistencies."""

    def __init__(self, report: Season2VerificationReport) -> None:
        self.report = report
        message = self._build_message(report)
        super().__init__(message)

    @staticmethod
    def _build_message(report: Season2VerificationReport) -> str:
        reasons: List[str] = []
        if report.participant_total_mismatches:
            reasons.append(
                f"participant totals mismatched in {len(report.participant_total_mismatches)} record(s)"
            )
        if report.fight_structure_issues:
            reasons.append(
                f"fight structure issues detected in {len(report.fight_structure_issues)} fight(s)"
            )
        if not reasons:
            return "Season 2 verification failed without specific issues"
        details = "; ".join(reasons)
        return f"Season 2 verification failed: {details}"


class Season2ResultsVerifier:
    """Run consistency checks against the Season 2 results schema."""

    def __init__(
        self,
        *,
        store: Season2ResultsStore,
        expected_questions_per_fight: int = 5,
    ) -> None:
        self._store = store
        self._expected_questions_per_fight = expected_questions_per_fight

    def verify(self) -> Season2VerificationReport:
        report = Season2VerificationReport()
        with self._store.connection() as conn:
            fights = conn.execute(
                "SELECT id, fight_code FROM fights ORDER BY fight_code"
            ).fetchall()
            report.fights_checked = len(fights)
            for fight_row in fights:
                fight_id = int(fight_row["id"])
                fight_code = str(fight_row["fight_code"])

                participants = conn.execute(
                    (
                        "SELECT id, seat_index, display_name, total_score "
                        "FROM fight_participants WHERE fight_id = ? ORDER BY seat_index"
                    ),
                    (fight_id,),
                ).fetchall()
                participant_count = len(participants)
                report.participants_checked += participant_count

                question_count = conn.execute(
                    "SELECT COUNT(*) FROM questions WHERE fight_id = ?",
                    (fight_id,),
                ).fetchone()[0]
                report.questions_checked += int(question_count)

                actual_results = conn.execute(
                    (
                        "SELECT COUNT(*) FROM question_results "
                        "WHERE question_id IN (SELECT id FROM questions WHERE fight_id = ?)"
                    ),
                    (fight_id,),
                ).fetchone()[0]
                expected_results = int(question_count) * participant_count

                if (
                    int(question_count) != self._expected_questions_per_fight
                    or actual_results != expected_results
                ):
                    report.fight_structure_issues.append(
                        Season2FightStructureIssue(
                            fight_code=fight_code,
                            participant_count=participant_count,
                            expected_questions=self._expected_questions_per_fight,
                            actual_questions=int(question_count),
                            expected_results=expected_results,
                            actual_results=int(actual_results),
                        )
                    )

                for participant in participants:
                    participant_id = int(participant["id"])
                    recorded_total = int(participant["total_score"])
                    computed_total_row = conn.execute(
                        (
                            "SELECT COALESCE(SUM(delta), 0) FROM question_results "
                            "WHERE participant_id = ?"
                        ),
                        (participant_id,),
                    ).fetchone()
                    computed_total = int(computed_total_row[0]) if computed_total_row else 0
                    if computed_total != recorded_total:
                        report.participant_total_mismatches.append(
                            Season2ParticipantTotalMismatch(
                                fight_code=fight_code,
                                participant_id=participant_id,
                                seat_index=int(participant["seat_index"]),
                                display_name=str(participant["display_name"]),
                                recorded_total=recorded_total,
                                computed_total=computed_total,
                            )
                        )
        return report

    def assert_valid(self) -> Season2VerificationReport:
        report = self.verify()
        if not report.is_successful:
            raise Season2VerificationError(report)
        return report


__all__ = [
    "Season2ResultsVerifier",
    "Season2VerificationReport",
    "Season2VerificationError",
    "Season2ParticipantTotalMismatch",
    "Season2FightStructureIssue",
]
