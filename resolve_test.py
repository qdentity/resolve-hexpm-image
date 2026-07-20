"""Unit tests for resolve.py — all HTTP mocked."""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch, call

import resolve


def make_refs(tags):
    """Build GitHub matching-refs response from tag list."""
    return [{"ref": f"refs/tags/{t}"} for t in tags]


def make_urlopen_response(data, status=200, headers=None):
    """Create a mock urllib response."""
    _headers = headers or {}
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.status = status
    mock_headers = MagicMock()
    mock_headers.get = lambda k, d="": _headers.get(k, d)
    resp.headers = mock_headers
    return resp


class TestResolveElixirVersion(unittest.TestCase):
    @patch("resolve.http_request")
    def test_resolves_prefix(self, mock_http):
        refs = make_refs(["v1.17.0", "v1.17.1", "v1.17.2", "v1.17.3"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_elixir_version("1.17")
        self.assertEqual(result, "1.17.3")

    @patch("resolve.http_request")
    def test_excludes_rcs(self, mock_http):
        refs = make_refs(["v1.18.0-rc.1", "v1.18.0-rc.2", "v1.18.0", "v1.18.1"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_elixir_version("1.18")
        self.assertEqual(result, "1.18.1")

    @patch("resolve.http_request")
    def test_exact_version(self, mock_http):
        refs = make_refs(["v1.17.3"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_elixir_version("1.17.3")
        self.assertEqual(result, "1.17.3")

    @patch("resolve.http_request")
    def test_no_match_exits(self, mock_http):
        mock_http.return_value = make_urlopen_response([])
        with self.assertRaises(SystemExit):
            resolve.resolve_elixir_version("99.99")


class TestResolveOtpCandidates(unittest.TestCase):
    @patch("resolve.http_request")
    def test_resolves_major(self, mock_http):
        refs = make_refs(["OTP-28.0", "OTP-28.1", "OTP-28.3.3", "OTP-28.4.1"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_otp_candidates("28")
        self.assertEqual(result[0], "28.4.1")

    @patch("resolve.http_request")
    def test_resolves_minor_prefix(self, mock_http):
        refs = make_refs(["OTP-28.3", "OTP-28.3.1", "OTP-28.3.2", "OTP-28.3.3"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_otp_candidates("28.3")
        self.assertEqual(result[0], "28.3.3")

    @patch("resolve.http_request")
    def test_excludes_rcs(self, mock_http):
        refs = make_refs(["OTP-28.0-rc1", "OTP-28.0", "OTP-28.0.1"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_otp_candidates("28.0")
        self.assertEqual(result[0], "28.0.1")

    @patch("resolve.http_request")
    def test_orders_newest_first(self, mock_http):
        refs = make_refs(["OTP-28.5", "OTP-28.5.0.1", "OTP-28.5.0.2", "OTP-28.5.0.3"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_otp_candidates("28.5")
        self.assertEqual(result, ["28.5.0.3", "28.5.0.2", "28.5.0.1", "28.5"])

    @patch("resolve.http_request")
    def test_respects_limit(self, mock_http):
        refs = make_refs(["OTP-28.5", "OTP-28.5.0.1", "OTP-28.5.0.2", "OTP-28.5.0.3"])
        mock_http.return_value = make_urlopen_response(refs)
        result = resolve.resolve_otp_candidates("28.5", limit=2)
        self.assertEqual(result, ["28.5.0.3", "28.5.0.2"])

    @patch("resolve.http_request")
    def test_no_match_exits(self, mock_http):
        mock_http.return_value = make_urlopen_response([])
        with self.assertRaises(SystemExit):
            resolve.resolve_otp_candidates("99.99")


class TestFilterDebianTags(unittest.TestCase):
    def test_sorts_by_date_descending(self):
        tags = [
            "bookworm-20260210-slim",
            "bookworm-20260316-slim",
            "bookworm-20260115-slim",
        ]
        result = resolve.filter_debian_tags(tags, "bookworm", "slim")
        self.assertEqual(result, [
            "bookworm-20260316-slim",
            "bookworm-20260210-slim",
            "bookworm-20260115-slim",
        ])

    def test_excludes_floating_tags(self):
        tags = [
            "bookworm",
            "bookworm-slim",
            "bookworm-backports",
            "bookworm-20260316-slim",
        ]
        result = resolve.filter_debian_tags(tags, "bookworm", "slim")
        self.assertEqual(result, ["bookworm-20260316-slim"])

    def test_no_variant(self):
        tags = [
            "bookworm-20260316",
            "bookworm-20260316-slim",
            "bookworm-20260210",
        ]
        result = resolve.filter_debian_tags(tags, "bookworm", "")
        self.assertEqual(result, ["bookworm-20260316", "bookworm-20260210"])


class TestFilterUbuntuTags(unittest.TestCase):
    def test_date_ordering(self):
        tags = [
            "noble-20260210",
            "noble-20260210.1",
            "noble-20260217",
        ]
        result = resolve.filter_ubuntu_tags(tags, "noble")
        self.assertEqual(result, [
            "noble-20260217",
            "noble-20260210.1",
            "noble-20260210",
        ])

    def test_excludes_non_matching(self):
        tags = ["noble", "noble-20260210", "focal-20260210"]
        result = resolve.filter_ubuntu_tags(tags, "noble")
        self.assertEqual(result, ["noble-20260210"])


class TestFilterAlpineTags(unittest.TestCase):
    def test_semver_sort(self):
        tags = ["3.9.0", "3.18.7", "3.21.6", "latest", "edge", "3.21"]
        result = resolve.filter_alpine_tags(tags)
        self.assertEqual(result, ["3.21.6", "3.18.7", "3.9.0"])


class TestDetectOsFamily(unittest.TestCase):
    def test_alpine_shortcut(self):
        result = resolve.detect_os_family("alpine", {})
        self.assertEqual(result, "alpine")

    @patch("resolve.docker_head")
    @patch("resolve.get_docker_token", return_value="tok")
    def test_detects_debian(self, mock_token, mock_head):
        mock_head.side_effect = [(200, {}), (404, {})]
        result = resolve.detect_os_family("bookworm", {})
        self.assertEqual(result, "debian")

    @patch("resolve.docker_head")
    @patch("resolve.get_docker_token", return_value="tok")
    def test_detects_ubuntu(self, mock_token, mock_head):
        mock_head.side_effect = [(404, {}), (200, {})]
        result = resolve.detect_os_family("noble", {})
        self.assertEqual(result, "ubuntu")

    @patch("resolve.docker_head")
    @patch("resolve.get_docker_token", return_value="tok")
    def test_ambiguity_error(self, mock_token, mock_head):
        mock_head.side_effect = [(200, {}), (200, {})]
        with self.assertRaises(SystemExit):
            resolve.detect_os_family("ambiguous", {})

    @patch("resolve.docker_head")
    @patch("resolve.get_docker_token", return_value="tok")
    def test_not_found_error(self, mock_token, mock_head):
        mock_head.side_effect = [(404, {}), (404, {})]
        with self.assertRaises(SystemExit):
            resolve.detect_os_family("nonexistent", {})


class TestVariantAuto(unittest.TestCase):
    def test_debian_gets_slim(self):
        self.assertEqual(resolve.resolve_variant("auto", "debian"), "slim")

    def test_ubuntu_gets_empty(self):
        self.assertEqual(resolve.resolve_variant("auto", "ubuntu"), "")

    def test_alpine_gets_empty(self):
        self.assertEqual(resolve.resolve_variant("auto", "alpine"), "")

    def test_explicit_slim(self):
        self.assertEqual(resolve.resolve_variant("slim", "ubuntu"), "slim")

    def test_explicit_empty(self):
        self.assertEqual(resolve.resolve_variant("", "debian"), "")


class TestFallbackBehavior(unittest.TestCase):
    @patch("resolve.docker_head")
    def test_newest_404_older_succeeds(self, mock_head):
        mock_head.side_effect = [
            (404, {}),
            (200, {"Docker-Content-Digest": "sha256:abc123"}),
        ]
        token = "test-token"

        # First candidate fails
        exists1, _ = resolve.verify_builder_tag("hexpm/elixir-amd64", "tag1", token)
        self.assertFalse(exists1)

        # Second candidate succeeds
        exists2, digest = resolve.verify_builder_tag("hexpm/elixir-amd64", "tag2", token)
        self.assertTrue(exists2)
        self.assertEqual(digest, "sha256:abc123")
        self.assertEqual(mock_head.call_args_list, [
            call("hexpm/elixir-amd64", "tag1", token),
            call("hexpm/elixir-amd64", "tag2", token),
        ])


class TestOtpFallbackInMain(unittest.TestCase):
    """OTP released upstream but not yet imaged by hexpm must fall back."""

    ENV = {
        "INPUT_ELIXIR_VERSION": "1.20.0",
        "INPUT_OTP_VERSION": "28.5",
        "INPUT_DISTRIBUTION": "trixie",
        "INPUT_OS_FAMILY": "debian",
        "INPUT_VARIANT": "slim",
        "INPUT_MAX_CANDIDATES": "5",
        "INPUT_ELIXIR_REPOSITORY": "hexpm/elixir",
        "INPUT_GITHUB_TOKEN": "",
        "GITHUB_OUTPUT": "",
    }

    @patch("resolve.set_output")
    @patch("resolve.verify_builder_tag")
    @patch("resolve.get_docker_token", return_value="tok")
    @patch("resolve.resolve_base_tags", return_value=["20260610-slim"])
    @patch("resolve.resolve_otp_candidates", return_value=["28.5.0.3", "28.5.0.2", "28.5"])
    @patch("resolve.resolve_elixir_version", return_value="1.20.0")
    def test_skips_unimaged_otp_and_uses_next(
        self, _elixir, _otp, _base, _token, mock_verify, mock_output
    ):
        # 28.5.0.3 exists upstream but hexpm has no image for it yet
        mock_verify.side_effect = [
            (False, ""),
            (True, "sha256:abc123"),
        ]

        with patch.dict("os.environ", self.ENV, clear=False):
            resolve.main()

        tried = [c.args[1] for c in mock_verify.call_args_list]
        self.assertEqual(tried, [
            "1.20.0-erlang-28.5.0.3-debian-20260610-slim",
            "1.20.0-erlang-28.5.0.2-debian-20260610-slim",
        ])

        outputs = dict(c.args for c in mock_output.call_args_list)
        self.assertEqual(outputs["otp-version"], "28.5.0.2")
        self.assertEqual(
            outputs["builder-image"],
            "hexpm/elixir:1.20.0-erlang-28.5.0.2-debian-20260610-slim",
        )

    @patch("resolve.set_output")
    @patch("resolve.verify_builder_tag", return_value=(False, ""))
    @patch("resolve.get_docker_token", return_value="tok")
    @patch("resolve.resolve_base_tags", return_value=["20260610-slim"])
    @patch("resolve.resolve_otp_candidates", return_value=["28.5.0.3", "28.5"])
    @patch("resolve.resolve_elixir_version", return_value="1.20.0")
    def test_exits_when_no_candidate_has_an_image(
        self, _elixir, _otp, _base, _token, _verify, _output
    ):
        with patch.dict("os.environ", self.ENV, clear=False):
            with self.assertRaises(SystemExit):
                resolve.main()


class TestRetryOn5xx(unittest.TestCase):
    @patch("resolve.time.sleep")
    @patch("resolve.urllib.request.urlopen")
    def test_retries_on_503(self, mock_urlopen, mock_sleep):
        error_503 = resolve.urllib.error.HTTPError(
            "http://x", 503, "Service Unavailable", {}, None
        )
        success = MagicMock()
        success.read.return_value = b'{"tags": []}'
        success.status = 200
        success.headers = MagicMock()
        success.headers.get = lambda k, d="": ""

        mock_urlopen.side_effect = [error_503, error_503, success]
        resp = resolve.http_request("http://x")
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(resp.status, 200)


class TestBuildRunnerImage(unittest.TestCase):
    def test_debian(self):
        result = resolve.build_runner_image("debian", "bookworm-20260316-slim")
        self.assertEqual(result, "debian:bookworm-20260316-slim")

    def test_ubuntu(self):
        result = resolve.build_runner_image("ubuntu", "noble-20260210")
        self.assertEqual(result, "ubuntu:noble-20260210")

    def test_alpine(self):
        result = resolve.build_runner_image("alpine", "3.21.6")
        self.assertEqual(result, "alpine:3.21.6")


class TestBuildHexpmTag(unittest.TestCase):
    def test_debian_slim(self):
        result = resolve.build_hexpm_tag("1.17.3", "27.1.2", "debian", "bookworm-20260316-slim")
        self.assertEqual(result, "1.17.3-erlang-27.1.2-debian-bookworm-20260316-slim")

    def test_ubuntu(self):
        result = resolve.build_hexpm_tag("1.18.4", "28.0.2", "ubuntu", "noble-20260210")
        self.assertEqual(result, "1.18.4-erlang-28.0.2-ubuntu-noble-20260210")

    def test_alpine(self):
        result = resolve.build_hexpm_tag("1.16.3", "26.2.5", "alpine", "3.21.6")
        self.assertEqual(result, "1.16.3-erlang-26.2.5-alpine-3.21.6")


class TestValidation(unittest.TestCase):
    def test_empty_elixir(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("", "28", "bookworm", "auto", "auto", 5, "hexpm/elixir")

    def test_empty_otp(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "", "bookworm", "auto", "auto", 5, "hexpm/elixir")

    def test_invalid_distribution(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "28", "Book-worm!", "auto", "auto", 5, "hexpm/elixir")

    def test_invalid_os_family(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "28", "bookworm", "windows", "auto", 5, "hexpm/elixir")

    def test_invalid_variant(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "28", "bookworm", "auto", "fat", 5, "hexpm/elixir")

    def test_zero_candidates(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "28", "bookworm", "auto", "auto", 0, "hexpm/elixir")

    def test_invalid_elixir_repository(self):
        with self.assertRaises(SystemExit):
            resolve.validate_inputs("1.17", "28", "bookworm", "auto", "auto", 5, "HexPM/elixir")

    def test_valid_inputs(self):
        # Should not raise
        resolve.validate_inputs("1.17", "28", "bookworm", "auto", "auto", 5, "hexpm/elixir")
        resolve.validate_inputs("1.17.3", "28.3.3", "alpine", "alpine", "", 1, "hexpm/elixir-amd64")


if __name__ == "__main__":
    unittest.main()
