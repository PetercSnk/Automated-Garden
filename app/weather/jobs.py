"""All functions required for retrieving weather data."""
import os
import yaml
import pytz
import openmeteo_requests
import pandas as pd
import numpy as np
from astral import LocationInfo
from astral.sun import sun
from app.weather.models import Daily, Hourly
from app import db, scheduler


@scheduler.task("cron", id="get_weather", minute="0", hour="1", day="*", month="*", day_of_week="*")
def get_weather():
    """Function used by the scheduler for automatic retrieval of weather data."""
    response = get_response()
    daily_dataframe, hourly_dataframe = format_response(response)
    daily_dataframe = insert_descriptions(daily_dataframe)
    daily_dataframe = insert_suntimes(daily_dataframe)
    daily_dataframe, hourly_dataframe = delete_anomalies(daily_dataframe, hourly_dataframe)
    daily_count, hourly_count = insert_into_db(daily_dataframe, hourly_dataframe)
    delete_old_records()
    return daily_count, hourly_count


def get_response():
    """Makes requests to the url specified in the applications config and returns response."""
    url = scheduler.app.config["URL"]
    params = {
        "latitude": scheduler.app.config["LATITUDE"],
        "longitude": scheduler.app.config["LONGITUDE"],
        "hourly": ["temperature_2m",
                   "relative_humidity_2m",
                   "precipitation_probability",
                   "precipitation"],
        "daily": "weather_code",
        "timezone": scheduler.app.config["TIMEZONE"],
        "past_days": 3
    }
    om = openmeteo_requests.Client()
    responses = om.weather_api(url, params=params)
    response = responses[0]
    return response


def format_response(response):
    """Formats responses and returns daily and hourly dataframes."""
    hourly = response.Hourly()
    hourly_temperature = np.round(hourly.Variables(0).ValuesAsNumpy().astype("float64"), 2)
    hourly_humidity = hourly.Variables(1).ValuesAsNumpy().astype(int)
    hourly_precipitation_probability = hourly.Variables(2).ValuesAsNumpy().astype(int)
    hourly_precipitation = np.round(hourly.Variables(3).ValuesAsNumpy().astype("float64"), 2)
    hourly_datetime_dataframe = pd.DataFrame({"datetime": pd.date_range(
        start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
        end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=hourly.Interval()),
        inclusive="left"
    )})
    hourly_data = {
        "date": pd.to_datetime(hourly_datetime_dataframe["datetime"]).dt.date,
        "time": pd.to_datetime(hourly_datetime_dataframe["datetime"]).dt.time,
        "temperature": hourly_temperature,
        "humidity": hourly_humidity,
        "precipitation_probability": hourly_precipitation_probability,
        "precipitation": hourly_precipitation
    }
    hourly_dataframe = pd.DataFrame(data=hourly_data)
    daily = response.Daily()
    daily_weather_code = daily.Variables(0).ValuesAsNumpy().astype(int)
    daily_datetime_dataframe = pd.DataFrame({"datetime": pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left"
    )})
    daily_data = {
        "date": pd.to_datetime(daily_datetime_dataframe["datetime"]).dt.date,
        "weather_code": daily_weather_code
    }
    daily_dataframe = pd.DataFrame(data=daily_data)
    return daily_dataframe, hourly_dataframe


def delete_anomalies(daily_dataframe, hourly_dataframe):
    """Deletes all records for a date when its hourly data does not contain 24 data points.

    Responses from Open-Meteo sometimes contain one date that only has 1 hourly data
    point. This is not useful and is subsequently removed.
    """
    dates = daily_dataframe["date"].tolist()
    for date in dates:
        hourly_series = hourly_dataframe.loc[hourly_dataframe["date"] == date]
        if hourly_series.size < 24:
            hourly_dataframe = hourly_dataframe[hourly_dataframe.date != date]
            daily_dataframe = daily_dataframe[daily_dataframe.date != date]
    return daily_dataframe, hourly_dataframe


def get_description(wmo_codes, code):
    """Converts wmo codes to their corresponding string description."""
    try:
        description = wmo_codes["codes"][code]
    except KeyError:
        scheduler.app.logger.debug(f"Weather code '{code}' is unknown")
        description = "Unknown"
    return description


def insert_descriptions(daily_dataframe):
    """Inserts descriptions for wmo codes into daily dataframes."""
    vfunc = np.vectorize(get_description)
    base_path = os.path.abspath(os.path.dirname(__file__))
    file_path = os.path.join(base_path, "wmo_codes.yaml")
    with open(file_path, "r") as file:
        data = yaml.safe_load(file)
    daily_dataframe["weather_description"] = vfunc(data, daily_dataframe["weather_code"])
    return daily_dataframe


def get_suntimes(city, tz, date):
    """Retrieves sunrise and sunset times for the given date."""
    s = sun(city.observer, tzinfo=tz, date=date)
    sunrise = s["sunrise"].time().replace(microsecond=0)
    sunset = s["sunset"].time().replace(microsecond=0)
    return sunrise, sunset


def insert_suntimes(daily_dataframe):
    """Inserts sunrise and sunset times into daily dataframes."""
    city = LocationInfo(scheduler.app.config["CITY"],
                        scheduler.app.config["REGION"],
                        scheduler.app.config["TIMEZONE"],
                        scheduler.app.config["LATITUDE"],
                        scheduler.app.config["LONGITUDE"])
    tz = pytz.timezone(scheduler.app.config["TIMEZONE"])
    vfunc = np.vectorize(get_suntimes)
    daily_dataframe["sunrise"], daily_dataframe["sunset"] = vfunc(city, tz, daily_dataframe["date"])
    return daily_dataframe


def add_daily_to_db(row, existing_dates):
    """Adds rows from daily dataframes to the daily table."""
    with scheduler.app.app_context():
        if row["date"] not in existing_dates:
            daily = Daily(date=row["date"],
                          sunrise=row["sunrise"],
                          sunset=row["sunset"],
                          weather_code=row["weather_code"],
                          weather_description=row["weather_description"])
            db.session.add(daily)
            db.session.commit()
            return row["date"]


def add_hourly_to_db(row, daily_id):
    """Adds rows from hourly dataframes to the hourly table."""
    with scheduler.app.app_context():
        hourly = Hourly(daily_id=daily_id,
                        time=row["time"],
                        temperature=row["temperature"],
                        humidity=row["humidity"],
                        precipitation_probability=row["precipitation_probability"],
                        precipitation=row["precipitation"])
        db.session.add(hourly)
        db.session.commit()
        return row["time"]


def insert_into_db(daily_dataframe, hourly_dataframe):
    """Applies add to db functions to the daily and hourly dataframes/series."""
    existing_dates = [row.date for row in Daily.query.all()]
    daily_result = daily_dataframe.apply(add_daily_to_db, existing_dates=existing_dates, axis=1)
    dates_added = daily_result.dropna().tolist()
    daily_count = len(dates_added)
    hourly_count = 0
    for date in dates_added:
        daily_id = Daily.query.filter(Daily.date == date).first().id
        hourly_series = hourly_dataframe.loc[hourly_dataframe["date"] == date]
        hourly_result = hourly_series.apply(add_hourly_to_db, daily_id=daily_id, axis=1)
        hourly_count += hourly_result.size
    return daily_count, hourly_count


def delete_old_records():
    """Deletes records older than 10 days in daily and hourly table."""
    with scheduler.app.app_context():
        daily_all = Daily.query.order_by(Daily.date).all()
        delete = daily_all[:-10]
        delete_log = []
        if delete:
            for record in delete:
                delete_log.append(record.date.strftime("%d/%m/%y"))
                db.session.delete(record)
            db.session.commit()
    scheduler.app.logger.debug(f"Deleted {delete_log} from database")
    return
