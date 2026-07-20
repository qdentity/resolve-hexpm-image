#!/usr/bin/env python3
"""Resolve hexpm/elixir Docker image tags for GitHub Actions."""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DOCKER_REGISTRY = "https://registry-1.docker.io"
DOCKER_AUTH = "https://auth.docker.io"
GITHUB_API = "https://api.github.com"
HTTP_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]

KNOWN_DISTRIBUTIONS = {"bookworm", "bullseye", "trixie", "noble", "focal", "alpine"}


def log(msg):
    print(f"::group::{msg}" if msg.startswith("[") else msg, flush=True)


def http_request(url, headers=None, method="GET", retries=MAX_RETRIES):
    """Make HTTP request with retry on 429/5xx."""
    headers = headers or {}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            return resp
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return e
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log(f"  HTTP {e.code} for {url}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed after {retries} retries: {url}")


def get_docker_token(repo):
    """Get anonymous bearer token for Docker registry."""
    url = f"{DOCKER_AUTH}/token?service=registry.docker.io&scope=repository:{repo}:pull"
    resp = http_request(url)
    return json.loads(resp.read().decode())["token"]


def docker_head(repo, tag, token):
    """HEAD request to Docker registry manifest. Returns (status_code, headers)."""
    url = f"{DOCKER_REGISTRY}/v2/{repo}/manifests/{tag}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": (
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.index.v1+json, "
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
    }
    resp = http_request(url, headers=headers, method="HEAD")
    if isinstance(resp, urllib.error.HTTPError):
        return resp.code, resp.headers
    return resp.status, resp.headers


def docker_tags(repo, token):
    """Fetch all tags from a Docker registry repo via pagination."""
    tags = []
    url = f"{DOCKER_REGISTRY}/v2/{repo}/tags/list?n=1000"
    headers = {"Authorization": f"Bearer {token}"}
    while url:
        resp = http_request(url, headers=headers)
        data = json.loads(resp.read().decode())
        tags.extend(data.get("tags", []))
        # Follow Link header for pagination
        link = resp.headers.get("Link", "")
        url = None
        if link:
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            if m:
                next_path = m.group(1)
                if next_path.startswith("/"):
                    url = f"{DOCKER_REGISTRY}{next_path}"
                elif next_path.startswith("http"):
                    url = next_path
                else:
                    url = f"{DOCKER_REGISTRY}/v2/{repo}/{next_path}"
    return tags


def parse_version(s):
    """Parse version string into tuple of ints. Returns None if unparseable."""
    parts = s.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def github_matching_refs(repo, prefix, github_token=None):
    """Fetch matching refs from GitHub API (server-side prefix match)."""
    refs = []
    url = f"{GITHUB_API}/repos/{repo}/git/matching-refs/{prefix}"
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    page = 1
    while True:
        page_url = f"{url}?per_page=100&page={page}"
        resp = http_request(page_url, headers=headers)
        data = json.loads(resp.read().decode())
        if not data:
            break
        refs.extend(data)
        if len(data) < 100:
            break
        page += 1
    return refs


def resolve_elixir_version(prefix, github_token=None):
    """Resolve elixir version prefix to exact version."""
    log(f"[resolve] Elixir version prefix: {prefix}")
    refs = github_matching_refs(
        "elixir-lang/elixir", f"tags/v{prefix}", github_token
    )
    versions = []
    for ref in refs:
        tag = ref["ref"].split("/")[-1]  # refs/tags/vX.Y.Z
        if tag.startswith("v"):
            tag = tag[1:]
        if "-" in tag:  # skip RCs
            continue
        v = parse_version(tag)
        if v and len(v) == 3:
            versions.append((v, tag))
    if not versions:
        sys.exit(f"No Elixir versions found matching prefix '{prefix}'")
    versions.sort(key=lambda x: x[0], reverse=True)
    result = versions[0][1]
    log(f"  Resolved: {result}")
    return result


def resolve_otp_candidates(prefix, github_token=None, limit=5):
    """Resolve OTP version prefix to candidate versions, newest first.

    An OTP release exists upstream before hexpm builds a matching Elixir image,
    so the newest OTP version can have no image for hours or days. Returning
    several candidates lets the caller fall back to the newest one that does.
    """
    log(f"[resolve] OTP version prefix: {prefix}")
    refs = github_matching_refs(
        "erlang/otp", f"tags/OTP-{prefix}", github_token
    )
    versions = []
    for ref in refs:
        tag = ref["ref"].split("/")[-1]  # refs/tags/OTP-X.Y.Z
        if tag.startswith("OTP-"):
            tag = tag[4:]
        if "-" in tag:  # skip RCs
            continue
        v = parse_version(tag)
        if v and len(v) >= 2:
            versions.append((v, tag))
    if not versions:
        sys.exit(f"No OTP versions found matching prefix '{prefix}'")
    versions.sort(key=lambda x: x[0], reverse=True)
    result = [tag for _, tag in versions[:limit]]
    log(f"  Top {len(result)} candidates: {', '.join(result)}")
    return result


def detect_os_family(distribution, token_cache):
    """Detect OS family by probing Docker registry."""
    if distribution == "alpine":
        return "alpine"

    log(f"[detect] Probing OS family for '{distribution}'...")

    debian_token = token_cache.setdefault(
        "library/debian", get_docker_token("library/debian")
    )
    debian_status, _ = docker_head("library/debian", distribution, debian_token)
    is_debian = debian_status == 200

    ubuntu_token = token_cache.setdefault(
        "library/ubuntu", get_docker_token("library/ubuntu")
    )
    ubuntu_status, _ = docker_head("library/ubuntu", distribution, ubuntu_token)
    is_ubuntu = ubuntu_status == 200

    if is_debian and is_ubuntu:
        sys.exit(
            f"Distribution '{distribution}' exists in both debian and ubuntu. "
            f"Please set os-family explicitly."
        )
    if is_debian:
        log(f"  Detected: debian")
        return "debian"
    if is_ubuntu:
        log(f"  Detected: ubuntu")
        return "ubuntu"
    sys.exit(
        f"Distribution '{distribution}' not found in debian or ubuntu registries. "
        f"Known distributions: {', '.join(sorted(KNOWN_DISTRIBUTIONS))}"
    )


def resolve_variant(variant, os_family):
    """Resolve variant=auto to concrete value."""
    if variant == "auto":
        return "slim" if os_family == "debian" else ""
    return variant


def filter_debian_tags(all_tags, release, variant):
    """Filter and sort debian tags by date."""
    if variant:
        pattern = re.compile(rf"^{re.escape(release)}-(\d{{8}})-{re.escape(variant)}$")
    else:
        pattern = re.compile(rf"^{re.escape(release)}-(\d{{8}})$")
    matches = []
    for tag in all_tags:
        m = pattern.match(tag)
        if m:
            matches.append((m.group(1), tag))
    matches.sort(key=lambda x: x[0], reverse=True)
    return [tag for _, tag in matches]


def filter_ubuntu_tags(all_tags, release):
    """Filter and sort ubuntu tags by date (YYYYMMDD.N format)."""
    pattern = re.compile(rf"^{re.escape(release)}-(\d{{8}}(?:\.\d+)?)$")
    matches = []
    for tag in all_tags:
        m = pattern.match(tag)
        if m:
            date_str = m.group(1)
            if "." in date_str:
                date_part, suffix = date_str.split(".", 1)
                sort_key = (date_part, int(suffix))
            else:
                sort_key = (date_str, 0)
            matches.append((sort_key, tag))
    matches.sort(key=lambda x: x[0], reverse=True)
    return [tag for _, tag in matches]


def filter_alpine_tags(all_tags):
    """Filter and sort alpine tags by semver."""
    pattern = re.compile(r"^\d+\.\d+\.\d+$")
    matches = []
    for tag in all_tags:
        if pattern.match(tag):
            v = parse_version(tag)
            if v:
                matches.append((v, tag))
    matches.sort(key=lambda x: x[0], reverse=True)
    return [tag for _, tag in matches]


def resolve_base_tags(distribution, os_family, variant, max_candidates, token_cache):
    """Resolve base image tags sorted by recency."""
    log(f"[resolve] Base image tags for {os_family}/{distribution}")

    if os_family == "alpine":
        repo = "library/alpine"
        token = token_cache.setdefault(repo, get_docker_token(repo))
        all_tags = docker_tags(repo, token)
        candidates = filter_alpine_tags(all_tags)
    elif os_family == "debian":
        repo = "library/debian"
        token = token_cache.setdefault(repo, get_docker_token(repo))
        all_tags = docker_tags(repo, token)
        candidates = filter_debian_tags(all_tags, distribution, variant)
    elif os_family == "ubuntu":
        repo = "library/ubuntu"
        token = token_cache.setdefault(repo, get_docker_token(repo))
        all_tags = docker_tags(repo, token)
        candidates = filter_ubuntu_tags(all_tags, distribution)
    else:
        sys.exit(f"Unknown OS family: {os_family}")

    if not candidates:
        sys.exit(f"No base image tags found for {os_family}/{distribution}")

    result = candidates[:max_candidates]
    log(f"  Top {len(result)} candidates: {', '.join(result)}")
    return result


def build_hexpm_tag(elixir, otp, os_family, base_tag):
    """Build hexpm/elixir tag string."""
    return f"{elixir}-erlang-{otp}-{os_family}-{base_tag}"


def build_runner_image(os_family, base_tag):
    """Build runner image string from OS family and base tag."""
    return f"{os_family}:{base_tag}"


def verify_builder_tag(elixir_repository, hexpm_tag, token):
    """Verify builder image tag exists. Returns (exists, digest)."""
    status, headers = docker_head(elixir_repository, hexpm_tag, token)
    if status == 200:
        digest = headers.get("Docker-Content-Digest", "")
        return True, digest
    return False, ""


def validate_inputs(
    elixir_version,
    otp_version,
    distribution,
    os_family,
    variant,
    max_candidates,
    elixir_repository,
):
    """Validate all inputs."""
    if not elixir_version:
        sys.exit("elixir-version is required")
    if not otp_version:
        sys.exit("otp-version is required")
    if not re.match(r"^[a-z]+$", distribution):
        sys.exit(f"Invalid distribution: '{distribution}' (must be lowercase letters only)")
    if os_family not in ("auto", "debian", "ubuntu", "alpine"):
        sys.exit(f"Invalid os-family: '{os_family}' (must be auto, debian, ubuntu, or alpine)")
    if variant not in ("auto", "slim", ""):
        sys.exit(f"Invalid variant: '{variant}' (must be auto, slim, or empty)")
    if max_candidates < 1:
        sys.exit(f"max-candidates must be positive, got {max_candidates}")
    repository_pattern = r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+$"
    if not re.match(repository_pattern, elixir_repository):
        sys.exit(
            f"Invalid elixir-repository: '{elixir_repository}' "
            "(must be a Docker Hub repository path)"
        )


def set_output(name, value):
    """Write GitHub Actions output."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{name}={value}\n")
    log(f"  Output {name}={value}")


def main():
    # Read inputs
    elixir_version = os.environ.get("INPUT_ELIXIR_VERSION", os.environ.get("INPUT_ELIXIR-VERSION", "")).strip()
    otp_version = os.environ.get("INPUT_OTP_VERSION", os.environ.get("INPUT_OTP-VERSION", "")).strip()
    distribution = os.environ.get("INPUT_DISTRIBUTION", "bookworm").strip()
    os_family = os.environ.get("INPUT_OS_FAMILY", os.environ.get("INPUT_OS-FAMILY", "auto")).strip()
    variant = os.environ.get("INPUT_VARIANT", "auto").strip()
    max_candidates = int(
        os.environ.get("INPUT_MAX_CANDIDATES", os.environ.get("INPUT_MAX-CANDIDATES", "5"))
    )
    elixir_repository = os.environ.get(
        "INPUT_ELIXIR_REPOSITORY", os.environ.get("INPUT_ELIXIR-REPOSITORY", "hexpm/elixir")
    ).strip()
    github_token = os.environ.get("INPUT_GITHUB_TOKEN", os.environ.get("INPUT_GITHUB-TOKEN", "")).strip()

    validate_inputs(elixir_version, otp_version, distribution, os_family, variant, max_candidates, elixir_repository)

    # Step 1: Resolve version prefixes
    elixir = resolve_elixir_version(elixir_version, github_token or None)
    otp_candidates = resolve_otp_candidates(otp_version, github_token or None, max_candidates)

    # Step 2: Detect OS family and resolve base tags
    token_cache = {}
    if os_family == "auto":
        os_family = detect_os_family(distribution, token_cache)

    resolved_variant = resolve_variant(variant, os_family)
    base_tags = resolve_base_tags(distribution, os_family, resolved_variant, max_candidates, token_cache)

    # Step 3: Verify builder image tag exists
    log(f"[verify] Checking {elixir_repository} tags...")
    builder_token = get_docker_token(elixir_repository)

    for otp in otp_candidates:
        for base_tag in base_tags:
            hexpm_tag = build_hexpm_tag(elixir, otp, os_family, base_tag)
            log(f"  Trying: {hexpm_tag}")
            exists, digest = verify_builder_tag(elixir_repository, hexpm_tag, builder_token)
            if exists:
                log(f"  Found!")
                builder_image = f"{elixir_repository}:{hexpm_tag}"
                runner_image = build_runner_image(os_family, base_tag)

                set_output("builder-image", builder_image)
                set_output("runner-image", runner_image)
                set_output("elixir-version", elixir)
                set_output("otp-version", otp)
                set_output("builder-digest", digest)
                return

            log(f"  Not found (404)")

    sys.exit(
        f"No {elixir_repository} image found for Elixir {elixir}, "
        f"{os_family}/{distribution} after trying OTP {', '.join(otp_candidates)} "
        f"against {len(base_tags)} base tags: {', '.join(base_tags)}"
    )


if __name__ == "__main__":
    main()
