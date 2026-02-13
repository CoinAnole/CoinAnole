import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import activity_detection


MISSING_SHA = object()


def make_branch(name: str, branch_time: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        commit=SimpleNamespace(
            commit=SimpleNamespace(
                author=SimpleNamespace(date=branch_time),
            )
        ),
    )


def make_commit(
    *,
    sha=MISSING_SHA,
    author_date: datetime | None = None,
    committer_date: datetime | None = None,
) -> SimpleNamespace:
    commit_payload = SimpleNamespace(
        author=None if author_date is None else SimpleNamespace(date=author_date),
        committer=None if committer_date is None else SimpleNamespace(date=committer_date),
    )
    if sha is MISSING_SHA:
        return SimpleNamespace(commit=commit_payload)
    return SimpleNamespace(sha=sha, commit=commit_payload)


class FakeRepo:
    def __init__(self, branches: list[SimpleNamespace], commits_by_branch: dict[str, list[SimpleNamespace]]) -> None:
        self._branches = branches
        self._commits_by_branch = commits_by_branch
        self.commit_calls: list[tuple[str, datetime, str | None]] = []

    def get_branches(self) -> list[SimpleNamespace]:
        return self._branches

    def get_commits(self, sha: str, since: datetime, author: str | None = None) -> list[SimpleNamespace]:
        self.commit_calls.append((sha, since, author))
        if sha == "broken":
            raise RuntimeError("branch fetch failed")
        return list(self._commits_by_branch.get(sha, []))


class FakeGithub:
    def __init__(
        self,
        token: str,
        repos: dict[str, object],
        login: str | None = "owner",
        raise_on_get_user: bool = False,
    ) -> None:
        self.token = token
        self._repos = repos
        self._login = login
        self._raise_on_get_user = raise_on_get_user

    def get_repo(self, repo_name: str) -> object:
        repo = self._repos.get(repo_name)
        if isinstance(repo, Exception):
            raise repo
        if repo is None:
            raise RuntimeError(f"unknown repo: {repo_name}")
        return repo

    def get_user(self) -> SimpleNamespace:
        if self._raise_on_get_user:
            raise RuntimeError("failed to resolve user")
        return SimpleNamespace(login=self._login)


class ActivityDetectionPathTests(unittest.TestCase):
    def test_get_watched_repos_prefers_env_then_profile_repo(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ["WATCHED_REPOS"] = " owner/one , owner/two ,, "
            os.environ["GITHUB_REPOSITORY"] = "ignored/ignored"
            self.assertEqual(activity_detection.get_watched_repos(), ["owner/one", "owner/two"])

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WATCHED_REPOS", None)
            os.environ["GITHUB_REPOSITORY"] = "alice/profile"
            self.assertEqual(activity_detection.get_watched_repos(), ["alice/alice"])

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WATCHED_REPOS", None)
            os.environ.pop("GITHUB_REPOSITORY", None)
            self.assertEqual(activity_detection.get_watched_repos(), [])

    def test_detect_activity_handles_dedupe_timezones_and_errors(self) -> None:
        last_check = datetime(2026, 2, 12, 22, 30, tzinfo=timezone.utc)
        now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)
        previous_tracker = {"open_session": None, "last_timeout_minutes": 55}

        branches = [
            make_branch("main", datetime(2026, 2, 13, 6, 0, tzinfo=timezone.utc)),
            make_branch("feature", datetime(2026, 2, 13, 5, 0, tzinfo=timezone.utc)),
            make_branch("broken", datetime(2026, 2, 13, 4, 0, tzinfo=timezone.utc)),
            make_branch("old1", datetime(2026, 2, 13, 3, 0, tzinfo=timezone.utc)),
            make_branch("old2", datetime(2026, 2, 13, 2, 0, tzinfo=timezone.utc)),
            make_branch("dropped", datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc)),
        ]
        repo_ok = FakeRepo(
            branches=branches,
            commits_by_branch={
                "main": [
                    make_commit(sha="a1", author_date=datetime(2026, 2, 12, 23, 0, tzinfo=timezone.utc)),
                    make_commit(sha="a2", committer_date=datetime(2026, 2, 13, 0, 30)),
                    make_commit(sha="skip", author_date=None, committer_date=None),
                    make_commit(author_date=datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc)),
                ],
                "feature": [
                    make_commit(sha="a1", author_date=datetime(2026, 2, 12, 23, 5, tzinfo=timezone.utc)),
                    make_commit(sha="a3", author_date=datetime(2026, 2, 13, 2, 0, tzinfo=timezone.utc)),
                ],
                "old1": [],
                "old2": [],
                "dropped": [
                    make_commit(sha="not-seen", author_date=datetime(2026, 2, 13, 3, 0, tzinfo=timezone.utc)),
                ],
            },
        )
        fake_github = FakeGithub(
            token="token-123",
            repos={
                "owner/repo": repo_ok,
                "owner/fail": RuntimeError("repo fetch failed"),
            },
        )

        captured_call: dict[str, object] = {}

        def fake_analyze_commit_sessions(
            *,
            commit_events,
            today,
            now,
            previous_session_tracker,
        ) -> dict:
            captured_call["commit_events"] = commit_events
            captured_call["today"] = today
            captured_call["now"] = now
            captured_call["previous_session_tracker"] = previous_session_tracker
            return {
                "session_duration_minutes": 120,
                "session_duration_today_minutes": 90,
                "marathon_detected": True,
                "session_split_timeout_minutes": 45,
                "session_count_detected": 2,
                "primary_session": {"duration_minutes": 120},
                "detected_sessions": [{"duration_minutes": 120}],
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            }

        with patch.dict(os.environ, {}, clear=False):
            os.environ["GH_TOKEN"] = "token-123"
            os.environ["GITHUB_REPOSITORY"] = "owner/profile"
            with patch.object(activity_detection, "HAS_GITHUB", True), patch.object(
                activity_detection,
                "Github",
                side_effect=lambda token: fake_github,
                create=True,
            ), patch.object(
                activity_detection,
                "analyze_commit_sessions",
                side_effect=fake_analyze_commit_sessions,
            ), patch("builtins.print") as print_mock:
                result = activity_detection.detect_activity(
                    watched_repos=["owner/repo", "owner/fail"],
                    last_check=last_check,
                    previous_session_tracker=previous_tracker,
                    now=now,
                )

        self.assertEqual(result["commits_detected"], 4)
        self.assertEqual(result["commits_today_detected"], 3)
        self.assertEqual(result["repos_touched"], ["owner/repo"])
        self.assertEqual(result["repos_touched_today"], ["owner/repo"])
        self.assertEqual(result["last_commit_timestamp"], "2026-02-13T02:00:00+00:00")
        self.assertTrue(result["marathon_detected"])
        self.assertEqual(result["session_duration_minutes"], 120)
        self.assertEqual(result["session_duration_today_minutes"], 90)

        self.assertEqual(captured_call["today"], "2026-02-13")
        self.assertEqual(captured_call["now"], now)
        self.assertEqual(captured_call["previous_session_tracker"], previous_tracker)
        commit_events = captured_call["commit_events"]
        self.assertEqual(len(commit_events), 4)
        self.assertEqual(
            [event["timestamp"].isoformat() for event in commit_events],
            [
                "2026-02-12T23:00:00+00:00",
                "2026-02-13T00:30:00+00:00",
                "2026-02-13T01:00:00+00:00",
                "2026-02-13T02:00:00+00:00",
            ],
        )
        self.assertTrue(all(event["timestamp"].tzinfo is not None for event in commit_events))
        self.assertTrue(all(event["repo"] == "owner/repo" for event in commit_events))

        queried_branches = [sha for sha, _, _ in repo_ok.commit_calls]
        self.assertEqual(queried_branches, ["main", "feature", "broken", "old1", "old2"])
        self.assertNotIn("dropped", queried_branches)
        self.assertTrue(all(author == "owner" for _, _, author in repo_ok.commit_calls))

        printed_lines = [str(call.args[0]) for call in print_mock.mock_calls if call.args]
        self.assertTrue(any("Marathon session detected" in line for line in printed_lines))

    def test_detect_activity_handles_branch_missing_metadata_without_crashing(self) -> None:
        last_check = datetime(2026, 2, 12, 22, 30, tzinfo=timezone.utc)
        now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

        branches = [
            make_branch("main", datetime(2026, 2, 13, 6, 0, tzinfo=timezone.utc)),
            SimpleNamespace(name="missing-meta", commit=SimpleNamespace(commit=SimpleNamespace(author=None))),
        ]
        repo = FakeRepo(
            branches=branches,
            commits_by_branch={
                "main": [make_commit(sha="a1", author_date=datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc))],
                "missing-meta": [],
            },
        )
        fake_github = FakeGithub(token="token-123", repos={"owner/repo": repo}, login="owner")

        with patch.dict(os.environ, {"GH_TOKEN": "token-123", "GITHUB_REPOSITORY": "owner/profile"}, clear=False):
            with patch.object(activity_detection, "HAS_GITHUB", True), patch.object(
                activity_detection,
                "Github",
                side_effect=lambda token: fake_github,
                create=True,
            ):
                result = activity_detection.detect_activity(
                    watched_repos=["owner/repo"],
                    last_check=last_check,
                    previous_session_tracker=None,
                    now=now,
                )

        self.assertEqual(result["commits_detected"], 1)
        queried_branches = [sha for sha, _, _ in repo.commit_calls]
        self.assertEqual(queried_branches, ["main", "missing-meta"])

    def test_detect_activity_uses_authenticated_user_when_repository_env_missing(self) -> None:
        last_check = datetime(2026, 2, 12, 22, 30, tzinfo=timezone.utc)
        now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

        repo = FakeRepo(
            branches=[make_branch("main", datetime(2026, 2, 13, 6, 0, tzinfo=timezone.utc))],
            commits_by_branch={
                "main": [make_commit(sha="a1", author_date=datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc))],
            },
        )
        fake_github = FakeGithub(token="token-123", repos={"owner/repo": repo}, login="owner")

        with patch.dict(os.environ, {"GH_TOKEN": "token-123"}, clear=False):
            os.environ.pop("GITHUB_REPOSITORY", None)
            with patch.object(activity_detection, "HAS_GITHUB", True), patch.object(
                activity_detection,
                "Github",
                side_effect=lambda token: fake_github,
                create=True,
            ):
                result = activity_detection.detect_activity(
                    watched_repos=["owner/repo"],
                    last_check=last_check,
                    previous_session_tracker=None,
                    now=now,
                )

        self.assertEqual(result["commits_detected"], 1)
        self.assertTrue(all(author == "owner" for _, _, author in repo.commit_calls))

    def test_detect_activity_fetches_without_author_when_username_unavailable(self) -> None:
        last_check = datetime(2026, 2, 12, 22, 30, tzinfo=timezone.utc)
        now = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)

        repo = FakeRepo(
            branches=[make_branch("main", datetime(2026, 2, 13, 6, 0, tzinfo=timezone.utc))],
            commits_by_branch={
                "main": [make_commit(sha="a1", author_date=datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc))],
            },
        )
        fake_github = FakeGithub(
            token="token-123",
            repos={"owner/repo": repo},
            login=None,
            raise_on_get_user=True,
        )

        with patch.dict(os.environ, {"GH_TOKEN": "token-123"}, clear=False):
            os.environ.pop("GITHUB_REPOSITORY", None)
            with patch.object(activity_detection, "HAS_GITHUB", True), patch.object(
                activity_detection,
                "Github",
                side_effect=lambda token: fake_github,
                create=True,
            ):
                result = activity_detection.detect_activity(
                    watched_repos=["owner/repo"],
                    last_check=last_check,
                    previous_session_tracker=None,
                    now=now,
                )

        self.assertEqual(result["commits_detected"], 1)
        self.assertTrue(all(author is None for _, _, author in repo.commit_calls))


if __name__ == "__main__":
    unittest.main()
