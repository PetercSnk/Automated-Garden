from flask import Blueprint

weather_bp = Blueprint("weather_bp", __name__, template_folder="templates", static_folder="base/static")

from app.weather import weather_bp
