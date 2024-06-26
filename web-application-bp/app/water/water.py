from flask import render_template, flash, current_app, redirect, url_for
from flask_login import login_required, current_user
from app.core.extensions import event
from app.water.models import History, Config, Plant
from app.water.forms import WaterForm, CancelForm, ConfigForm, PlantForm
from app.water import water_bp
from app import db
import threading
#from app.water.systems import objs
from datetime import datetime
import time


@water_bp.route("/configure", methods=["GET"])
@login_required
def configure_index():
    plant = Plant.query.first()
    return redirect(url_for("water_bp.configure", plant_id=plant.id))


@water_bp.route("/configure/<int:plant_id>", methods=["GET", "POST"])
@login_required
def configure(plant_id):
    plant_form = PlantForm()
    config_form = ConfigForm()
    plant = Plant.query.filter(Plant.id == plant_id).first()
    config = plant.config
    if plant_form.submit.data and plant_form.validate():
        plant.name = plant_form.name.data
        plant.description = plant_form.description.data
        db.session.commit()
    elif config_form.submit.data and config_form.validate():
        if config:
            config.enabled = config_form.enabled.data
            config.duration_sec = config_form.duration_sec.data
            config.min_wait_hr = config_form.win_wait_hr.data
            config.mode = config_form.mode.data
            config.default = config_form.default.data
            config.rain_reset = config_form.rain_reset.data
        else:
            new_config = Config(enabled=config_form.enabled.data,
                                duration_sec=config_form.duration_sec.data,
                                min_wait_hr=config_form.min_wait_hr.data,
                                mode=config_form.mode.data,
                                default=config_form.default.data,
                                rain_reset=config_form.rain_reset.data)
            db.session.add(new_config)
        db.session.commit()
    plants = Plant.query.order_by(Plant.id).all()
    return render_template("water/configure.html",
                           user=current_user,
                           plant_form=plant_form,
                           config_form=config_form,
                           plants=plants,
                           plant=plant)


@water_bp.route("/water", methods=["GET"])
@login_required
def water_index():
    plant = Plant.query.first()
    return redirect(url_for("water_bp.water", plant_id=plant.id))


@water_bp.route("/water/<int:plant_id>", methods=["GET", "POST"])
@login_required
def water(plant_id):
    plant = Plant.query.filter(Plant.id == plant_id)
    water_form = WaterForm()
    cancel_form = CancelForm()
    if water_form.submit.data and water_form.validate():
        if plant.status:
            flash("Already Runnning", category="error")
        else:
            duration_sec = water_form.duration_sec.data
            # REPLACE [] with objs
            thread = threading.Thread(target=process,
                                      args=(current_app._get_current_object(), duration_sec, []),
                                      daemon=True)
            thread.start()
            current_app.logger.debug("Started thread")
            flash("Started Process", category="success")
            return render_template("water/water.html",
                                   user=current_user,
                                   status=True,
                                   water_form=water_form,
                                   cancel_form=cancel_form)
    elif cancel_form.submit.data and cancel_form.validate():
        if plant.status:
            event.set()
            current_app.logger.debug("Event set")
            flash("Stopped Process", category="success")
            return render_template("water/water.html",
                                   user=current_user,
                                   status=False,
                                   water_form=water_form,
                                   cancel_form=cancel_form)
        else:
            flash("Not Running", category="error")
    return render_template("water/water.html",
                           user=current_user,
                           status=plant.status,
                           water_form=water_form,
                           cancel_form=cancel_form)


def process(app, duration_sec, plant_id):
    with app.app_context():
        selected_plant = Plant.query.filter(Plant.id == plant_id).first()
        selected_plant.status = True
        selected_plant.history.append(History(start_date_time=datetime.now(), duration_sec=duration_sec))
        db.session.commit()
        app.logger.debug(f"Water status set to {selected_plant.status}")
        app.logger.info(f"Watering for {duration_sec} seconds")
        # for obj in objs:
        #     obj.on()
        loop(app, duration_sec)
        # for obj in objs:
        #     obj.off()
        app.logger.info("Finished watering process")
        selected_plant.status = False
        db.session.commit()
        app.logger.debug(f"Water status set to {selected_plant.status}")
    return


def loop(app, duration_sec):
    for x in range(duration_sec):
        time.sleep(1)
        if event.is_set():
            app.logger.debug("Loop stopped")
            event.clear()
            return
