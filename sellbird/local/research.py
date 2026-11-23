"""Explicit public-page capture. The AI worker only sees saved text."""

import asyncio
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from protego import Protego
from scrapy.http import HtmlResponse

from sellbird.public_http import public_http_client

AGENT = "SellbirdLocalResearch"
LIMIT = 1_000_000


async def get_page(client, url):
    async with asyncio.timeout(22):
        async with client.stream("GET", url) as response:
            if response.status_code in (404, 410):
                return response.url, response.status_code, "", ""
            response.raise_for_status()
            blocks = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=16384):
                blocks.extend(chunk)
                if len(blocks) > LIMIT:
                    raise ValueError("Page exceeds the 1 MB capture limit.")
            return response.url, response.status_code, response.headers.get("content-type", ""), blocks.decode(
                response.encoding or "utf-8", "replace",
            )


async def allowed(client, url):
    robots_url = url.copy_with(path="/robots.txt", query=None, fragment=None)
    actual, status, _, text = await get_page(client, robots_url)
    if actual.netloc != url.netloc:
        raise ValueError("The site's robots policy could not be verified.")
    if status == 200 and not Protego.parse(text).can_fetch(str(url), AGENT):
        raise ValueError("This path is disallowed by the site's robots policy.")


async def capture(url):
    first = httpx.URL(url).copy_with(fragment=None)
    if first.scheme not in {"http", "https"} or not first.host or first.userinfo:
        raise ValueError("Enter a public HTTP or HTTPS page URL.")
    async with public_http_client(headers={"User-Agent": AGENT}) as client:
        # Check robots before fetching every page, including redirected paths.
        client.follow_redirects = False
        current = first
        for _ in range(5):
            await allowed(client, current)
            async with asyncio.timeout(22):
                async with client.stream("GET", current) as response:
                    if response.is_redirect and response.headers.get("location"):
                        current = httpx.URL(urljoin(str(current), response.headers["location"]))
                        continue
                    response.raise_for_status()
                    if "html" not in response.headers.get("content-type", "").lower():
                        raise ValueError("The URL must return an HTML page.")
                    blocks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        blocks.extend(chunk)
                        if len(blocks) > LIMIT:
                            raise ValueError("Page exceeds the 1 MB capture limit.")
                    return str(current), extract(str(current), bytes(blocks), response.encoding)
        raise ValueError("The page exceeded the redirect limit.")


def extract(url, body, encoding):
    response = HtmlResponse(url=url, body=body, encoding=encoding)
    content = response.css("main").get() or response.css("body").get() or response.text
    soup = BeautifulSoup(content, "html.parser")
    for element in soup.select("script, style, nav, footer, noscript, template, svg, [hidden]"):
        element.decompose()
    text = " ".join(soup.stripped_strings)[:12000]
    if len(text) < 30:
        raise ValueError("Little readable text was found. Import a saved page snapshot or paste evidence.")
    return text


async def render_saved_html(html):
    """Collect displayed text from a saved HTML snapshot with networking and scripts disabled."""
    return await asyncio.to_thread(_render_snapshot, html)


def _render_snapshot(html):
    # Sync Playwright runs in a dedicated thread. Windows Uvicorn's selector
    # event loop cannot spawn the Playwright subprocess directly.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(offline=True, java_script_enabled=False, service_workers="block")
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(html, wait_until="domcontentloaded", timeout=12000)
            page.locator("script, style, nav, footer, noscript, template, svg").evaluate_all(
                "(nodes) => nodes.forEach(node => node.remove())",
            )
            text = " ".join(page.locator("body").inner_text(timeout=5000).split())[:12000]
            if len(text) < 30:
                raise ValueError("The snapshot contains too little readable text.")
            return text
        finally:
            browser.close()
