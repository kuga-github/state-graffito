from datetime import date
import unittest
from unittest.mock import MagicMock, patch

import main as scraper
from main import (
    DietBill,
    collect_diet_bills,
    decode_page,
    extract_bill_rows,
    extract_body_html,
    extract_reference_urls,
    fetch_page,
    latest_date_from_history,
    iter_diet_bills,
    parse_era_date,
    save_bill,
)


INDEX_URL = "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/kaiji142.htm"


class FetchDietBillsTests(unittest.TestCase):
    def test_retries_transient_network_timeouts(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"<html></html>"

        with (
            patch("main.urlopen", side_effect=[TimeoutError("timed out"), response]) as open_url,
            patch("main.time.sleep") as sleep,
        ):
            self.assertEqual(fetch_page("https://example.test"), "<html></html>")

        self.assertEqual(open_url.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_raises_after_all_network_retries_fail(self):
        with (
            patch("main.urlopen", side_effect=TimeoutError("timed out")) as open_url,
            patch("main.time.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "3回失敗しました"):
                fetch_page("https://example.test")

        self.assertEqual(open_url.call_count, 3)

    def test_decodes_windows_31j_extensions_when_shift_jis_is_declared(self):
        data = b"\xf0\x40"
        with self.assertRaises(UnicodeDecodeError):
            data.decode("shift_jis")

        self.assertEqual(decode_page(data, "shift_jis", "https://example.test"), data.decode("cp932"))

    def test_converts_japanese_era_dates_to_gregorian_dates(self):
        self.assertEqual(parse_era_date("平成10年 2月10日"), date(1998, 2, 10))
        self.assertEqual(parse_era_date("令和元年5月1日"), date(2019, 5, 1))

    def test_extracts_only_the_requested_bill_categories(self):
        html = """
        <table><caption>衆法の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th><th>本文情報</th></tr>
          <tr><td>142</td><td>99</td><td>除外</td><td>成立</td><td></td><td></td></tr>
        </table>
        <table><caption>閣法の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th><th>本文情報</th></tr>
          <tr><td>142</td><td>1</td><td>法案</td><td>成立</td>
            <td><a href="./keika/1.htm">経過</a></td>
            <td><a href="./honbun/1.htm">本文</a></td></tr>
        </table>
        <table><caption>条約の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th></tr>
          <tr><td>142</td><td>2</td><td>条約</td><td>承認</td>
            <td><a href="./keika/2.htm">経過</a></td></tr>
        </table>
        <table><caption>予算の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th><th>本文情報</th></tr>
          <tr><td>142</td><td>3</td><td>予算案</td><td>成立</td>
            <td><a href="./keika/3.htm">経過</a></td>
            <td><a href="./honbun/3.htm">本文</a></td></tr>
        </table>
        <table><caption>決議の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th><th>本文情報</th></tr>
          <tr><td>142</td><td></td><td></td><td>可決</td><td></td><td></td></tr>
          <tr><td>142</td><td>4</td><td>決議案</td><td></td><td></td><td></td></tr>
        </table>
        """

        rows = extract_bill_rows(html, 142, INDEX_URL)

        self.assertEqual(
            [row.category for row in rows], ["閣法", "条約", "予算", "決議", "決議"]
        )
        self.assertEqual(rows[0].history_url, INDEX_URL.replace("kaiji142.htm", "keika/1.htm"))
        self.assertEqual(rows[0].body_url, INDEX_URL.replace("kaiji142.htm", "honbun/1.htm"))
        self.assertIsNone(rows[1].body_url)
        self.assertEqual(rows[2].bill_title, "予算案")
        self.assertEqual(rows[2].body_url, INDEX_URL.replace("kaiji142.htm", "honbun/3.htm"))
        self.assertEqual(rows[3].bill_number, "")
        self.assertIsNone(rows[3].bill_title)
        self.assertEqual(rows[3].deliberation_status, "可決")
        self.assertEqual(rows[4].bill_title, "決議案")
        self.assertIsNone(rows[4].deliberation_status)

    def test_returns_no_bills_when_the_diet_has_no_target_categories(self):
        self.assertEqual(collect_diet_bills(148, lambda _url: "<html></html>"), [])

    def test_uses_latest_date_in_history_table(self):
        history = """
        <table><tr><th>項目</th><th>内容</th></tr>
          <tr><td>衆議院議案受理年月日</td><td>平成10年 2月10日</td></tr>
          <tr><td>参議院審査終了年月日</td><td>平成10年 2月13日 ／ 可決</td></tr>
        </table>
        """

        self.assertEqual(
            latest_date_from_history(history),
            (date(1998, 2, 13), "平成10年2月13日"),
        )

    def test_removes_presentation_attributes_from_body_markup(self):
        body = '<BODY class="page"><p>法案</p></BODY>'

        self.assertEqual(
            extract_body_html(f"<html>{body}</html>"), "<body><p>法案</p></body>"
        )

    def test_extracts_only_content_after_the_main_content_marker(self):
        html = """
        <body>
          <div id="HeaderBlock"><p>衆議院ヘッダー</p></div>
          <div id="mainlayout">
            <div id="breadcrumb">パンくず</div>
            <h2 id="TopContents" tabindex="200"></h2>
            <p class="bill-text" style="color: red">議案本文</p>
            <script src="search.js"></script>
          </div>
          <div id="FooterBlock"><p>衆議院フッター</p></div>
        </body>
        """

        extracted = extract_body_html(html)

        self.assertIn("議案本文", extracted)
        self.assertNotIn("衆議院ヘッダー", extracted)
        self.assertNotIn("パンくず", extracted)
        self.assertNotIn("衆議院フッター", extracted)
        self.assertNotIn("<script", extracted)
        self.assertNotIn('class="', extracted)
        self.assertNotIn('style="', extracted)
        self.assertNotIn('id="', extracted)

    def test_extracts_reference_document_links_from_their_list(self):
        body = """
        <body><h2>照会できる情報の一覧</h2><span><ul>
          <li><a href="./houan/1.htm">提出時法律案</a></li>
          <li><a href="./syuuseian/1.htm">修正案</a></li>
        </ul></span></body>
        """

        self.assertEqual(
            extract_reference_urls(body, INDEX_URL.replace("kaiji142.htm", "honbun/g142.htm")),
            [
                "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/1.htm",
                "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/syuuseian/1.htm",
            ],
        )

    def test_collects_history_body_and_reference_html(self):
        index = """
        <table><caption>閣法の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th><th>本文情報</th></tr>
          <tr><td>142</td><td>1</td><td>法案</td><td>成立</td>
            <td><a href="./keika/1.htm">経過</a></td>
            <td><a href="./honbun/1.htm">本文</a></td></tr>
        </table>
        """
        history = """
        <table><tr><th>項目</th><th>内容</th></tr>
          <tr><td>日付</td><td>平成10年2月13日</td></tr></table>
        """
        body = (
            '<body><h2>照会できる情報の一覧</h2><ul>'
            '<li><a href="./houan/1.htm">提出時法律案</a></li>'
            '<li><a href="./syuuseian/1.htm">修正案</a></li></ul></body>'
        )
        reference = "<body><p>提出本文</p></body>"
        amendment = "<body><p>修正案</p></body>"
        pages = {
            INDEX_URL: index,
            INDEX_URL.replace("kaiji142.htm", "keika/1.htm"): history,
            INDEX_URL.replace("kaiji142.htm", "honbun/1.htm"): body,
            INDEX_URL.replace("kaiji142.htm", "honbun/houan/1.htm"): reference,
            INDEX_URL.replace("kaiji142.htm", "honbun/syuuseian/1.htm"): amendment,
        }

        bills = collect_diet_bills(142, pages.__getitem__)

        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0].date_gregorian, date(1998, 2, 13))
        self.assertEqual(bills[0].date_era, "平成10年2月13日")
        self.assertEqual(bills[0].bill_body, body)
        self.assertEqual(
            bills[0].reference_information, f"{reference}\n\n{amendment}"
        )

    def test_yields_each_bill_before_fetching_the_next_one(self):
        index = """
        <table><caption>閣法の一覧</caption><tr><th>提出回次</th><th>番号</th>
          <th>議案件名</th><th>審議状況</th><th>経過情報</th></tr>
          <tr><td>142</td><td>1</td><td>最初</td><td>成立</td>
            <td><a href="./keika/1.htm">経過</a></td></tr>
          <tr><td>142</td><td>2</td><td>次</td><td>成立</td>
            <td><a href="./keika/2.htm">経過</a></td></tr>
        </table>
        """
        history = """
        <table><tr><th>項目</th><th>内容</th></tr>
          <tr><td>提出日</td><td>平成22年2月1日</td></tr></table>
        """
        events = []

        def page_fetcher(url):
            events.append(url)
            return index if url == INDEX_URL else history

        bills = iter_diet_bills(142, page_fetcher)
        next(bills)

        self.assertEqual(
            events,
            [INDEX_URL, INDEX_URL.replace("kaiji142.htm", "keika/1.htm")],
        )
        next(bills)
        self.assertEqual(
            events,
            [
                INDEX_URL,
                INDEX_URL.replace("kaiji142.htm", "keika/1.htm"),
                INDEX_URL.replace("kaiji142.htm", "keika/2.htm"),
            ],
        )

    def test_main_saves_each_bill_before_fetching_next_bill(self):
        events = []
        connection = MagicMock()
        bills = [
            DietBill(142, "閣法", 142, "1", "最初", "成立", None, None, None, None),
            DietBill(142, "閣法", 142, "2", "次", "成立", None, None, None, None),
        ]

        def iter_bills(_diet_number):
            events.append("fetch first")
            yield bills[0]
            events.append("fetch second")
            yield bills[1]

        def save(_connection, bill):
            events.append(f"save {bill.bill_number}")

        with (
            patch("main.connect_database", return_value=connection),
            patch("main.ensure_schema"),
            patch("main.iter_diet_bills", side_effect=iter_bills),
            patch("main.save_bill", side_effect=save),
        ):
            scraper.main(["--from-number", "142", "--to-number", "142"])

        self.assertEqual(
            events,
            ["fetch first", "save 1", "fetch second", "save 2"],
        )
        connection.close.assert_called_once()

    def test_inserts_bill_with_null_title_and_status(self):
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = None
        bill = DietBill(
            diet_number=142,
            category="閣法",
            submission_session=142,
            bill_number="1",
            bill_title=None,
            deliberation_status=None,
            date_gregorian=date(1998, 2, 13),
            date_era="平成10年2月13日",
            bill_body="<body>法案</body>",
            reference_information=None,
        )

        save_bill(connection, bill)

        self.assertIn(
            "INSERT INTO diet_bills",
            connection.cursor.return_value.execute.call_args.args[0],
        )
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_updates_existing_bill_by_number(self):
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = (7,)
        bill = DietBill(
            diet_number=142,
            category="閣法",
            submission_session=142,
            bill_number="1",
            bill_title="法案",
            deliberation_status="成立",
            date_gregorian=date(1998, 2, 13),
            date_era="平成10年2月13日",
            bill_body=None,
            reference_information=None,
        )

        save_bill(connection, bill)

        self.assertIn(
            "UPDATE diet_bills",
            connection.cursor.return_value.execute.call_args.args[0],
        )
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
