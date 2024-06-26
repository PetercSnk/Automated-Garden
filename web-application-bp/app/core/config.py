import os

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class Config(object):
    SECRET_KEY = os.urandom(12).hex()
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "core", "instance", "default.db")
    SQLALCHEMY_BINDS = {
        "users": "sqlite:///" + os.path.join(basedir, "auth", "instance", "users.db"),
        "weather": "sqlite:///" + os.path.join(basedir, "weather", "instance", "weather.db"),
        "water": "sqlite:///" + os.path.join(basedir, "water", "instance", "water.db")
    }
    SCHEDULER_API_ENABLED = True
