from __future__ import annotations

import asyncio
import getpass
import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

TELEGRAM_WEB_URL = "https://web.telegram.org/k/"


class TelegramWebSession:
    """Read Telegram counters through a persistent official Web K session.

    Telegram Web owns the MTProto application credentials.  This wrapper only
    drives the official client and keeps its browser profile on local disk.
    """

    def __init__(
        self,
        profile_path: str | Path,
        *,
        headless: bool = True,
        concurrency: int = 3,
    ) -> None:
        self.profile_path = Path(profile_path)
        self.headless = headless
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._authorized = False

    @property
    def connected(self) -> bool:
        return self._page is not None and self._authorized

    @staticmethod
    def _playwright_import() -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on deployment extras
            raise RuntimeError(
                "Playwright is required for DATA_SOURCE=telegram_web; "
                "install requirements and Chromium"
            ) from exc
        return async_playwright

    async def connect(self, *, require_authorized: bool = True) -> None:
        if self._page is not None:
            if require_authorized:
                try:
                    await self._page.wait_for_function(
                        "() => Boolean(window.rootScope?.myId)",
                        timeout=60_000,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Telegram Web session is not authorized; "
                        "run `python -m app auth-web` "
                        f"({exc.__class__.__name__}: {exc})"
                    ) from exc
                self._authorized = True
            else:
                self._authorized = await self.is_authorized()
            return

        self.profile_path.mkdir(parents=True, exist_ok=True)
        async_playwright = self._playwright_import()
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.profile_path),
                headless=self.headless,
                args=("--disable-dev-shm-usage",),
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._page.goto(TELEGRAM_WEB_URL, wait_until="domcontentloaded")
            await self._page.wait_for_function(
                "() => Boolean(window.rootScope && window.rootScope.managers)",
                timeout=60_000,
            )
            try:
                await self._page.wait_for_function(
                    "() => Boolean(window.rootScope?.myId)",
                    timeout=60_000 if require_authorized else 10_000,
                )
                self._authorized = True
            except Exception as exc:
                self._authorized = False
                if require_authorized:
                    raise RuntimeError(
                        "Telegram Web session is not authorized; "
                        "run `python -m app auth-web` "
                        f"({exc.__class__.__name__}: {exc})"
                    ) from exc
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._page = None
        self._context = None
        self._playwright = None
        self._authorized = False
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()

    async def is_authorized(self) -> bool:
        if self._page is None:
            return False
        try:
            return bool(await self._page.evaluate("() => Boolean(window.rootScope?.myId)"))
        except Exception:
            return False

    async def _wait_for_auth_stage(
        self,
        timeout_seconds: int = 120,
        *,
        accept: tuple[str, ...] = ("code", "password"),
    ) -> str:
        assert self._page is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            if await self.is_authorized():
                return "authorized"
            code = self._page.locator('input[autocomplete="one-time-code"]')
            if (
                "code" in accept
                and await code.count()
                and await code.first.is_visible()
                and await code.first.is_enabled()
            ):
                return "code"
            password = self._page.locator('.input-field-password input[name="notsearch_password"]')
            if (
                "password" in accept
                and await password.count()
                and await password.first.is_visible()
                and await password.first.is_enabled()
            ):
                return "password"
            await asyncio.sleep(0.25)
        raise TimeoutError("Telegram Web did not advance to the next authorization step")

    async def authorize_interactive(self, phone: str | None = None) -> None:
        await self.connect(require_authorized=False)
        if await self.is_authorized():
            print("Telegram Web session is already authorized")
            return

        assert self._page is not None
        phone = (phone or input("Telegram phone (+country code): ")).strip()
        if not phone.startswith("+"):
            raise ValueError("Telegram phone must include + and the country code")

        phone_input = self._page.locator(".input-field-phone .input-field-input").first
        if not await phone_input.count():
            phone_login = self._page.locator(
                "button.btn-primary.btn-secondary.btn-primary-transparent.primary"
            ).first
            await phone_login.wait_for(state="visible", timeout=60_000)
            await phone_login.click()
        await phone_input.wait_for(state="visible", timeout=60_000)
        await phone_input.fill(phone)
        await phone_input.press("Enter")

        stage = await self._wait_for_auth_stage()
        if stage == "code":
            code = input("Telegram login code: ").strip().replace(" ", "")
            code_input = self._page.locator('input[autocomplete="one-time-code"]').first
            await code_input.fill(code)
            stage = await self._wait_for_auth_stage(accept=("password",))

        if stage == "password":
            password = getpass.getpass("Telegram 2FA password: ")
            password_input = self._page.locator(
                '.input-field-password input[name="notsearch_password"]'
            ).first
            await password_input.fill(password)
            await self._page.locator("button.btn-primary.btn-color-primary").first.click()
            stage = await self._wait_for_auth_stage(accept=())

        if stage != "authorized":
            raise RuntimeError(f"Unexpected Telegram Web authorization stage: {stage}")
        self._authorized = True
        # Web K writes MTProto authorization keys to IndexedDB asynchronously.
        # Closing Chromium immediately after the UI switches to the chat list
        # can leave a profile that looks successful but cannot be reopened.
        await self._page.wait_for_timeout(5_000)
        await self._page.reload(wait_until="domcontentloaded")
        await self._page.wait_for_function(
            "() => Boolean(window.rootScope?.managers && window.rootScope?.myId)",
            timeout=60_000,
        )
        print(f"Telegram Web session saved in {self.profile_path}")

    async def comments(
        self, username: str, message_ids: Iterable[int],
    ) -> dict[int, int | None]:
        ids = list(dict.fromkeys(int(message_id) for message_id in message_ids))
        if not ids:
            return {}
        if self._page is None:
            await self.connect()

        script = """
        async ({username, messageIds}) => {
          let stage = 'rootScope';
          try {
            const scope = window.rootScope;
            if (!scope || !scope.myId || !scope.managers) {
              throw new Error('Telegram Web session is not authorized');
            }
            const managers = scope.managers;
            stage = 'resolveUsername';
            const peer = await managers.appUsersManager.resolveUsername(username);
            if (!peer || peer._ === 'user' || peer.id === undefined) {
              throw new Error(`@${username} is not a Telegram channel`);
            }
            stage = 'getChannelInput';
            const channel = await managers.appChatsManager.getChannelInput(peer.id);
            stage = 'channels.getMessages';
            const response = await managers.apiManager.invokeApi('channels.getMessages', {
              channel,
              id: messageIds.map((id) => ({_: 'inputMessageID', id}))
            });
            const commentsById = Object.fromEntries(
              response.messages
                .filter((message) => message && message.id)
                .map((message) => [
                  message.id,
                  Number.isInteger(message.replies?.replies)
                    ? message.replies.replies
                    : null
                ])
            );
            const rows = messageIds.map((id) => [id, commentsById[id] ?? null]);
            return {rows: Object.fromEntries(rows)};
          } catch (error) {
            return {error: {
              stage,
              name: error && error.name,
              type: error && error.type,
              code: error && error.code,
              message: error && error.message,
              value: String(error)
            }};
          }
        }
        """
        async with self._semaphore:
            result = await self._page.evaluate(
                script, {"username": username, "messageIds": ids},
            )
        if result.get("error"):
            raise RuntimeError(f"Telegram Web query failed: {result['error']}")
        rows = result["rows"]
        return {int(message_id): value for message_id, value in rows.items()}
