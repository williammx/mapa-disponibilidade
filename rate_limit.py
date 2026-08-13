"""Limite de tentativas de senha para login e links protegidos.

Guarda o carimbo de tempo de cada falha numa janela deslizante por chave
(escopo + identificador + IP). Usa Redis quando REDIS_URL existe, para que
varios workers uvicorn compartilhem o mesmo contador; sem Redis cai para um
dicionario do processo, que e o suficiente em desenvolvimento e em teste.
"""
import math
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request, status

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_WINDOW_SECONDS = 15 * 60
KEY_PREFIX = "nexolote:rate:"

_memory_hits: dict[str, list[float]] = {}
_memory_lock = threading.Lock()
_redis_client = None
_redis_url = ""


def max_attempts() -> int:
    return _positive_env("LOGIN_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)


def window_seconds() -> int:
    return _positive_env("LOGIN_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS)


def _positive_env(name: str, fallback: int) -> int:
    # Uma variavel de ambiente errada nao pode derrubar o login nem desligar o
    # limite: valor invalido ou <= 0 volta para o default.
    try:
        value = int(os.getenv(name, "").strip() or fallback)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def client_ip(request: Request | None) -> str:
    """IP do cliente atras do Nginx.

    A ordem importa para o limite servir de alguma coisa. O Nginx grava
    ``X-Real-IP`` com ``$remote_addr``, que o cliente nao consegue forjar. Ja o
    ``X-Forwarded-For`` e montado com ``$proxy_add_x_forwarded_for``, que
    *anexa* o IP real ao que o cliente mandou: quem envia um
    ``X-Forwarded-For`` aleatorio a cada requisicao controla o primeiro
    elemento e troca de chave sempre, zerando o limite. Por isso lemos o
    ``X-Real-IP`` primeiro e, no ``X-Forwarded-For``, o ULTIMO elemento — o
    unico que foi escrito pelo proprio proxy.
    """
    if request is None:
        return "desconhecido"
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for", "")
    for candidate in reversed(forwarded.split(",")):
        candidate = candidate.strip()
        if candidate:
            return candidate
    if request.client and request.client.host:
        return request.client.host
    return "desconhecido"


def _redis():
    global _redis_client, _redis_url
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    if _redis_client is None or _redis_url != url:
        from redis import Redis

        _redis_client = Redis.from_url(url, decode_responses=True)
        _redis_url = url
    return _redis_client


class PasswordAttempts:
    """Contador de falhas de senha de uma chave (escopo, identificador, IP)."""

    def __init__(self, scope: str, identifier: str, ip: str) -> None:
        self.key = f"{KEY_PREFIX}{scope}:{identifier}:{ip}"

    def retry_after(self) -> int:
        """Segundos ate liberar, ou 0 quando ainda ha tentativa disponivel."""
        window = window_seconds()
        now = time.time()
        hits = self._hits(now, window)
        if len(hits) < max_attempts():
            return 0
        return max(1, math.ceil(hits[0] + window - now))

    def register_failure(self) -> None:
        now = time.time()
        window = window_seconds()
        client = _redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.zremrangebyscore(self.key, 0, now - window)
                # O sufixo aleatorio impede que duas falhas simultaneas em
                # workers diferentes virem um unico membro do sorted set.
                pipe.zadd(self.key, {f"{now:.6f}:{secrets.token_hex(4)}": now})
                pipe.expire(self.key, window)
                pipe.execute()
                return
            except Exception:
                # Redis fora do ar nao pode liberar forca bruta: segue no
                # contador em memoria deste worker.
                pass
        with _memory_lock:
            hits = [hit for hit in _memory_hits.get(self.key, []) if hit > now - window]
            hits.append(now)
            _memory_hits[self.key] = hits

    def clear(self) -> None:
        client = _redis()
        if client is not None:
            try:
                client.delete(self.key)
            except Exception:
                pass
        with _memory_lock:
            _memory_hits.pop(self.key, None)

    def enforce(self) -> None:
        seconds = self.retry_after()
        if not seconds:
            return
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=blocked_message(seconds),
            headers={"Retry-After": str(seconds)},
        )

    def _hits(self, now: float, window: int) -> list[float]:
        client = _redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.zremrangebyscore(self.key, 0, now - window)
                pipe.zrange(self.key, 0, -1, withscores=True)
                _, stored = pipe.execute()
                return sorted(score for _, score in stored)
            except Exception:
                pass
        with _memory_lock:
            hits = [hit for hit in _memory_hits.get(self.key, []) if hit > now - window]
            if hits:
                _memory_hits[self.key] = hits
            else:
                _memory_hits.pop(self.key, None)
            return hits


def blocked_message(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    unidade = "minuto" if minutes == 1 else "minutos"
    return f"Muitas tentativas. Tente novamente em {minutes} {unidade}."


def password_attempts(scope: str, identifier: str, request: Request | None) -> PasswordAttempts:
    return PasswordAttempts(scope, identifier, client_ip(request))


def reset() -> None:
    """Zera o estado do limitador. Usado entre testes."""
    global _redis_client, _redis_url
    client = _redis()
    if client is not None:
        try:
            keys = list(client.scan_iter(match=f"{KEY_PREFIX}*"))
            if keys:
                client.delete(*keys)
        except Exception:
            pass
    _redis_client = None
    _redis_url = ""
    with _memory_lock:
        _memory_hits.clear()
