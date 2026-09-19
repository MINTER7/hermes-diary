#!/usr/bin/env python3
import json
import sys
sys.dont_write_bytecode = True
import urllib.parse
import urllib.request
from datetime import date
from http.client import HTTPException

from diary_common import atomic_write, current_city

WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CITY_QUERY_MAP = {"深圳": "Shenzhen", "广州": "Guangzhou", "上海": "Shanghai", "北京": "Beijing",
                  "杭州": "Hangzhou", "东莞": "Dongguan", "佛山": "Foshan", "珠海": "Zhuhai",
                  "惠州": "Huizhou", "香港": "Hong Kong", "澳门": "Macau"}
WEATHER_MAPPING = {"clear": "晴", "sunny": "晴", "partly cloudy": "多云", "cloudy": "阴",
                   "overcast": "阴", "mist": "雾", "fog": "雾", "light rain": "小雨",
                   "moderate rain": "中雨", "heavy rain": "大雨", "light rain shower": "阵雨",
                   "patchy light rain": "阵雨", "patchy rain nearby": "可能有雨",
                   "thundery outbreaks possible": "雷阵雨", "thunder": "雷阵雨",
                   "light snow": "小雪", "moderate snow": "中雪", "heavy snow": "大雪", "sleet": "雨夹雪"}


def weather(city, language="en", unit="C"):
    try:
        query = urllib.parse.quote(CITY_QUERY_MAP.get(city, city), safe="")
        request = urllib.request.Request(f"https://wttr.in/{query}?format=j1",
                                         headers={"User-Agent": "hermes-diary/2.3"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
        current = data["current_condition"][0]
        description = current["weatherDesc"][0]["value"].strip()
        label = WEATHER_MAPPING.get(description.lower(), description) if language == "zh" else description
        return f"{label} {current['temp_' + unit]}°{unit}"
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, HTTPException):
        print("Weather lookup failed; using an unknown-weather label.", file=sys.stderr)
        return "天气未知" if language == "zh" else "Weather unavailable"


def compose(settings, day, today):
    """One explicit day for the whole run, even if a weather request crosses midnight."""
    raw = settings.diary_dir / f"{day}.md"
    if not raw.exists():
        return None
    fragments = [line.strip() for line in raw.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not fragments:
        return None
    chinese = settings.language == "zh"
    city = current_city(settings) if day == today else ("城市未记录" if chinese else "City not recorded")
    city = city or ("城市未设置" if chinese else "City not set")
    weekday = (WEEKDAYS_CN if chinese else WEEKDAYS_EN)[date.fromisoformat(day).weekday()]
    fields = [weekday, day.replace('-', '.') if chinese else day]
    if settings.weather_enabled:
        if day == today and current_city(settings):
            conditions = weather(current_city(settings), settings.language, settings.temperature_unit)
        elif day != today:
            conditions = "天气未记录" if chinese else "Weather not recorded"
        else:
            conditions = "天气未知" if chinese else "Weather unavailable"
        fields.append(conditions)
    fields.append(city)
    header = " · ".join(fields)
    output = settings.diary_dir / "composed" / f"{day}.md"
    atomic_write(output, header + "\n\n" + "\n".join(fragments) + "\n")
    return output


if __name__ == "__main__":
    from diary_cli import main
    sys.exit(main(["compose", *sys.argv[1:]]))
