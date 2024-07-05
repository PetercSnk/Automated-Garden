from flask import render_template, flash, current_app, redirect, url_for, request
from flask_login import login_required, current_user
from app.core.extensions import event
from app.water.models import History, Config, Plant, System
from app.water.forms import WaterForm, ConfigForm, PlantForm
from app.water import water_bp
from app import db
import threading
from datetime import datetime
import time


@water_bp.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    """Create plants & auto assign a default config"""
    plant_form = PlantForm()
    systems_available = [(system.id, system.name) for system in System.query.all()]
    plant_form.system.choices = systems_available
    if request.method == "POST" and plant_form.validate():
        default = datetime.strptime("6", "%H").time()
        new_plant = Plant(system_id=plant_form.system.data,
                          name=plant_form.name.data,
                          description=plant_form.description.data,
                          status=False,
                          estimate=default)
        new_config = Config(enabled=False,
                            duration_sec=120,
                            min_wait_hr=24,
                            mode=3,
                            default=default,
                            rain_reset=False)
        new_plant.config.append(new_config)
        db.session.add(new_plant)
        db.session.commit()
    plants_available = Plant.query.order_by(Plant.id).all()
    return render_template("water/setup.html",
                           user=current_user,
                           plant_form=plant_form,
                           plants_available=plants_available)


@water_bp.route("/delete/<int:plant_id>", methods=["GET", "POST"])
@login_required
def delete(plant_id):
    """Delete plants & all relationships"""
    plant_selected = Plant.query.filter(Plant.id == plant_id).first()
    if plant_selected:
        flash("Deleted plant", category="success")
        db.session.delete(plant_selected)
        db.session.commit()
    else:
        flash("Does not exist", category="error")
    return redirect(url_for("water_bp.setup"))


@water_bp.route("/configure/<int:plant_id>", methods=["GET", "POST"])
@login_required
def configure(plant_id):
    """Edit plant config settings"""
    plant_selected = Plant.query.filter(Plant.id == plant_id).first()
    if plant_selected:
        config_form = ConfigForm()
        config_selected = plant_selected.config
        if request.method == "POST" and config_form.validate():
            config_selected.enabled = config_form.enabled.data
            config_selected.duration_sec = config_form.duration_sec.data
            config_selected.min_wait_hr = config_form.min_wait_hr.data
            config_selected.mode = config_form.mode.data
            config_selected.default = config_form.default.data
            config_selected.rain_reset = config_form.rain_reset.data
            db.session.commit()
        plants_available = Plant.query.order_by(Plant.id).all()
        return render_template("water/configure.html",
                               user=current_user,
                               plant_selected=plant_selected,
                               config_selected=config_selected,
                               config_form=config_form,
                               plants_available=plants_available)
    else:
        flash("Does not exist", category="error")
        return redirect(url_for("water_bp.configure_check"))


@water_bp.route("/configure/check", methods=["GET"])
@login_required
def configure_check():
    """Check if plants exist and redirect accordingly"""
    plant = Plant.query.first()
    if plant:
        return redirect(url_for("water_bp.configure", plant_id=plant.id))
    else:
        flash("Must create plant to access configure options", category="error")
        return redirect(url_for("water_bp.setup"))


@water_bp.route("/water/<int:plant_id>", methods=["GET", "POST"])
@login_required
def water(plant_id):
    """Create new thread and start watering process"""
    plant_selected = Plant.query.filter(Plant.id == plant_id).first()
    if plant_selected:
        water_form = WaterForm()
        if request.method == "POST" and water_form.validate():
            if plant_selected.status:
                flash("Already Runnning", category="error")
            else:
                plant_selected.status = True
                duration_sec = water_form.duration_sec.data
                plant_selected.history.append(History(start_date_time=datetime.now(), duration_sec=duration_sec))
                db.session.commit()
                current_app.logger.debug(f"Plant status set to {plant_selected.status}")
                current_app.logger.info(f"Watering for {duration_sec} seconds")
                thread = threading.Thread(target=process,
                                          args=(current_app._get_current_object(), duration_sec, plant_id),
                                          daemon=True)
                thread.start()
                current_app.logger.debug("Started thread")
                flash("Started Process", category="success")
        plants_available = Plant.query.order_by(Plant.id).all()
        return render_template("water/water.html",
                               user=current_user,
                               plant_selected=plant_selected,
                               water_form=water_form,
                               plants_available=plants_available)
    else:
        flash("Does not exist", category="error")
        return redirect(url_for("water_bp.water_check"))


@water_bp.route("/water/check", methods=["GET"])
@login_required
def water_check():
    """Check if plants exist and redirect accordingly"""
    plant = Plant.query.first()
    if plant:
        return redirect(url_for("water_bp.water", plant_id=plant.id))
    else:
        flash("Must create plant to access water options", category="error")
        return redirect(url_for("water_bp.setup"))


@water_bp.route("/cancel/<int:plant_id>", methods=["GET", "POST"])
@login_required
def cancel(plant_id):
    """Cancel watering process in thread created by water"""
    plant_selected = Plant.query.filter(Plant.id == plant_id).first()
    if plant_selected:
        if plant_selected.status:
            event.set()
            current_app.logger.debug("Event set")
            # duplicate set status so page is updated when process cancelled?
            plant_selected.status = False
            db.session.commit()
            flash("Stopped Process", category="success")
        else:
            flash("Not Running", category="error")
        return redirect(url_for("water_bp.water", plant_id=plant_id))
    else:
        flash("Does not exist", category="error")
        return redirect(url_for("water_bp.water_check"))


def process(app, duration_sec, plant_id):
    """Watering process"""
    with app.app_context():
        app.logger.debug("Started watering process")
        plant_selected = Plant.query.filter(Plant.id == plant_id).first()
        plant_selected.system.obj.on()
        loop(app, duration_sec)
        plant_selected.system.obj.off()
        plant_selected.status = False
        db.session.commit()
        app.logger.debug(f"Water status set to {plant_selected.status}")
        app.logger.debug("Finished watering process")
    return


def loop(app, duration_sec):
    """Inner loop of watering process"""
    app.logger.debug("Loop started")
    for x in range(duration_sec):
        time.sleep(1)
        if event.is_set():
            app.logger.debug("Loop stopped")
            event.clear()
            return
    app.logger.debug("Loop stopped")
    return
