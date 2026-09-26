import os
import xml.etree.ElementTree as ET
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")                     # 기존 뉴스용 (anon 또는 service)
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # predictions 업데이트용, 반드시 service role

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_lotto_news():
    url = "https://news.google.com/rss/search?q=%EB%A1%9C%EB%98%90+1%EB%93%B1&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}

    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print("구글 뉴스 요청 실패:", res.status_code)
        return

    root = ET.fromstring(res.content)
    items = root.findall(".//item")
    print(f"수집된 뉴스 개수: {len(items)}")

    for item in items[:15]:
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
        description = item.find("description").text if item.find("description") is not None else ""

        data = {"title": title, "link": link, "pub_date": pub_date, "description": description}
        try:
            supabase.table("lotto_news").upsert(data, on_conflict="link").execute()
            print("저장 완료:", title[:20])
        except Exception as e:
            print("DB 저장 에러:", e)


# =========================================================
# 여기부터 신규: 당첨번호 수집 + 채점
# =========================================================

def get_next_round_no():
    """lotto_draws에 기록된 마지막 회차 + 1 = 이번에 확인할 회차"""
    res = supabase_admin.table("lotto_draws").select("round_no").order("round_no", desc=True).limit(1).execute()
    if not res.data:
        print("lotto_draws가 비어있습니다. 최초 1회는 회차를 수동으로 시드해주세요 (Supabase Studio에서 최근 회차 하나 직접 insert).")
        return None
    return res.data[0]["round_no"] + 1


def fetch_draw_result(round_no):
    """동행복권 QR API로 특정 회차 결과 조회. 아직 추첨 전이면 None 반환."""
    url = f"https://qr.dhlottery.co.kr/api/lottery/LOTTO/draw/{round_no}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://qr.dhlottery.co.kr/",
    }
    res = requests.get(url, headers=headers, timeout=10)
    try:
        data = res.json()
    except ValueError:
        print(f"{round_no}회차 응답이 JSON이 아닙니다. status={res.status_code}, body={res.text[:200]}")
        return None
    if data.get("drawStatus") != "PRIZE_CONFIRMED":
        print(f"{round_no}회차 아직 결과가 확정되지 않았습니다. drawStatus={data.get('drawStatus')}")
        return None
    numbers = [data[f"drawNo{i}"] for i in range(1, 7)]
    return {
        "round_no": data["round"],
        "numbers": numbers,
        "bonus_no": data["bonusNo"],
        "drawn_at": data["drawDate"],
    }


def calc_rank(match_count, bonus_matched):
    if match_count == 6:
        return 1
    if match_count == 5 and bonus_matched:
        return 2
    if match_count == 5:
        return 3
    if match_count == 4:
        return 4
    if match_count == 3:
        return 5
    return None


def score_predictions(round_no, numbers, bonus_no):
    draw_set = set(numbers)
    res = (
        supabase_admin.table("predictions")
        .select("id, numbers")
        .eq("round_no", round_no)
        .is_("match_count", "null")
        .execute()
    )
    rows = res.data or []
    print(f"{round_no}회차 채점 대상: {len(rows)}건")

    for row in rows:
        picked = set(row["numbers"])
        match_count = len(picked & draw_set)
        bonus_matched = bool(bonus_no in picked and match_count == 5)
        rank = calc_rank(match_count, bonus_matched)
        supabase_admin.table("predictions").update({
            "match_count": match_count,
            "bonus_matched": bonus_matched,
            "official_rank": rank,
        }).eq("id", row["id"]).execute()


def run_weekly_draw_batch():
    round_no = get_next_round_no()
    if not round_no:
        return

    draw = fetch_draw_result(round_no)
    if not draw:
        return  # 아직 결과 미공개. 다음 예약 실행 때 재시도됨 (upsert라 여러 번 돌아도 안전)

    # 1) draws에 scored=false로 기록
    supabase_admin.table("lotto_draws").upsert({
        "round_no": draw["round_no"],
        "numbers": draw["numbers"],
        "bonus_no": draw["bonus_no"],
        "drawn_at": draw["drawn_at"],
        "scored": False,
    }, on_conflict="round_no").execute()

    # 2) 예측 채점
    try:
        score_predictions(draw["round_no"], draw["numbers"], draw["bonus_no"])
    except Exception as e:
        print("채점 중 에러 발생, scored=false로 유지:", e)
        return

    # 3) 전부 끝났으니 scored=true (프론트가 이 값으로 '결과 나옴' 판단)
    supabase_admin.table("lotto_draws").update({"scored": True}).eq("round_no", draw["round_no"]).execute()
    print(f"{draw['round_no']}회차 채점 완료 (scored=true)")


if __name__ == "__main__":
    fetch_lotto_news()
    run_weekly_draw_batch()
