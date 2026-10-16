# Deployment

## Container contract

The root `Dockerfile` produces one HTTP service on port `8000`. It builds the
React application and C++ library in separate stages, then copies both into a
non-root Python runtime.

Required durable mounts:

- `/data` for uploaded videos, thumbnails, SQLite, and vector indexes.
- The generated `/data/.session-secret` must persist with the library so existing
  browser sessions remain valid. Do not bake a shared signing key into an image.
- `/home/sceneseek/.cache/huggingface` for model weights (recommended, otherwise
  replacements download the model again).

Useful environment variables are listed in `.env.example`. Set
`SCENESEEK_COOKIE_SECURE=true` for HTTPS. A production service
should set a request-body limit at its load balancer at or above
`SCENESEEK_MAX_UPLOAD_MB`.

## Small private deployment

For a single trusted user or small team, deploy the image to a VM with Docker
Compose and place an HTTPS reverse proxy with authentication in front of port
`8000`. Back up the `/data` volume together; the SQLite catalog and `.npz` files
form one logical snapshot.

## Managed container deployment

The image can run on ECS, Cloud Run, Fly.io, or another service that supports a
persistent volume and at least 2 GB of memory. Use one application worker. A
platform with ephemeral storage can demonstrate search, but indexed videos will
disappear when the instance is replaced.

Typical CPU sizing for the base CLIP model:

- 2–4 vCPU
- 4 GB RAM
- storage sized for original media plus roughly one thumbnail and one 512-float
  vector per sampling interval

## Public-launch checklist

- Browser-session ownership is enforced on every library/job/media/search route.
  Add authenticated account identity or an authenticated proxy for sensitive
  collections; session isolation alone is not a login system.
- Add malware scanning and stricter media probing before decoding untrusted files.
- Put uploads into object storage using signed URLs rather than proxying very
  large bodies through the API.
- Move jobs to a durable worker queue and publish retry/dead-letter metrics.
- Add a privacy/retention policy and automated deletion schedule.
- Pin the container by digest and enable dependency/image vulnerability scans.
- Configure HTTPS, request throttling, logs, health checks, and resource alarms.

The existing Detour App Runner instance has only 512 MB and ephemeral storage.
A real CLIP process exceeded 1 GB during verification, so it cannot safely host
this application unchanged. Do not repurpose that preview, increase its size, or
provision storage without explicit hosting authorization.

