from datetime import date
import unittest
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from main import (
    extract_prime_minister_links,
    kana_to_passport,
    parse_cabinet_members,
    parse_era_date,
    parse_count,
    parse_tenure_period,
    parse_prime_minister_page,
    PrimeMinister,
    save_prime_minister,
)


class FetchCabinetInfoTests(unittest.TestCase):
    def test_extracts_links_in_requested_generation_range(self):
        html = """
        <a href="/jp/rekidainaikaku/104.html#link01">第1次内閣</a>
        <a href="/jp/rekidainaikaku/103.html#link01">第2次内閣</a>
        """

        self.assertEqual(
            extract_prime_minister_links(html, 103, 104),
            {
                103: "https://www.kantei.go.jp/jp/rekidainaikaku/103.html",
                104: "https://www.kantei.go.jp/jp/rekidainaikaku/104.html",
            },
        )

    def test_converts_kana_to_passport_romaji(self):
        self.assertEqual(kana_to_passport("たかいち　さなえ"), "takaichi sanae")
        self.assertEqual(kana_to_passport("しんぶん"), "shimbun")
        self.assertEqual(kana_to_passport("ちゅうおう"), "chuo")

    def test_parses_japanese_era_dates(self):
        self.assertEqual(str(parse_era_date("天保12年9月2日")), "1841-09-02")
        self.assertEqual(str(parse_era_date("慶應2年2月5日")), "1866-02-05")
        self.assertEqual(str(parse_era_date("令和元年5月1日")), "2019-05-01")
        self.assertEqual(str(parse_era_date("昭和36年3月7日")), "1961-03-07")

    def test_splits_tenure_period_into_era_and_gregorian_dates(self):
        start_date, end_date, start_era, end_era = parse_tenure_period(
            "令和7年10月21日 ～ 令和8年2月18日"
        )
        self.assertEqual((str(start_date), str(end_date)), ("2025-10-21", "2026-02-18"))
        self.assertEqual((start_era, end_era), ("令和7年10月21日", "令和8年2月18日"))

    def test_uses_current_japan_date_for_current_tenure(self):
        today = date(2026, 10, 26)
        start_date, end_date, start_era, end_era = parse_tenure_period(
            "令和7年10月21日～現在", today
        )
        self.assertEqual((str(start_date), str(end_date)), ("2025-10-21", "2026-10-26"))
        self.assertEqual((start_era, end_era), ("令和7年10月21日", "令和8年10月26日"))

    def test_marks_unreported_numeric_values_as_null(self):
        self.assertIsNone(parse_count("ー", "通算在職日数"))

    def test_saves_without_restarting_an_active_transaction(self):
        connection = MagicMock()
        prime_minister = PrimeMinister(
            number=104,
            name="高市 早苗",
            name_kana="たかいち さなえ",
            name_romaji="takaichi sanae",
            birth_date=date(1961, 3, 7),
            birth_place="奈良県",
            tenure_start_date=date(2025, 10, 21),
            tenure_end_date=date(2026, 2, 18),
            tenure_start_date_era="令和7年10月21日",
            tenure_end_date_era="令和8年2月18日",
            appointment_age=64,
            tenure_days=121,
            cumulative_tenure_days=121,
            cabinet_members=(("第1次高市内閣", "内閣総理大臣", "高市 早苗"),),
        )

        save_prime_minister(connection, prime_minister)

        connection.start_transaction.assert_not_called()
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_parses_profile_and_one_row_per_concurrent_role(self):
        html = """
        <div class="module-meibo-profile">
          <h1>高市　早苗<!-- .module-text--note追加--><span class="module-text--note">たかいち　さなえ</span></h1>
          <p class="generation">第104代</p>
        </div>
        <dl class="rekidai-profile">
          <dt>生年月日</dt><dd>昭和36年3月7日</dd>
          <dt>出身地</dt><dd>奈良県</dd>
          <dt>就任時年齢</dt><dd>64歳</dd>
          <dt>在職期間</dt><dd>令和7年10月21日<br>～令和8年2月18日</dd>
          <dt>在職日数</dt><dd>121日</dd>
          <dt>通算在職日数</dt><dd>121日</dd>
        </dl>
        <section>
          <div class="rekidai-cabinet-heading"><h2>第1次高市内閣</h2></div>
          <div class="module-accordion__item">
            <button class="module-accordion__tab">第1次高市内閣 閣僚名簿</button>
            <div class="module-accordion__body"><table><tbody>
              <tr><th scope="row"><ul><li>財務大臣</li><li>金融担当大臣</li></ul></th>
                  <td>片山　さつき（かたやま　さつき）</td></tr>
              <tr><th scope="row"><ul><li>内閣官房副長官</li></ul></th>
                  <td><img alt="おざき　まさなお"/>（おざき　まさなお）</td></tr>
            </tbody></table></div>
          </div>
          <div class="module-accordion__item">
            <button class="module-accordion__tab">第1次高市内閣 副大臣名簿</button>
          </div>
        </section>
        """

        prime_minister = parse_prime_minister_page(html, 104)

        self.assertEqual(prime_minister.name, "高市 早苗")
        self.assertEqual(prime_minister.name_kana, "たかいち さなえ")
        self.assertEqual(prime_minister.name_romaji, "takaichi sanae")
        self.assertEqual(str(prime_minister.birth_date), "1961-03-07")
        self.assertEqual(
            (str(prime_minister.tenure_start_date), str(prime_minister.tenure_end_date)),
            ("2025-10-21", "2026-02-18"),
        )
        self.assertEqual(
            (prime_minister.tenure_start_date_era, prime_minister.tenure_end_date_era),
            ("令和7年10月21日", "令和8年2月18日"),
        )
        self.assertEqual(
            prime_minister.cabinet_members,
            (
                ("第1次高市内閣", "財務大臣", "片山 さつき"),
                ("第1次高市内閣", "金融担当大臣", "片山 さつき"),
                ("第1次高市内閣", "内閣官房副長官", "おざき まさなお"),
            ),
        )

    def test_parses_historic_roster_without_modern_heading_markup(self):
        html = """
        <div class="module-accordion__item">
          <button class="module-accordion__tab">第1次伊藤内閣 閣僚名簿 開く 閉じる</button>
          <div class="module-accordion__body"><table><tbody>
            <tr><th scope="row"><ul><li>外務大臣</li><li>明治20年9月17日～</li></ul></th>
                <td>伊藤 博文 (臨兼)</td></tr>
            <tr><th scope="row"><ul><li>内閣書記官長明治21年5月28日～</li></ul></th>
                <td>小牧 昌業</td></tr>
            <tr><th scope="row"><ul><li>大東亜大臣 [</li></ul></th>
                <td>青木 一男＊</td></tr>
            <tr><td colspan="2">備考</td></tr>
            <tr><th scope="row">備考</th><td>兼任に関する説明</td></tr>
          </tbody></table></div>
        </div>
        """

        members = parse_cabinet_members(BeautifulSoup(html, "html.parser"))

        self.assertEqual(
            members,
            (
                ("第1次伊藤内閣", "外務大臣", "伊藤 博文"),
                ("第1次伊藤内閣", "内閣書記官長", "小牧 昌業"),
                ("第1次伊藤内閣", "大東亜大臣", "青木 一男"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
