import os
import xml.etree.ElementTree as ET
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

        data = {
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "description": description
        }
        try:
            supabase.table("lotto_news").upsert(data, on_conflict="link").execute()
            print("저장 완료:", title[:20])
        except Exception as e:
            print("DB 저장 에러:", e)

if __name__ == "__main__":
    fetch_lotto_news()
