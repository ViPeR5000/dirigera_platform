import datetime
from enum import Enum
import logging

from dirigera import Hub
from .dirigera_lib_patch import HubX
from dirigera.devices.environment_sensor import EnvironmentSensor
from dirigera.devices.controller import Controller
from dirigera.devices.scene import Info, Icon
from dirigera.devices.outlet import Outlet
from .base_classes import ikea_base_device, battery_percentage_sensor,ikea_base_device_sensor, current_amps_sensor , current_active_power_sensor, current_voltage_sensor, total_energy_consumed_sensor, energy_consumed_at_last_reset_sensor , total_energy_consumed_last_updated_sensor, total_energy_consumed_sensor, time_of_last_energy_reset_sensor
from .switch import ikea_outlet, ikea_outlet_switch_sensor
from dirigera.devices.motion_sensor import MotionSensor
from dirigera.devices.open_close_sensor import OpenCloseSensor
from dirigera.devices.water_sensor import WaterSensor
from .binary_sensor import ikea_motion_sensor, ikea_motion_sensor_device, ikea_open_close_device, ikea_open_close, ikea_water_sensor_device, ikea_water_sensor
from dirigera.devices.blinds import Blind
from .cover import IkeaBlindsDevice, IkeaBlinds

from homeassistant.helpers.entity import Entity
from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN
from homeassistant.core import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
    
from .const import DOMAIN
from .base_classes import ikea_base_device, ikea_base_device_sensor
logger = logging.getLogger("custom_components.dirigera_platform")

async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    logger.debug("sensor Starting async_setup_entry")
    """Setup sensors from a config entry created in the integrations UI."""
    logger.debug("Staring async_setup_entry in SENSOR...")
    logger.debug(dict(config_entry.data))
    logger.debug(f"async_setup_entry SENSOR {config_entry.unique_id} {config_entry.state} {config_entry.entry_id} {config_entry.title} {config_entry.domain}")
    
    config = hass.data[DOMAIN][config_entry.entry_id]
    logger.debug(config)

    hub = HubX(config[CONF_TOKEN], config[CONF_IP_ADDRESS])

    env_devices = []
    controller_devices = []

    # If mock then start with mocks
    if config[CONF_IP_ADDRESS] == "mock":
        logger.warning("Setting up mock environment sensors")
        from .mocks.ikea_vindstyrka_mock import ikea_vindstyrka_device_mock

        mock_env_device = ikea_vindstyrka_device_mock()
        env_devices = [mock_env_device]

        logger.warning("Setting up mock controllers")
        from .mocks.ikea_controller_mock import ikea_controller_mock

        mock_controller1 = ikea_controller_mock()
        controller_devices = [mock_controller1]

        ikea_vindstyrka_temperature.async_will_remove_from_hass = (
            ikea_vindstyrka_device_mock.async_will_remove_from_hass
        )
    else:
        hub_devices = await hass.async_add_executor_job(hub.get_environment_sensors)
        env_devices = [
            ikea_vindstyrka_device(hass, hub, env_device) for env_device in hub_devices
        ]

        hub_controllers = await hass.async_add_executor_job(hub.get_controllers)
        logger.debug(f"Got {len(hub_controllers)} controllers...")
        
        # Controllers with more one button are returned as spearate controllers
        # their uniqueid has _1, _2 suffixes. Only the primary controller has 
        # battery % attribute which we shall use to identify
        controller_devices = []
        
        # Precuationary delete all empty scenes
        await hass.async_add_executor_job(hub.delete_empty_scenes)
        
        for controller_device in hub_controllers:
            controller : ikea_controller = ikea_controller(hass, hub, controller_device)
            
            # Hack to create empty scene so that we can associate it the controller
            # so that click of buttons on the controller can generate events on the hub
            clicks_supported = controller_device.capabilities.can_send
            clicks_supported = [ x for x in clicks_supported if x.endswith("Press") ]

            if len(clicks_supported) == 0:
                logger.debug(f"Ignoring controller for scene creation : {controller_device.id} as no press event supported : {controller_device.capabilities.can_send}")
            else:
                #hub.create_empty_scene(controller_id=controller_device.id,clicks_supported=clicks_supported)
                await hass.async_add_executor_job(hub.create_empty_scene,controller_device.id, clicks_supported)
                     
            if controller_device.attributes.battery_percentage :
                controller_devices.append(controller)

    env_sensors = []
    for env_device in env_devices:
        # For each device setup up multiple entities
        env_sensors.append(ikea_vindstyrka_temperature(env_device))
        env_sensors.append(ikea_vindstyrka_humidity(env_device))
        env_sensors.append(ikea_vindstyrka_pm25(env_device, WhichPM25.CURRENT))
        env_sensors.append(ikea_vindstyrka_pm25(env_device, WhichPM25.MAX))
        env_sensors.append(ikea_vindstyrka_pm25(env_device, WhichPM25.MIN))
        env_sensors.append(ikea_vindstyrka_voc_index(env_device))

    logger.debug("Found {} env devices to setup...".format(len(env_devices)))
    logger.debug("Found {} env entities to setup...".format(len(env_sensors)))
    logger.debug("Found {} controller devices to setup...".format(len(controller_devices)))

    async_add_entities(env_sensors)
    async_add_entities(controller_devices)

    # Add sensors for the outlets
    hub_outlets : list[Outlet]  = await hass.async_add_executor_job(hub.get_outlets)
    extra_entities = []
    
    extra_attrs=["current_amps","current_active_power","current_voltage","total_energy_consumed","energy_consumed_at_last_reset","time_of_last_energy_reset","total_energy_consumed_last_updated"]
    # Some outlets like INSPELNING Smart plug have ability to report power, so add those as well
    logger.debug("Looking for extra attributes of power/current/voltage in outlet....")
    for hub_outlet in hub_outlets:
        outlet = ikea_outlet(hass, hub, hub_outlet)
        for attr in extra_attrs:
            if getattr(hub_outlet.attributes,attr) is not None:
                extra_entities.append(eval(f"{attr}_sensor(outlet)"))
                
    logger.debug(f"Found {len(extra_entities)}, power attribute sensors for outlets")
    async_add_entities(extra_entities)
    
    # Add battery sensors
    battery_sensors = []

    hub_motion_sensors : list[MotionSensor] = await hass.async_add_executor_job(hub.get_motion_sensors)
    motion_sensor_devices : list[ikea_motion_sensor_device] = [ikea_motion_sensor_device(hass, hub, m) for m in hub_motion_sensors]

    for device in motion_sensor_devices:
        battery_sensors.append(battery_percentage_sensor(device))
    
    hub_open_close_sensors : list[OpenCloseSensor] = await hass.async_add_executor_job(hub.get_open_close_sensors)
    open_close_devices : list[ikea_open_close_device] = [
        ikea_open_close_device(hass, hub, open_close_sensor)
        for open_close_sensor in hub_open_close_sensors
    ]

    for device in open_close_devices:
        battery_sensors.append(battery_percentage_sensor(device))

    hub_water_sensors : list[WaterSensor] = await hass.async_add_executor_job(hub.get_water_sensors)
    water_sensor_devices = [ ikea_water_sensor_device(hass, hub, hub_water_sensor) 
                            for hub_water_sensor in hub_water_sensors
                        ]
    
    for device in water_sensor_devices:
        battery_sensors.append(battery_percentage_sensor(device))

    hub_blinds = await hass.async_add_executor_job(hub.get_blinds)
    devices = [IkeaBlindsDevice(hass, hub, b) for b in hub_blinds]
    for device in devices:
        if getattr(device,"battery_percentage",None) is not None:
            battery_sensors.append(battery_percentage_sensor(device))
            
    logger.debug(f"Found {len(battery_sensors)} battery sensors...")
    async_add_entities(battery_sensors)
    logger.debug("sensor Complete async_setup_entry")

class ikea_vindstyrka_device(ikea_base_device):
    def __init__(self, hass:core.HomeAssistant, hub:Hub , json_data:EnvironmentSensor) -> None:
        super().__init__(hass, hub, json_data, hub.get_environment_sensor_by_id)
        self._updated_at = None 

    async def async_update(self):        
        if self._updated_at is None or (datetime.datetime.now() - self._updated_at).total_seconds() > 30:
            try:
                logger.debug("env sensor update called...")
                self._json_data = await self._hass.async_add_executor_job(self._hub.get_environment_sensor_by_id, self._json_data.id)
                self._updated_at = datetime.datetime.now()
            except Exception as ex:
                logger.error(
                    "error encountered running update on : {}".format(self.name)
                )
                logger.error(ex)
                raise HomeAssistantError(ex, DOMAIN, "hub_exception")

class ikea_vindstyrka_temperature(ikea_base_device_sensor, SensorEntity):
    def __init__(self, device: ikea_vindstyrka_device) -> None:
        super().__init__(device, id_suffix="TEMP", name="Temperature")
        logger.debug("ikea_vindstyrka_temperature ctor...")

    @property
    def device_class(self):
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self) -> float:
        return self._device.current_temperature

    @property
    def native_unit_of_measurement(self) -> str:
        return "°C"

    @property
    def state_class(self) -> str:
        return "measurement"

class ikea_vindstyrka_humidity(ikea_base_device_sensor, SensorEntity):
    def __init__(self, device: ikea_vindstyrka_device) -> None:
        logger.debug("ikea_vindstyrka_humidity ctor...")
        super().__init__(device, id_suffix="HUM", name="Humidity")

    @property
    def device_class(self):
        return SensorDeviceClass.HUMIDITY

    @property
    def native_value(self) -> int:
        return self._device.current_r_h

    @property
    def native_unit_of_measurement(self) -> str:
        return "%"

class WhichPM25(Enum):
    CURRENT = 0
    MIN = 1
    MAX = 2

class ikea_vindstyrka_pm25(ikea_base_device_sensor, SensorEntity):
    def __init__(
        self, device: ikea_vindstyrka_device, pm25_type: WhichPM25
    ) -> None:
        logger.debug("ikea_vindstyrka_pm25 ctor...")
        self._pm25_type = pm25_type
        id_suffix = " "
        name_suffix = " "
        if self._pm25_type == WhichPM25.CURRENT:
            id_suffix = "CURPM25"
            name_suffix = "Current PM2.5"
        if self._pm25_type == WhichPM25.MAX:
            id_suffix = "MAXPM25"
            name_suffix = "Max Measured PM2.5"
        if self._pm25_type == WhichPM25.MIN:
            id_suffix = "MINPM25"
            name_suffix = "Min Measured PM2.5"
        
        super().__init__(device, id_suffix=id_suffix, name=name_suffix)

    @property
    def device_class(self):
        return SensorDeviceClass.PM25

    @property
    def native_value(self) -> int:
        if self._pm25_type == WhichPM25.CURRENT:
            return self._device.current_p_m25
        elif self._pm25_type == WhichPM25.MAX:
            return self._device.max_measured_p_m25
        elif self._pm25_type == WhichPM25.MIN:
            return self._device.min_measured_p_m25
        logger.debug("ikea_vindstyrka_pm25.native_value() shouldnt be here")
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        return "µg/m³"

class ikea_vindstyrka_voc_index(ikea_base_device_sensor, SensorEntity):
    def __init__(self, device: ikea_vindstyrka_device) -> None:
        logger.debug("ikea_vindstyrka_voc_index ctor...")
        super().__init__(device, id_suffix="VOC", name="VOC Index")

    @property
    def device_class(self):
        return SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS

    @property
    def native_value(self) -> int:
        return self._device.voc_index

    @property
    def native_unit_of_measurement(self) -> str:
        return "µg/m³"

# SOMRIG Controllers act differently in the gateway Hub
# While its one device but two id's are sent back each
# representing the two buttons on the controler. The id is
# all same except _1 and _2 suffix. The serial number on the
# controllers is same.

CONTROLLER_BUTTON_MAP = { "SOMRIG shortcut button" : 2 }

class ikea_controller(ikea_base_device, SensorEntity):
    def __init__(self,hass:core.HomeAssistant, hub:Hub, json_data:Controller):
        logger.debug("ikea_controller ctor...")
        self._buttons = 1
        if json_data.attributes.model in CONTROLLER_BUTTON_MAP:
            self._buttons = CONTROLLER_BUTTON_MAP[json_data.attributes.model]
            logger.debug(f"Set #buttons to {self._buttons} as controller model is : {json_data.attributes.model}")
        
        super().__init__(hass , hub, json_data, hub.get_controller_by_id)

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC
    
    @property
    def icon(self):
        return "mdi:battery"
    
    @property
    def native_value(self):
        return self.battery_percentage

    @property
    def native_unit_of_measurement(self) -> str:
        return "%"

    @property
    def device_class(self) -> str:
        return SensorDeviceClass.BATTERY

    @property
    def number_of_buttons(self) -> int:
        return self._buttons
    
    async def async_update(self):  
        pass