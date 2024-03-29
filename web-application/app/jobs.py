from .models import db, ThreeHour, Day
from sqlalchemy import desc
from datetime import datetime
from . import scheduler
import requests

# use a dictionary for weather data and date as key? potentially better solution

@scheduler.task("cron", id="get_weather", minute="0", hour="1", day="*", month="*", day_of_week="*")
def get_weather():
    try:
        status, reason, ok, json = request_weather()
        if ok:
            dates, sunrise, sunset, weather_data = extract_data(json)
            # openweathermap includes the first half for day 6 in a 5 day weather forecast? remove this as we don't want it
            dates, weather_data = remove_last(dates, weather_data)
            dates_added = add_to_db(dates, sunrise, sunset, weather_data)
            if dates_added:
                return "Added: " + ", ".join(dates_added)
            else:
                return "No New Data"
        else:
            scheduler.app.logger.error(status)
            scheduler.app.logger.error(reason)
            scheduler.app.logger.error(json)
            return "Error"
    except Exception as e:
        scheduler.app.logger.error(e)
        return "Error"

def kelvin_to_celsius(kelvin):
    return (kelvin - 273.15)

def request_weather():
    BASE_URL = "http://api.openweathermap.org/data/2.5/forecast?"
    with open("api", "r") as f:
        API_KEY = f.read()
    LAT = "51.529"
    LON = "-3.191"
    url = BASE_URL + "lat=" + LAT + "&lon=" + LON + "&appid=" + API_KEY
    request = requests.get(url)
    return request.status_code, request.reason, request.ok, request.json()

def extract_data(json):
    timezone = json["city"]["timezone"]
    sunrise = datetime.utcfromtimestamp(json["city"]["sunrise"] + timezone).time()
    sunset = datetime.utcfromtimestamp(json["city"]["sunset"] + timezone).time()
    weather_data = []
    dates = []
    for dt_dict in json["list"]:
        date_time = datetime.utcfromtimestamp(dt_dict["dt"] + timezone)
        date = date_time.date()
        time = date_time.time()
        if date not in dates:
            dates.append(date)
        temperature = round(kelvin_to_celsius(dt_dict["main"]["temp"]), 2)
        humidity = dt_dict["main"]["humidity"]
        weather = dt_dict["weather"][0]["description"]
        rain_chance = dt_dict["pop"]
        if "rain" in dt_dict:
            rain_recorded = dt_dict["rain"]["3h"]
        else:
            rain_recorded = 0
        weather_data.append((date, time, temperature, humidity, weather, rain_chance, rain_recorded))
    return dates, sunrise, sunset, weather_data

def remove_last(dates, weather_data):
    dates.sort()
    weather_data.sort(key=lambda x : x[0])
    length_weather_data = len(weather_data)
    index = 0
    while True:
        if index == length_weather_data - 1:
            scheduler.app.logger.error("Weather Data Missing")
            return dates, weather_data
        if weather_data[index][0] == dates[-1]:
            return dates[:-1], weather_data[:index]
        index = index + 1

def add_to_db(dates, sunrise, sunset, weather_data):
    with scheduler.app.app_context():
        db_dates = [day.date for day in Day.query.order_by(Day.date).all()]
        dates_added = []
        for date in dates:
            if date not in db_dates:
                dates_added.append(date.strftime("%d/%m/%y"))
                db.session.add(Day(date=date, sunrise=sunrise, sunset=sunset))
                for _3h in weather_data:
                    if _3h[0] == date:
                        date =          _3h[0]
                        time =          _3h[1]
                        temperature =   _3h[2]
                        humidity =      _3h[3]
                        weather =       _3h[4]
                        rain_chance =   _3h[5]
                        rain_recorded = _3h[6]
                        db.session.add(ThreeHour(date=date, time=time, temperature=temperature, humidity=humidity, weather=weather, rain_chance=rain_chance, rain_recorded=rain_recorded))
                db.session.commit()
        return dates_added

@scheduler.task("cron", id="delete_old_records", minute="0", hour="2", day="*", month="*", day_of_week="*")
def delete_old_records():
    with scheduler.app.app_context():
        db_days = Day.query.order_by(Day.date).all()
        days_to_delete = db_days[:-7]
        if days_to_delete:
            for day in days_to_delete:
                _3h_to_delete = ThreeHour.query.filter(ThreeHour.date==day.date).all()
                for _3h in _3h_to_delete:
                    db.session.delete(_3h)
                db.session.delete(day)
            db.session.commit()
        return