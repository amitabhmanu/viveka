"""HTTP access to data sources: rate limits, retries, a raw archive and a spend cap (spec §13, §14).

Every live response is archived once under ``data/raw/<source>/``, keyed by its request, with a
sidecar recording the URL and parameters (secrets are never part of a request), the retrieval
time, the source's terms reference and the content hash. A request already in the archive is
replayed and costs nothing, so re-running a stage reproduces its inputs exactly.

Before every live attempt the ``UsageMeter`` prices the call from the registry and refuses one
that would take today's spend on that source past the registered cap. Today's spend is kept in
``data/usage/<source>-<date>.jsonl`` so that drafting lookups, which are not runs, count too.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from viveka import __version__
from viveka.hashing import sha256_bytes

RAW = "data/raw"
USAGE = "data/usage"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5


class FetchError(RuntimeError):
    pass


class SpendCapExceeded(FetchError):
    pass


class NotArchived(FetchError):
    """An offline fetcher was asked for a response that would need a live call."""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Request:
    source: str
    kind: str  # price class: singleton, list, search, content, or free
    url: str
    params: tuple[tuple[str, str], ...] = ()

    @classmethod
    def build(cls, source: str, kind: str, url: str, **params: object) -> Request:
        return cls(source, kind, url, tuple(sorted((k, str(v)) for k, v in params.items() if v is not None)))

    def key(self) -> str:
        payload = json.dumps([self.source, self.url, [list(p) for p in self.params]], separators=(",", ":"))
        return sha256_bytes(payload.encode("utf-8")).removeprefix("sha256:")


@dataclass(frozen=True)
class Response:
    status: int
    body: dict | None
    raw_path: Path
    live: bool


@dataclass
class Usage:
    live_calls: dict[str, dict[str, int]] = field(default_factory=dict)
    replayed: dict[str, int] = field(default_factory=dict)
    usd: dict[str, float] = field(default_factory=dict)

    def charge(self, request: Request, usd: float) -> None:
        by_kind = self.live_calls.setdefault(request.source, {})
        by_kind[request.kind] = by_kind.get(request.kind, 0) + 1
        self.usd[request.source] = self.usd.get(request.source, 0.0) + usd

    def replay(self, request: Request) -> None:
        self.replayed[request.source] = self.replayed.get(request.source, 0) + 1

    def as_manifest(self) -> dict:
        return {
            "live_calls": {s: dict(sorted(k.items())) for s, k in sorted(self.live_calls.items())},
            "replayed": dict(sorted(self.replayed.items())),
            "usd": {s: round(v, 6) for s, v in sorted(self.usd.items())},
        }


class UsageMeter:
    """Prices live calls and enforces each priced source's daily cap."""

    def __init__(self, root: Path, prices: Mapping[str, Mapping[str, float]], caps: Mapping[str, float],
                 today: Callable[[], dt.date] | None = None):
        self.root = root
        self.prices = {s: dict(p) for s, p in prices.items()}
        self.caps = dict(caps)
        self.today = today or (lambda: dt.datetime.now(dt.UTC).date())
        self._spent: dict[tuple[str, dt.date], float] = {}

    def price(self, request: Request) -> float:
        return float(self.prices.get(request.source, {}).get(request.kind, 0.0))

    def log_path(self, source: str, day: dt.date) -> Path:
        return self.root / USAGE / f"{source}-{day:%Y-%m-%d}.jsonl"

    def spent_today(self, source: str) -> float:
        day = self.today()
        if (source, day) not in self._spent:
            path = self.log_path(source, day)
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            self._spent[(source, day)] = sum(float(json.loads(line)["usd"]) for line in lines if line.strip())
        return self._spent[(source, day)]

    def charge(self, request: Request, run_id: str | None) -> float:
        price = self.price(request)
        if price <= 0:
            return 0.0
        day = self.today()
        spent = self.spent_today(request.source)
        cap = self.caps.get(request.source)
        if cap is not None and spent + price > cap + 1e-9:
            raise SpendCapExceeded(
                f"{request.source}: a {request.kind} call (${price}) would take today's spend from ${spent:.4f} "
                f"past the registered cap of ${cap:.2f}; stopping (resume tomorrow, or change the cap by decision D-6)"
            )
        path = self.log_path(request.source, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"time": _now(), "source": request.source, "kind": request.kind, "usd": price,
                                 "run_id": run_id}) + "\n")
        self._spent[(request.source, day)] = spent + price
        return price


class Archive:
    def __init__(self, root: Path, terms: Callable[[str], str | None]):
        self.root = root
        self.terms = terms

    def paths(self, request: Request) -> tuple[Path, Path]:
        key = request.key()
        base = self.root / RAW / request.source / key[:2]
        return base / f"{key}.json", base / f"{key}.meta.json"

    def get(self, request: Request) -> tuple[int, dict | None, Path] | None:
        body_path, _ = self.paths(request)
        if not body_path.is_file():
            return None
        data = json.loads(body_path.read_text(encoding="utf-8"))
        return int(data["status"]), data["body"], body_path

    def put(self, request: Request, status: int, body: dict | None) -> Path:
        body_path, meta_path = self.paths(request)
        content = json.dumps({"status": status, "body": body}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        body_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(body_path, "xb") as fh:
                fh.write(content)
        except FileExistsError:
            return body_path  # archived files are never overwritten
        meta = {"source": request.source, "kind": request.kind, "url": request.url, "params": dict(request.params),
                "retrieved_at": _now(), "terms_reference": self.terms(request.source),
                "sha256": sha256_bytes(content), "viveka_version": __version__}
        with open(meta_path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        return body_path


def _retry_after(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After", "")
    return min(float(header), 60.0) if header.isdigit() else min(2.0**attempt, 60.0)


class Fetcher:
    """GETs JSON from the registered sources, archive first.

    ``secrets`` maps a source to the query parameters and headers that carry its credentials; they
    are added only at send time, so they never reach the archive, a request key or an error message.
    """

    def __init__(self, root: Path, *, rates: Mapping[str, float], meter: UsageMeter,
                 terms: Callable[[str], str | None],
                 secrets: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
                 contact_email: str | None = None, transport: httpx.BaseTransport | None = None,
                 offline: bool = False, run_id: str | None = None,
                 sleep: Callable[[float], None] | None = None, clock: Callable[[], float] | None = None):
        self.archive = Archive(root, terms)
        self.rates = dict(rates)
        self.meter = meter
        self.secrets = {s: {part: dict(values) for part, values in v.items()} for s, v in (secrets or {}).items()}
        self.offline = offline
        self.run_id = run_id
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        agent = f"viveka/{__version__}" + (f" (mailto:{contact_email})" if contact_email else "")
        self.client = httpx.Client(transport=transport, timeout=60.0, headers={"User-Agent": agent},
                                   follow_redirects=True)
        self.usage = Usage()
        self.used_paths: dict[str, Path] = {}
        self._last_call: dict[str, float] = {}

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.client.close()
        return False

    def archived(self, request: Request) -> Response | None:
        hit = self.archive.get(request)
        return None if hit is None else Response(hit[0], hit[1], hit[2], live=False)

    def get(self, request: Request) -> Response:
        hit = self.archived(request)
        if hit is not None:
            self.usage.replay(request)
            self.used_paths[str(hit.raw_path)] = hit.raw_path
            return hit
        if self.offline:
            raise NotArchived(f"{request.source}: {request.url} is not in the raw archive")
        status, body = self._live(request)
        path = self.archive.put(request, status, body)
        self.used_paths[str(path)] = path
        return Response(status, body, path, live=True)

    def _wait(self, source: str) -> None:
        rate = self.rates.get(source)
        if not rate:
            return
        last = self._last_call.get(source)
        if last is not None:
            gap = 1.0 / rate - (self.clock() - last)
            if gap > 0:
                self.sleep(gap)
        self._last_call[source] = self.clock()

    def _live(self, request: Request) -> tuple[int, dict | None]:
        secret = self.secrets.get(request.source, {})
        params = {**dict(request.params), **secret.get("params", {})}
        headers = dict(secret.get("headers", {}))
        problem = "no attempt made"
        for attempt in range(MAX_ATTEMPTS):
            self.usage.charge(request, self.meter.charge(request, self.run_id))
            self._wait(request.source)
            try:
                response = self.client.get(request.url, params=params, headers=headers)
            except httpx.TransportError as exc:  # message may contain the full URL, so it is not repeated
                problem = type(exc).__name__
                self.sleep(min(2.0**attempt, 60.0))
                continue
            if response.status_code == 200:
                try:
                    return 200, response.json()
                except ValueError:
                    raise FetchError(f"{request.source} {request.url}: response is not JSON") from None
            if response.status_code == 404:
                return 404, None
            problem = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUSES:
                break
            self.sleep(_retry_after(response, attempt))
        raise FetchError(f"{request.source} {request.url}: {problem}")
