# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Exercise each chart payload field at its HTML and CSS output boundary."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from Lib.Design import html_charts

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/chart_security_data.json").read_text(
        encoding="utf-8"
    )
)
FIELD_PROBE = r"""({name, data}) => {
  const build = name.startsWith('clientdetail-') ? builders[data.kind] : BUILDERS[name];
  const fields = [];
  function leaves(value, path=[]) {
    if (value !== null && typeof value === 'object') {
      Object.entries(value).forEach(([key, child]) => leaves(child, [...path, key]));
    } else if (!['chart', 'kind'].includes(path[0])) fields.push(path);
  }
  leaves(data);
  const payloads = [
    '<img data-chart-injection src="https://chart-security.invalid/pixel" onerror="window.__CHART_PWNED__=true">',
    '\"><svg data-chart-injection onload="window.__CHART_PWNED__=true">',
    'red;background-image:url(https://chart-security.invalid/pixel)',
  ];
  const failures = [], rejected = [];
  const host = document.createElement('div');
  host.innerHTML = build(data);
  if (!host.children.length) throw new Error('Fixture did not exercise its builder');
  for (const path of fields) {
    for (const payload of payloads) {
      const candidate = structuredClone(data);
      let parent = candidate;
      for (const key of path.slice(0, -1)) parent = parent[key];
      parent[path.at(-1)] = payload;
      try { host.innerHTML = build(candidate); }
      catch (error) {
        if (!(error instanceof TypeError)) throw error;
        rejected.push(path.join('.'));
        continue;
      }
      const markup = host.querySelector('script,img,iframe,object,embed,link,style,svg,math,[data-chart-injection]');
      const unsafeAttribute = [...host.querySelectorAll('*')].some(node =>
        [...node.attributes].some(attribute =>
          /^on/i.test(attribute.name) ||
          (attribute.name === 'style' && /url\s*\(|expression\s*\(|@import|chart-security\.invalid/i.test(attribute.value)) ||
          /^(?:src|href|srcdoc|xlink:href)$/i.test(attribute.name)
        )
      );
      if (markup || unsafeAttribute) failures.push(path.join('.'));
    }
  }
  return {checked: fields.length * payloads.length, rejected, failures};
}"""


@pytest.fixture(scope="module")
def chart_browser():
    with sync_playwright() as playwright:
        browser = html_charts._launch_chart_browser(playwright)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_chart_field_cannot_create_markup_or_external_css(chart_browser, name):
    data = FIXTURES[name]
    chart = "clientdetail" if name.startswith("clientdetail-") else name
    page = chart_browser.new_page()
    try:
        page.route("**/*", lambda route: route.abort())
        page.set_content(html_charts._build_html(chart, data), wait_until="load")
        page.wait_for_function("window.__RENDERED__ === true")
        result = page.evaluate(FIELD_PROBE, {"name": name, "data": data})
        assert result["checked"] > 0
        assert len(result["rejected"]) < result["checked"]
        assert not result["failures"], result
    finally:
        page.close()


@pytest.mark.parametrize("chart", ["overview", "clientdetail"])
def test_chart_document_blocks_external_content_and_inline_event_handlers(
    chart_browser, chart
):
    data = FIXTURES["clientdetail-distribution" if chart == "clientdetail" else chart]
    html = html_charts._build_html(chart, data)
    nonce = re.search(r"script-src 'nonce-([^']+)'", html).group(1)
    assert all(f'nonce="{nonce}"' in tag for tag in re.findall(r"<script\b[^>]*>", html))
    assert nonce not in html_charts._build_html(chart, data)
    page = chart_browser.new_page()
    requests = []
    try:
        page.route(
            "**/*", lambda route: (requests.append(route.request.url), route.abort())
        )
        page.set_content(html, wait_until="load")
        page.wait_for_function("window.__RENDERED__ === true")
        page.evaluate("""() => {
          window.__CHART_PWNED__ = false;
          const script = document.createElement('script');
          script.textContent = 'window.__CHART_PWNED__=true';
          document.body.append(script);
          const image = document.createElement('img');
          image.src = 'https://chart-security.invalid/pixel';
          image.setAttribute('onerror', 'window.__CHART_PWNED__=true');
          document.body.append(image);
          image.dispatchEvent(new Event('error'));
          fetch('https://chart-security.invalid/fetch').catch(() => {});
        }""")
        assert page.evaluate("window.__CHART_PWNED__") is False
        assert requests == []
    finally:
        page.close()
