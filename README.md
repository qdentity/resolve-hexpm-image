# resolve-hexpm-image

Resolves the latest HexPM Elixir Docker image tag for given Elixir/OTP versions and OS distribution.

Handles version prefix resolution (e.g., `1.17` → `1.17.3`), base image date tag discovery, and hexpm tag verification — all via stdlib-only Python 3.

## Usage

```yaml
- uses: qdentity/resolve-hexpm-image@v1
  id: images
  with:
    elixir-version: '1.17'
    otp-version: '27'

- run: docker pull ${{ steps.images.outputs.builder-image }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `elixir-version` | yes | — | Elixir version prefix (`1.17` → latest `1.17.x`) |
| `otp-version` | yes | — | OTP version prefix (`28` → latest `28.x.y`) |
| `distribution` | no | `bookworm` | OS codename or `alpine` |
| `os-family` | no | `auto` | `debian`, `ubuntu`, `alpine`, or `auto` |
| `variant` | no | `auto` | `auto` = slim for debian, none for ubuntu/alpine |
| `max-candidates` | no | `5` | Base image date tags to try |
| `elixir-repository` | no | `hexpm/elixir` | Docker Hub repository for Elixir builder images |
| `github-token` | no | `${{ github.token }}` | GitHub API token |

## Outputs

| Output | Example |
|--------|---------|
| `builder-image` | `hexpm/elixir:1.17.3-erlang-27.1.2-debian-bookworm-20260316-slim` |
| `runner-image` | `debian:bookworm-20260316-slim` |
| `elixir-version` | `1.17.3` |
| `otp-version` | `27.1.2` |
| `builder-digest` | `sha256:...` |

## Examples

```yaml
# Ubuntu noble:
- uses: qdentity/resolve-hexpm-image@v1
  with:
    elixir-version: '1.18.4'
    otp-version: '28.0.2'
    distribution: noble

# Alpine:
- uses: qdentity/resolve-hexpm-image@v1
  with:
    elixir-version: '1.16.3'
    otp-version: '26.2.5'
    distribution: alpine

# Explicit OS family:
- uses: qdentity/resolve-hexpm-image@v1
  with:
    elixir-version: '1.19'
    otp-version: '28.3'
    distribution: trixie
    os-family: debian

# amd64-only HexPM image repository:
- uses: qdentity/resolve-hexpm-image@v1
  with:
    elixir-version: '1.20.0'
    otp-version: '28'
    distribution: bookworm
    elixir-repository: hexpm/elixir-amd64
```
