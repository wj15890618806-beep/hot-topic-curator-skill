import argparse
import html
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests


API_URL = "https://api.tikhub.io/api/v1/douyin/search/fetch_video_search_v2"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "resources" / "douyin_search.json"


def load_config(config_path):
    with config_path.open(encoding="utf-8") as file:
        return json.load(file)


def parse_args():
    parser = argparse.ArgumentParser(description="抓取抖音中文财经爆款视频")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser.parse_args()


def iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def find_videos(payload):
    videos = []
    seen = set()
    for value in iter_dicts(payload):
        candidate = value.get("aweme_info") if isinstance(value.get("aweme_info"), dict) else value
        aweme_id = str(candidate.get("aweme_id") or "")
        if not aweme_id or aweme_id in seen or not isinstance(candidate.get("statistics"), dict):
            continue
        seen.add(aweme_id)
        videos.append(candidate)
    return videos


def count(stats, *keys):
    for key in keys:
        value = stats.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return 0


def normalize_video(video, keyword):
    stats = video.get("statistics") or {}
    author = video.get("author") or {}
    aweme_id = str(video.get("aweme_id"))
    timestamp = int(video.get("create_time") or 0)
    return {
        "keyword": keyword,
        "title": (video.get("desc") or "").strip(),
        "video_url": f"https://www.douyin.com/video/{aweme_id}",
        "aweme_id": aweme_id,
        "published_at": datetime.fromtimestamp(timestamp).astimezone().isoformat() if timestamp else "",
        "author": author.get("nickname") or "",
        "author_id": author.get("unique_id") or author.get("short_id") or "",
        "sec_uid": author.get("sec_uid") or "",
        "likes": count(stats, "digg_count", "like_count"),
        "comments": count(stats, "comment_count"),
        "shares": count(stats, "share_count", "forward_count"),
        "plays": count(stats, "play_count", "play_count_real"),
    }


def passes_thresholds(item, thresholds):
    return any(item[name] >= int(limit) for name, limit in thresholds.items())


def fetch_keyword(session, api_key, keyword, pages, publish_time):
    results = []
    cursor = 0
    search_id = ""
    for _ in range(pages):
        body = {
            "keyword": keyword,
            "cursor": cursor,
            "sort_type": "1",
            "publish_time": publish_time,
        }
        if search_id:
            body["search_id"] = search_id
        response = session.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=45,
        )
        try:
            payload = response.json()
        except requests.JSONDecodeError:
            payload = {}
        if not response.ok:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            message = detail.get("message_zh") if isinstance(detail, dict) else ""
            raise RuntimeError(f"TikHub 请求失败（HTTP {response.status_code}）：{message or '请检查令牌和接口权限'}")
        if payload.get("code") not in (None, 0, 200):
            raise RuntimeError(payload.get("message") or payload.get("detail") or "TikHub 返回错误")
        results.extend(find_videos(payload))
        data = payload.get("data") or {}
        business_config = data.get("business_config") or {}
        next_page = business_config.get("next_page") or {}
        cursor = next_page.get("cursor") or 0
        search_id = next_page.get("search_id") or search_id
        if not business_config.get("has_more") or not cursor:
            break
    return results


def score(item, thresholds):
    return max(item[name] / max(1, int(limit)) for name, limit in thresholds.items())


def save_report(items, days):
    output_dir = ROOT / "topics" / datetime.now().strftime("%Y-%m-%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "douyin_selected.json"
    html_path = output_dir / "douyin_index.html"
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "\n".join(
        "<tr>"
        f"<td><a href=\"{html.escape(item['video_url'])}\">{html.escape(item['title'] or '无标题')}</a></td>"
        f"<td>{html.escape(item['author'])}</td><td>{item['likes']}</td><td>{item['comments']}</td>"
        f"<td>{item['shares']}</td><td>{item['plays']}</td><td>{html.escape(item['published_at'])}</td>"
        "</tr>"
        for item in items
    )
    html_path.write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>抖音财经贷款爆款</title>"
        "<style>body{font:14px sans-serif;margin:32px}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f5f5f5}</style>"
        f"<h1>近{days}天抖音财经贷款爆款</h1><table><thead><tr><th>视频</th><th>账号</th>"
        "<th>点赞</th><th>评论</th><th>转发</th><th>播放</th><th>发布时间</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>",
        encoding="utf-8",
    )
    return json_path, html_path


def main():
    args = parse_args()
    api_key = os.getenv("TIKHUB_API_KEY", "").strip()
    if not api_key:
        print("缺少环境变量 TIKHUB_API_KEY。", file=sys.stderr)
        return 2
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_config(config_path)
    thresholds = config["thresholds"]
    days = int(config["days"])
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    publish_time = "1" if days <= 1 else "7" if days <= 7 else "180" if days <= 180 else "0"
    deduplicated = {}
    try:
        with requests.Session() as session:
            for keyword in config["keywords"]:
                print(f"检索：{keyword}")
                for raw in fetch_keyword(
                    session,
                    api_key,
                    keyword,
                    int(config["pages_per_keyword"]),
                    publish_time,
                ):
                    item = normalize_video(raw, keyword)
                    published = datetime.fromisoformat(item["published_at"]) if item["published_at"] else None
                    if published and published >= cutoff and passes_thresholds(item, thresholds):
                        previous = deduplicated.get(item["aweme_id"])
                        if previous is None or score(item, thresholds) > score(previous, thresholds):
                            deduplicated[item["aweme_id"]] = item
    except (requests.RequestException, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    items = sorted(deduplicated.values(), key=lambda item: score(item, thresholds), reverse=True)
    items = items[: int(config["max_results"])]
    json_path, html_path = save_report(items, days)
    print(f"命中 {len(items)} 条。")
    print(json_path)
    print(html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
