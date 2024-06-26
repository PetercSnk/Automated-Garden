from app import db
from app.weather.models import Day
import click


@click.command()
@click.argument("day_id")
def drop_day(day_id):
    """Delete specific day entry by id."""
    day = Day.query.filter_by(id=day_id).first()
    if day:
        db.session.delete(day)
        db.session.commit()
    else:
        print(f"Day with id '{day_id}' does not exist")
