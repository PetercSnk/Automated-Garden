from .models import db, ThreeHour, Day
from sqlalchemy import desc
from datetime import datetime
import requests

def get_weather():
    latest_weather_data = ThreeHour.query.order_by(desc(ThreeHour.date)).first()
    json_response = request_weather()
    current_date, sunrise, sunset, weather_data = extract_data(json_response)
    if latest_weather_data:
        if latest_weather_data.date == current_date:
            return
        else:
            add_weather_to_db(current_date, sunrise, sunset, weather_data)
    else:
        add_weather_to_db(current_date, sunrise, sunset, weather_data)

def add_weather_to_db(current_date, sunrise, sunset, weather_data):
    for wd in weather_data:
        time =          wd[0]
        temperature =   wd[1]
        humidity =      wd[2]
        weather =       wd[3]
        rain_chance =   wd[4]
        rain_recorded = wd[5]
        db.session.add(ThreeHour(date=current_date, time=time, temperature=temperature, humidity=humidity, weather=weather, rain_chance=rain_chance, rain_recorded=rain_recorded))
    db.session.add(Day(date=current_date, sunrise=sunrise, sunset=sunset))
    db.session.commit()

def kelvin_to_celsius(kelvin):
    return (kelvin - 273.15)

def request_weather():
    BASE_URL = "http://api.openweathermap.org/data/2.5/forecast?"
    with open("api.txt", "r") as f:
        API_KEY = f.read()
    LAT = "51.529"
    LON = "-3.191"
    url = BASE_URL + "lat=" + LAT + "&lon=" + LON + "&appid=" + API_KEY
    json_response = requests.get(url).json()
    return json_response

def extract_data(json):
    timezone = json["city"]["timezone"]
    sunrise = datetime.utcfromtimestamp(json["city"]["sunrise"] + timezone).time()
    sunset = datetime.utcfromtimestamp(json["city"]["sunset"] + timezone).time()
    current_date = datetime.now().date()
    weather_data = []
    for t_dict in json["list"]:
        date_time = datetime.utcfromtimestamp(t_dict["dt"] + timezone)
        if date_time.date() == current_date:
            temperature = round(kelvin_to_celsius(t_dict["main"]["temp"]), 2)
            humidity = t_dict["main"]["humidity"]
            weather = t_dict["weather"][0]["description"]
            rain_chance = t_dict["pop"]
            if "rain" in t_dict:
                rain_recorded = t_dict["rain"]["3h"]
            else:
                rain_recorded = 0
            weather_data.append((date_time.time(), temperature, humidity, weather, rain_chance, rain_recorded))
    return current_date, sunrise, sunset, weather_data