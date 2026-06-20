#!/usr/bin/env python3
"""Genera la bozza settimanale del post LinkedIn per la community Atlassian Roma.

Flusso:
1. Carica le linee guida editoriali da editorial_guidelines.md (system prompt).
2. Guarda gli ultimi post archiviati in posts/ per evitare di ripetere lo
   stesso tema due settimane di fila.
3. Chiede a Claude (con web search attivo) di scegliere un tema e scrivere il
   post, restituendo un JSON strutturato.
4. Se il tema richiede un'immagine stock, cerca una foto royalty-free su
   Unsplash.
5. Invia la bozza su Telegram per la revisione manuale.
6. Archivia la bozza in posts/ per la cronologia e per evitare ripetizioni
   future.

Questo script NON pubblica nulla su LinkedIn: produce solo una bozza da
copiare a mano dopo revisione umana.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic

LOG = logging.getLogger("weekly_linkedin_draft")

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDELINES_PATH = REPO_ROOT / "editorial_guidelines.md"
POSTS_DIR = REPO_ROOT / "posts"

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_MAX_TOKENS = 2000
RECENT_THEMES_LOOKBACK = 4
HTTP_TIMEOUT_SECONDS = 20
HTTP_MAX_RETRIES = 3
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_MAX_CAPTION_LENGTH = 1024

VALID_THEMES = {"novita", "guida", "opinione", "community"}


class ConfigError(RuntimeError):
    """Variabile d'ambiente richiesta mancante o non valida."""


class DraftGenerationError(RuntimeError):
    """Errore durante la generazione o la validazione della bozza."""


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    unsplash_access_key: str | None


def load_config() -> Config:
    """Carica e valida le variabili d'ambiente richieste.

    Non vengono mai loggati i valori dei secret, solo i nomi di quelli
    eventualmente mancanti.
    """
    required = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ConfigError("Variabili d'ambiente mancanti: " + ", ".join(missing))
    return Config(
        anthropic_api_key=required["ANTHROPIC_API_KEY"],
        telegram_bot_token=required["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=required["TELEGRAM_CHAT_ID"],
        unsplash_access_key=os.environ.get("UNSPLASH_ACCESS_KEY") or None,
    )


def slugify(value: str) -> str:
    """Crea uno slug semplice e sicuro per i nomi di file (solo a-z0-9-)."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "post"


def load_system_prompt() -> str:
    if not GUIDELINES_PATH.exists():
        raise ConfigError(f"File delle linee guida non trovato: {GUIDELINES_PATH}")
    return GUIDELINES_PATH.read_text(encoding="utf-8")


def get_recent_themes(limit: int = RECENT_THEMES_LOOKBACK) -> list[str]:
    """Legge il front-matter degli ultimi post archiviati per evitare ripetizioni."""
    if not POSTS_DIR.exists():
        return []
    files = sorted(
        (p for p in POSTS_DIR.glob("*.md") if p.name != ".gitkeep"), reverse=True
    )[:limit]
    themes: list[str] = []
    front_matter_pattern = re.compile(r"^theme:\s*(\w+)", re.MULTILINE)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            LOG.warning("Impossibile leggere %s: %s", path.name, exc)
            continue
        match = front_matter_pattern.search(text)
        if match:
            themes.append(match.group(1))
    return themes


def build_user_message(recent_themes: list[str]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    avoid = ", ".join(recent_themes) if recent_themes else "nessuno (prima pubblicazione)"
    schema = (
        '{"theme": "novita|guida|opinione|community", '
        '"hashtags": ["Atlassian", "..."], '
        '"post_text": "testo completo pronto per LinkedIn", '
        '"image_suggestion": {"type": "stock|screenshot|community_photo|none", '
        '"query": "query inglese per Unsplash, solo se type=stock", '
        '"note": "fonte da citare o motivazione della scelta"}, '
        '"sources": ["https://..."]}'
    )
    return (
        f"Data di oggi: {today}.\n"
        f"Temi usati nelle ultime {RECENT_THEMES_LOOKBACK} settimane "
        f"(da evitare se possibile): {avoid}.\n\n"
        "Segui le istruzioni editoriali del system prompt per scegliere il tema e "
        "scrivere il post di questa settimana. Verifica prima le notizie più recenti "
        "con la ricerca web se il tema è 'novita'. Riformula sempre con parole tue, "
        "non copiare frasi dalle fonti.\n\n"
        "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo prima o "
        f"dopo, nessun blocco markdown) con questo schema esatto:\n{schema}"
    )


def extract_text(message: Any) -> str:
    """Concatena tutti i blocchi di testo della risposta, ignorando i blocchi di tool use."""
    parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return "\n".join(parts).strip()


def call_claude(config: Config, system_prompt: str, user_message: str) -> dict[str, Any]:
    client = Anthropic(api_key=config.anthropic_api_key)
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:  # noqa: BLE001 - qualsiasi errore SDK deve essere intercettato
        raise DraftGenerationError(f"Chiamata all'API Claude fallita: {exc}") from exc

    raw_text = extract_text(response)
    raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DraftGenerationError(
            f"La risposta di Claude non è un JSON valido: {exc}\nContenuto: {raw_text[:500]}"
        ) from exc

    if data.get("theme") not in VALID_THEMES:
        raise DraftGenerationError(f"Tema non valido nella risposta: {data.get('theme')!r}")
    if not data.get("post_text"):
        raise DraftGenerationError("Il campo post_text è vuoto nella risposta.")
    return data


def _request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Esegue una richiesta HTTP con un numero limitato di retry su errori transitori."""
    last_exc: Exception | None = None
    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
            if response.status_code >= 500 or response.status_code == 429:
                response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            LOG.warning(
                "Tentativo %s/%s fallito per %s: %s", attempt, HTTP_MAX_RETRIES, url, exc
            )
            if attempt < HTTP_MAX_RETRIES:
                time.sleep(2**attempt)
    assert last_exc is not None
    raise last_exc


def search_unsplash(query: str, access_key: str) -> dict[str, str] | None:
    """Cerca una foto royalty-free su Unsplash. None se non trova nulla o in caso di errore."""
    try:
        response = _request_with_retry(
            "GET",
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {access_key}"},
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        LOG.warning("Ricerca Unsplash fallita: %s", exc)
        return None

    results = response.json().get("results", [])
    if not results:
        return None
    photo = results[0]
    return {
        "url": photo["urls"]["regular"],
        "credit": f"Foto di {photo['user']['name']} su Unsplash",
        "link": photo["links"]["html"],
    }


def send_telegram_message(config: Config, text: str) -> None:
    text = text[:TELEGRAM_MAX_MESSAGE_LENGTH]
    response = _request_with_retry(
        "POST",
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        json={"chat_id": config.telegram_chat_id, "text": text},
    )
    response.raise_for_status()


def send_telegram_photo(config: Config, photo_url: str, caption: str) -> None:
    response = _request_with_retry(
        "POST",
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendPhoto",
        json={
            "chat_id": config.telegram_chat_id,
            "photo": photo_url,
            "caption": caption[:TELEGRAM_MAX_CAPTION_LENGTH],
        },
    )
    response.raise_for_status()


def notify_failure(config: Config, error: BaseException) -> None:
    """Tenta di avvisare via Telegram in caso di errore, senza propagare ulteriori eccezioni."""
    try:
        send_telegram_message(
            config,
            "⚠️ La generazione della bozza settimanale è fallita. "
            "Controlla i log della Action su GitHub per i dettagli.\n"
            f"Errore: {type(error).__name__}",
        )
    except Exception as notify_exc:  # noqa: BLE001
        LOG.error("Anche la notifica di errore su Telegram è fallita: %s", notify_exc)


def archive_post(data: dict[str, Any], image_info: dict[str, str] | None) -> Path:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    slug = slugify(data["theme"])
    path = POSTS_DIR / f"{today}-{slug}.md"

    front_matter_lines = [
        "---",
        f"date: {today}",
        f"theme: {data['theme']}",
        f"hashtags: {json.dumps(data.get('hashtags', []), ensure_ascii=False)}",
        f"sources: {json.dumps(data.get('sources', []), ensure_ascii=False)}",
    ]
    if image_info:
        front_matter_lines.append(f"image_url: {image_info['url']}")
        front_matter_lines.append(f"image_credit: {image_info['credit']}")
    front_matter_lines.append("---")

    content = "\n".join(front_matter_lines) + "\n\n" + data["post_text"] + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = load_config()
    except ConfigError as exc:
        LOG.error("Configurazione non valida: %s", exc)
        return 1

    try:
        system_prompt = load_system_prompt()
        recent_themes = get_recent_themes()
        user_message = build_user_message(recent_themes)

        LOG.info("Richiamo l'API Claude (modello %s)...", ANTHROPIC_MODEL)
        data = call_claude(config, system_prompt, user_message)
        LOG.info("Bozza generata. Tema scelto: %s", data["theme"])

        image_info: dict[str, str] | None = None
        suggestion = data.get("image_suggestion", {}) or {}
        if (
            suggestion.get("type") == "stock"
            and suggestion.get("query")
            and config.unsplash_access_key
        ):
            image_info = search_unsplash(suggestion["query"], config.unsplash_access_key)

        archived_path = archive_post(data, image_info)
        LOG.info("Bozza archiviata in %s", archived_path.relative_to(REPO_ROOT))

        message_lines = [f"Bozza post settimanale ({data['theme']})", "", data["post_text"]]
        if image_info:
            message_lines += ["", f"Immagine suggerita: {image_info['link']}", image_info["credit"]]
        elif suggestion.get("note"):
            message_lines += ["", f"Immagine suggerita: {suggestion['note']}"]

        send_telegram_message(config, "\n".join(message_lines))
        if image_info:
            send_telegram_photo(config, image_info["url"], image_info["credit"])

        LOG.info("Notifica Telegram inviata con successo.")
        return 0

    except DraftGenerationError as exc:
        LOG.error("Generazione bozza fallita: %s", exc)
        notify_failure(config, exc)
        return 1
    except requests.exceptions.RequestException as exc:
        LOG.error("Errore di rete: %s", exc)
        notify_failure(config, exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - ultima rete di sicurezza, non deve fallire silenziosamente
        LOG.exception("Errore inatteso")
        notify_failure(config, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
