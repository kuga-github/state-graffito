import unittest
from unittest.mock import MagicMock, patch

from main import (
    CabinetPage,
    CabinetWiki,
    extract_body_html,
    extract_cabinet_pages,
    fetch_cabinet_wiki,
    fetch_page,
    save_cabinet_wiki,
)


class FetchCabinetWikiTests(unittest.TestCase):
    def test_percent_encodes_non_ascii_characters_in_request_url(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"<html></html>"

        with patch("main.urlopen", return_value=response) as open_url:
            self.assertEqual(fetch_page("https://ja.wikipedia.org/wiki/日本国歴代内閣"), "<html></html>")

        request_url = open_url.call_args.args[0].full_url
        self.assertNotIn("日本国", request_url)
        self.assertIn("%E6%97%A5", request_url)

    def test_extracts_and_groups_cabinets_by_prime_minister_number(self):
        html = """
        <div id="mw-content-text"><div class="mw-parser-output">
          <table class="wikitable">
            <tr><th>代</th><th>内閣</th><th>成立年月日</th><th>終了年月日</th>
                <th>内閣総理大臣</th></tr>
            <tr><th>1</th><td><a href="/wiki/第1次山縣内閣">第1次山縣内閣</a></td>
                <td>1889年</td><td>1891年</td>
                <td rowspan="2"><a href="/wiki/山縣有朋">山縣有朋</a></td></tr>
            <tr><th>1</th><td><a href="https://ja.wikipedia.org/wiki/第1次松方内閣">第1次松方内閣</a></td>
                <td>1891年</td><td>1892年</td></tr>
            <tr><th>─</th><td><a href="/wiki/三條暫定内閣">三條暫定内閣</a></td>
                <td>1889年</td><td>1889年</td>
                <td><a href="/wiki/三条実美">三條實美</a></td></tr>
            <tr><th>2</th><td><a href="/wiki/第2次伊藤内閣">第2次伊藤内閣</a></td>
                <td>1892年</td><td>1896年</td>
                <td><a href="/wiki/伊藤博文">伊藤博文</a></td></tr>
          </table>
        </div></div>
        """

        cabinet_pages = extract_cabinet_pages(html)

        self.assertEqual(
            cabinet_pages,
            {
                1: (
                    CabinetPage("第1次山縣内閣", "https://ja.wikipedia.org/wiki/第1次山縣内閣"),
                    CabinetPage("第1次松方内閣", "https://ja.wikipedia.org/wiki/第1次松方内閣"),
                ),
                2: (
                    CabinetPage("第2次伊藤内閣", "https://ja.wikipedia.org/wiki/第2次伊藤内閣"),
                ),
            },
        )

    def test_extracts_html_body_without_head_css_or_display_attributes(self):
        html = """
        <html><head><title>内閣</title><link rel="stylesheet" href="wiki.css"></head>
        <body><div id="mw-content-text"><div class="mw-parser-output">
          <div class="mw-editsection">編集</div>
          <h2 class="heading" style="color:red">概要</h2>
          <p id="description">内閣の説明 <a href="/wiki/日本">日本</a></p>
          <script>ignored()</script>
        </div></div></body></html>
        """

        extracted = extract_body_html(html)

        self.assertIn("<body>", extracted)
        self.assertIn("<h2>概要</h2>", extracted)
        self.assertIn('href="/wiki/日本"', extracted)
        self.assertNotIn("wiki.css", extracted)
        self.assertNotIn("編集", extracted)
        self.assertNotIn("<script", extracted)
        self.assertNotIn('class="', extracted)
        self.assertNotIn('style="', extracted)
        self.assertNotIn('id="', extracted)
        self.assertNotIn("<head>", extracted)

    def test_fetches_each_group_page_and_keeps_page_content_order(self):
        pages = {
            3: (
                CabinetPage("第1次内閣", "https://example.test/first"),
                CabinetPage("第2次内閣", "https://example.test/second"),
            )
        }
        page_html = """<div id="mw-content-text"><div class="mw-parser-output"><p>本文</p></div></div>"""
        requested_urls = []

        def fetch(url):
            requested_urls.append(url)
            return page_html

        cabinet_wikis = fetch_cabinet_wiki(pages, fetch)

        self.assertEqual(requested_urls, [page.url for page in pages[3]])
        self.assertEqual(cabinet_wikis[0].wiki_bodies, ("<body><p>本文</p></body>",) * 2)

    def test_saves_combined_names_and_bodies_with_blank_lines(self):
        connection = MagicMock()
        cabinet_wiki = CabinetWiki(
            prime_minister_number=3,
            cabinet_pages=(
                CabinetPage("第1次内閣", "https://example.test/first"),
                CabinetPage("第2次内閣", "https://example.test/second"),
            ),
            wiki_bodies=("<body>1</body>", "<body>2</body>"),
        )

        save_cabinet_wiki(connection, cabinet_wiki)

        query, values = connection.cursor.return_value.execute.call_args.args
        self.assertIn("ON DUPLICATE KEY UPDATE", query)
        self.assertEqual(
            values,
            (3, "第1次内閣\n\n第2次内閣", "<body>1</body>\n\n<body>2</body>"),
        )
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
