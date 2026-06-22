import os
import pytest
from unittest.mock import patch, MagicMock
from hermes.pr_builder import create_github_pr, push_branch, _build_pr_body, _parse_github_repo


def test_parse_github_repo_https():
    owner, name = _parse_github_repo("https://github.com/acme/myrepo.git")
    assert owner == "acme"
    assert name == "myrepo"


def test_parse_github_repo_ssh():
    owner, name = _parse_github_repo("git@github.com:acme/myrepo.git")
    assert owner == "acme"
    assert name == "myrepo"


def test_build_pr_body_contains_author_and_root_cause():
    body = _build_pr_body(
        root_cause="The add function subtracted instead of adding.",
        author="Jane Doe",
        test_output="1 passed in 0.12s",
    )
    assert "Jane Doe" in body
    assert "The add function subtracted instead of adding." in body
    assert "1 passed in 0.12s" in body


def test_create_github_pr_calls_github_api():
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/acme/myrepo/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    mock_github = MagicMock()
    mock_github.get_repo.return_value = mock_repo

    with patch("hermes.pr_builder.Github", return_value=mock_github):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            url = create_github_pr(
                repo_url="https://github.com/acme/myrepo.git",
                branch_name="hotfix/hermes-20260622-120000",
                base_branch="main",
                root_cause="Bug: subtraction instead of addition.",
                author="Jane Doe",
                test_output="1 passed",
            )

    assert url == "https://github.com/acme/myrepo/pull/42"
    mock_repo.create_pull.assert_called_once()
    call_kwargs = mock_repo.create_pull.call_args[1]
    assert call_kwargs["draft"] is False
    assert "Jane Doe" in call_kwargs["body"]
    assert "Bug: subtraction instead of addition." in call_kwargs["body"]
    assert "1 passed" in call_kwargs["body"]
